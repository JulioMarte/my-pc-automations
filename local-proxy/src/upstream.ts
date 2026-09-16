import net from 'node:net';
import http from 'node:http';

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'proxy-connection',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

export interface ProxyTarget {
  host: string;
  port: number;
  user?: string;
  pass?: string;
}

export class ProxyError extends Error {
  readonly statusCode: number;

  constructor(message: string, statusCode: number) {
    super(message);
    this.name = 'ProxyError';
    this.statusCode = statusCode;
  }
}

export function basic(user: string, pass?: string): string {
  return `Basic ${Buffer.from(`${user}:${pass || ''}`).toString('base64')}`;
}

export function stripHopByHop(
  headers: http.IncomingHttpHeaders | http.OutgoingHttpHeaders,
): Record<string, string | string[]> {
  const connectionTokens = String(headers.connection || '')
    .split(',')
    .map((token) => token.trim().toLowerCase())
    .filter(Boolean);
  const result: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(headers)) {
    const lower = key.toLowerCase();
    if (HOP_BY_HOP.has(lower) || connectionTokens.includes(lower)) continue;
    result[key] = value as string | string[];
  }
  return result;
}

function rawHeaders(headers: http.IncomingHttpHeaders): string {
  return Object.entries(headers)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
    .join('\r\n');
}

export function formatAuthority(host: string, port: number): string {
  return host.includes(':') ? `[${host}]:${port}` : `${host}:${port}`;
}

export function connectViaHttpProxy(opts: {
  proxy: ProxyTarget;
  host: string;
  port: number;
  timeoutMs?: number;
}): Promise<net.Socket> {
  const { proxy, host, port, timeoutMs = 20000 } = opts;
  return new Promise((resolve, reject) => {
    const socket = net.connect(proxy.port, proxy.host);
    socket.setNoDelay(true);
    socket.setKeepAlive(true, 30000);
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      socket.destroy();
      reject(new ProxyError('timeout conectando al exit', 504));
    }, timeoutMs);

    socket.on('connect', () => {
      const authority = formatAuthority(host, port);
      const lines = [`CONNECT ${authority} HTTP/1.1`, `Host: ${authority}`];
      if (proxy.user) lines.push(`Proxy-Authorization: ${basic(proxy.user, proxy.pass)}`);
      socket.write(`${lines.join('\r\n')}\r\n\r\n`);
    });

    let response = '';
    const onData = (chunk: Buffer) => {
      response += chunk.toString('latin1');
      const end = response.indexOf('\r\n\r\n');
      if (end === -1) return;
      socket.removeListener('data', onData);
      const match = /^HTTP\/\d\.\d\s+(\d{3})/.exec(response);
      const status = match ? Number(match[1]) : 0;
      if (status !== 200) {
        settled = true;
        clearTimeout(timer);
        socket.destroy();
        reject(new ProxyError(`exit respondio ${status || 'respuesta invalida'}`, 502));
        return;
      }
      settled = true;
      clearTimeout(timer);
      const rest = Buffer.from(response.slice(end + 4), 'latin1');
      if (rest.length) {
        socket.pause();
        socket.unshift(rest);
      }
      resolve(socket);
    };

    socket.on('data', onData);
    socket.on('end', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new ProxyError('exit cerro la conexion sin responder', 502));
    });
    socket.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new ProxyError(error.message, 502));
    });
  });
}

export interface ForwardHooks {
  countUp?(chunk: Buffer): void;
  countDown?(chunk: Buffer): void;
  onDone?(): void;
  onResponse?(res: http.IncomingMessage): boolean | void;
  onError?(error: Error): boolean | void;
}

export function forwardHttp(
  request: http.IncomingMessage,
  response: http.ServerResponse,
  proxy: ProxyTarget,
  hooks: ForwardHooks = {},
): http.ClientRequest {
  const headers = stripHopByHop(request.headers);
  delete headers['proxy-authorization'];
  delete headers['proxy-connection'];
  if (proxy.user) headers['proxy-authorization'] = basic(proxy.user, proxy.pass);
  const proxyRequest = http.request(
    {
      host: proxy.host,
      port: proxy.port,
      method: request.method,
      path: request.url,
      headers,
    },
    (proxyResponse) => {
      if (hooks.onResponse && hooks.onResponse(proxyResponse) === true) {
        proxyResponse.resume();
        return;
      }
      if (!response.headersSent) {
        response.writeHead(proxyResponse.statusCode as number, stripHopByHop(proxyResponse.headers));
      }
      if (hooks.countDown) proxyResponse.on('data', hooks.countDown);
      proxyResponse.on('end', () => hooks.onDone?.());
      proxyResponse.on('error', () => hooks.onDone?.());
      proxyResponse.pipe(response);
    },
  );
  if (hooks.countUp) request.on('data', hooks.countUp);
  request.on('error', () => proxyRequest.destroy());
  proxyRequest.on('close', () => hooks.onDone?.());
  proxyRequest.on('error', (error) => {
    if (hooks.onError && hooks.onError(error)) return;
    if (response.headersSent) {
      response.destroy();
      return;
    }
    response.writeHead(502);
    response.end();
  });
  request.pipe(proxyRequest);
  return proxyRequest;
}

export function pipeUpgrade(args: {
  request: http.IncomingMessage;
  clientSocket: net.Socket;
  head: Buffer | null;
  options: http.RequestOptions;
  onDone?(): void;
  onError?(error: Error): boolean | void;
}): http.ClientRequest {
  const { request, clientSocket, head, options, onDone, onError } = args;
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    onDone?.();
  };
  const upstream = http.request(options);
  if (head && head.length) upstream.write(head);
  upstream.on('upgrade', (upgradeResponse, upstreamSocket, upstreamHead) => {
    clientSocket.write(
      `HTTP/1.1 ${upgradeResponse.statusCode} ${upgradeResponse.statusMessage}\r\n${rawHeaders(upgradeResponse.headers)}\r\n\r\n`,
    );
    if (upstreamHead && upstreamHead.length) clientSocket.write(upstreamHead);
    clientSocket.pipe(upstreamSocket);
    upstreamSocket.pipe(clientSocket);
    const closeBoth = () => {
      clientSocket.destroy();
      upstreamSocket.destroy();
      finish();
    };
    clientSocket.on('error', () => upstreamSocket.destroy());
    upstreamSocket.on('error', () => clientSocket.destroy());
    clientSocket.on('end', closeBoth);
    clientSocket.on('close', closeBoth);
    upstreamSocket.on('end', closeBoth);
    upstreamSocket.on('close', closeBoth);
  });
  upstream.on('response', (proxyResponse) => {
    if (!clientSocket.writable) return finish();
    clientSocket.write(
      `HTTP/1.1 ${proxyResponse.statusCode} ${proxyResponse.statusMessage}\r\n${rawHeaders(proxyResponse.headers)}\r\n\r\n`,
    );
    proxyResponse.pipe(clientSocket);
    proxyResponse.on('end', finish);
    proxyResponse.on('error', finish);
  });
  upstream.on('error', (error) => {
    if (onError && onError(error)) return;
    if (clientSocket.writable) clientSocket.write('HTTP/1.1 502 Bad Gateway\r\n\r\n');
    clientSocket.destroy();
    finish();
  });
  request.on('error', () => upstream.destroy());
  request.pipe(upstream);
  return upstream;
}
