import test from 'node:test';
import assert from 'node:assert/strict';
import { isBlockedHost } from '../src/exit.ts';
import {
  startExit,
  startOrigin,
  closeServer,
  httpGet,
  httpGetThroughProxy,
  connectThroughProxy,
} from './helpers.ts';

test('isBlockedHost: bloquea loopback, privadas, link-local, IPv6 locales y puerto 25', () => {
  for (const host of [
    '127.0.0.1',
    '10.0.0.1',
    '172.16.0.1',
    '192.168.1.1',
    '100.64.0.1',
    '169.254.169.254',
    '::1',
    'fe80::1',
    'localhost',
  ]) {
    assert.equal(isBlockedHost(host, 80), true, `${host} deberia bloquearse`);
  }
  assert.equal(isBlockedHost('8.8.8.8', 25), true);
  assert.equal(isBlockedHost('127.0.0.1', 25), true);
});

test('isBlockedHost: permite destinos publicos y hostnames', () => {
  assert.equal(isBlockedHost('8.8.8.8', 80), false);
  assert.equal(isBlockedHost('example.com', 80), false);
  assert.equal(isBlockedHost('1.1.1.1', 443), false);
});

test('exit: /__health responde 200 JSON sin auth', async (t) => {
  const exit = await startExit({ name: 'exit-a', user: 'gw', pass: 'clave' });
  t.after(async () => {
    await closeServer(exit.server);
  });
  const response = await httpGet({ port: exit.port, path: '/__health' });
  assert.equal(response.status, 200);
  const payload = JSON.parse(response.body);
  assert.equal(payload.ok, true);
  assert.equal(payload.name, 'exit-a');
  assert.equal(typeof payload.uptimeMs, 'number');
});

test('exit: URL absoluta a /__health se proxya al origen, no colisiona con el health', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a', blockPrivate: false });
  t.after(async () => {
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: exit.port,
    targetUrl: `${origin.url}/__health`,
    username: '',
    password: '',
  });
  assert.equal(response.status, 200);
  assert.equal(response.body, 'origin-ok');
  assert.equal(response.headers['x-origin'], 'yes');
  assert.doesNotMatch(response.body, /"ok":true/);
});

test('exit: CONNECT a 127.0.0.1 con blockPrivate devuelve 403', async (t) => {
  const exit = await startExit({ name: 'exit-a', blockPrivate: true });
  t.after(async () => {
    await closeServer(exit.server);
  });
  await assert.rejects(
    connectThroughProxy({ proxyPort: exit.port, target: '127.0.0.1:80' }),
    /CONNECT respondio 403/,
  );
});

test('exit: HTTP absoluto a 127.0.0.1 con blockPrivate devuelve 403', async (t) => {
  const exit = await startExit({ name: 'exit-a', blockPrivate: true });
  t.after(async () => {
    await closeServer(exit.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: exit.port,
    targetUrl: 'http://127.0.0.1:1/',
    username: '',
    password: '',
  });
  assert.equal(response.status, 403);
});

test('exit: /metrics abierto por defecto', async (t) => {
  const exit = await startExit({ name: 'exit-a' });
  t.after(async () => {
    await closeServer(exit.server);
  });
  const response = await httpGet({ port: exit.port, path: '/metrics' });
  assert.equal(response.status, 200);
  assert.ok(String(response.headers['content-type']).startsWith('text/plain'));
  assert.match(response.body, /localproxy_build_info/);
  assert.match(response.body, /localproxy_uptime_seconds/);
});

test('exit: /metrics exige token cuando esta configurado', async (t) => {
  const exit = await startExit({ name: 'exit-a', metricsToken: 'tok' });
  t.after(async () => {
    await closeServer(exit.server);
  });
  assert.equal((await httpGet({ port: exit.port, path: '/metrics' })).status, 403);
  assert.equal((await httpGet({ port: exit.port, path: '/metrics?token=malo' })).status, 403);
  assert.equal((await httpGet({ port: exit.port, path: '/metrics?token=tok' })).status, 200);
});

test('exit: users multiples autentican y proxya con cada credencial', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({
    name: 'exit-a',
    users: [
      { user: 'a', pass: '1' },
      { user: 'b', pass: '2' },
    ],
  });
  t.after(async () => {
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const validas: ReadonlyArray<readonly [string, string]> = [
    ['a', '1'],
    ['b', '2'],
  ];
  for (const [username, password] of validas) {
    const response = await httpGetThroughProxy({
      proxyPort: exit.port,
      targetUrl: `${origin.url}/`,
      username,
      password,
    });
    assert.equal(response.status, 200, `${username}:${password} deberia autenticar`);
    assert.equal(response.body, 'origin-ok');
  }
  const invalidas: ReadonlyArray<readonly [string, string]> = [
    ['a', '2'],
    ['b', '1'],
    ['', ''],
  ];
  for (const [username, password] of invalidas) {
    const response = await httpGetThroughProxy({
      proxyPort: exit.port,
      targetUrl: `${origin.url}/`,
      username,
      password,
    });
    assert.equal(response.status, 407, `${username}:${password} deberia rechazarse`);
  }
});

test('exit: rotacion sin downtime acepta ambas claves del mismo usuario', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({
    name: 'exit-a',
    users: [
      { user: 'a', pass: 'old' },
      { user: 'a', pass: 'new' },
    ],
  });
  t.after(async () => {
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  for (const password of ['old', 'new']) {
    const response = await httpGetThroughProxy({
      proxyPort: exit.port,
      targetUrl: `${origin.url}/`,
      username: 'a',
      password,
    });
    assert.equal(response.status, 200, `clave ${password} deberia seguir valida`);
  }
  const stale = await httpGetThroughProxy({
    proxyPort: exit.port,
    targetUrl: `${origin.url}/`,
    username: 'a',
    password: 'otra',
  });
  assert.equal(stale.status, 407);
});

test('exit: compatibilidad legacy con user/pass sigue autenticando', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a', user: 'legacy', pass: 'pw' });
  t.after(async () => {
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const ok = await httpGetThroughProxy({
    proxyPort: exit.port,
    targetUrl: `${origin.url}/`,
    username: 'legacy',
    password: 'pw',
  });
  assert.equal(ok.status, 200);
  const bad = await httpGetThroughProxy({
    proxyPort: exit.port,
    targetUrl: `${origin.url}/`,
    username: 'legacy',
    password: 'mala',
  });
  assert.equal(bad.status, 407);
});

test('exit: localproxy_auth_failures_total incrementa tras un 407', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a', users: [{ user: 'a', pass: '1' }] });
  t.after(async () => {
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const rejected = await httpGetThroughProxy({
    proxyPort: exit.port,
    targetUrl: `${origin.url}/`,
    username: 'a',
    password: 'mala',
  });
  assert.equal(rejected.status, 407);
  const metrics = await httpGet({ port: exit.port, path: '/metrics' });
  assert.equal(metrics.status, 200);
  const match = metrics.body.match(/^localproxy_auth_failures_total (\d+)$/m);
  assert.ok(match, 'deberia existir la metrica de fallos de auth');
  assert.ok(Number(match[1]) >= 1);
});

test('exit: URL absoluta a /metrics se proxya al origen, no colisiona con las metricas', async (t) => {
  const origin = await startOrigin();
  const exit = await startExit({ name: 'exit-a', blockPrivate: false });
  t.after(async () => {
    await closeServer(origin.server);
    await closeServer(exit.server);
  });
  const response = await httpGetThroughProxy({
    proxyPort: exit.port,
    targetUrl: `${origin.url}/metrics`,
    username: '',
    password: '',
  });
  assert.equal(response.status, 200);
  assert.equal(response.body, 'origin-ok');
  assert.equal(response.headers['x-origin'], 'yes');
  assert.doesNotMatch(response.body, /# HELP/);
});
