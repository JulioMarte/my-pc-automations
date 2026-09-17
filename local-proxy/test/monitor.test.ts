import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { mkdtemp, rm } from 'node:fs/promises';
import { listen, closeServer, trackSockets } from './helpers.ts';
import { createLogger } from '../src/logger.ts';
import {
  buildAlertText,
  classifyHealth,
  createNotifier,
  describeProbe,
  main,
  parseMonitorConfig,
  readStateFile,
  runOnce,
  writeStateFile,
} from '../scripts/monitor.ts';
import type { FetchLike, HealthProbe, MonitorConfig, MonitorState } from '../scripts/monitor.ts';

interface CapturedRequest {
  method: string;
  url: string;
  body: string;
  headers: http.IncomingHttpHeaders;
}

interface CaptureServer {
  server: http.Server;
  url: string;
  requests: CapturedRequest[];
}

async function startCapture(): Promise<CaptureServer> {
  const requests: CapturedRequest[] = [];
  const server = http.createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => {
      requests.push({
        method: request.method ?? 'GET',
        url: request.url ?? '/',
        body: Buffer.concat(chunks).toString('utf8'),
        headers: request.headers,
      });
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end('{"ok":true}');
    });
  });
  trackSockets(server);
  const port = await listen(server);
  return { server, url: `http://127.0.0.1:${port}`, requests };
}

interface FakeGateway {
  server: http.Server;
  url: string;
  setHealth(status: number): void;
  setReady(status: number): void;
}

async function startFakeGateway(): Promise<FakeGateway> {
  const statuses = { healthz: 200, readyz: 200 };
  const server = http.createServer((request, response) => {
    if (request.url === '/healthz') {
      response.writeHead(statuses.healthz, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ok: statuses.healthz === 200 }));
      return;
    }
    if (request.url === '/readyz') {
      response.writeHead(statuses.readyz, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ready: statuses.readyz === 200 }));
      return;
    }
    response.writeHead(404);
    response.end();
  });
  trackSockets(server);
  const port = await listen(server);
  return {
    server,
    url: `http://127.0.0.1:${port}`,
    setHealth: (status) => {
      statuses.healthz = status;
    },
    setReady: (status) => {
      statuses.readyz = status;
    },
  };
}

function makeConfig(overrides: Partial<MonitorConfig> = {}): MonitorConfig {
  return {
    url: 'http://127.0.0.1:1',
    intervalMs: 60000,
    timeoutMs: 2000,
    token: undefined,
    stateFile: path.join(os.tmpdir(), `monitor-test-${process.pid}-${Math.random()}.json`),
    cooldownMs: 0,
    ntfyUrl: undefined,
    ntfyToken: undefined,
    telegramBotToken: undefined,
    telegramChatId: undefined,
    telegramApiBase: 'https://api.telegram.org',
    webhookUrl: undefined,
    ...overrides,
  };
}

function silentLogger() {
  const lines: string[] = [];
  const logger = createLogger({
    level: 'debug',
    out: (line) => lines.push(line),
    err: (line) => lines.push(line),
  });
  return { logger, lines };
}

function memoryState(initial: MonitorState | null = null) {
  let state = initial;
  return {
    readState: async (): Promise<MonitorState | null> => state,
    writeState: async (next: MonitorState): Promise<void> => {
      state = next;
    },
    get: (): MonitorState | null => state,
  };
}

test('monitor: classifyHealth, describeProbe y buildAlertText', () => {
  assert.equal(classifyHealth({ healthzStatus: 200, readyzStatus: 200, error: null }), 'up');
  assert.equal(classifyHealth({ healthzStatus: 200, readyzStatus: 503, error: null }), 'down');
  assert.equal(classifyHealth({ healthzStatus: 503, readyzStatus: 200, error: null }), 'down');
  assert.equal(classifyHealth({ healthzStatus: null, readyzStatus: null, error: 'boom' }), 'down');
  assert.match(
    describeProbe({ healthzStatus: null, readyzStatus: null, error: 'ECONNREFUSED' }),
    /error=ECONNREFUSED/,
  );
  assert.match(buildAlertText('up', 'down', 'healthz=503'), /CAIDO/);
  assert.match(buildAlertText('down', 'up', 'healthz=200'), /RECUPERADO/);
});

test('monitor: parseMonitorConfig aplica defaults y overrides', () => {
  const defaults = parseMonitorConfig({});
  assert.equal(defaults.url, 'http://127.0.0.1:8888');
  assert.equal(defaults.intervalMs, 60000);
  assert.equal(defaults.timeoutMs, 5000);
  assert.equal(defaults.cooldownMs, 600000);
  assert.equal(defaults.stateFile, 'monitor-state.json');
  assert.equal(defaults.telegramApiBase, 'https://api.telegram.org');

  const custom = parseMonitorConfig({
    MONITOR_URL: 'http://example.test:9999/',
    MONITOR_INTERVAL_MS: '1500',
    MONITOR_TIMEOUT_MS: '250',
    MONITOR_TOKEN: 'tok',
    MONITOR_STATE_FILE: 'C:/tmp/state.json',
    ALERT_COOLDOWN_MS: '0',
    ALERT_NTFY_URL: 'https://ntfy.sh/topic',
    ALERT_TELEGRAM_BOT_TOKEN: 'b',
    ALERT_TELEGRAM_CHAT_ID: 'c',
    ALERT_WEBHOOK_URL: 'https://hook.test/x',
  });
  assert.equal(custom.url, 'http://example.test:9999');
  assert.equal(custom.intervalMs, 1500);
  assert.equal(custom.timeoutMs, 250);
  assert.equal(custom.token, 'tok');
  assert.equal(custom.stateFile, 'C:/tmp/state.json');
  assert.equal(custom.cooldownMs, 0);
  assert.equal(custom.ntfyUrl, 'https://ntfy.sh/topic');
  assert.equal(custom.telegramBotToken, 'b');
  assert.equal(custom.telegramChatId, 'c');
  assert.equal(custom.webhookUrl, 'https://hook.test/x');
});

test('monitor: createNotifier envia a ntfy, Telegram y webhook', async (t) => {
  const capture = await startCapture();
  t.after(async () => {
    await closeServer(capture.server);
  });
  const config = makeConfig({
    ntfyUrl: `${capture.url}/topic`,
    ntfyToken: 'secret-token',
    telegramBotToken: '123:ABC',
    telegramChatId: '42',
    telegramApiBase: capture.url,
    webhookUrl: `${capture.url}/hook`,
  });
  const notifier = createNotifier(config, fetch);
  assert.deepEqual([...notifier.backends].sort(), ['ntfy', 'telegram', 'webhook']);

  const payload = {
    prev: 'up' as const,
    next: 'down' as const,
    detail: 'healthz=503',
    text: 'proxy CAIDO: healthz=503',
  };
  const result = await notifier.send(payload);
  assert.deepEqual([...result.delivered].sort(), ['ntfy', 'telegram', 'webhook']);
  assert.deepEqual(result.failed, []);

  const ntfy = capture.requests.find((request) => request.url === '/topic');
  assert.ok(ntfy);
  assert.equal(ntfy.method, 'POST');
  assert.equal(ntfy.body, payload.text);
  assert.equal(ntfy.headers.authorization, 'Bearer secret-token');

  const telegram = capture.requests.find((request) => request.url === '/bot123:ABC/sendMessage');
  assert.ok(telegram);
  const telegramBody = JSON.parse(telegram.body) as { chat_id: string; text: string };
  assert.equal(telegramBody.chat_id, '42');
  assert.equal(telegramBody.text, payload.text);

  const webhook = capture.requests.find((request) => request.url === '/hook');
  assert.ok(webhook);
  const webhookBody = JSON.parse(webhook.body) as { prev: string; next: string; text: string };
  assert.equal(webhookBody.prev, 'up');
  assert.equal(webhookBody.next, 'down');
  assert.equal(webhookBody.text, payload.text);
});

test('monitor: un backend caido no impide los demas', async (t) => {
  const capture = await startCapture();
  t.after(async () => {
    await closeServer(capture.server);
  });
  const config = makeConfig({
    ntfyUrl: `${capture.url}/topic`,
    webhookUrl: 'http://127.0.0.1:1/hook',
  });
  const notifier = createNotifier(config, fetch);
  const result = await notifier.send({
    prev: 'up',
    next: 'down',
    detail: 'x',
    text: 'proxy CAIDO: x',
  });
  assert.deepEqual(result.delivered, ['ntfy']);
  assert.equal(result.failed.length, 1);
  assert.equal(result.failed[0]!.backend, 'webhook');
});

test('monitor: detecta caida y recuperacion una sola vez', async (t) => {
  const gateway = await startFakeGateway();
  const capture = await startCapture();
  t.after(async () => {
    await closeServer(gateway.server);
    await closeServer(capture.server);
  });
  const { logger } = silentLogger();
  const config = makeConfig({
    url: gateway.url,
    cooldownMs: 0,
    ntfyUrl: `${capture.url}/topic`,
  });
  const notifier = createNotifier(config, fetch);
  const state = memoryState(null);
  const deps = {
    config,
    logger,
    notifier,
    fetchImpl: fetch,
    now: () => Date.now(),
    readState: state.readState,
    writeState: state.writeState,
  };

  const initial = await runOnce(deps);
  assert.equal(initial.prev, 'up');
  assert.equal(initial.next, 'up');
  assert.equal(initial.transition, false);
  assert.equal(capture.requests.length, 0);

  gateway.setReady(503);
  const down = await runOnce(deps);
  assert.equal(down.next, 'down');
  assert.equal(down.transition, true);
  assert.equal(down.alerted, true);
  assert.equal(capture.requests.length, 1);
  assert.match(capture.requests[0]!.body, /proxy CAIDO/);

  const stillDown = await runOnce(deps);
  assert.equal(stillDown.transition, false);
  assert.equal(capture.requests.length, 1);

  gateway.setReady(200);
  const recovered = await runOnce(deps);
  assert.equal(recovered.next, 'up');
  assert.equal(recovered.transition, true);
  assert.equal(recovered.alerted, true);
  assert.equal(capture.requests.length, 2);
  assert.match(capture.requests[1]!.body, /proxy RECUPERADO/);
});

test('monitor: el cooldown suprime alertas duplicadas', async (t) => {
  const capture = await startCapture();
  t.after(async () => {
    await closeServer(capture.server);
  });
  const { logger, lines } = silentLogger();
  const config = makeConfig({ cooldownMs: 600000, ntfyUrl: `${capture.url}/topic` });
  const notifier = createNotifier(config, fetch);
  let probeState: 'up' | 'down' = 'down';
  const probe = async (): Promise<HealthProbe> =>
    probeState === 'up'
      ? { healthzStatus: 200, readyzStatus: 200, error: null }
      : { healthzStatus: 200, readyzStatus: 503, error: null };
  const state = memoryState(null);
  const now = (): number => 1_700_000_000_000;
  const deps = {
    config,
    logger,
    notifier,
    fetchImpl: fetch,
    now,
    readState: state.readState,
    writeState: state.writeState,
    probe,
  };

  const down = await runOnce(deps);
  assert.equal(down.alerted, true);
  assert.equal(capture.requests.length, 1);

  probeState = 'up';
  const recovered = await runOnce(deps);
  assert.equal(recovered.transition, true);
  assert.equal(recovered.alerted, false);
  assert.equal(recovered.suppressed, true);
  assert.equal(capture.requests.length, 1);
  assert.ok(lines.some((line) => line.includes('cooldown')));
});

test('monitor: sin backends registra warn y no falla', async (t) => {
  const gateway = await startFakeGateway();
  t.after(async () => {
    await closeServer(gateway.server);
  });
  gateway.setReady(503);
  const { logger, lines } = silentLogger();
  const config = makeConfig({ url: gateway.url, cooldownMs: 0 });
  const notifier = createNotifier(config, fetch);
  const state = memoryState(null);
  const result = await runOnce({
    config,
    logger,
    notifier,
    fetchImpl: fetch,
    now: () => Date.now(),
    readState: state.readState,
    writeState: state.writeState,
  });
  assert.equal(result.next, 'down');
  assert.equal(result.alerted, false);
  assert.equal(result.suppressed, true);
  assert.ok(lines.some((line) => line.includes('sin backends')));
});

test('monitor: --once detecta transiciones entre invocaciones con state file', async (t) => {
  const gateway = await startFakeGateway();
  const capture = await startCapture();
  const dir = await mkdtemp(path.join(os.tmpdir(), 'monitor-once-'));
  t.after(async () => {
    await closeServer(gateway.server);
    await closeServer(capture.server);
    await rm(dir, { recursive: true, force: true });
  });
  const stateFile = path.join(dir, 'state.json');
  const config = makeConfig({
    url: gateway.url,
    stateFile,
    cooldownMs: 0,
    ntfyUrl: `${capture.url}/topic`,
  });
  const { logger } = silentLogger();

  const run = async () => {
    const notifier = createNotifier(config, fetch);
    return runOnce({
      config,
      logger,
      notifier,
      fetchImpl: fetch,
      now: () => Date.now(),
      readState: () => readStateFile(stateFile),
      writeState: (next) => writeStateFile(stateFile, next),
    });
  };

  gateway.setReady(503);
  const first = await run();
  assert.equal(first.next, 'down');
  assert.equal(first.alerted, true);
  const persisted = await readStateFile(stateFile);
  assert.equal(persisted?.state, 'down');

  gateway.setReady(200);
  const second = await run();
  assert.equal(second.prev, 'down');
  assert.equal(second.next, 'up');
  assert.equal(second.alerted, true);
  assert.equal(capture.requests.length, 2);
  assert.match(capture.requests[0]!.body, /CAIDO/);
  assert.match(capture.requests[1]!.body, /RECUPERADO/);
});

test('monitor: main --once no arranca el bucle y registra la transicion', async (t) => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'monitor-main-'));
  t.after(async () => {
    await rm(dir, { recursive: true, force: true });
  });
  const lines: string[] = [];
  const fakeFetch: FetchLike = async (input) => {
    const status = String(input).endsWith('/healthz') ? 200 : 503;
    return new Response('{}', { status });
  };
  const code = await main({
    env: {
      MONITOR_URL: 'http://gateway.test',
      MONITOR_STATE_FILE: path.join(dir, 'state.json'),
    },
    argv: ['--once'],
    stdout: (line) => lines.push(line),
    fetchImpl: fakeFetch,
    now: () => 1_700_000_000_000,
  });
  assert.equal(code, 0);
  assert.ok(lines.some((line) => line.includes('estado=DOWN')));
  assert.equal((await readStateFile(path.join(dir, 'state.json')))?.state, 'down');
});
