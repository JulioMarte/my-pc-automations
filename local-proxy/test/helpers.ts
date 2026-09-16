import http from 'node:http';
import net from 'node:net';
import { createExitServer, type ExitServerOptions } from '../src/exit.ts';
import { createGateway, type GatewayConfig } from '../src/gateway.ts';
import { basic } from '../src/upstream.ts';

const socketsByServer = new WeakMap<net.Server, Set<net.Socket>>();

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

function trackSockets(server: net.Server): Set<net.Socket> {
  const sockets = new Set<net.Socket>();
  socketsByServer.set(server, sockets);
  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  return sockets;
}

function closeServer(server: net.Server): Promise<void> {
  return new Promise((resolve) => {
    if (!server.listening) {
      resolve();
      return;
    }
    const sockets = socketsByServer.get(server);
    if (sockets) {
      for (const socket of sockets) socket.destroy();
    }
    (server as http.Server).closeAllConnections?.();
    server.close(() => resolve());
  });
}

interface OriginHandle {
  server: http.Server;
  port: number;
  url: string;
}

async function startOrigin(handler?: http.RequestListener): Promise<OriginHandle> {
  const server = http.createServer(
    handler ||
      ((request, response) => {
        response.writeHead(200, { 'content-type': 'text/plain', 'x-origin': 'yes' });
        response.end('origin-ok');
      }),
  );
  trackSockets(server);
  const port = await listen(server);
  return { server, port, url: `http://127.0.0.1:${port}` };
}

interface ExitHandle {
  server: http.Server;
  port: number;
  stats: { connections: number; requests: number };
}

async function startExit(options: ExitServerOptions = {}): Promise<ExitHandle> {
  const stats = { connections: 0, requests: 0 };
  const server = createExitServer({ blockPrivate: false, ...options });
  trackSockets(server);
  server.on('connection', () => {
    stats.connections += 1;
  });
  server.on('request', () => {
    stats.requests += 1;
  });
  const port = await listen(server);
  return { server, port, stats };
}

async function startGateway(config: GatewayConfig = {}) {
  const gateway = createGateway({ httpPort: 0, socksPort: 0, ...config });
  const addresses = await gateway.start();
  return { gateway, ...addresses };
}

interface ProxyResponse {
  status: number | undefined;
  headers: http.IncomingHttpHeaders;
  body: string;
}

interface HttpGetThroughProxyOptions {
  proxyPort: number;
  targetUrl: string;
  username: string;
  password: string;
  method?: string;
  headers?: http.OutgoingHttpHeaders;
  body?: string;
}

function httpGetThroughProxy({
  proxyPort,
  targetUrl,
  username,
  password,
  method = 'GET',
  headers = {},
  body,
}: HttpGetThroughProxyOptions): Promise<ProxyResponse> {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        host: '127.0.0.1',
        port: proxyPort,
        method,
        path: targetUrl,
        headers: {
          host: new URL(targetUrl).host,
          'proxy-authorization': basic(username, password),
          ...headers,
        },
      },
      (response) => {
        let text = '';
        response.on('data', (chunk: Buffer) => {
          text += chunk;
        });
        response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body: text }));
      },
    );
    request.on('error', reject);
    if (body !== undefined) request.write(body);
    request.end();
  });
}

interface ConnectThroughProxyOptions {
  proxyPort: number;
  target: string;
  username?: string;
  password?: string;
}

function connectThroughProxy({ proxyPort, target, username, password }: ConnectThroughProxyOptions): Promise<net.Socket> {
  return new Promise((resolve, reject) => {
    const socket = net.connect(proxyPort, '127.0.0.1');
    let buffer = '';
    const onData = (chunk: Buffer) => {
      buffer += chunk.toString('latin1');
      const end = buffer.indexOf('\r\n\r\n');
      if (end === -1) return;
      socket.removeListener('data', onData);
      const status = Number(buffer.split(' ')[1] || 0);
      if (status !== 200) {
        socket.destroy();
        reject(new Error(`CONNECT respondio ${status}`));
        return;
      }
      const rest = buffer.slice(end + 4);
      if (rest) socket.unshift(Buffer.from(rest, 'latin1'));
      resolve(socket);
    };
    socket.on('data', onData);
    socket.on('error', reject);
    socket.on('connect', () => {
      const lines = [`CONNECT ${target} HTTP/1.1`, `Host: ${target}`];
      if (username) lines.push(`Proxy-Authorization: ${basic(username, password)}`);
      socket.write(`${lines.join('\r\n')}\r\n\r\n`);
    });
  });
}

function readBytes(socket: net.Socket, count: number): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    let buffer = Buffer.alloc(0);
    const onData = (chunk: Buffer) => {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length < count) return;
      socket.removeListener('data', onData);
      socket.removeListener('error', onError);
      const extra = buffer.subarray(count);
      if (extra.length) socket.unshift(extra);
      resolve(buffer.subarray(0, count));
    };
    const onError = (error: Error) => {
      socket.removeListener('data', onData);
      reject(error);
    };
    socket.on('data', onData);
    socket.on('error', onError);
  });
}

interface Socks5ConnectOptions {
  proxyPort: number;
  targetHost: string;
  targetPort: number;
  username: string;
  password: string;
}

async function socks5Connect({
  proxyPort,
  targetHost,
  targetPort,
  username,
  password,
}: Socks5ConnectOptions): Promise<net.Socket> {
  const socket = net.connect(proxyPort, '127.0.0.1');
  await new Promise<void>((resolve, reject) => {
    socket.once('connect', resolve);
    socket.once('error', reject);
  });
  socket.write(Buffer.from([0x05, 0x01, 0x02]));
  const method = await readBytes(socket, 2);
  if (method[1] !== 0x02) throw new Error('SOCKS5 no acepto user/pass');
  const user = Buffer.from(username);
  const pass = Buffer.from(password);
  socket.write(Buffer.concat([Buffer.from([0x01, user.length]), user, Buffer.from([pass.length]), pass]));
  const auth = await readBytes(socket, 2);
  if (auth[1] !== 0x00) throw new Error('SOCKS5 auth rechazada');
  const host = Buffer.from(targetHost);
  const port = Buffer.alloc(2);
  port.writeUInt16BE(targetPort, 0);
  socket.write(Buffer.concat([Buffer.from([0x05, 0x01, 0x00, 0x03, host.length]), host, port]));
  const reply = await readBytes(socket, 10);
  if (reply[1] !== 0x00) throw new Error(`SOCKS5 connect respondio ${reply[1]}`);
  return socket;
}

function waitFor(predicate: () => unknown, timeoutMs = 4000): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const tick = (): void => {
      let result: unknown;
      try {
        result = predicate();
      } catch (error) {
        reject(error);
        return;
      }
      if (result) {
        resolve(result);
        return;
      }
      if (Date.now() > deadline) {
        reject(new Error('waitFor: timeout'));
        return;
      }
      setTimeout(tick, 25);
    };
    tick();
  });
}

async function freePort(): Promise<number> {
  const server = net.createServer();
  const port = await listen(server);
  await closeServer(server);
  return port;
}

interface HttpGetOptions {
  port: number;
  path: string;
  headers?: http.OutgoingHttpHeaders;
}

function httpGet({ port, path: requestPath, headers = {} }: HttpGetOptions): Promise<ProxyResponse> {
  return new Promise((resolve, reject) => {
    const request = http.request({ host: '127.0.0.1', port, path: requestPath, headers }, (response) => {
      let body = '';
      response.on('data', (chunk: Buffer) => {
        body += chunk;
      });
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body }));
    });
    request.on('error', reject);
    request.end();
  });
}

function readAll(socket: net.Socket): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let done = false;
    const finish = (): void => {
      if (done) return;
      done = true;
      resolve(Buffer.concat(chunks).toString());
    };
    socket.on('data', (chunk: Buffer) => chunks.push(chunk));
    socket.on('end', finish);
    socket.on('close', finish);
    socket.on('error', reject);
  });
}

export {
  listen,
  closeServer,
  trackSockets,
  waitFor,
  freePort,
  startOrigin,
  startExit,
  startGateway,
  httpGetThroughProxy,
  connectThroughProxy,
  socks5Connect,
  httpGet,
  readAll,
};
