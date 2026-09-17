// Monitor de salud ligero para local-proxy.
//
// Sondea GET /healthz y GET /readyz del gateway, detecta transiciones
// up <-> down y notifica por ntfy, Telegram o webhook generico. Sin
// dependencias de runtime: usa fetch nativo. Pensado para complementar el
// dashboard /panel (que es pull) con alertas push.
//
// Modos:
//   node scripts/monitor.ts          -> bucle infinito cada MONITOR_INTERVAL_MS
//   node scripts/monitor.ts --once   -> una sola pasada (Task Scheduler, cron,
//                                       systemd timer); el estado se guarda en
//                                       MONITOR_STATE_FILE para detectar
//                                       transiciones entre invocaciones.
//
// El estado y los secretos nunca se registran: el logger redacta tokens.

import { readFile, writeFile } from 'node:fs/promises';
import { loadEnv } from '../src/env.ts';
import { createLogger } from '../src/logger.ts';
import type { Logger } from '../src/logger.ts';

export type HealthState = 'up' | 'down';
export type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export interface HealthProbe {
  healthzStatus: number | null;
  readyzStatus: number | null;
  error: string | null;
}

export interface NotifierConfig {
  ntfyUrl?: string | undefined;
  ntfyToken?: string | undefined;
  telegramBotToken?: string | undefined;
  telegramChatId?: string | undefined;
  telegramApiBase?: string | undefined;
  webhookUrl?: string | undefined;
}

export interface MonitorConfig extends NotifierConfig {
  url: string;
  intervalMs: number;
  timeoutMs: number;
  token: string | undefined;
  stateFile: string;
  cooldownMs: number;
}

export interface MonitorState {
  state: HealthState;
  lastAlertAt: number;
}

export interface AlertPayload {
  prev: HealthState;
  next: HealthState;
  detail: string;
  text: string;
}

export interface BackendFailure {
  backend: string;
  error: string;
}

export interface AlertResult {
  delivered: string[];
  failed: BackendFailure[];
}

export interface Notifier {
  backends: string[];
  send(payload: AlertPayload): Promise<AlertResult>;
}

export interface RunOnceDeps {
  config: MonitorConfig;
  logger: Logger;
  notifier: Notifier;
  fetchImpl: FetchLike;
  now: () => number;
  readState: () => Promise<MonitorState | null>;
  writeState: (state: MonitorState) => Promise<void>;
  probe?: (config: MonitorConfig, fetchImpl: FetchLike) => Promise<HealthProbe>;
}

export interface RunResult {
  prev: HealthState;
  next: HealthState;
  detail: string;
  transition: boolean;
  alerted: boolean;
  suppressed: boolean;
  delivered: string[];
  failed: BackendFailure[];
  text: string | null;
}

export interface CliOptions {
  once: boolean;
}

export interface MainDeps {
  env?: Record<string, string | undefined>;
  argv?: string[];
  logger?: Logger;
  fetchImpl?: FetchLike;
  now?: () => number;
  stdout?: (line: string) => void;
}

const DEFAULT_URL = 'http://127.0.0.1:8888';
const DEFAULT_INTERVAL_MS = 60000;
const DEFAULT_TIMEOUT_MS = 5000;
const DEFAULT_COOLDOWN_MS = 600000;
const DEFAULT_STATE_FILE = 'monitor-state.json';
const DEFAULT_TELEGRAM_API_BASE = 'https://api.telegram.org';

function readString(env: Record<string, string | undefined>, key: string): string | undefined {
  const value = env[key];
  if (value === undefined) return undefined;
  const trimmed = value.trim();
  return trimmed === '' ? undefined : trimmed;
}

function readPositiveInt(
  env: Record<string, string | undefined>,
  key: string,
  fallback: number,
): number {
  const raw = readString(env, key);
  if (raw === undefined) return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function readNonNegativeInt(
  env: Record<string, string | undefined>,
  key: string,
  fallback: number,
): number {
  const raw = readString(env, key);
  if (raw === undefined) return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : fallback;
}

export function parseMonitorConfig(env: Record<string, string | undefined>): MonitorConfig {
  const url = readString(env, 'MONITOR_URL') ?? DEFAULT_URL;
  return {
    url: url.replace(/\/+$/, ''),
    intervalMs: readPositiveInt(env, 'MONITOR_INTERVAL_MS', DEFAULT_INTERVAL_MS),
    timeoutMs: readPositiveInt(env, 'MONITOR_TIMEOUT_MS', DEFAULT_TIMEOUT_MS),
    token: readString(env, 'MONITOR_TOKEN'),
    stateFile: readString(env, 'MONITOR_STATE_FILE') ?? DEFAULT_STATE_FILE,
    cooldownMs: readNonNegativeInt(env, 'ALERT_COOLDOWN_MS', DEFAULT_COOLDOWN_MS),
    ntfyUrl: readString(env, 'ALERT_NTFY_URL'),
    ntfyToken: readString(env, 'ALERT_NTFY_TOKEN'),
    telegramBotToken: readString(env, 'ALERT_TELEGRAM_BOT_TOKEN'),
    telegramChatId: readString(env, 'ALERT_TELEGRAM_CHAT_ID'),
    telegramApiBase: readString(env, 'ALERT_TELEGRAM_API_BASE') ?? DEFAULT_TELEGRAM_API_BASE,
    webhookUrl: readString(env, 'ALERT_WEBHOOK_URL'),
  };
}

export function parseArgs(argv: string[]): CliOptions {
  return { once: argv.includes('--once') };
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export function classifyHealth(probe: HealthProbe): HealthState {
  return probe.healthzStatus === 200 && probe.readyzStatus === 200 ? 'up' : 'down';
}

export function describeProbe(probe: HealthProbe): string {
  const healthz = probe.healthzStatus === null ? 'sin-respuesta' : String(probe.healthzStatus);
  const readyz = probe.readyzStatus === null ? 'sin-respuesta' : String(probe.readyzStatus);
  const parts = [`healthz=${healthz}`, `readyz=${readyz}`];
  if (probe.error) parts.push(`error=${probe.error}`);
  return parts.join(' ');
}

export function buildAlertText(prev: HealthState, next: HealthState, detail: string): string {
  if (prev === 'up' && next === 'down') return `proxy CAIDO: ${detail}`;
  if (prev === 'down' && next === 'up') return `proxy RECUPERADO: ${detail}`;
  return `proxy estado ${next}: ${detail}`;
}

interface EndpointProbe {
  status: number | null;
  error: string | null;
}

async function probeEndpoint(
  url: string,
  fetchImpl: FetchLike,
  timeoutMs: number,
  token: string | undefined,
): Promise<EndpointProbe> {
  try {
    const headers: Record<string, string> = {};
    if (token) headers.authorization = `Bearer ${token}`;
    const response = await fetchImpl(url, {
      method: 'GET',
      headers,
      signal: AbortSignal.timeout(timeoutMs),
    });
    return { status: response.status, error: null };
  } catch (error) {
    return { status: null, error: errorMessage(error) };
  }
}

export async function probeHealth(
  config: MonitorConfig,
  fetchImpl: FetchLike,
): Promise<HealthProbe> {
  const base = config.url.replace(/\/+$/, '');
  const [healthz, readyz] = await Promise.all([
    probeEndpoint(`${base}/healthz`, fetchImpl, config.timeoutMs, config.token),
    probeEndpoint(`${base}/readyz`, fetchImpl, config.timeoutMs, config.token),
  ]);
  return {
    healthzStatus: healthz.status,
    readyzStatus: readyz.status,
    error: healthz.error ?? readyz.error,
  };
}

export function createNotifier(config: NotifierConfig, fetchImpl: FetchLike): Notifier {
  const backends: string[] = [];
  if (config.ntfyUrl) backends.push('ntfy');
  if (config.telegramBotToken && config.telegramChatId) backends.push('telegram');
  if (config.webhookUrl) backends.push('webhook');

  const send = async (payload: AlertPayload): Promise<AlertResult> => {
    const delivered: string[] = [];
    const failed: BackendFailure[] = [];
    const attempts: Array<{ backend: string; run: () => Promise<void> }> = [];

    const ntfyUrl = config.ntfyUrl;
    if (ntfyUrl) {
      attempts.push({
        backend: 'ntfy',
        run: async () => {
          const headers: Record<string, string> = { 'content-type': 'text/plain; charset=utf-8' };
          if (config.ntfyToken) headers.authorization = `Bearer ${config.ntfyToken}`;
          const response = await fetchImpl(ntfyUrl, { method: 'POST', headers, body: payload.text });
          if (!response.ok) throw new Error(`ntfy respondio HTTP ${response.status}`);
        },
      });
    }

    const telegramBotToken = config.telegramBotToken;
    const telegramChatId = config.telegramChatId;
    if (telegramBotToken && telegramChatId) {
      const base = (config.telegramApiBase ?? DEFAULT_TELEGRAM_API_BASE).replace(/\/+$/, '');
      const telegramUrl = `${base}/bot${telegramBotToken}/sendMessage`;
      attempts.push({
        backend: 'telegram',
        run: async () => {
          const response = await fetchImpl(telegramUrl, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
              chat_id: telegramChatId,
              text: payload.text,
              disable_web_page_preview: true,
            }),
          });
          if (!response.ok) throw new Error(`telegram respondio HTTP ${response.status}`);
        },
      });
    }

    const webhookUrl = config.webhookUrl;
    if (webhookUrl) {
      attempts.push({
        backend: 'webhook',
        run: async () => {
          const response = await fetchImpl(webhookUrl, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
              source: 'local-proxy-monitor',
              prev: payload.prev,
              next: payload.next,
              detail: payload.detail,
              text: payload.text,
            }),
          });
          if (!response.ok) throw new Error(`webhook respondio HTTP ${response.status}`);
        },
      });
    }

    await Promise.all(
      attempts.map(async (attempt) => {
        try {
          await attempt.run();
          delivered.push(attempt.backend);
        } catch (error) {
          failed.push({ backend: attempt.backend, error: errorMessage(error) });
        }
      }),
    );

    return { delivered, failed };
  };

  return { backends, send };
}

export async function readStateFile(file: string): Promise<MonitorState | null> {
  try {
    const raw = await readFile(file, 'utf8');
    const data = JSON.parse(raw) as { state?: unknown; lastAlertAt?: unknown };
    if (data.state !== 'up' && data.state !== 'down') return null;
    const lastAlertAt =
      typeof data.lastAlertAt === 'number' && Number.isFinite(data.lastAlertAt)
        ? data.lastAlertAt
        : 0;
    return { state: data.state, lastAlertAt };
  } catch {
    return null;
  }
}

export async function writeStateFile(file: string, state: MonitorState): Promise<void> {
  await writeFile(file, `${JSON.stringify(state)}\n`, 'utf8');
}

export async function runOnce(deps: RunOnceDeps): Promise<RunResult> {
  const { config, logger, notifier } = deps;
  const prior = await deps.readState();
  const prev: HealthState = prior?.state ?? 'up';
  const lastAlertAt = prior?.lastAlertAt ?? 0;

  const probe = await (deps.probe ?? probeHealth)(config, deps.fetchImpl);
  const next = classifyHealth(probe);
  const detail = describeProbe(probe);
  const transition = next !== prev;

  let alerted = false;
  let suppressed = false;
  let text: string | null = null;
  let delivered: string[] = [];
  let failed: BackendFailure[] = [];

  if (transition) {
    text = buildAlertText(prev, next, detail);
    const now = deps.now();
    if (notifier.backends.length === 0) {
      suppressed = true;
      logger.warn?.('transicion detectada sin backends de alerta configurados', {
        prev,
        next,
        detail,
      });
    } else if (now - lastAlertAt < config.cooldownMs) {
      suppressed = true;
      logger.info?.('alerta suprimida por cooldown', {
        prev,
        next,
        remainingMs: config.cooldownMs - (now - lastAlertAt),
      });
    } else {
      const result = await notifier.send({ prev, next, detail, text });
      delivered = result.delivered;
      failed = result.failed;
      alerted = delivered.length > 0;
      if (failed.length > 0) logger.error?.('fallo al enviar alerta', { failed });
      if (alerted) logger.info?.('alerta enviada', { prev, next, delivered });
    }
  }

  // Solo se persiste la transicion si la alerta se envio o si se decidio
  // deliberadamente no enviarla (cooldown / sin backends). Si el envio fallo
  // por completo, no se persiste para reintentar en el siguiente ciclo.
  const commit = !transition || alerted || suppressed;
  if (commit) {
    const state: MonitorState = { state: next, lastAlertAt: alerted ? deps.now() : lastAlertAt };
    await deps.writeState(state);
  }

  return { prev, next, detail, transition, alerted, suppressed, delivered, failed, text };
}

function humanLine(result: RunResult): string {
  const status = result.next === 'up' ? 'UP' : 'DOWN';
  let action = '';
  if (result.alerted) action = ` alerta=enviada(${result.delivered.join(',')})`;
  else if (result.suppressed) action = ' alerta=suprimida';
  return `monitor: estado=${status}${action} :: ${result.detail}`;
}

export async function main(deps: MainDeps = {}): Promise<number> {
  // En uso real (CLI) carga el .env del proyecto, igual que el gateway/exit, para
  // poder definir ALERT_* y MONITOR_* ahi. Los tests pasan deps.env explicito.
  if (!deps.env) loadEnv();
  const env = deps.env ?? process.env;
  const argv = deps.argv ?? process.argv.slice(2);
  const write =
    deps.stdout ??
    ((line: string): void => {
      process.stdout.write(`${line}\n`);
    });
  const logger = deps.logger ?? createLogger({ role: 'monitor', out: write, err: write });
  const fetchImpl = deps.fetchImpl ?? fetch;
  const now = deps.now ?? ((): number => Date.now());
  const config = parseMonitorConfig(env);
  const options = parseArgs(argv);
  const notifier = createNotifier(config, fetchImpl);
  const readState = (): Promise<MonitorState | null> => readStateFile(config.stateFile);
  const writeState = (state: MonitorState): Promise<void> =>
    writeStateFile(config.stateFile, state);

  if (notifier.backends.length === 0) {
    logger.warn?.(
      'no hay backends de alerta configurados (ALERT_NTFY_URL / ALERT_TELEGRAM_* / ALERT_WEBHOOK_URL)',
      {},
    );
  }

  const tick = async (): Promise<RunResult> => {
    const result = await runOnce({
      config,
      logger,
      notifier,
      fetchImpl,
      now,
      readState,
      writeState,
    });
    write(humanLine(result));
    return result;
  };

  if (options.once) {
    await tick();
    return 0;
  }

  let stopping = false;
  let timer: NodeJS.Timeout | undefined;
  let resolveDelay: (() => void) | undefined;
  const stop = (): void => {
    stopping = true;
    if (timer) {
      clearTimeout(timer);
      timer = undefined;
    }
    if (resolveDelay) {
      const resolve = resolveDelay;
      resolveDelay = undefined;
      resolve();
    }
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);

  while (!stopping) {
    try {
      await tick();
    } catch (error) {
      logger.error?.('ciclo del monitor fallo', { error: errorMessage(error) });
    }
    if (stopping) break;
    await new Promise<void>((resolve) => {
      resolveDelay = resolve;
      timer = setTimeout(() => {
        timer = undefined;
        resolveDelay = undefined;
        resolve();
      }, config.intervalMs);
    });
  }
  return 0;
}

if (import.meta.main) {
  main()
    .then((code) => {
      process.exitCode = code;
    })
    .catch((error: unknown) => {
      process.stdout.write(
        `${JSON.stringify({
          ts: new Date().toISOString(),
          level: 'error',
          msg: 'monitor fallo',
          error: errorMessage(error),
        })}\n`,
      );
      process.exitCode = 1;
    });
}
