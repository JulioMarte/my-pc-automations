import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import net from 'node:net';
import { ExitPool, type ExitConfig } from '../src/router.ts';
import { basic } from '../src/upstream.ts';
import {
  closeServer,
  trackSockets,
  waitFor,
  freePort,
  startOrigin,
  startExit,
  startGateway,
  httpGetThroughProxy,
  connectThroughProxy,
  socks5Connect,
  httpGet,
  readAll,
} from './helpers.ts';

let counter = 0;
function statsFile(): string {
  counter += 1;
  return path.join(os.tmpdir(), `local-proxy-test-${process.pid}-${counter}.jsonl`);
}

function exitConfig(name: string, port: number, overrides: Partial<ExitConfig> = {}): ExitConfig {
  return { name, host: '127.0.0.1', port, ...overrides };
}

async function readStats(file: string, predicate: (item: any) => boolean, timeoutMs = 3000): Promise<any> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(file)) {
      const lines = fs
        .readFileSync(file, 'utf8')
        .trim()
        .split('\n')
        .filter(Boolean)
        .map((line) => JSON.parse(line));
      const found = lines.find(predicate);
      if (found) return found;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error('no se encontro la linea esperada en stats');
}

test('HTTP: GET absoluto a traves del gateway y metering', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const file = statsFile();
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: file,
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/hola`,
    username: 'julio',
    password: 'clave',
    method: 'POST',
    body: 'hola-origen',
  });
  assert.equal(response.status, 200);
  assert.equal(response.body, 'origin-ok');
  assert.equal(response.headers['x-exit-name'], 'exit-a');
  const line = await readStats(file, (item) => item.label === 'http');
  assert.equal(line.exit, 'exit-a');
  assert.ok(line.bytesUp >= 'hola-origen'.length);
  assert.ok(line.bytesDown > 0);
});

test('HTTP: clave incorrecta devuelve 407', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio',
    password: 'mala',
  });
  assert.equal(response.status, 407);
});

test('Rotacion: alterna entre exits sanos', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a' });
  const exitB = await startExit({ name: 'exit-b' });
  const pool = new ExitPool([exitConfig('exit-a', exitA.port), exitConfig('exit-b', exitB.port)]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  const a = pool.exits.find((exit) => exit.name === 'exit-a')!;
  const b = pool.exits.find((exit) => exit.name === 'exit-b')!;
  for (let index = 0; index < 4; index += 1) {
    // Fuerza el orden P2C: el menos cargado es siempre el primero.
    a.active = index % 2 === 0 ? 0 : 100;
    b.active = index % 2 === 0 ? 100 : 0;
    const response = await httpGetThroughProxy({
      proxyPort: httpPort,
      targetUrl: `${origin.url}/`,
      username: 'julio',
      password: 'clave',
    });
    assert.equal(response.status, 200);
  }
  assert.equal(exitA.stats.requests, 2);
  assert.equal(exitB.stats.requests, 2);
});

test('Sticky: la misma sesion usa el mismo exit', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a' });
  const exitB = await startExit({ name: 'exit-b' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exitA.port), exitConfig('exit-b', exitB.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  for (let index = 0; index < 3; index += 1) {
    const response = await httpGetThroughProxy({
      proxyPort: httpPort,
      targetUrl: `${origin.url}/`,
      username: 'julio-session-abc',
      password: 'clave',
    });
    assert.equal(response.status, 200);
  }
  assert.deepEqual([exitA.stats.requests, exitB.stats.requests].sort(), [0, 3]);
});

test('Exit forzado: soporta nombres con guiones (exit-b)', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a' });
  const exitB = await startExit({ name: 'exit-b' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exitA.port), exitConfig('exit-b', exitB.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio-exit-exit-b',
    password: 'clave',
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers['x-exit-name'], 'exit-b');
  assert.equal(exitA.stats.requests, 0);
  assert.equal(exitB.stats.requests, 1);
});

test('Failover: si el primer exit falla usa el siguiente', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a', user: 'gw', pass: 'correcta' });
  const exitB = await startExit({ name: 'exit-b', user: 'gw', pass: 'correcta' });
  const pool = new ExitPool([
    exitConfig('exit-a', exitA.port, { user: 'gw', pass: 'incorrecta' }),
    exitConfig('exit-b', exitB.port, { user: 'gw', pass: 'correcta' }),
  ]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  // Fuerza a que exit-a sea el primer candidato para probar el failover.
  pool.exits.find((exit) => exit.name === 'exit-a')!.active = 0;
  pool.exits.find((exit) => exit.name === 'exit-b')!.active = 100;
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio',
    password: 'clave',
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers['x-exit-name'], 'exit-b');
  assert.ok(pool.exits.find((exit) => exit.name === 'exit-a')!.failures >= 1);
});

test('CONNECT: tunel HTTP con auth', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const socket = await connectThroughProxy({
    proxyPort: httpPort,
    target: `127.0.0.1:${origin.port}`,
    username: 'julio',
    password: 'clave',
  });
  socket.write(`GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n`);
  const data = await readAll(socket);
  assert.match(data, /origin-ok/);
});

test('SOCKS5: tunel con DNS remoto y metering correcto', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const file = statsFile();
  const { gateway, socksPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: file,
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const socket = await socks5Connect({
    proxyPort: socksPort,
    targetHost: 'localhost',
    targetPort: origin.port,
    username: 'julio',
    password: 'clave',
  });
  socket.write(`GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n`);
  const data = await readAll(socket);
  assert.match(data, /origin-ok/);
  const line = await readStats(file, (item) => item.label === 'socks5');
  assert.ok(line.bytesUp > 0);
  assert.ok(line.bytesDown > 0);
  assert.notEqual(line.bytesUp, line.bytesDown);
});

test('Upgrade/WebSocket: se reenvia el upgrade extremo a extremo', async (t) => {
  const origin = http.createServer();
  trackSockets(origin);
  origin.on('upgrade', (request, socket) => {
    socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: test\r\nConnection: Upgrade\r\n\r\n');
    socket.on('data', (chunk) => socket.write(chunk));
  });
  const originPort = await new Promise<number>((resolve) => {
    origin.listen(0, '127.0.0.1', () => {
      const address = origin.address();
      resolve(address && typeof address === 'object' ? address.port : 0);
    });
  });
  const exit = await startExit({ name: 'exit-a' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin);
    await closeServer(exit.server);
  });
  const echoed = await new Promise<string>((resolve, reject) => {
    const request = http.request({
      host: '127.0.0.1',
      port: httpPort,
      path: `http://127.0.0.1:${originPort}/ws`,
      headers: {
        host: `127.0.0.1:${originPort}`,
        connection: 'Upgrade',
        upgrade: 'test',
        'proxy-authorization': basic('julio', 'clave'),
      },
    });
    request.on('upgrade', (response, socket) => {
      socket.write('ping');
      socket.once('data', (chunk: Buffer) => {
        socket.destroy();
        resolve(chunk.toString());
      });
    });
    request.on('response', (response) => reject(new Error(`respuesta inesperada ${response.statusCode}`)));
    request.on('error', reject);
    request.end();
  });
  assert.equal(echoed, 'ping');
});

test('Stats: requiere token y expone el estado', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
    statsToken: 'secreto',
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const unauthorized = await httpGet({ port: httpPort, path: '/__stats' });
  assert.equal(unauthorized.status, 403);
  const authorized = await httpGet({
    port: httpPort,
    path: '/__stats',
    headers: { authorization: 'Bearer secreto' },
  });
  assert.equal(authorized.status, 200);
  const payload = JSON.parse(authorized.body);
  assert.equal(payload.exits.length, 1);
  assert.equal(payload.exits[0].name, 'exit-a');
});

test('Stats: acepta token por query', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
    statsToken: 'secreto',
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  assert.equal((await httpGet({ port: httpPort, path: '/__stats' })).status, 403);
  assert.equal((await httpGet({ port: httpPort, path: '/__stats?token=malo' })).status, 403);
  assert.equal((await httpGet({ port: httpPort, path: '/__stats?token=secreto' })).status, 200);
});

test('Failover: CONNECT usa el siguiente exit si el primero falla', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a', user: 'gw', pass: 'correcta' });
  const exitB = await startExit({ name: 'exit-b', user: 'gw', pass: 'correcta' });
  const pool = new ExitPool([
    exitConfig('exit-a', exitA.port, { user: 'gw', pass: 'incorrecta' }),
    exitConfig('exit-b', exitB.port, { user: 'gw', pass: 'correcta' }),
  ]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  // Fuerza a que exit-a sea el primer candidato para probar el failover.
  pool.exits.find((exit) => exit.name === 'exit-a')!.active = 0;
  pool.exits.find((exit) => exit.name === 'exit-b')!.active = 100;
  const socket = await connectThroughProxy({
    proxyPort: httpPort,
    target: `127.0.0.1:${origin.port}`,
    username: 'julio',
    password: 'clave',
  });
  socket.write('GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n');
  const data = await readAll(socket);
  assert.match(data, /origin-ok/);
  assert.equal(exitA.stats.connections, 1);
  assert.equal(exitB.stats.connections, 1);
});

test('Failover: SOCKS5 usa el siguiente exit si el primero falla', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a', user: 'gw', pass: 'correcta' });
  const exitB = await startExit({ name: 'exit-b', user: 'gw', pass: 'correcta' });
  const pool = new ExitPool([
    exitConfig('exit-a', exitA.port, { user: 'gw', pass: 'incorrecta' }),
    exitConfig('exit-b', exitB.port, { user: 'gw', pass: 'correcta' }),
  ]);
  const { gateway, socksPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  // Fuerza a que exit-a sea el primer candidato para probar el failover.
  pool.exits.find((exit) => exit.name === 'exit-a')!.active = 0;
  pool.exits.find((exit) => exit.name === 'exit-b')!.active = 100;
  const socket = await socks5Connect({
    proxyPort: socksPort,
    targetHost: 'localhost',
    targetPort: origin.port,
    username: 'julio',
    password: 'clave',
  });
  socket.write('GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n');
  const data = await readAll(socket);
  assert.match(data, /origin-ok/);
  assert.equal(exitA.stats.connections, 1);
  assert.equal(exitB.stats.connections, 1);
});

test('Sin exits disponibles: HTTP y CONNECT devuelven 503', async (t) => {
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
  });
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: 'http://127.0.0.1:1/',
    username: 'julio',
    password: 'clave',
  });
  assert.equal(response.status, 503);
  assert.equal(response.headers['retry-after'], '5');
  await assert.rejects(
    connectThroughProxy({
      proxyPort: httpPort,
      target: '127.0.0.1:1',
      username: 'julio',
      password: 'clave',
    }),
    /CONNECT respondio 503/,
  );
});

test('EXIT_ALLOW: rechaza peers no autorizados y el gateway devuelve 502', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a', allowFrom: ['10.99.99.99'] });
  const pool = new ExitPool([exitConfig('exit-a', exit.port)]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio',
    password: 'clave',
  });
  assert.equal(response.status, 502);
  assert.equal(exit.stats.requests, 1);
  assert.ok(pool.exits[0]!.failures >= 1);
});

test('Health: marca un exit no sano y lo recupera al volver el destino', async (t) => {
  const targetPort = await freePort();
  const exit = await startExit({ name: 'exit-a' });
  const pool = new ExitPool([exitConfig('exit-a', exit.port)]);
  const { gateway } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 50,
    healthTimeoutMs: 300,
    healthTarget: { host: '127.0.0.1', port: targetPort },
  });
  const target = net.createServer();
  t.after(async () => {
    await gateway.close();
    await closeServer(target);
    await closeServer(exit.server);
  });
  await waitFor(() => pool.exits[0]!.healthy === false);
  await new Promise<void>((resolve, reject) => {
    target.once('error', reject);
    target.listen(targetPort, '127.0.0.1', () => resolve());
  });
  await waitFor(() => pool.exits[0]!.healthy === true);
});

test('loc: filtra exits por ubicacion extremo a extremo', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a' });
  const exitB = await startExit({ name: 'exit-b' });
  const pool = new ExitPool([
    exitConfig('exit-a', exitA.port, { location: 'do-santiago' }),
    exitConfig('exit-b', exitB.port, { location: 'us-east' }),
  ]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio-loc-us-east',
    password: 'clave',
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers['x-exit-name'], 'exit-b');
  assert.equal(exitA.stats.requests, 0);
  assert.equal(exitB.stats.requests, 1);
});

test('Sticky: expira el TTL y elige un exit nuevo', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a' });
  const exitB = await startExit({ name: 'exit-b' });
  const pool = new ExitPool(
    [exitConfig('exit-a', exitA.port), exitConfig('exit-b', exitB.port)],
    { sessionTtlMs: 100 },
  );
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  const a = pool.exits.find((exit) => exit.name === 'exit-a')!;
  const b = pool.exits.find((exit) => exit.name === 'exit-b')!;
  a.active = 0;
  b.active = 100;
  const first = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio-session-s',
    password: 'clave',
  });
  assert.equal(first.headers['x-exit-name'], 'exit-a');
  await new Promise((resolve) => setTimeout(resolve, 150));
  // Sesion expirada: el menos cargado pasa a ser exit-b.
  a.active = 100;
  b.active = 0;
  const second = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio-session-s',
    password: 'clave',
  });
  assert.equal(second.headers['x-exit-name'], 'exit-b');
});

test('Un 502 del origen no marca el exit como fallido', async (t) => {
  const origin = await startOrigin((request, response) => {
    response.writeHead(502, { 'content-type': 'text/plain' });
    response.end('origin-bad-gateway');
  });
  const exit = await startExit({ name: 'exit-a' });
  const pool = new ExitPool([exitConfig('exit-a', exit.port)]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio',
    password: 'clave',
  });
  assert.equal(response.status, 502);
  assert.equal(response.body, 'origin-bad-gateway');
  assert.equal(pool.exits[0]!.failures, 0);
  assert.equal(pool.exits[0]!.healthy, true);
});

test('CONNECT: destino IPv6', async (t) => {
  const origin = http.createServer((request, response) => response.end('ipv6-ok'));
  trackSockets(origin);
  const listening = await new Promise<boolean>((resolve) => {
    origin.once('error', () => resolve(false));
    origin.listen(0, '::1', () => resolve(true));
  });
  if (!listening) {
    t.skip('IPv6 no disponible en esta maquina');
    return;
  }
  const exit = await startExit({ name: 'exit-a' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin);
    await closeServer(exit.server);
  });
  const address = origin.address();
  const originPort = address && typeof address === 'object' ? address.port : 0;
  const socket = await connectThroughProxy({
    proxyPort: httpPort,
    target: `[::1]:${originPort}`,
    username: 'julio',
    password: 'clave',
  });
  socket.write('GET / HTTP/1.1\r\nHost: [::1]\r\nConnection: close\r\n\r\n');
  const data = await readAll(socket);
  assert.match(data, /ipv6-ok/);
});

test('HTTP: HEAD se reenvia sin body', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio',
    password: 'clave',
    method: 'HEAD',
  });
  assert.equal(response.status, 200);
  assert.equal(response.body, '');
  assert.equal(response.headers['x-exit-name'], 'exit-a');
});

test('HTTP: body grande se reenvia completo y se metrifica', async (t) => {
  const origin = await startOrigin((request, response) => {
    let size = 0;
    request.on('data', (chunk: Buffer) => {
      size += chunk.length;
    });
    request.on('end', () => response.end(String(size)));
  });
  const exit = await startExit({ name: 'exit-a' });
  const file = statsFile();
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([exitConfig('exit-a', exit.port)]),
    statsFile: file,
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const payload = 'x'.repeat(512 * 1024);
  const response = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio',
    password: 'clave',
    method: 'POST',
    body: payload,
  });
  assert.equal(response.status, 200);
  assert.equal(response.body, String(payload.length));
  const line = await readStats(file, (item) => item.label === 'http');
  assert.ok(line.bytesUp >= payload.length);
});

test('rotate: ignora la sesion guardada y elige otra salida', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a' });
  const exitB = await startExit({ name: 'exit-b' });
  const pool = new ExitPool([exitConfig('exit-a', exitA.port), exitConfig('exit-b', exitB.port)]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  const a = pool.exits.find((exit) => exit.name === 'exit-a')!;
  const b = pool.exits.find((exit) => exit.name === 'exit-b')!;
  a.active = 0;
  b.active = 100;
  const first = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio-session-s',
    password: 'clave',
  });
  assert.equal(first.headers['x-exit-name'], 'exit-a');
  // rotate ignora la sesion y vuelve a elegir por carga.
  a.active = 100;
  b.active = 0;
  const rotated = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio-rotate-session-s',
    password: 'clave',
  });
  assert.equal(rotated.headers['x-exit-name'], 'exit-b');
  const third = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/`,
    username: 'julio-session-s',
    password: 'clave',
  });
  assert.equal(third.headers['x-exit-name'], 'exit-b');
});

test('Concurrencia: 20 requests simultaneos se reparten y responden', async (t) => {
  const origin = await startOrigin();
  const exitA = await startExit({ name: 'exit-a' });
  const exitB = await startExit({ name: 'exit-b' });
  const pool = new ExitPool([exitConfig('exit-a', exitA.port), exitConfig('exit-b', exitB.port)]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exitA.server);
    await closeServer(exitB.server);
  });
  const responses = await Promise.all(
    Array.from({ length: 20 }, () =>
      httpGetThroughProxy({
        proxyPort: httpPort,
        targetUrl: `${origin.url}/`,
        username: 'julio',
        password: 'clave',
      }),
    ),
  );
  assert.ok(responses.every((response) => response.status === 200 && response.body === 'origin-ok'));
  assert.equal(exitA.stats.requests + exitB.stats.requests, 20);
  assert.ok(exitA.stats.requests > 0 && exitB.stats.requests > 0);
});
