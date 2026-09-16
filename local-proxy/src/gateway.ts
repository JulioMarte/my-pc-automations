import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import net from 'node:net';
import { loadEnv, watchEnv, envString, envNumber, envList } from './env.ts';
import { connectViaHttpProxy, forwardHttp, pipeUpgrade, upgradeHeaders, basic, ProxyError } from './upstream.ts';
import { createSocks5Server } from './socks5.ts';
import {
  createAuthenticator,
  decodeBasic,
  parseUsers,
  ExitPool,
  safeEqual,
  createAuthLimiter,
  type ParsedUser,
  type ExitConfig,
  type Exit,
  type AuthLimiter,
} from './router.ts';
import { Registry, startTimer, elapsedSeconds, type Counter } from './metrics.ts';
import { createLogger, parseLogLevel, parseLogFormat, type Logger } from './logger.ts';
import { ConnectionLimiter } from './limits.ts';

const RETRYABLE_STATUS = new Set([407, 502, 503, 504]);
const HTTP_TIMEOUTS = { headersTimeout: 10000, requestTimeout: 30000, keepAliveTimeout: 10000 };
const HEALTH_JITTER = 0.2;
const HEALTH_STAGGER_MS = 250;

export type GatewayLogger = Logger;

export interface HealthTarget {
  host: string;
  port: number;
}

export interface GatewayConfig {
  host?: string;
  httpPort?: number;
  socksPort?: number;
  users?: Map<string, string>;
  pool?: ExitPool;
  statsFile?: string;
  statsToken?: string;
  connectTimeoutMs?: number;
  healthIntervalMs?: number;
  healthTarget?: HealthTarget;
  healthTargets?: HealthTarget[];
  healthTimeoutMs?: number;
  maxConnections?: number;
  maxConnectionsPerUser?: number;
  limiter?: ConnectionLimiter;
  authLimiter?: AuthLimiter;
  authMaxFailures?: number;
  authWindowMs?: number;
  authBlockMs?: number;
  readyz?: boolean;
  logger?: Logger;
  metrics?: Registry;
  metricsToken?: string;
  version?: string;
}

export interface GatewayAddresses {
  httpPort: number;
  socksPort: number;
}

// Sin exits: error distinguible para mapear a 503.
class NoExitsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NoExitsError';
  }
}

function resolveFile(file: string): string {
  return path.isAbsolute(file) ? file : path.join(import.meta.dirname, '..', file);
}

function normalizeAddress(address: string | undefined): string {
  if (!address) return '';
  return address.startsWith('::ffff:') ? address.slice(7) : address;
}

function pathnameOf(url: string | undefined): string {
  const value = url ?? '';
  const index = value.indexOf('?');
  return index === -1 ? value : value.slice(0, index);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function statusForError(error: unknown): number {
  if (error instanceof ProxyError) return error.statusCode === 504 ? 504 : 502;
  return 502;
}

function circuitValue(state: string): number {
  if (state === 'open') return 2;
  if (state === 'halfOpen') return 1;
  return 0;
}

function portOf(server: http.Server | net.Server, fallback: number): number {
  const address = server.address();
  if (address && typeof address === 'object') return address.port;
  return fallback;
}

export function parseExits(data: unknown): ExitConfig[] {
  if (!Array.isArray(data)) throw new Error('exits.json debe ser un array');
  const seen = new Set<string>();
  return data.map((entry: unknown): ExitConfig => {
    if (!entry || typeof entry !== 'object') throw new Error('cada exit necesita "name" y "host"');
    const exit = entry as Record<string, unknown>;
    if (!exit.name || !exit.host) throw new Error('cada exit necesita "name" y "host"');
    const name = String(exit.name);
    if (seen.has(name)) throw new Error(`exit duplicado: ${name}`);
    seen.add(name);
    return {
      name,
      location: exit.location ? String(exit.location) : '',
      host: String(exit.host),
      port: Number(exit.port || 8899),
      user: exit.user ? String(exit.user) : '',
      pass: exit.pass ? String(exit.pass) : '',
    };
  });
}

export function loadExits(file: string): ExitConfig[] {
  const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  return parseExits(JSON.parse(text));
}

export function parseTarget(authority: string): HealthTarget {
  const value = String(authority);
  const separator = value.lastIndexOf(':');
  if (separator === -1) return { host: value.replace(/^\[|\]$/g, ''), port: 443 };
  const host = value.slice(0, separator).replace(/^\[|\]$/g, '');
  const port = Number(value.slice(separator + 1)) || 443;
  return { host, port };
}

export function parseHealthTarget(raw: unknown): HealthTarget {
  const value = String(raw || 'api.ipify.org:443');
  const separator = value.lastIndexOf(':');
  const host = value.slice(0, separator).replace(/^\[|\]$/g, '');
  const port = Number(value.slice(separator + 1)) || 443;
  return { host, port };
}

interface Meter {
  countUp(chunk: Buffer): void;
  countDown(chunk: Buffer): void;
  done(): void;
}

function createMeter({ exit, label, statsFile, bytes }: { exit: Exit; label: string; statsFile: string; bytes: Counter }): Meter {
  const startedAt = Date.now();
  let up = 0;
  let down = 0;
  let finished = false;
  exit.connections += 1;
  return {
    countUp: (chunk: Buffer): void => {
      up += chunk.length;
      exit.bytesUp += chunk.length;
      bytes.inc({ direction: 'up', exit: exit.name }, chunk.length);
    },
    countDown: (chunk: Buffer): void => {
      down += chunk.length;
      exit.bytesDown += chunk.length;
      bytes.inc({ direction: 'down', exit: exit.name }, chunk.length);
    },
    done: (): void => {
      if (finished) return;
      finished = true;
      const line = `${JSON.stringify({
        at: new Date().toISOString(),
        exit: exit.name,
        label,
        ms: Date.now() - startedAt,
        bytesUp: up,
        bytesDown: down,
      })}\n`;
      fs.appendFile(statsFile, line, () => {});
    },
  };
}

export function createGateway(config: GatewayConfig = {}) {
  const {
    host = '127.0.0.1',
    httpPort = 8888,
    socksPort = 1080,
    users = new Map<string, string>(),
    pool = new ExitPool(),
    statsFile = resolveFile('stats.jsonl'),
    statsToken = '',
    connectTimeoutMs = 20000,
    healthIntervalMs = 60000,
    healthTarget = { host: 'api.ipify.org', port: 443 },
    healthTargets,
    healthTimeoutMs = 10000,
    maxConnections = 0,
    maxConnectionsPerUser = 0,
    authLimiter,
    authMaxFailures = 10,
    authWindowMs = 60000,
    authBlockMs = 60000,
    readyz = true,
    logger = createLogger({ role: 'gateway' }),
    metrics: metricsRegistry,
    metricsToken = '',
    version,
  } = config;

  let currentStatsToken = statsToken;
  let currentMetricsToken = metricsToken;

  const registry = metricsRegistry ?? new Registry();
  const requestsTotal = registry.counter('localproxy_requests_total', 'Peticiones atendidas por protocolo y codigo', ['protocol', 'code']);
  const bytesTotal = registry.counter('localproxy_bytes_total', 'Bytes transferidos', ['direction', 'exit']);
  const activeConnections = registry.gauge('localproxy_active_connections', 'Conexiones activas', ['protocol']);
  const authFailures = registry.counter('localproxy_auth_failures_total', 'Fallos de autenticacion');
  const authBlocked = registry.counter('localproxy_auth_blocked_total', 'Peticiones bloqueadas por rate-limit');
  const upstreamErrors = registry.counter('localproxy_upstream_errors_total', 'Errores de upstream', ['kind']);
  const exitHealthy = registry.gauge('localproxy_exit_healthy', 'Salud del exit (1/0)', ['exit']);
  const exitCircuit = registry.gauge('localproxy_exit_circuit', 'Estado del circuit breaker (0=closed,1=halfOpen,2=open)', ['exit']);
  const sessionsGauge = registry.gauge('localproxy_sessions', 'Sesiones sticky activas');
  const healthcheckFailures = registry.counter('localproxy_healthcheck_failures_total', 'Fallos de health check', ['exit']);
  const requestDuration = registry.histogram('localproxy_request_duration_seconds', 'Duracion de peticion', undefined, ['protocol']);
  const connectDuration = registry.histogram('localproxy_connect_duration_seconds', 'Duracion de establecimiento de tunel', undefined, ['exit']);
  const uptimeGauge = registry.gauge('localproxy_uptime_seconds', 'Uptime del proceso');
  const userConnections = registry.gauge('localproxy_user_connections', 'Conexiones activas por usuario', ['user']);
  const userLimitRejections = registry.counter('localproxy_user_limit_rejections_total', 'Rechazos por limite de conexiones por usuario', ['user']);
  const globalLimitDrops = registry.counter('localproxy_global_limit_drops_total', 'Conexiones descartadas por el limite global del servidor');
  const buildInfo = registry.gauge('localproxy_build_info', 'Info de build', ['version', 'role']);
  buildInfo.set(1, { version: version ?? 'unknown', role: 'gateway' });

  function syncGauges(): void {
    const snapshot = pool.stats();
    for (const exit of snapshot.exits) {
      exitHealthy.set(exit.healthy ? 1 : 0, { exit: exit.name });
      exitCircuit.set(circuitValue(exit.circuit), { exit: exit.name });
    }
    sessionsGauge.set(snapshot.sessions.length);
    uptimeGauge.set(process.uptime());
  }

  const authenticate = createAuthenticator(users);
  const authRateLimiter: AuthLimiter =
    authLimiter ?? createAuthLimiter({ maxFailures: authMaxFailures, windowMs: authWindowMs, blockMs: authBlockMs });
  const limiter = config.limiter ?? new ConnectionLimiter({ max: maxConnectionsPerUser });
  const targets: HealthTarget[] =
    healthTargets && healthTargets.length ? healthTargets : [healthTarget];
  const checking = new Set<string>();
  const sockets = new Set<net.Socket>();

  const track = (socket: net.Socket): void => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  };

  function admit(user: string): boolean {
    if (limiter.acquire(user)) {
      userConnections.inc({ user });
      return true;
    }
    userLimitRejections.inc({ user });
    return false;
  }

  function trackUser(user: string, target: { on(event: 'close', listener: () => void): void }): void {
    let released = false;
    target.on('close', () => {
      if (released) return;
      released = true;
      limiter.release(user);
      userConnections.dec({ user });
    });
  }

  function reject407(response: http.ServerResponse): void {
    response.writeHead(407, { 'proxy-authenticate': 'Basic realm="local-proxy"' });
    response.end();
  }

  function reject407Socket(socket: net.Socket): void {
    socket.write('HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="local-proxy"\r\n\r\n');
    socket.destroy();
  }

  function reject429(response: http.ServerResponse): void {
    response.writeHead(429, { 'retry-after': '5' });
    response.end('demasiados intentos');
  }

  function reject429Socket(socket: net.Socket): void {
    socket.write('HTTP/1.1 429 Too Many Requests\r\nRetry-After: 5\r\n\r\n');
    socket.destroy();
  }

  function reject503(response: http.ServerResponse): void {
    response.writeHead(503, { 'retry-after': '5' });
    response.end('sin exits disponibles');
  }

  function reject503Socket(socket: net.Socket): void {
    socket.write('HTTP/1.1 503 Service Unavailable\r\nRetry-After: 5\r\n\r\n');
    socket.destroy();
  }

  interface AuthOutcome {
    parsed: ParsedUser | null;
    key: string;
    limited: boolean;
  }

  function authorize(header: unknown, remoteAddress: string | undefined): AuthOutcome {
    const credentials = decodeBasic(header);
    const username = credentials ? credentials.username : '';
    const key = `${normalizeAddress(remoteAddress)}|${username}`;
    if (!authRateLimiter.allowed(key)) {
      authBlocked.inc();
      return { parsed: null, key, limited: true };
    }
    if (!credentials) return { parsed: null, key, limited: false };
    const parsed = authenticate(credentials.username, credentials.password);
    if (!parsed) {
      authRateLimiter.recordFailure(key);
      authFailures.inc();
      return { parsed: null, key, limited: false };
    }
    authRateLimiter.recordSuccess(key);
    return { parsed, key, limited: false };
  }

  function statsAuthorized(request: http.IncomingMessage): boolean {
    if (!currentStatsToken) return false;
    let query = '';
    try {
      const url = new URL(request.url ?? '/', 'http://localhost');
      query = url.searchParams.get('token') ?? '';
    } catch {
      query = '';
    }
    if (query && safeEqual(query, currentStatsToken)) return true;
    const header = request.headers.authorization ?? '';
    if (header.startsWith('Bearer ')) {
      const token = header.slice(7).trim();
      return token.length > 0 && safeEqual(token, currentStatsToken);
    }
    return false;
  }

  function metricsAuthorized(request: http.IncomingMessage): boolean {
    if (!currentMetricsToken) return true;
    let query = '';
    try {
      const url = new URL(request.url ?? '/', 'http://localhost');
      query = url.searchParams.get('token') ?? '';
    } catch {
      query = '';
    }
    if (query && safeEqual(query, currentMetricsToken)) return true;
    const header = request.headers.authorization ?? '';
    if (header.startsWith('Bearer ')) {
      const token = header.slice(7).trim();
      return token.length > 0 && safeEqual(token, currentMetricsToken);
    }
    return false;
  }

  function statsPayload() {
    return {
      host,
      httpPort: portOf(httpServer, httpPort),
      socksPort: portOf(socksServer, socksPort),
      ...pool.stats(),
    };
  }

  async function openTunnel(
    parsed: ParsedUser,
    targetHost: string,
    targetPort: number,
  ): Promise<{ exit: Exit; remote: net.Socket }> {
    const candidates = pool.candidates(parsed);
    if (!candidates.length) {
      upstreamErrors.inc({ kind: 'no_exits' });
      throw new NoExitsError('sin exits disponibles');
    }
    let lastError: unknown;
    for (const exit of candidates) {
      const started = startTimer();
      try {
        const remote = await connectViaHttpProxy({
          proxy: exit,
          host: targetHost,
          port: targetPort,
          timeoutMs: connectTimeoutMs,
        });
        pool.recordSuccess(exit);
        pool.commit(parsed, exit);
        connectDuration.observe(elapsedSeconds(started), { exit: exit.name });
        return { exit, remote };
      } catch (error) {
        lastError = error;
        pool.recordFailure(exit);
        logger.warn?.('exit fallo', { exit: exit.name, error: errorMessage(error) });
      }
    }
    upstreamErrors.inc({ kind: String(statusForError(lastError)) });
    throw lastError ?? new NoExitsError('sin exits disponibles');
  }

  function forwardHttpWithFailover(
    request: http.IncomingMessage,
    response: http.ServerResponse,
    parsed: ParsedUser,
  ): void {
    const candidates = pool.candidates(parsed);
    if (!candidates.length) {
      upstreamErrors.inc({ kind: 'no_exits' });
      reject503(response);
      return;
    }
    const canRetry = request.method === 'GET' || request.method === 'HEAD';
    let attempt = 0;
    const tryNext = (): void => {
      const exit = candidates[attempt];
      if (!exit) {
        reject503(response);
        return;
      }
      const meter = createMeter({ exit, label: 'http', statsFile, bytes: bytesTotal });
      let settled = false;
      const failover = (status: number): boolean => {
        if (settled) return true;
        settled = true;
        pool.recordFailure(exit);
        meter.done();
        attempt += 1;
        if (canRetry && attempt < candidates.length && !response.headersSent) {
          tryNext();
          return true;
        }
        upstreamErrors.inc({ kind: String(status) });
        if (!response.headersSent) {
          response.writeHead(status);
          response.end();
        } else {
          response.destroy();
        }
        return true;
      };
      forwardHttp(request, response, exit, {
        countUp: meter.countUp,
        countDown: meter.countDown,
        onDone: meter.done,
        onResponse: (proxyResponse) => {
          const exitLevel = !proxyResponse.headers['x-exit-name'];
          const statusCode = proxyResponse.statusCode ?? 502;
          if (exitLevel && RETRYABLE_STATUS.has(statusCode)) {
            logger.warn?.('exit respondio estado retryable', { exit: exit.name, status: statusCode });
            return failover(statusCode === 504 ? 504 : 502);
          }
          settled = true;
          pool.recordSuccess(exit);
          pool.commit(parsed, exit);
          return false;
        },
        onError: (error) => failover(statusForError(error)),
      });
    };
    tryNext();
  }

  function forwardUpgradeWithFailover(
    request: http.IncomingMessage,
    clientSocket: net.Socket,
    head: Buffer,
    parsed: ParsedUser,
  ): void {
    const candidates = pool.candidates(parsed);
    if (!candidates.length) {
      reject503Socket(clientSocket);
      return;
    }
    let attempt = 0;
    const tryNext = (): void => {
      const exit = candidates[attempt];
      if (!exit) {
        // Sin candidatos restantes: 502.
        if (clientSocket.writable) clientSocket.write('HTTP/1.1 502 Bad Gateway\r\n\r\n');
        clientSocket.destroy();
        return;
      }
      const headers = upgradeHeaders(request.headers, request.headers.host ?? '');
      if (exit.user) headers['proxy-authorization'] = basic(exit.user, exit.pass);
      pipeUpgrade({
        request,
        clientSocket,
        head,
        options: {
          host: exit.host,
          port: exit.port,
          method: request.method,
          path: request.url,
          headers,
        },
        onUpgrade: () => {
          pool.recordSuccess(exit);
          pool.commit(parsed, exit);
          requestsTotal.inc({ protocol: 'upgrade', code: '101' });
          return false; // pipeUpgrade escribe el 101 y hace el pipe
        },
        onResponse: (proxyResponse) => {
          const status = proxyResponse.statusCode ?? 502;
          requestsTotal.inc({ protocol: 'upgrade', code: String(status) });
          if (RETRYABLE_STATUS.has(status)) {
            pool.recordFailure(exit);
            attempt += 1;
            if (attempt < candidates.length) {
              tryNext();
              return true; // takeover y reintenta
            }
          }
          return false; // se le pasa al cliente la respuesta del exit
        },
        onError: () => {
          pool.recordFailure(exit);
          attempt += 1;
          if (attempt < candidates.length) {
            tryNext();
            return true;
          }
          requestsTotal.inc({ protocol: 'upgrade', code: '502' });
          return false; // pipeUpgrade escribe 502
        },
      });
    };
    tryNext();
  }

  const httpServer = http.createServer((request: http.IncomingMessage, response: http.ServerResponse) => {
    const pathname = pathnameOf(request.url);
    if (pathname === '/healthz') {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ok: true, uptimeMs: Math.round(process.uptime() * 1000) }));
      return;
    }
    if (pathname === '/readyz') {
      if (!readyz) {
        response.writeHead(404);
        response.end();
        return;
      }
      const ready = pool.healthyExits().length > 0;
      response.writeHead(ready ? 200 : 503, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ ready }));
      return;
    }
    if (pathname === '/__stats') {
      if (!statsAuthorized(request)) {
        response.writeHead(403, { 'content-type': 'application/json' });
        response.end(JSON.stringify({ error: currentStatsToken ? 'no autorizado' : 'stats deshabilitado' }));
        return;
      }
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify(statsPayload(), null, 2));
      return;
    }
    if (pathname === '/metrics') {
      if (!metricsAuthorized(request)) {
        response.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' });
        response.end('no autorizado');
        return;
      }
      syncGauges();
      response.writeHead(200, { 'content-type': 'text/plain; version=0.0.4; charset=utf-8' });
      response.end(registry.render());
      return;
    }
    const outcome = authorize(request.headers['proxy-authorization'], request.socket.remoteAddress);
    if (outcome.limited) {
      reject429(response);
      return;
    }
    if (!outcome.parsed) {
      reject407(response);
      return;
    }
    const user = outcome.parsed.base;
    if (!admit(user)) {
      reject429(response);
      return;
    }
    trackUser(user, response);
    // Solo las peticiones proxied cuentan como trafico (no /healthz, /readyz, /__stats, /metrics).
    const started = startTimer();
    response.on('finish', () => {
      requestsTotal.inc({ protocol: 'http', code: String(response.statusCode) });
      requestDuration.observe(elapsedSeconds(started), { protocol: 'http' });
    });
    forwardHttpWithFailover(request, response, outcome.parsed);
  });

  httpServer.on('connect', (request: http.IncomingMessage, clientSocket: net.Socket, head: Buffer) => {
    track(clientSocket);
    const outcome = authorize(request.headers['proxy-authorization'], clientSocket.remoteAddress);
    if (outcome.limited) {
      reject429Socket(clientSocket);
      return;
    }
    if (!outcome.parsed) {
      reject407Socket(clientSocket);
      return;
    }
    const user = outcome.parsed.base;
    if (!admit(user)) {
      reject429Socket(clientSocket);
      return;
    }
    trackUser(user, clientSocket);
    const { host: targetHost, port: targetPort } = parseTarget(request.url ?? '');
    openTunnel(outcome.parsed, targetHost, targetPort)
      .then(({ exit, remote }) => {
        requestsTotal.inc({ protocol: 'connect', code: '200' });
        track(remote);
        const meter = createMeter({ exit, label: 'http-connect', statsFile, bytes: bytesTotal });
        clientSocket.on('data', meter.countUp);
        remote.on('data', meter.countDown);
        clientSocket.on('close', meter.done);
        remote.on('close', meter.done);
        clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
        if (head && head.length) remote.write(head);
        clientSocket.pipe(remote);
        remote.pipe(clientSocket);
        clientSocket.on('error', () => remote.destroy());
        remote.on('error', () => clientSocket.destroy());
        clientSocket.on('end', () => remote.destroy());
        remote.on('end', () => clientSocket.destroy());
        clientSocket.on('close', () => remote.destroy());
        remote.on('close', () => clientSocket.destroy());
      })
      .catch((error: unknown) => {
        logger.warn?.('CONNECT fallo', { target: `${targetHost}:${targetPort}`, error: errorMessage(error) });
        if (error instanceof NoExitsError) {
          requestsTotal.inc({ protocol: 'connect', code: '503' });
          reject503Socket(clientSocket);
          return;
        }
        const status = statusForError(error);
        requestsTotal.inc({ protocol: 'connect', code: String(status) });
        clientSocket.write(
          `HTTP/1.1 ${status} ${status === 504 ? 'Gateway Timeout' : 'Bad Gateway'}\r\n\r\n`,
        );
        clientSocket.destroy();
      });
  });

  httpServer.on('upgrade', (request: http.IncomingMessage, clientSocket: net.Socket, head: Buffer) => {
    track(clientSocket);
    const outcome = authorize(request.headers['proxy-authorization'], clientSocket.remoteAddress);
    if (outcome.limited) {
      reject429Socket(clientSocket);
      return;
    }
    if (!outcome.parsed) {
      reject407Socket(clientSocket);
      return;
    }
    const user = outcome.parsed.base;
    if (!admit(user)) {
      reject429Socket(clientSocket);
      return;
    }
    trackUser(user, clientSocket);
    forwardUpgradeWithFailover(request, clientSocket, head, outcome.parsed);
  });

  const socksServer = createSocks5Server({
    // El callback auth no recibe el socket; la IP se aplica en connect().
    auth: (username, password) => {
      const key = `${''}|${username}`;
      if (!authRateLimiter.allowed(key)) {
        requestsTotal.inc({ protocol: 'socks5', code: 'error' });
        return false;
      }
      const parsed = authenticate(username, password);
      if (!parsed) {
        authRateLimiter.recordFailure(key);
        requestsTotal.inc({ protocol: 'socks5', code: 'error' });
        return false;
      }
      authRateLimiter.recordSuccess(key);
      return true;
    },
    connect: async ({ username, password, host: targetHost, port: targetPort, client }) => {
      try {
        const key = `${normalizeAddress(client.remoteAddress)}|${username}`;
        if (!authRateLimiter.allowed(key)) throw new Error('demasiados intentos');
        const parsed = authenticate(username, password);
        if (!parsed) {
          authRateLimiter.recordFailure(key);
          throw new Error('no autorizado');
        }
        const user = parsed.base;
        if (!admit(user)) {
          const error = new Error('limite de conexiones') as NodeJS.ErrnoException;
          error.code = 'EACCES';
          throw error;
        }
        trackUser(user, client);
        const { exit, remote } = await openTunnel(parsed, targetHost, targetPort);
        requestsTotal.inc({ protocol: 'socks5', code: 'ok' });
        const meter = createMeter({ exit, label: 'socks5', statsFile, bytes: bytesTotal });
        client.on('data', meter.countUp);
        remote.on('data', meter.countDown);
        client.on('close', meter.done);
        remote.on('close', meter.done);
        return remote;
      } catch (error) {
        requestsTotal.inc({ protocol: 'socks5', code: 'error' });
        throw error;
      }
    },
  });

  // Node emite 'drop' cuando se supera maxConnections del servidor.
  httpServer.on('drop', () => globalLimitDrops.inc());
  socksServer.on('drop', () => globalLimitDrops.inc());

  async function healthCheck(exit: Exit): Promise<void> {
    if (checking.has(exit.name)) return;
    checking.add(exit.name);
    try {
      const target = targets[Math.floor(Math.random() * targets.length)];
      if (!target) return;
      const socket = await connectViaHttpProxy({
        proxy: exit,
        host: target.host,
        port: target.port,
        timeoutMs: healthTimeoutMs,
      });
      socket.destroy();
      pool.recordSuccess(exit);
    } catch {
      healthcheckFailures.inc({ exit: exit.name });
      pool.recordFailure(exit);
    } finally {
      checking.delete(exit.name);
    }
  }

  let closed = false;
  let healthTimer: NodeJS.Timeout | null = null;
  const staggerTimers = new Set<NodeJS.Timeout>();

  function scheduleHealth(): void {
    if (closed || healthIntervalMs <= 0) return;
    const jitter = 1 + (Math.random() * 2 - 1) * HEALTH_JITTER;
    const delay = Math.max(0, Math.round(healthIntervalMs * jitter));
    healthTimer = setTimeout(() => {
      pool.exits.forEach((exit, index) => {
        const stagger = setTimeout(() => {
          staggerTimers.delete(stagger);
          void healthCheck(exit);
        }, index * HEALTH_STAGGER_MS);
        staggerTimers.add(stagger);
        stagger.unref();
      });
      scheduleHealth();
    }, delay);
    healthTimer.unref();
  }

  scheduleHealth();
  const sweepTimer = setInterval(() => pool.sweep(), 60000);
  sweepTimer.unref();

  function listen(server: http.Server | net.Server, port: number): Promise<void> {
    return new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(port, host, () => {
        server.removeListener('error', reject);
        resolve();
      });
    });
  }

  async function start(): Promise<GatewayAddresses> {
    httpServer.on('connection', track);
    socksServer.on('connection', track);
    httpServer.on('connection', (socket: net.Socket) => {
      activeConnections.inc({ protocol: 'http' });
      socket.on('close', () => activeConnections.dec({ protocol: 'http' }));
    });
    socksServer.on('connection', (socket: net.Socket) => {
      activeConnections.inc({ protocol: 'socks5' });
      socket.on('close', () => activeConnections.dec({ protocol: 'socks5' }));
    });
    await listen(httpServer, httpPort);
    await listen(socksServer, socksPort);
    return { httpPort: portOf(httpServer, httpPort), socksPort: portOf(socksServer, socksPort) };
  }

  function close(): Promise<void> {
    closed = true;
    if (healthTimer) clearTimeout(healthTimer);
    for (const timer of staggerTimers) clearTimeout(timer);
    staggerTimers.clear();
    clearInterval(sweepTimer);
    return new Promise((resolve) => {
      let pending = 2;
      const done = (): void => {
        pending -= 1;
        if (pending === 0) resolve();
      };
      httpServer.close(done);
      socksServer.close(done);
      for (const socket of sockets) socket.destroy();
    });
  }

  // Recarga en caliente: muta el Map de usuarios (el authenticator lo comparte) y los tokens.
  function reload(next: { users?: Map<string, string>; statsToken?: string; metricsToken?: string }): void {
    if (next.users) {
      users.clear();
      for (const [key, value] of next.users) users.set(key, value);
      logger.info?.('usuarios recargados', { count: users.size });
    }
    if (next.statsToken !== undefined) currentStatsToken = next.statsToken;
    if (next.metricsToken !== undefined) currentMetricsToken = next.metricsToken;
  }

  Object.assign(httpServer, HTTP_TIMEOUTS);
  // net.Server no consume estos timeouts, se asignan por uniformidad.
  Object.assign(socksServer, HTTP_TIMEOUTS);
  if (maxConnections > 0) {
    httpServer.maxConnections = maxConnections;
    socksServer.maxConnections = maxConnections;
  }

  return { httpServer, socksServer, pool, users, limiter, start, close, reload, stats: statsPayload };
}

export function watchExits(file: string, pool: ExitPool, logger: Logger = console): fs.FSWatcher | null {
  let timer: NodeJS.Timeout | null = null;
  const schedule = (): void => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      try {
        pool.reload(loadExits(file));
        logger.log?.('exits recargados', { file: path.basename(file), exits: pool.exits.length });
      } catch (error) {
        logger.error?.('archivo de exits invalido', { file: path.basename(file), error: errorMessage(error) });
      }
    }, 300);
    timer.unref();
  };
  try {
    const directory = path.dirname(file);
    const base = path.basename(file);
    const watcher = fs.watch(directory, (eventType, filename) => {
      if (!filename || path.basename(String(filename)) === base) schedule();
    });
    watcher.on('error', () => {});
    watcher.unref();
    return watcher;
  } catch {
    return null;
  }
}

const entry = process.argv[1];
const isMain = entry !== undefined && path.resolve(entry) === import.meta.filename;

export function runGateway(): void {
  const logger = createLogger({
    level: parseLogLevel(envString('LOG_LEVEL', 'info')),
    format: parseLogFormat(envString('LOG_FORMAT', 'json')),
    role: 'gateway',
  });
  process.on('uncaughtException', (error) => {
    logger.error?.('excepcion no capturada', { error: errorMessage(error) });
    process.exit(1);
  });
  process.on('unhandledRejection', (reason) => {
    logger.error?.('promesa rechazada', { error: errorMessage(reason) });
    process.exit(1);
  });

  loadEnv();
  const host = envString('GATEWAY_HOST', '127.0.0.1');
  const exitsFile = resolveFile(envString('EXITS_FILE', 'exits.json'));
  let exits: ExitConfig[] = [];
  try {
    exits = loadExits(exitsFile);
  } catch (error) {
    logger.error?.('no pude leer el archivo de exits', { file: exitsFile, error: errorMessage(error) });
  }
  const users = parseUsers(envString('PROXY_USERS'));
  const pool = new ExitPool(exits, { sessionTtlMs: envNumber('SESSION_TTL_MS', 600000) });
  const healthTargets = envList('HEALTH_TARGETS').map((entry) => parseHealthTarget(entry));
  const version = JSON.parse(fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8')).version as string;
  const gateway = createGateway({
    host,
    httpPort: envNumber('GATEWAY_HTTP_PORT', 8888),
    socksPort: envNumber('GATEWAY_SOCKS_PORT', 1080),
    users,
    pool,
    statsFile: resolveFile(envString('STATS_FILE', 'stats.jsonl')),
    statsToken: envString('STATS_TOKEN', ''),
    connectTimeoutMs: envNumber('CONNECT_TIMEOUT_MS', 20000),
    healthIntervalMs: envNumber('HEALTH_INTERVAL_MS', 60000),
    healthTarget: parseHealthTarget(envString('HEALTH_TARGET', 'api.ipify.org:443')),
    healthTargets: healthTargets.length ? healthTargets : undefined,
    healthTimeoutMs: envNumber('HEALTH_TIMEOUT_MS', 10000),
    maxConnections: envNumber('MAX_CONNECTIONS', 0),
    maxConnectionsPerUser: envNumber('MAX_CONNECTIONS_PER_USER', 0),
    metricsToken: envString('METRICS_TOKEN', ''),
    version,
    logger,
  });

  if (host === '0.0.0.0') {
    logger.warn?.('GATEWAY_HOST=0.0.0.0 expone el proxy en todas las interfaces. Usa la IP de Tailscale.');
  }
  if (!users.size) {
    logger.warn?.('PROXY_USERS vacio; ningun cliente podra autenticarse.');
  }
  if (!exits.length) {
    logger.warn?.('no hay exits configurados', { file: exitsFile });
  }

  gateway
    .start()
    .then((addresses) => {
      logger.info?.('HTTP proxy escuchando', { url: `http://${host}:${addresses.httpPort}` });
      logger.info?.('SOCKS5 escuchando', { url: `socks5://${host}:${addresses.socksPort}` });
      logger.info?.('exits configurados', { exits: exits.length, users: users.size });
      watchExits(exitsFile, pool, logger);
      watchEnv(
        resolveFile('.env'),
        (values) => {
          const next: { users?: Map<string, string>; statsToken?: string; metricsToken?: string } = {};
          if (values.PROXY_USERS !== undefined) next.users = parseUsers(values.PROXY_USERS);
          if (values.STATS_TOKEN !== undefined) next.statsToken = values.STATS_TOKEN;
          if (values.METRICS_TOKEN !== undefined) next.metricsToken = values.METRICS_TOKEN;
          if (Object.keys(next).length === 0) return;
          gateway.reload(next);
        },
        logger,
      );
    })
    .catch((error: unknown) => {
      logger.error?.('no pude escuchar', { host, error: errorMessage(error) });
      logger.error?.('verifica que Tailscale este arriba y que GATEWAY_HOST sea la IP 100.x correcta.');
      process.exit(1);
    });

  const shutdown = (): void => {
    logger.info?.('cerrando...');
    gateway.close().then(() => {
      setTimeout(() => process.exit(0), 100);
    });
    setTimeout(() => process.exit(0), 2000).unref();
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

if (isMain) runGateway();
