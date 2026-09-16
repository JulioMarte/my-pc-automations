import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import net from 'node:net';
import { loadEnv, envString, envNumber, envList } from './env.ts';
import { connectViaHttpProxy, forwardHttp, pipeUpgrade, basic, ProxyError } from './upstream.ts';
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

const RETRYABLE_STATUS = new Set([407, 502, 503, 504]);
const HTTP_TIMEOUTS = { headersTimeout: 10000, requestTimeout: 30000, keepAliveTimeout: 10000 };
const HEALTH_JITTER = 0.2;
const HEALTH_STAGGER_MS = 250;

export interface GatewayLogger {
  log?(...args: unknown[]): void;
  warn?(...args: unknown[]): void;
  error?(...args: unknown[]): void;
}

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
  authLimiter?: AuthLimiter;
  authMaxFailures?: number;
  authWindowMs?: number;
  authBlockMs?: number;
  readyz?: boolean;
  logger?: GatewayLogger;
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

function createMeter({ exit, label, statsFile }: { exit: Exit; label: string; statsFile: string }): Meter {
  const startedAt = Date.now();
  let up = 0;
  let down = 0;
  let finished = false;
  exit.connections += 1;
  return {
    countUp: (chunk: Buffer): void => {
      up += chunk.length;
      exit.bytesUp += chunk.length;
    },
    countDown: (chunk: Buffer): void => {
      down += chunk.length;
      exit.bytesDown += chunk.length;
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
    authLimiter,
    authMaxFailures = 10,
    authWindowMs = 60000,
    authBlockMs = 60000,
    readyz = true,
    logger = console,
  } = config;

  const authenticate = createAuthenticator(users);
  const limiter: AuthLimiter =
    authLimiter ?? createAuthLimiter({ maxFailures: authMaxFailures, windowMs: authWindowMs, blockMs: authBlockMs });
  const targets: HealthTarget[] =
    healthTargets && healthTargets.length ? healthTargets : [healthTarget];
  const checking = new Set<string>();
  const sockets = new Set<net.Socket>();

  const track = (socket: net.Socket): void => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  };

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
    if (!limiter.allowed(key)) return { parsed: null, key, limited: true };
    if (!credentials) return { parsed: null, key, limited: false };
    const parsed = authenticate(credentials.username, credentials.password);
    if (!parsed) {
      limiter.recordFailure(key);
      return { parsed: null, key, limited: false };
    }
    limiter.recordSuccess(key);
    return { parsed, key, limited: false };
  }

  function statsAuthorized(request: http.IncomingMessage): boolean {
    if (!statsToken) return false;
    let query = '';
    try {
      const url = new URL(request.url ?? '/', 'http://localhost');
      query = url.searchParams.get('token') ?? '';
    } catch {
      query = '';
    }
    if (query && safeEqual(query, statsToken)) return true;
    const header = request.headers.authorization ?? '';
    if (header.startsWith('Bearer ')) {
      const token = header.slice(7).trim();
      return token.length > 0 && safeEqual(token, statsToken);
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
    if (!candidates.length) throw new NoExitsError('sin exits disponibles');
    let lastError: unknown;
    for (const exit of candidates) {
      try {
        const remote = await connectViaHttpProxy({
          proxy: exit,
          host: targetHost,
          port: targetPort,
          timeoutMs: connectTimeoutMs,
        });
        pool.recordSuccess(exit);
        pool.commit(parsed, exit);
        return { exit, remote };
      } catch (error) {
        lastError = error;
        pool.recordFailure(exit);
        logger.warn?.(`[gateway] exit ${exit.name} fallo: ${errorMessage(error)}`);
      }
    }
    throw lastError ?? new NoExitsError('sin exits disponibles');
  }

  function forwardHttpWithFailover(
    request: http.IncomingMessage,
    response: http.ServerResponse,
    parsed: ParsedUser,
  ): void {
    const candidates = pool.candidates(parsed);
    if (!candidates.length) {
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
      const meter = createMeter({ exit, label: 'http', statsFile });
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
            logger.warn?.(`[gateway] exit ${exit.name} respondio ${statusCode}, reintentando`);
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
        response.end(JSON.stringify({ error: statsToken ? 'no autorizado' : 'stats deshabilitado' }));
        return;
      }
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify(statsPayload(), null, 2));
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
    const { host: targetHost, port: targetPort } = parseTarget(request.url ?? '');
    openTunnel(outcome.parsed, targetHost, targetPort)
      .then(({ exit, remote }) => {
        track(remote);
        const meter = createMeter({ exit, label: 'http-connect', statsFile });
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
        logger.warn?.(`[gateway] CONNECT ${targetHost}:${targetPort} fallo: ${errorMessage(error)}`);
        if (error instanceof NoExitsError) {
          reject503Socket(clientSocket);
          return;
        }
        const status = statusForError(error);
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
    const exit = pool.candidates(outcome.parsed)[0];
    if (!exit) {
      reject503Socket(clientSocket);
      return;
    }
    const headers: Record<string, string | string[] | undefined> = {
      ...request.headers,
      host: request.headers.host ?? '',
    };
    delete headers['proxy-connection'];
    delete headers['proxy-authorization'];
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
      onError: () => {
        pool.recordFailure(exit);
        return false;
      },
    });
  });

  const socksServer = createSocks5Server({
    // El callback auth no recibe el socket; la IP se aplica en connect().
    auth: (username, password) => {
      const key = `${''}|${username}`;
      if (!limiter.allowed(key)) return false;
      const parsed = authenticate(username, password);
      if (!parsed) {
        limiter.recordFailure(key);
        return false;
      }
      limiter.recordSuccess(key);
      return true;
    },
    connect: async ({ username, password, host: targetHost, port: targetPort, client }) => {
      const key = `${normalizeAddress(client.remoteAddress)}|${username}`;
      if (!limiter.allowed(key)) throw new Error('demasiados intentos');
      const parsed = authenticate(username, password);
      if (!parsed) {
        limiter.recordFailure(key);
        throw new Error('no autorizado');
      }
      const { exit, remote } = await openTunnel(parsed, targetHost, targetPort);
      const meter = createMeter({ exit, label: 'socks5', statsFile });
      client.on('data', meter.countUp);
      remote.on('data', meter.countDown);
      client.on('close', meter.done);
      remote.on('close', meter.done);
      return remote;
    },
  });

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

  Object.assign(httpServer, HTTP_TIMEOUTS);
  // net.Server no consume estos timeouts, se asignan por uniformidad.
  Object.assign(socksServer, HTTP_TIMEOUTS);
  if (maxConnections > 0) {
    httpServer.maxConnections = maxConnections;
    socksServer.maxConnections = maxConnections;
  }

  return { httpServer, socksServer, pool, users, start, close, stats: statsPayload };
}

export function watchExits(file: string, pool: ExitPool, logger: GatewayLogger = console): fs.FSWatcher | null {
  let timer: NodeJS.Timeout | null = null;
  const schedule = (): void => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      try {
        pool.reload(loadExits(file));
        logger.log?.(`[gateway] ${path.basename(file)} recargado (${pool.exits.length} exits)`);
      } catch (error) {
        logger.error?.(`[gateway] ${path.basename(file)} invalido: ${errorMessage(error)}`);
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

if (isMain) {
  process.on('uncaughtException', (error) => {
    console.error(`[gateway] excepcion no capturada: ${error.message}`);
    process.exit(1);
  });
  process.on('unhandledRejection', (reason) => {
    console.error(`[gateway] promesa rechazada: ${errorMessage(reason)}`);
    process.exit(1);
  });

  loadEnv();
  const host = envString('GATEWAY_HOST', '127.0.0.1');
  const exitsFile = resolveFile(envString('EXITS_FILE', 'exits.json'));
  let exits: ExitConfig[] = [];
  try {
    exits = loadExits(exitsFile);
  } catch (error) {
    console.error(`[gateway] no pude leer ${exitsFile}: ${errorMessage(error)}`);
  }
  const users = parseUsers(envString('PROXY_USERS'));
  const pool = new ExitPool(exits, { sessionTtlMs: envNumber('SESSION_TTL_MS', 600000) });
  const healthTargets = envList('HEALTH_TARGETS').map((entry) => parseHealthTarget(entry));
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
  });

  if (host === '0.0.0.0') {
    console.warn('[gateway] ADVERTENCIA: GATEWAY_HOST=0.0.0.0 expone el proxy en todas las interfaces. Usa la IP de Tailscale.');
  }
  if (!users.size) {
    console.warn('[gateway] ADVERTENCIA: PROXY_USERS vacio; ningun cliente podra autenticarse.');
  }
  if (!exits.length) {
    console.warn(`[gateway] ADVERTENCIA: no hay exits en ${exitsFile}.`);
  }

  gateway
    .start()
    .then((addresses) => {
      console.log(`[gateway] HTTP proxy en http://${host}:${addresses.httpPort}`);
      console.log(`[gateway] SOCKS5 en socks5://${host}:${addresses.socksPort}`);
      console.log(`[gateway] ${exits.length} exits configurados, ${users.size} usuarios.`);
      watchExits(exitsFile, pool);
    })
    .catch((error: unknown) => {
      console.error(`[gateway] no pude escuchar en ${host}: ${errorMessage(error)}`);
      console.error('[gateway] verifica que Tailscale este arriba y que GATEWAY_HOST sea la IP 100.x correcta.');
      process.exit(1);
    });

  const shutdown = (): void => {
    console.log('[gateway] cerrando...');
    gateway.close().then(() => {
      setTimeout(() => process.exit(0), 100);
    });
    setTimeout(() => process.exit(0), 2000).unref();
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}
