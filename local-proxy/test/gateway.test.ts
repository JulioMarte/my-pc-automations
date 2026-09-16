import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { ExitPool } from '../src/router.ts';
import { startGateway, httpGet, httpGetThroughProxy } from './helpers.ts';

let counter = 0;
function statsFile(): string {
  counter += 1;
  return path.join(os.tmpdir(), `local-proxy-gateway-${process.pid}-${counter}.jsonl`);
}

test('gateway: /healthz responde 200', async (t) => {
  const { gateway, httpPort } = await startGateway({ pool: new ExitPool([]), healthIntervalMs: 0, statsFile: statsFile() });
  t.after(async () => {
    await gateway.close();
  });
  const response = await httpGet({ port: httpPort, path: '/healthz' });
  assert.equal(response.status, 200);
  const payload = JSON.parse(response.body);
  assert.equal(payload.ok, true);
  assert.equal(typeof payload.uptimeMs, 'number');
});

test('gateway: /readyz responde 200 con exit sano y 503 sin exits', async (t) => {
  const healthy = await startGateway({
    pool: new ExitPool([{ name: 'a', host: '127.0.0.1', port: 1 }]),
    healthIntervalMs: 0,
    statsFile: statsFile(),
  });
  const empty = await startGateway({ pool: new ExitPool([]), healthIntervalMs: 0, statsFile: statsFile() });
  t.after(async () => {
    await healthy.gateway.close();
    await empty.gateway.close();
  });
  assert.equal((await httpGet({ port: healthy.httpPort, path: '/readyz' })).status, 200);
  assert.equal((await httpGet({ port: empty.httpPort, path: '/readyz' })).status, 503);
});

test('gateway: sin exits devuelve 503 con retry-after', async (t) => {
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([]),
    healthIntervalMs: 0,
    statsFile: statsFile(),
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
});

test('gateway: /__stats exige token (403 sin token, 200 con token)', async (t) => {
  const { gateway, httpPort } = await startGateway({
    pool: new ExitPool([{ name: 'a', host: '127.0.0.1', port: 1 }]),
    statsToken: 'secreto',
    healthIntervalMs: 0,
    statsFile: statsFile(),
  });
  t.after(async () => {
    await gateway.close();
  });
  assert.equal((await httpGet({ port: httpPort, path: '/__stats' })).status, 403);
  assert.equal((await httpGet({ port: httpPort, path: '/__stats?token=malo' })).status, 403);
  const authorized = await httpGet({ port: httpPort, path: '/__stats?token=secreto' });
  assert.equal(authorized.status, 200);
  const payload = JSON.parse(authorized.body);
  assert.equal(payload.exits.length, 1);
});

test('gateway: lockout por fallos de auth devuelve 429', async (t) => {
  const { gateway, httpPort } = await startGateway({
    users: new Map([['julio', 'clave']]),
    pool: new ExitPool([]),
    authMaxFailures: 3,
    authWindowMs: 60000,
    authBlockMs: 60000,
    healthIntervalMs: 0,
    statsFile: statsFile(),
  });
  t.after(async () => {
    await gateway.close();
  });
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await httpGetThroughProxy({
      proxyPort: httpPort,
      targetUrl: 'http://127.0.0.1:1/',
      username: 'julio',
      password: 'mala',
    });
    assert.equal(response.status, 407);
  }
  const blocked = await httpGetThroughProxy({
    proxyPort: httpPort,
    targetUrl: 'http://127.0.0.1:1/',
    username: 'julio',
    password: 'mala',
  });
  assert.equal(blocked.status, 429);
});

test('gateway: /metrics abierto por defecto', async (t) => {
  const { gateway, httpPort } = await startGateway({ pool: new ExitPool([]), healthIntervalMs: 0, statsFile: statsFile() });
  t.after(async () => {
    await gateway.close();
  });
  const response = await httpGet({ port: httpPort, path: '/metrics' });
  assert.equal(response.status, 200);
  assert.ok(String(response.headers['content-type']).startsWith('text/plain'));
  assert.match(response.body, /localproxy_build_info/);
  assert.match(response.body, /localproxy_uptime_seconds/);
  assert.match(response.body, /localproxy_exit_healthy/);
});

test('gateway: /metrics exige token cuando esta configurado', async (t) => {
  const { gateway, httpPort } = await startGateway({
    pool: new ExitPool([]),
    metricsToken: 'tok',
    healthIntervalMs: 0,
    statsFile: statsFile(),
  });
  t.after(async () => {
    await gateway.close();
  });
  assert.equal((await httpGet({ port: httpPort, path: '/metrics' })).status, 403);
  assert.equal((await httpGet({ port: httpPort, path: '/metrics?token=malo' })).status, 403);
  assert.equal((await httpGet({ port: httpPort, path: '/metrics?token=tok' })).status, 200);
  const bearer = await httpGet({ port: httpPort, path: '/metrics', headers: { authorization: 'Bearer tok' } });
  assert.equal(bearer.status, 200);
});

test('gateway: /metrics no incrementa localproxy_requests_total', async (t) => {
  const { gateway, httpPort } = await startGateway({ pool: new ExitPool([]), healthIntervalMs: 0, statsFile: statsFile() });
  t.after(async () => {
    await gateway.close();
  });
  await httpGet({ port: httpPort, path: '/metrics' });
  const response = await httpGet({ port: httpPort, path: '/metrics' });
  assert.equal(response.status, 200);
  assert.doesNotMatch(response.body, /localproxy_requests_total\{/);
});

test('gateway: localproxy_build_info incluye rol y version', async (t) => {
  const { gateway, httpPort } = await startGateway({
    pool: new ExitPool([]),
    version: '9.9.9',
    healthIntervalMs: 0,
    statsFile: statsFile(),
  });
  t.after(async () => {
    await gateway.close();
  });
  const response = await httpGet({ port: httpPort, path: '/metrics' });
  assert.match(response.body, /localproxy_build_info\{role="gateway",version="9\.9\.9"\} 1/);
});
