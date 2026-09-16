import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { URL } from 'node:url';
import { loadEnv, watchEnv, envString, envNumber, envBool, envList } from './env.ts';
import { createLogger, parseLogLevel, parseLogFormat, type Logger } from './logger.ts';
import { Registry } from './metrics.ts';
import { parseCredentials, safeEqual, type Credential } from './router.ts';
import { stripHopByHop, pipeUpgrade, upgradeHeaders } from './upstream.ts';

export interface ExitServerOptions {
  name?: string;
  user?: string;
  pass?: string;
  users?: Credential[];
  allowFrom?: string[];
  connectTimeoutMs?: number;
  blockPrivate?: boolean;
  idleTimeoutMs?: number;
  healthPath?: string;
  metrics?: Registry;
  metricsToken?: string;
  logger?: Logger;
  version?: string;
}

export interface ExitServer extends http.Server {
  reloadCredentials(next: Credential[]): void;
}

// Rangos IPv4 bloqueados: [base, prefijo].
const BLOCKED_IPV4: ReadonlyArray<readonly [number, number]> = [
  [0x00000000, 8], // 0.0.0.0/8
  [0x0a000000, 8], // 10.0.0.0/8
  [0x64400000, 10], // 100.64.0.0/10 (CGNAT / Tailscale)
  [0x7f000000, 8], // 127.0.0.0/8
  [0xa9fe0000, 16], // 169.254.0.0/16 (link-local + metadata)
  [0xac100000, 12], // 172.16.0.0/12
  [0xc0a80000, 16], // 192.168.0.0/16
  [0xe0000000, 4], // 224.0.0.0/4 (multicast)
  [0xf0000000, 4], // 240.0.0.0/4 (reservado)
];

function ipv4ToInt(host: string): number | null {
  const parts = host.split('.');
  if (parts.length !== 4) return null;
  let value = 0;
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) return null;
    const octet = Number(part);
    if (octet > 255) return null;
    value = value * 256 + octet;
  }
  return value >>> 0;
}

function inCidr(value: number, base: number, bits: number): boolean {
  if (bits === 0) return true;
  const mask = (0xffffffff << (32 - bits)) >>> 0;
  return ((value & mask) >>> 0) === ((base & mask) >>> 0);
}

function isBlockedIpv4(value: number): boolean {
  return BLOCKED_IPV4.some(([base, bits]) => inCidr(value, base, bits));
}

function ipv6Groups(input: string): number[] | null {
  let value = input;
  const zone = value.indexOf('%');
  if (zone !== -1) value = value.slice(0, zone);
  if (!value.includes(':')) return null;
  if (value.includes('.')) {
    const lastColon = value.lastIndexOf(':');
    if (lastColon === -1) return null;
    const tail = ipv4ToInt(value.slice(lastColon + 1));
    if (tail === null) return null;
    const high = ((tail >>> 16) & 0xffff).toString(16);
    const low = (tail & 0xffff).toString(16);
    value = `${value.slice(0, lastColon)}:${high}:${low}`;
  }
  const halves = value.split('::');
  if (halves.length > 2) return null;
  const parse = (part: string): number[] | null => {
    if (part === '') return [];
    const groups: number[] = [];
    for (const piece of part.split(':')) {
      if (!/^[0-9a-fA-F]{1,4}$/.test(piece)) return null;
      groups.push(parseInt(piece, 16));
    }
    return groups;
  };
  if (halves.length === 2) {
    const head = parse(halves[0] ?? '');
    const tail = parse(halves[1] ?? '');
    if (head === null || tail === null) return null;
    const missing = 8 - head.length - tail.length;
    if (missing < 0) return null;
    return [...head, ...new Array<number>(missing).fill(0), ...tail];
  }
  const groups = parse(value);
  if (groups === null || groups.length !== 8) return null;
  return groups;
}

function isBlockedIpv6(groups: number[]): boolean {
  const first = groups[0] ?? 0;
  if (groups.every((group) => group === 0)) return true; // ::
  if (groups.slice(0, 7).every((group) => group === 0) && groups[7] === 1) return true; // ::1
  if ((first & 0xffc0) === 0xfe80) return true; // fe80::/10
  if ((first & 0xfe00) === 0xfc00) return true; // fc00::/7
  if (groups.slice(0, 5).every((group) => group === 0) && (groups[5] === 0xffff || groups[5] === 0)) {
    const mapped = (((groups[6] ?? 0) << 16) | (groups[7] ?? 0)) >>> 0;
    return isBlockedIpv4(mapped);
  }
  return false;
}

// Bloquea por literal IP y por el hostname "localhost".
// No se resuelve DNS aqui: dominios que apunten a IPs privadas quedan fuera de alcance.
export function isBlockedHost(host: string, port: number): boolean {
  if (port === 25) return true;
  const value = host.toLowerCase();
  if (value === '' || value === 'localhost') return true;
  const ipv4 = ipv4ToInt(value);
  if (ipv4 !== null) return isBlockedIpv4(ipv4);
  const ipv6 = ipv6Groups(value);
  if (ipv6 !== null) return isBlockedIpv6(ipv6);
  return false;
}

function normalizeAddress(address: string | undefined): string {
  if (!address) return '';
  return address.startsWith('::ffff:') ? address.slice(7) : address;
}

function parseTarget(request: http.IncomingMessage): URL | null {
  const raw = request.url ?? '';
  try {
    if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw)) return new URL(raw);
    if (raw.startsWith('/')) {
      return new URL(`http://${request.headers.host || 'localhost'}${raw}`);
    }
    return null;
  } catch {
    return null;
  }
}

function parseAuthority(authority: unknown): { host: string; port: number } {
  const value = String(authority);
  const separator = value.lastIndexOf(':');
  if (separator === -1) return { host: value.replace(/^\[|\]$/g, ''), port: 443 };
  const host = value.slice(0, separator).replace(/^\[|\]$/g, '');
  const port = Number(value.slice(separator + 1)) || 443;
  return { host, port };
}

// Solo tratamos como health las peticiones directas (path relativo). Las peticiones
// proxied llegan con URL absoluta (http://host/__health) y NO deben colisionar.
function isHealthRequest(url: string | undefined, healthPath: string): boolean {
  const value = String(url ?? '');
  if (!value.startsWith('/')) return false;
  return value === healthPath || value.startsWith(`${healthPath}?`);
}

// Igual que el health: solo path relativo, para no colisionar con URLs absolutas proxied.
function isMetricsRequest(url: string | undefined): boolean {
  const value = String(url ?? '');
  if (!value.startsWith('/')) return false;
  return value === '/metrics' || value.startsWith('/metrics?');
}

export function createExitServer(options: ExitServerOptions = {}): ExitServer {
  const {
    name = 'exit',
    user = '',
    pass = '',
    allowFrom = [],
    connectTimeoutMs = 15000,
    blockPrivate = true,
    idleTimeoutMs = 0,
    healthPath = '/__health',
    metricsToken = '',
    logger,
    version = 'unknown',
  } = options;

  const startedAt = Date.now();
  const allowed = new Set(allowFrom.map(normalizeAddress));
  // Lista de credenciales validas; el modo legacy user/pass se suma al final.
  const credentials: Credential[] = [...(options.users ?? [])];
  if (user) credentials.push({ user, pass: pass ?? '' });

  const registry = options.metrics ?? new Registry();
  const requestsTotal = registry.counter('localproxy_requests_total', 'Peticiones atendidas', ['code']);
  const authFailures = registry.counter('localproxy_auth_failures_total', 'Fallos de autenticacion');
  const bytesTotal = registry.counter('localproxy_bytes_total', 'Bytes transferidos', ['direction']);
  const activeConnections = registry.gauge('localproxy_active_connections', 'Conexiones activas');
  const blockedTotal = registry.counter('localproxy_blocked_total', 'Destinos bloqueados', ['reason']);
  const uptimeSeconds = registry.gauge('localproxy_uptime_seconds', 'Uptime del proceso');
  const buildInfo = registry.gauge('localproxy_build_info', 'Info de build', ['version', 'role']);
  buildInfo.set(1, { version: version ?? 'unknown', role: 'exit' });

  function metricsAuthorized(request: http.IncomingMessage): boolean {
    if (!metricsToken) return true;
    const url = new URL(request.url ?? '/', 'http://localhost');
    const queryToken = url.searchParams.get('token') ?? '';
    const header = String(request.headers.authorization ?? '');
    const bearer = header.startsWith('Bearer ') ? header.slice(7) : '';
    return safeEqual(queryToken, metricsToken) || safeEqual(bearer, metricsToken);
  }

  function authorized(request: http.IncomingMessage): boolean {
    const remote = normalizeAddress(request.socket.remoteAddress);
    if (allowed.size && !allowed.has(remote)) return false;
    if (credentials.length === 0) return true;
    const header = String(request.headers['proxy-authorization'] ?? '');
    if (!header.startsWith('Basic ')) return false;
    const decoded = Buffer.from(header.slice(6), 'base64').toString();
    const index = decoded.indexOf(':');
    if (index === -1) return false;
    const decodedUser = decoded.slice(0, index);
    const decodedPass = decoded.slice(index + 1);
    // Se comparan todas las credenciales sin salir antes: no revela cual coincidio.
    let matched = false;
    for (const cred of credentials) {
      const userOk = safeEqual(decodedUser, cred.user);
      const passOk = safeEqual(decodedPass, cred.pass);
      if (userOk && passOk) matched = true;
    }
    return matched;
  }

  const server = http.createServer((request: http.IncomingMessage, response: http.ServerResponse) => {
    // Health endpoint local: sin auth ni allowlist.
    if (request.method === 'GET' && isHealthRequest(request.url, healthPath)) {
      const body = JSON.stringify({ ok: true, name, uptimeMs: Date.now() - startedAt });
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(body);
      return;
    }
    // Metricas locales: mismo guard de path relativo, antes de la auth.
    if (request.method === 'GET' && isMetricsRequest(request.url)) {
      if (!metricsAuthorized(request)) {
        response.writeHead(403);
        response.end();
        return;
      }
      uptimeSeconds.set(process.uptime());
      response.writeHead(200, { 'content-type': 'text/plain; version=0.0.4; charset=utf-8' });
      response.end(registry.render());
      return;
    }
    // Solo las peticiones proxied cuentan como trafico (no /__health ni /metrics).
    response.on('finish', () => requestsTotal.inc({ code: String(response.statusCode) }));
    if (!authorized(request)) {
      authFailures.inc();
      response.writeHead(407, { 'proxy-authenticate': 'Basic realm="exit"' });
      response.end();
      return;
    }
    const target = parseTarget(request);
    if (!target || target.protocol !== 'http:') {
      response.writeHead(400);
      response.end();
      return;
    }
    const host = target.hostname.replace(/^\[|\]$/g, '');
    const port = Number(target.port) || 80;
    if (blockPrivate && isBlockedHost(host, port)) {
      blockedTotal.inc({ reason: 'ssrf' });
      logger?.warn?.('destino bloqueado', { host, port, reason: 'ssrf' });
      response.writeHead(403);
      response.end();
      return;
    }
    const headers = stripHopByHop(request.headers);
    delete headers['proxy-authorization'];
    delete headers['proxy-connection'];
    headers.host = target.host;
    const proxyRequest = http.request(
      {
        host,
        port,
        path: `${target.pathname}${target.search}`,
        method: request.method,
        headers,
      },
      (proxyResponse) => {
        response.writeHead(proxyResponse.statusCode ?? 502, {
          ...stripHopByHop(proxyResponse.headers),
          'x-exit-name': name,
        });
        proxyResponse.pipe(response);
        proxyResponse.on('data', (chunk: Buffer) => bytesTotal.inc({ direction: 'down' }, chunk.length));
      },
    );
    proxyRequest.setTimeout(connectTimeoutMs, () => proxyRequest.destroy());
    proxyRequest.on('error', () => {
      if (!response.headersSent) response.writeHead(502);
      response.end();
    });
    request.on('error', () => proxyRequest.destroy());
    request.pipe(proxyRequest);
    request.on('data', (chunk: Buffer) => bytesTotal.inc({ direction: 'up' }, chunk.length));
  });

  server.on('connection', (socket: net.Socket) => {
    activeConnections.inc();
    socket.on('close', () => activeConnections.dec());
  });

  server.headersTimeout = 10000;
  server.requestTimeout = 30000;
  server.keepAliveTimeout = 10000;
  server.timeout = idleTimeoutMs;

  server.on('connect', (request: http.IncomingMessage, clientSocket: net.Socket, head: Buffer) => {
    if (!authorized(request)) {
      authFailures.inc();
      requestsTotal.inc({ code: '407' });
      clientSocket.write(
        'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="exit"\r\n\r\n',
      );
      clientSocket.destroy();
      return;
    }
    const { host, port } = parseAuthority(request.url);
    if (blockPrivate && isBlockedHost(host, port)) {
      blockedTotal.inc({ reason: 'ssrf' });
      requestsTotal.inc({ code: '403' });
      logger?.warn?.('destino bloqueado', { host, port, reason: 'ssrf' });
      clientSocket.write('HTTP/1.1 403 Forbidden\r\n\r\n');
      clientSocket.destroy();
      return;
    }
    const upstream = net.connect({ host, port });
    upstream.setNoDelay(true);
    upstream.setKeepAlive(true, 30000);
    const timer = setTimeout(() => upstream.destroy(), connectTimeoutMs);
    let established = false;
    if (idleTimeoutMs > 0) {
      clientSocket.setTimeout(idleTimeoutMs, () => clientSocket.destroy());
      clientSocket.on('close', () => clientSocket.setTimeout(0));
    }
    upstream.on('connect', () => {
      clearTimeout(timer);
      established = true;
      requestsTotal.inc({ code: '200' });
      clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head && head.length) upstream.write(head);
      upstream.pipe(clientSocket);
      clientSocket.pipe(upstream);
      clientSocket.on('data', (chunk: Buffer) => bytesTotal.inc({ direction: 'up' }, chunk.length));
      upstream.on('data', (chunk: Buffer) => bytesTotal.inc({ direction: 'down' }, chunk.length));
    });
    upstream.on('error', () => {
      clearTimeout(timer);
      if (!established) requestsTotal.inc({ code: '502' });
      clientSocket.destroy();
    });
    upstream.on('close', () => {
      clearTimeout(timer);
      clientSocket.destroy();
    });
    upstream.on('end', () => clientSocket.destroy());
    clientSocket.on('error', () => upstream.destroy());
    clientSocket.on('end', () => upstream.destroy());
    clientSocket.on('close', () => upstream.destroy());
  });

  server.on('upgrade', (request: http.IncomingMessage, clientSocket: net.Socket, head: Buffer) => {
    if (!authorized(request)) {
      authFailures.inc();
      requestsTotal.inc({ code: '407' });
      clientSocket.write(
        'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="exit"\r\n\r\n',
      );
      clientSocket.destroy();
      return;
    }
    const target = parseTarget(request);
    if (!target || target.protocol !== 'http:') {
      requestsTotal.inc({ code: '400' });
      clientSocket.write('HTTP/1.1 400 Bad Request\r\n\r\n');
      clientSocket.destroy();
      return;
    }
    const host = target.hostname.replace(/^\[|\]$/g, '');
    const port = Number(target.port) || 80;
    if (blockPrivate && isBlockedHost(host, port)) {
      blockedTotal.inc({ reason: 'ssrf' });
      requestsTotal.inc({ code: '403' });
      logger?.warn?.('destino bloqueado', { host, port, reason: 'ssrf' });
      clientSocket.write('HTTP/1.1 403 Forbidden\r\n\r\n');
      clientSocket.destroy();
      return;
    }
    const headers = upgradeHeaders(request.headers, target.host);
    const upstream = pipeUpgrade({
      request,
      clientSocket,
      head,
      options: {
        host,
        port,
        method: request.method,
        path: `${target.pathname}${target.search}`,
        headers,
      },
    });
    upstream.on('upgrade', (_response, upstreamSocket) => {
      requestsTotal.inc({ code: '101' });
      clientSocket.on('data', (chunk: Buffer) => bytesTotal.inc({ direction: 'up' }, chunk.length));
      upstreamSocket.on('data', (chunk: Buffer) => bytesTotal.inc({ direction: 'down' }, chunk.length));
    });
    upstream.on('response', (proxyResponse) => {
      requestsTotal.inc({ code: String(proxyResponse.statusCode) });
    });
    upstream.on('error', () => requestsTotal.inc({ code: '502' }));
  });

  // Rota credenciales en caliente mutando el mismo array que usa authorized().
  const reloadCredentials = (next: Credential[]): void => {
    credentials.length = 0;
    for (const credential of next) credentials.push(credential);
  };
  (server as ExitServer).reloadCredentials = reloadCredentials;

  return server as ExitServer;
}

const isMain = process.argv[1] !== undefined && path.resolve(process.argv[1]) === import.meta.filename;

export function runExit(): void {
  loadEnv();
  const name = envString('EXIT_NAME', 'exit');
  const host = envString('EXIT_HOST', '127.0.0.1');
  const port = envNumber('EXIT_PORT', 8899);
  const user = envString('EXIT_USER');
  const users = parseCredentials(envString('EXIT_USERS'));
  const credentialsCount = users.length + (user ? 1 : 0);
  const allowFrom = envList('EXIT_ALLOW');
  const logger = createLogger({
    level: parseLogLevel(envString('LOG_LEVEL', 'info')),
    format: parseLogFormat(envString('LOG_FORMAT', 'json')),
    role: 'exit',
    name,
  });
  const manifest = JSON.parse(
    fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
  ) as { version?: string };
  const server = createExitServer({
    name,
    user,
    pass: envString('EXIT_PASS'),
    users,
    allowFrom,
    connectTimeoutMs: envNumber('EXIT_CONNECT_TIMEOUT_MS', 15000),
    blockPrivate: envBool('EXIT_BLOCK_PRIVATE', true),
    idleTimeoutMs: envNumber('EXIT_IDLE_TIMEOUT_MS', 0),
    metricsToken: envString('METRICS_TOKEN'),
    logger,
    version: manifest.version ?? 'unknown',
  });
  process.on('uncaughtException', (error) => {
    logger.error?.(`excepcion no capturada: ${error.message}`);
    process.exit(1);
  });
  process.on('unhandledRejection', (reason) => {
    const message = reason instanceof Error ? reason.message : String(reason);
    logger.error?.(`promesa rechazada: ${message}`);
    process.exit(1);
  });
  server.listen(port, host, () => {
    const auth = credentialsCount ? ' (con auth)' : '';
    const allow = allowFrom.length ? ` allow=${allowFrom.join(',')}` : '';
    logger.info?.(`HTTP proxy escuchando en ${host}:${port}${auth}${allow} credentials=${credentialsCount}`, {
      host,
      port,
      auth: credentialsCount > 0,
      credentials: credentialsCount,
      allow: allowFrom,
    });
  });
  server.on('error', (error) => {
    logger.error?.(`no pude escuchar en ${host}:${port}: ${error.message}`);
    process.exit(1);
  });
  // Recarga de credenciales en caliente: solo si el .env trae las claves relevantes.
  watchEnv(
    path.join(import.meta.dirname, '..', '.env'),
    (values) => {
      if (
        values.EXIT_USERS === undefined &&
        values.EXIT_USER === undefined &&
        values.EXIT_PASS === undefined
      ) {
        return;
      }
      const next = parseCredentials(values.EXIT_USERS ?? '');
      if (values.EXIT_USER) next.push({ user: values.EXIT_USER, pass: values.EXIT_PASS ?? '' });
      server.reloadCredentials(next);
      logger.info?.('credenciales recargadas', { count: next.length });
    },
    logger,
  );
}

if (isMain) runExit();
