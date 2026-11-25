// Jornadas de usuario de extremo a extremo sobre sockets reales.
//
// A diferencia de integration.test.ts (que verifica cada pieza por separado),
// aqui se recorren flujos completos de un usuario contra un gateway real con
// varios exits: rotacion, sesiones sticky, exit forzado, filtro por ubicacion,
// failover, SOCKS5 con DNS remoto, limites de conexion y observabilidad
// (/__stats + stats.jsonl).
//
// Todo es deterministico: el orden de seleccion P2C se controla ajustando
// `active` en el pool (el menos cargado se elige primero), y los exits "muertos"
// apuntan a un puerto libre en 127.0.0.1.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { ExitPool, type ExitConfig, type ExitPoolOptions } from '../src/router.ts';
import {
  closeServer,
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
  return path.join(os.tmpdir(), `local-proxy-journey-${process.pid}-${counter}.jsonl`);
}

interface JourneyExitSpec {
  name: string;
  location?: string;
  // Si es true no se arranca un exit real: se apunta a un puerto libre (muerto).
  dead?: boolean;
}

interface JourneyOptions {
  exits: JourneyExitSpec[];
  users?: Map<string, string>;
  statsToken?: string;
  maxConnectionsPerUser?: number;
  poolOptions?: ExitPoolOptions;
}

// Monta origen + exits + gateway y devuelve los handles junto con un close()
// que apaga todo. Los tests lo registran en t.after.
async function startJourney(options: JourneyOptions) {
  const origin = await startOrigin();
  const servers: http.Server[] = [origin.server];
  const exitStats = new Map<string, { connections: number; requests: number }>();
  const exitServers = new Map<string, http.Server>();
  const configs: ExitConfig[] = [];

  for (const spec of options.exits) {
    if (spec.dead) {
      const port = await freePort();
      configs.push({ name: spec.name, location: spec.location ?? '', host: '127.0.0.1', port });
      continue;
    }
    const exit = await startExit({ name: spec.name });
    exitStats.set(spec.name, exit.stats);
    exitServers.set(spec.name, exit.server);
    servers.push(exit.server);
    configs.push({ name: spec.name, location: spec.location ?? '', host: '127.0.0.1', port: exit.port });
  }

  const file = statsFile();
  const pool = new ExitPool(configs, options.poolOptions);
  const started = await startGateway({
    users: options.users ?? new Map([['agent', 'clave']]),
    pool,
    statsFile: file,
    statsToken: options.statsToken ?? 'token-journey',
    healthIntervalMs: 0,
    maxConnectionsPerUser: options.maxConnectionsPerUser ?? 0,
  });

  return {
    origin,
    pool,
    exitStats,
    exitServers,
    statsFile: file,
    gateway: started.gateway,
    httpPort: started.httpPort,
    socksPort: started.socksPort,
    close: async (): Promise<void> => {
      await started.gateway.close();
      for (const server of servers) await closeServer(server);
    },
  };
}

interface StatsLine {
  label?: string;
  exit?: string;
  bytesUp?: number;
  bytesDown?: number;
}

// Espera a que stats.jsonl tenga al menos `minimum` lineas de metering.
async function readStatsLines(file: string, minimum: number, timeoutMs = 3000): Promise<StatsLine[]> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fs.existsSync(file)) {
      const lines = fs
        .readFileSync(file, 'utf8')
        .split('\n')
        .filter(Boolean)
        .map((line) => JSON.parse(line) as StatsLine);
      if (lines.length >= minimum) return lines;
    }
    if (Date.now() > deadline) throw new Error('timeout esperando stats.jsonl');
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

function exitName(response: { headers: http.IncomingHttpHeaders }): string {
  return String(response.headers['x-exit-name']);
}

test('jornada: rotacion devuelve el body del origen desde un exit sano', async (t) => {
  const journey = await startJourney({
    exits: [
      { name: 'vps-01', location: 'us-ny' },
      { name: 'vps-02', location: 'us-ny' },
    ],
  });
  t.after(() => journey.close());

  const response = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/hola`,
    username: 'agent',
    password: 'clave',
  });
  assert.equal(response.status, 200);
  assert.equal(response.body, 'origin-ok');
  assert.ok(['vps-01', 'vps-02'].includes(exitName(response)));
  const atendidas =
    (journey.exitStats.get('vps-01')?.requests ?? 0) + (journey.exitStats.get('vps-02')?.requests ?? 0);
  assert.equal(atendidas, 1);
});

test('jornada: sesion sticky mantiene el exit y rotate la cambia', async (t) => {
  const journey = await startJourney({
    exits: [{ name: 'vps-01' }, { name: 'vps-02' }],
  });
  t.after(() => journey.close());
  const a = journey.pool.exits.find((exit) => exit.name === 'vps-01')!;
  const b = journey.pool.exits.find((exit) => exit.name === 'vps-02')!;

  // Fuerza a que el primer elegido sea vps-01 (el menos cargado).
  a.active = 0;
  b.active = 100;
  const first = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent-session-abc',
    password: 'clave',
  });
  assert.equal(first.status, 200);
  assert.equal(exitName(first), 'vps-01');

  // Segunda peticion de la misma sesion: reutiliza el exit guardado.
  const second = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent-session-abc',
    password: 'clave',
  });
  assert.equal(exitName(second), 'vps-01');

  // rotate ignora la sesion y elige el menos cargado (ahora vps-02).
  a.active = 100;
  b.active = 0;
  const rotated = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent-rotate-session-abc',
    password: 'clave',
  });
  assert.equal(exitName(rotated), 'vps-02');

  // La sesion queda re-apuntada al nuevo exit.
  const third = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent-session-abc',
    password: 'clave',
  });
  assert.equal(exitName(third), 'vps-02');
});

test('jornada: exit forzado con nombre que contiene guiones', async (t) => {
  const journey = await startJourney({
    exits: [{ name: 'vps-01' }, { name: 'vps-02' }],
  });
  t.after(() => journey.close());

  const response = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent-exit-vps-02',
    password: 'clave',
  });
  assert.equal(response.status, 200);
  assert.equal(exitName(response), 'vps-02');
  assert.equal(journey.exitStats.get('vps-01')?.requests, 0);
  assert.equal(journey.exitStats.get('vps-02')?.requests, 1);
});

test('jornada: filtro por ubicacion y ubicacion inexistente devuelve 503', async (t) => {
  const journey = await startJourney({
    exits: [
      { name: 'vps-01', location: 'us-ny' },
      { name: 'vps-02', location: 'do-santiago' },
    ],
  });
  t.after(() => journey.close());

  const filtered = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent-loc-us-ny',
    password: 'clave',
  });
  assert.equal(filtered.status, 200);
  assert.equal(exitName(filtered), 'vps-01');
  assert.equal(journey.exitStats.get('vps-02')?.requests, 0);

  const missing = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent-loc-eu-fra',
    password: 'clave',
  });
  assert.equal(missing.status, 503);
});

test('jornada: failover con un exit muerto y luego sin exits sanos', async (t) => {
  const journey = await startJourney({
    exits: [{ name: 'vps-01' }, { name: 'vps-dead', dead: true }],
  });
  t.after(() => journey.close());
  const healthy = journey.pool.exits.find((exit) => exit.name === 'vps-01')!;
  const dead = journey.pool.exits.find((exit) => exit.name === 'vps-dead')!;

  // El exit muerto es el primero: la peticion cae en el failover.
  dead.active = 0;
  healthy.active = 100;
  const recovered = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent',
    password: 'clave',
  });
  assert.equal(recovered.status, 200);
  assert.equal(exitName(recovered), 'vps-01');
  assert.ok(dead.failures >= 1);

  // Ahora tambien se cae el exit sano: el gateway deja de poder servir.
  await closeServer(journey.exitServers.get('vps-01')!);
  let lastStatus = 0;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const response = await httpGetThroughProxy({
      proxyPort: journey.httpPort,
      targetUrl: `${journey.origin.url}/`,
      username: 'agent',
      password: 'clave',
    });
    lastStatus = response.status ?? 0;
    assert.ok(lastStatus === 502 || lastStatus === 503, `estado inesperado ${lastStatus}`);
    if (lastStatus === 503) break;
  }
  assert.equal(lastStatus, 503);
});

test('jornada: SOCKS5 con DNS remoto llega al origen', async (t) => {
  const journey = await startJourney({ exits: [{ name: 'vps-01' }] });
  t.after(() => journey.close());

  const socket = await socks5Connect({
    proxyPort: journey.socksPort,
    targetHost: 'localhost',
    targetPort: journey.origin.port,
    username: 'agent',
    password: 'clave',
  });
  socket.write('GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n');
  const data = await readAll(socket);
  assert.match(data, /origin-ok/);
  // El tunel CONNECT se metrifica con label socks5 (no pasa por 'request' del exit).
  const lines = await readStatsLines(journey.statsFile, 1);
  assert.ok(lines.some((line) => line.label === 'socks5' && (line.bytesUp ?? 0) > 0));
});

test('jornada: autenticacion incorrecta (407) y limite por usuario (429)', async (t) => {
  const journey = await startJourney({
    exits: [{ name: 'vps-01' }],
    maxConnectionsPerUser: 1,
  });
  t.after(() => journey.close());

  const wrongPassword = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent',
    password: 'mala',
  });
  assert.equal(wrongPassword.status, 407);

  // Ocupa el unico cupo del usuario con un tunel CONNECT vivo.
  const tunnel = await connectThroughProxy({
    proxyPort: journey.httpPort,
    target: `127.0.0.1:${journey.origin.port}`,
    username: 'agent',
    password: 'clave',
  });
  const limited = await httpGetThroughProxy({
    proxyPort: journey.httpPort,
    targetUrl: `${journey.origin.url}/`,
    username: 'agent',
    password: 'clave',
  });
  assert.equal(limited.status, 429);
  tunnel.destroy();
});

test('jornada: /__stats y stats.jsonl reflejan exits y sesiones', async (t) => {
  const journey = await startJourney({
    exits: [{ name: 'vps-01' }, { name: 'vps-02' }],
    statsToken: 'secreto-journey',
  });
  t.after(() => journey.close());

  for (let index = 0; index < 2; index += 1) {
    const response = await httpGetThroughProxy({
      proxyPort: journey.httpPort,
      targetUrl: `${journey.origin.url}/`,
      username: 'agent-session-obs',
      password: 'clave',
    });
    assert.equal(response.status, 200);
  }

  const stats = await httpGet({ port: journey.httpPort, path: '/__stats?token=secreto-journey' });
  assert.equal(stats.status, 200);
  const payload = JSON.parse(stats.body);
  const names = payload.exits.map((exit: { name: string }) => exit.name).sort();
  assert.deepEqual(names, ['vps-01', 'vps-02']);
  assert.ok(payload.sessions.some((session: { key: string }) => session.key === 'agent:obs'));

  const lines = await readStatsLines(journey.statsFile, 2);
  const metering = lines.filter((line) => line.label === 'http');
  assert.equal(metering.length, 2);
  assert.ok(metering.every((line) => typeof line.bytesDown === 'number' && line.bytesDown > 0));
});
