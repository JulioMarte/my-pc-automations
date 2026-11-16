import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { ExitPool } from '../src/router.ts';
import {
  closeServer,
  waitFor,
  freePort,
  startOrigin,
  startExit,
  startGateway,
  httpGet,
  httpGetThroughProxy,
} from './helpers.ts';

let counter = 0;
function statsFile(): string {
  counter += 1;
  return path.join(os.tmpdir(), `local-proxy-ops-${process.pid}-${counter}.jsonl`);
}

test('Health multi-target: un destino caido no marca el exit como no sano', async (t) => {
  const deadPort = await freePort();
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const pool = new ExitPool([{ name: 'exit-a', host: '127.0.0.1', port: exit.port }]);
  const { gateway } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    statsToken: 'tok',
    healthIntervalMs: 50,
    healthTimeoutMs: 300,
    healthTargets: [
      { host: '127.0.0.1', port: deadPort },
      { host: '127.0.0.1', port: origin.port },
    ],
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });

  await waitFor(() => pool.exits[0]!.healthy === true);
  // Con el fallback real el exit sigue sano aunque un destino este caido; espera
  // varios ciclos de health check para detectar cualquier falso negativo.
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.equal(pool.exits[0]!.healthy, true);
  assert.equal(pool.exits[0]!.failures, 0);
});

test('Health multi-target: si TODOS los destinos fallan, el exit queda no sano', async (t) => {
  const deadA = await freePort();
  const deadB = await freePort();
  const exit = await startExit({ name: 'exit-a' });
  const pool = new ExitPool([{ name: 'exit-a', host: '127.0.0.1', port: exit.port }]);
  const { gateway } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool,
    statsFile: statsFile(),
    healthIntervalMs: 50,
    healthTimeoutMs: 300,
    healthTargets: [
      { host: '127.0.0.1', port: deadA },
      { host: '127.0.0.1', port: deadB },
    ],
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(exit.server);
  });
  await waitFor(() => pool.exits[0]!.healthy === false);
});

test('Panel: /panel y / sirven el dashboard sin interceptar peticiones proxied', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a' });
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([{ name: 'exit-a', host: '127.0.0.1', port: exit.port }]),
    statsFile: statsFile(),
    statsToken: 'tok',
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
    await closeServer(origin.server);
    await closeServer(exit.server);
  });

  const panel = await httpGet({ port: httpPort, path: '/panel' });
  assert.equal(panel.status, 200);
  assert.match(panel.headers['content-type'] ?? '', /text\/html/);
  assert.match(panel.body, /local-proxy/);
  assert.match(panel.body, /STATS_TOKEN/);
  assert.ok(panel.headers['content-security-policy']);

  const root = await httpGet({ port: httpPort, path: '/' });
  assert.equal(root.status, 200);
  assert.match(root.body, /local-proxy/);

  // Una peticion proxied (absoluta) a /panel debe ir al origen, no al dashboard.
  const proxied = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: `${origin.url}/panel`,
    username: 'julio',
    password: 'clave',
  });
  assert.equal(proxied.status, 200);
  assert.equal(proxied.body, 'origin-ok');
});

test('Panel: se puede desactivar con panelEnabled=false', async (t) => {
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([]),
    statsFile: statsFile(),
    healthIntervalMs: 0,
    panelEnabled: false,
  });
  t.after(async () => {
    await gateway.close();
  });
  const response = await httpGet({ port: httpPort, path: '/panel' });
  assert.equal(response.status, 407);
});

test('/__stats incluye uptimeMs', async (t) => {
  const { gateway, httpPort } = await startGateway({
    pool: new ExitPool([]),
    statsFile: statsFile(),
    statsToken: 'tok',
    healthIntervalMs: 0,
  });
  t.after(async () => {
    await gateway.close();
  });
  const response = await httpGet({ port: httpPort, path: '/__stats?token=tok' });
  assert.equal(response.status, 200);
  const payload = JSON.parse(response.body);
  assert.equal(typeof payload.uptimeMs, 'number');
});
