import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { ExitPool, type ExitConfig } from '../src/router.ts';
import { basic, upgradeHeaders } from '../src/upstream.ts';
import { closeServer, listen, trackSockets, startExit, startGateway } from './helpers.ts';

let counter = 0;
function statsFile(): string {
  counter += 1;
  return path.join(os.tmpdir(), `local-proxy-upgrade-${process.pid}-${counter}.jsonl`);
}

function exitConfig(name: string, port: number, overrides: Partial<ExitConfig> = {}): ExitConfig {
  return { name, host: '127.0.0.1', port, ...overrides };
}

// Origen que acepta el upgrade y hace eco del trafico.
async function startUpgradeOrigin(): Promise<{ server: http.Server; port: number }> {
  const server = http.createServer();
  trackSockets(server);
  server.on('upgrade', (_request, socket) => {
    socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n');
    socket.on('data', (chunk: Buffer) => socket.write(chunk));
  });
  const port = await listen(server);
  return { server, port };
}

interface RawUpgradeOptions {
  proxyPort: number;
  targetUrl: string;
  headers?: Record<string, string>;
}

interface RawUpgradeResult {
  status: number;
  socket: net.Socket;
}

// Handshake crudo: GET absoluto con Connection/Upgrade a traves del gateway.
function rawUpgrade({ proxyPort, targetUrl, headers = {} }: RawUpgradeOptions): Promise<RawUpgradeResult> {
  const target = new URL(targetUrl);
  return new Promise((resolve, reject) => {
    const socket = net.connect(proxyPort, '127.0.0.1');
    let buffer = '';
    const onData = (chunk: Buffer): void => {
      buffer += chunk.toString('latin1');
      const end = buffer.indexOf('\r\n\r\n');
      if (end === -1) return;
      socket.removeListener('data', onData);
      socket.removeListener('error', onError);
      const status = Number(buffer.slice(0, end).split(' ')[1] ?? 0);
      resolve({ status, socket });
    };
    const onError = (error: Error): void => {
      socket.removeListener('data', onData);
      reject(error);
    };
    socket.on('data', onData);
    socket.on('error', onError);
    socket.on('connect', () => {
      const lines = [
        `GET ${targetUrl} HTTP/1.1`,
        `Host: ${target.host}`,
        'Connection: Upgrade',
        'Upgrade: websocket',
        ...Object.entries(headers).map(([key, value]) => `${key}: ${value}`),
      ];
      socket.write(`${lines.join('\r\n')}\r\n\r\n`);
    });
  });
}

test('Upgrade: failover al siguiente exit antes del 101', async (t) => {
  const origin = await startUpgradeOrigin();
  const exit = await startExit({ name: 'exit-ok' });
  const pool = new ExitPool([exitConfig('dead', 1), exitConfig('exit-ok', exit.port)]);
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
  const result = await rawUpgrade({
    proxyPort: httpPort,
    targetUrl: `http://127.0.0.1:${origin.port}/ws`,
    headers: { 'proxy-authorization': basic('julio', 'clave') },
  });
  assert.equal(result.status, 101);
  result.socket.destroy();
  assert.ok(pool.exits.find((item) => item.name === 'dead')!.failures >= 1);
  assert.equal(exit.stats.connections, 1);
});

test('Upgrade: todos los exits muertos devuelve 502', async (t) => {
  const pool = new ExitPool([exitConfig('dead-a', 1), exitConfig('dead-b', 1)]);
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
  });
  const result = await rawUpgrade({
    proxyPort: httpPort,
    targetUrl: 'http://127.0.0.1:9/ws',
    headers: { 'proxy-authorization': basic('julio', 'clave') },
  });
  assert.equal(result.status, 502);
  result.socket.destroy();
});

test('Upgrade: limpia hop-by-hop y usa la credencial del exit', async (t) => {
  const origin = await startUpgradeOrigin();
  const exit = await startExit({ name: 'exit-ok', user: 'exit-user', pass: 'exit-pass' });
  let captured: http.IncomingHttpHeaders | null = null;
  exit.server.on('upgrade', (request) => {
    captured = request.headers;
  });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([
      exitConfig('exit-ok', exit.port, { user: 'exit-user', pass: 'exit-pass' }),
    ]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const result = await rawUpgrade({
    proxyPort: httpPort,
    targetUrl: `http://127.0.0.1:${origin.port}/ws`,
    headers: {
      'proxy-authorization': basic('julio', 'clave'),
      'keep-alive': 'timeout=5',
      te: 'trailers',
      trailer: 'x-trailer',
      'transfer-encoding': 'chunked',
      'proxy-connection': 'keep-alive',
      'sec-websocket-key': 'dGhlIHNhbXBsZSBub25jZQ==',
      'sec-websocket-version': '13',
    },
  });
  assert.equal(result.status, 101);
  result.socket.destroy();
  assert.ok(captured);
  const headers = captured as http.IncomingHttpHeaders;
  assert.equal(headers.connection, 'Upgrade');
  assert.equal(headers.upgrade, 'websocket');
  assert.ok(headers.host);
  assert.equal(headers['keep-alive'], undefined);
  assert.equal(headers.te, undefined);
  assert.equal(headers.trailer, undefined);
  assert.equal(headers['transfer-encoding'], undefined);
  assert.equal(headers['proxy-connection'], undefined);
  assert.equal(headers['proxy-authorization'], basic('exit-user', 'exit-pass'));
  assert.notEqual(headers['proxy-authorization'], basic('julio', 'clave'));
  assert.equal(headers['sec-websocket-key'], 'dGhlIHNhbXBsZSBub25jZQ==');
});

test('upgradeHeaders: elimina hop-by-hop y normaliza Connection/Upgrade', () => {
  const result = upgradeHeaders(
    {
      host: 'example.com',
      connection: 'keep-alive, Upgrade',
      upgrade: 'websocket',
      'sec-websocket-key': 'abc',
      'sec-websocket-version': '13',
      'keep-alive': 'timeout=5',
      te: 'trailers',
      trailer: 'x-trailer',
      'transfer-encoding': 'chunked',
      'proxy-authenticate': 'Basic realm="x"',
      'proxy-authorization': 'Basic zzz',
      'proxy-connection': 'keep-alive',
      'x-custom': '1',
    },
    '127.0.0.1:1234',
  );
  assert.equal(result.connection, 'Upgrade');
  assert.equal(result.upgrade, 'websocket');
  assert.equal(result['sec-websocket-key'], 'abc');
  assert.equal(result['sec-websocket-version'], '13');
  assert.equal(result.host, '127.0.0.1:1234');
  assert.equal(result['x-custom'], '1');
  for (const key of [
    'keep-alive',
    'te',
    'trailer',
    'transfer-encoding',
    'proxy-authenticate',
    'proxy-authorization',
    'proxy-connection',
  ]) {
    assert.equal(result[key], undefined);
  }
});
