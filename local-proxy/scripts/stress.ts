// Generador de carga hermetico para local-proxy.
//
// Levanta en el mismo proceso un origen HTTP, un exit real y un gateway con dos
// exits (uno apuntando a un puerto muerto para ejercitar el failover), y lanza N
// workers concurrentes que hacen R peticiones cada uno. Dos modos:
//
//   --mode=http     GET absoluto a traves del proxy HTTP (sin tunel).
//   --mode=connect  tunel CONNECT crudo; envia un payload y verifica el eco.
//
// El cliente HTTP minimo va inline a proposito (no importa test/helpers.ts) para
// que el script sea autocontenido. Sin dependencias de runtime.
//
// Uso:
//   node scripts/stress.ts
//   node scripts/stress.ts --connections=20 --requests=50 --mode=connect
//   node scripts/stress.ts --size=4096 --duration=10 --max-error-rate=0.05
//
// Imprime una tabla legible y un resumen JSON. Sale con codigo 0 si la tasa de
// error observada es <= --max-error-rate; 1 en caso contrario.

import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { createExitServer } from '../src/exit.ts';
import { createGateway } from '../src/gateway.ts';
import { ExitPool } from '../src/router.ts';
import type { Logger } from '../src/logger.ts';

// El exit muerto genera un warning por cada failover; se silencia para no
// ensuciar la salida del reporte.
const silentLogger: Logger = {};

type Mode = 'http' | 'connect';

interface Options {
  host: string;
  connections: number;
  requests: number;
  size: number;
  mode: Mode;
  maxErrorRate: number;
  durationMs: number;
  user: string;
  pass: string;
  timeoutMs: number;
}

interface Counters {
  total: number;
  ok: number;
  errors: number;
  bytesUp: number;
  bytesDown: number;
  latencies: number[];
  sampleErrors: string[];
}

interface Summary {
  mode: Mode;
  connections: number;
  requestsPerWorker: number;
  size: number;
  total: number;
  ok: number;
  errors: number;
  errorRate: number;
  requestsPerSecond: number;
  latencyMs: { p50: number; p95: number; p99: number; max: number };
  bytesUp: number;
  bytesDown: number;
  elapsedMs: number;
  durationMs: number;
  peakRssBytes: number;
  maxErrorRate: number;
  passed: boolean;
  sampleErrors: string[];
}

interface Ports {
  proxy: number;
  origin: number;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}

function parseArgs(argv: string[], env: NodeJS.ProcessEnv): Options {
  const flags = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index] as string;
    if (!arg.startsWith('--')) continue;
    const equals = arg.indexOf('=');
    if (equals !== -1) {
      flags.set(arg.slice(2, equals), arg.slice(equals + 1));
      continue;
    }
    const next = argv[index + 1];
    if (next !== undefined && !next.startsWith('--')) {
      flags.set(arg.slice(2), next);
      index += 1;
    } else {
      flags.set(arg.slice(2), 'true');
    }
  }
  const numeric = (flag: string, envKey: string, fallback: number): number => {
    const raw = flags.get(flag) ?? env[envKey];
    if (raw === undefined) return fallback;
    const value = Number(raw);
    return Number.isFinite(value) && value >= 0 ? value : fallback;
  };
  const modeValue = (flags.get('mode') ?? env.STRESS_MODE ?? 'http').toLowerCase();
  const mode: Mode = modeValue === 'connect' ? 'connect' : 'http';
  return {
    host: '127.0.0.1',
    connections: Math.max(1, Math.floor(numeric('connections', 'STRESS_CONNECTIONS', 10))),
    requests: Math.max(1, Math.floor(numeric('requests', 'STRESS_REQUESTS', 50))),
    size: Math.max(0, Math.floor(numeric('size', 'STRESS_SIZE', 1024))),
    mode,
    maxErrorRate: numeric('max-error-rate', 'STRESS_MAX_ERROR_RATE', 0.01),
    durationMs: Math.floor(numeric('duration', 'STRESS_DURATION', 0) * 1000),
    user: flags.get('user') ?? env.STRESS_USER ?? 'stress',
    pass: flags.get('pass') ?? env.STRESS_PASS ?? 'clave',
    timeoutMs: Math.max(1000, Math.floor(numeric('timeout', 'STRESS_TIMEOUT_MS', 10000))),
  };
}

function listen(server: net.Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject);
      const address = server.address();
      if (address && typeof address === 'object') resolve(address.port);
      else reject(new Error('el servidor no tiene direccion'));
    });
  });
}

function closeServer(server: net.Server): Promise<void> {
  return new Promise((resolve) => {
    if (!server.listening) {
      resolve();
      return;
    }
    (server as http.Server).closeAllConnections?.();
    server.close(() => resolve());
  });
}

async function freePort(): Promise<number> {
  const server = net.createServer();
  const port = await listen(server);
  await closeServer(server);
  return port;
}

function startOrigin(): Promise<{ server: http.Server; port: number }> {
  const server = http.createServer((request, response) => {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1');
    if (url.pathname === '/payload') {
      const requested = Number(url.searchParams.get('n'));
      const size = Number.isFinite(requested) && requested > 0 ? Math.floor(requested) : 1024;
      const body = Buffer.alloc(size, 0x78);
      response.writeHead(200, { 'content-type': 'application/octet-stream', 'content-length': String(body.length) });
      response.end(body);
      return;
    }
    if (url.pathname === '/echo') {
      const chunks: Buffer[] = [];
      request.on('data', (chunk: Buffer) => chunks.push(chunk));
      request.on('end', () => {
        const body = Buffer.concat(chunks);
        response.writeHead(200, { 'content-type': 'application/octet-stream', 'content-length': String(body.length) });
        response.end(body);
      });
      return;
    }
    response.writeHead(404);
    response.end();
  });
  return listen(server).then((port) => ({ server, port }));
}

function basicToken(user: string, pass: string): string {
  return Buffer.from(`${user}:${pass}`).toString('base64');
}

function readAllBytes(socket: net.Socket, timeoutMs: number): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let done = false;
    const finish = (): void => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve(Buffer.concat(chunks));
    };
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      socket.destroy();
      reject(new Error('timeout leyendo respuesta'));
    }, timeoutMs);
    socket.on('data', (chunk: Buffer) => chunks.push(chunk));
    socket.on('end', finish);
    socket.on('close', finish);
    socket.on('error', (error) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      reject(error);
    });
  });
}

// Decodifica un body con Transfer-Encoding: chunked (el gateway puede
// re-codificar al reenviar si no conserva Content-Length).
function dechunk(input: Buffer): Buffer {
  const parts: Buffer[] = [];
  let offset = 0;
  for (;;) {
    const lineEnd = input.indexOf('\r\n', offset);
    if (lineEnd === -1) break;
    const size = parseInt(input.subarray(offset, lineEnd).toString('latin1').split(';')[0] ?? '0', 16);
    if (!Number.isFinite(size) || size <= 0) break;
    const start = lineEnd + 2;
    parts.push(input.subarray(start, start + size));
    offset = start + size + 2;
  }
  return Buffer.concat(parts);
}

function parseHttpResponse(raw: Buffer): { status: number; body: Buffer } {
  const text = raw.toString('latin1');
  const end = text.indexOf('\r\n\r\n');
  if (end === -1) throw new Error('respuesta HTTP incompleta');
  const lines = text.slice(0, end).split('\r\n');
  const statusLine = lines[0] ?? '';
  const status = Number(statusLine.split(' ')[1] ?? 0);
  const headers = new Map<string, string>();
  for (const line of lines.slice(1)) {
    const colon = line.indexOf(':');
    if (colon === -1) continue;
    headers.set(line.slice(0, colon).trim().toLowerCase(), line.slice(colon + 1).trim());
  }
  let body = raw.subarray(end + 4);
  if ((headers.get('transfer-encoding') ?? '').toLowerCase().includes('chunked')) {
    body = dechunk(body);
  }
  return { status, body };
}

// Modo http: GET absoluto (el proxy lo reenvia al exit). El origen devuelve
// `size` bytes y se verifican. `up` es el tamano exacto de la peticion.
async function httpOnce(options: Options, ports: Ports): Promise<{ up: number; down: number }> {
  const socket = net.connect(ports.proxy, options.host);
  socket.setNoDelay(true);
  await new Promise<void>((resolve, reject) => {
    socket.once('connect', resolve);
    socket.once('error', reject);
  });
  const target = `http://127.0.0.1:${ports.origin}/payload?n=${options.size}`;
  const request =
    `GET ${target} HTTP/1.1\r\n` +
    `Host: 127.0.0.1:${ports.origin}\r\n` +
    `Proxy-Authorization: Basic ${basicToken(options.user, options.pass)}\r\n` +
    `Connection: close\r\n\r\n`;
  socket.write(request);
  const raw = await readAllBytes(socket, options.timeoutMs);
  const response = parseHttpResponse(raw);
  if (response.status !== 200) throw new Error(`HTTP ${response.status}`);
  if (response.body.length !== options.size) {
    throw new Error(`body ${response.body.length} != ${options.size}`);
  }
  return { up: Buffer.byteLength(request), down: raw.length };
}

function openTunnel(options: Options, ports: Ports): Promise<net.Socket> {
  return new Promise((resolve, reject) => {
    const socket = net.connect(ports.proxy, options.host);
    socket.setNoDelay(true);
    let buffer = '';
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error('timeout en CONNECT'));
    }, options.timeoutMs);
    const onData = (chunk: Buffer): void => {
      buffer += chunk.toString('latin1');
      const end = buffer.indexOf('\r\n\r\n');
      if (end === -1) return;
      socket.removeListener('data', onData);
      const status = Number(buffer.split(' ')[1] ?? 0);
      if (status !== 200) {
        clearTimeout(timer);
        socket.destroy();
        reject(new Error(`CONNECT respondio ${status}`));
        return;
      }
      clearTimeout(timer);
      const rest = buffer.slice(end + 4);
      if (rest) socket.unshift(Buffer.from(rest, 'latin1'));
      resolve(socket);
    };
    socket.on('data', onData);
    socket.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    socket.on('connect', () => {
      const authority = `127.0.0.1:${ports.origin}`;
      const request =
        `CONNECT ${authority} HTTP/1.1\r\n` +
        `Host: ${authority}\r\n` +
        `Proxy-Authorization: Basic ${basicToken(options.user, options.pass)}\r\n\r\n`;
      socket.write(request);
    });
  });
}

// Modo connect: abre el tunel y envia un POST con `size` bytes; el origen hace
// eco del payload y se verifica que vuelvan los mismos bytes.
async function connectOnce(options: Options, ports: Ports): Promise<{ up: number; down: number }> {
  const socket = await openTunnel(options, ports);
  const payload = Buffer.alloc(options.size, 0x78);
  const head =
    `POST /echo HTTP/1.1\r\n` +
    `Host: 127.0.0.1:${ports.origin}\r\n` +
    `Content-Length: ${options.size}\r\n` +
    `Connection: close\r\n\r\n`;
  socket.write(head);
  if (payload.length) socket.write(payload);
  const raw = await readAllBytes(socket, options.timeoutMs);
  const response = parseHttpResponse(raw);
  if (response.status !== 200) throw new Error(`HTTP ${response.status}`);
  if (response.body.length !== options.size) {
    throw new Error(`eco ${response.body.length} != ${options.size}`);
  }
  return { up: Buffer.byteLength(head) + payload.length, down: raw.length };
}

async function runWorker(
  options: Options,
  ports: Ports,
  counters: Counters,
  deadline: number,
): Promise<void> {
  let completed = 0;
  for (;;) {
    if (options.durationMs > 0) {
      if (Date.now() >= deadline) return;
    } else if (completed >= options.requests) {
      return;
    }
    const started = performance.now();
    try {
      const result = options.mode === 'connect' ? await connectOnce(options, ports) : await httpOnce(options, ports);
      counters.latencies.push(performance.now() - started);
      counters.bytesUp += result.up;
      counters.bytesDown += result.down;
      counters.ok += 1;
    } catch (error) {
      counters.errors += 1;
      if (counters.sampleErrors.length < 5) counters.sampleErrors.push(errorMessage(error));
    }
    counters.total += 1;
    completed += 1;
  }
}

function percentile(sorted: number[], ratio: number): number {
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(ratio * sorted.length) - 1));
  return sorted[index] as number;
}

function renderTable(summary: Summary): string {
  const rows: Array<[string, string]> = [
    ['modo', summary.mode],
    ['workers', String(summary.connections)],
    ['peticiones/worker', summary.durationMs > 0 ? '(por duracion)' : String(summary.requestsPerWorker)],
    ['payload', formatBytes(summary.size)],
    ['total', String(summary.total)],
    ['ok', String(summary.ok)],
    ['errores', String(summary.errors)],
    ['tasa error', `${(summary.errorRate * 100).toFixed(2)}% (max ${(summary.maxErrorRate * 100).toFixed(2)}%)`],
    ['req/s', summary.requestsPerSecond.toFixed(1)],
    ['p50', `${summary.latencyMs.p50.toFixed(2)} ms`],
    ['p95', `${summary.latencyMs.p95.toFixed(2)} ms`],
    ['p99', `${summary.latencyMs.p99.toFixed(2)} ms`],
    ['max', `${summary.latencyMs.max.toFixed(2)} ms`],
    ['bytes up', formatBytes(summary.bytesUp)],
    ['bytes down', formatBytes(summary.bytesDown)],
    ['elapsed', `${(summary.elapsedMs / 1000).toFixed(2)} s`],
    ['peak RSS', formatBytes(summary.peakRssBytes)],
    ['resultado', summary.passed ? 'OK' : 'FALLO'],
  ];
  const width = Math.max(...rows.map(([key]) => key.length));
  const lines = rows.map(([key, value]) => `  ${key.padEnd(width)}  ${value}`);
  return ['local-proxy stress', ...lines].join('\n');
}

async function main(): Promise<number> {
  const options = parseArgs(process.argv.slice(2), process.env);

  const origin = await startOrigin();
  const exit = createExitServer({ name: 'exit-a', blockPrivate: false });
  const exitPort = await listen(exit);
  const deadPort = await freePort();
  // El exit muerto nunca se marca no sano (umbrales altos) para que el P2C lo
  // siga eligiendo y el failover se ejercite durante toda la corrida.
  const pool = new ExitPool(
    [
      { name: 'exit-a', location: 'local', host: '127.0.0.1', port: exitPort },
      { name: 'exit-dead', location: 'local', host: '127.0.0.1', port: deadPort },
    ],
    { unhealthyThreshold: 1_000_000, circuitThreshold: 1_000_000, healthyThreshold: 1 },
  );
  const statsFile = path.join(os.tmpdir(), `local-proxy-stress-${process.pid}-${Date.now()}.jsonl`);
  const gateway = createGateway({
    host: options.host,
    httpPort: 0,
    socksPort: 0,
    users: new Map([[options.user, options.pass]]),
    pool,
    statsFile,
    healthIntervalMs: 0,
    panelEnabled: false,
    logger: silentLogger,
  });
  const addresses = await gateway.start();

  const counters: Counters = {
    total: 0,
    ok: 0,
    errors: 0,
    bytesUp: 0,
    bytesDown: 0,
    latencies: [],
    sampleErrors: [],
  };
  let peakRss = process.memoryUsage().rss;
  const sampler = setInterval(() => {
    peakRss = Math.max(peakRss, process.memoryUsage().rss);
  }, 25);
  sampler.unref();

  const ports: Ports = { proxy: addresses.httpPort, origin: origin.port };
  const deadline = Date.now() + options.durationMs;
  const startedAt = performance.now();
  try {
    await Promise.all(
      Array.from({ length: options.connections }, () => runWorker(options, ports, counters, deadline)),
    );
  } finally {
    const elapsedMs = performance.now() - startedAt;
    clearInterval(sampler);
    peakRss = Math.max(peakRss, process.memoryUsage().rss);
    await gateway.close();
    await closeServer(exit);
    await closeServer(origin.server);

    const sorted = [...counters.latencies].sort((a, b) => a - b);
    const errorRate = counters.total > 0 ? counters.errors / counters.total : 1;
    const summary: Summary = {
      mode: options.mode,
      connections: options.connections,
      requestsPerWorker: options.requests,
      size: options.size,
      total: counters.total,
      ok: counters.ok,
      errors: counters.errors,
      errorRate,
      requestsPerSecond: elapsedMs > 0 ? (counters.total / elapsedMs) * 1000 : 0,
      latencyMs: {
        p50: round(percentile(sorted, 0.5)),
        p95: round(percentile(sorted, 0.95)),
        p99: round(percentile(sorted, 0.99)),
        max: round(sorted[sorted.length - 1] ?? 0),
      },
      bytesUp: counters.bytesUp,
      bytesDown: counters.bytesDown,
      elapsedMs: round(elapsedMs, 1),
      durationMs: options.durationMs,
      peakRssBytes: peakRss,
      maxErrorRate: options.maxErrorRate,
      passed: errorRate <= options.maxErrorRate,
      sampleErrors: counters.sampleErrors,
    };
    process.stdout.write(`${renderTable(summary)}\n\n`);
    process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
    return summary.passed ? 0 : 1;
  }
}

if (import.meta.main) {
  main()
    .then((code) => {
      process.exitCode = code;
    })
    .catch((error: unknown) => {
      process.stdout.write(`${JSON.stringify({ error: errorMessage(error) })}\n`);
      process.exitCode = 1;
    });
}
