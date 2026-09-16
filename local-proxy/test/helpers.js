const http = require('http');
const net = require('net');
const { createExitServer } = require('../src/exit');
const { createGateway } = require('../src/gateway');
const { basic } = require('../src/upstream');

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject);
      resolve(server.address().port);
    });
  });
}

function trackSockets(server) {
  const sockets = new Set();
  server.__sockets = sockets;
  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  return sockets;
}

function closeServer(server) {
  return new Promise((resolve) => {
    if (!server.listening) return resolve();
    if (server.__sockets) {
      for (const socket of server.__sockets) socket.destroy();
    }
    server.closeAllConnections?.();
    server.close(() => resolve());
  });
}

async function startOrigin(handler) {
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

async function startExit(options) {
  const stats = { connections: 0, requests: 0 };
  const server = createExitServer(options);
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

async function startGateway(config) {
  const gateway = createGateway({ httpPort: 0, socksPort: 0, ...config });
  const addresses = await gateway.start();
  return { gateway, ...addresses };
}

function httpGetThroughProxy({
  proxyPort,
  targetUrl,
  username,
  password,
  method = 'GET',
  headers = {},
  body,
}) {
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
        response.on('data', (chunk) => {
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

function connectThroughProxy({ proxyPort, target, username, password }) {
  return new Promise((resolve, reject) => {
    const socket = net.connect(proxyPort, '127.0.0.1');
    let buffer = '';
    const onData = (chunk) => {
      buffer += chunk.toString('latin1');
      const end = buffer.indexOf('\r\n\r\n');
      if (end === -1) return;
      socket.removeListener('data', onData);
      const status = Number((buffer.split(' ')[1] || 0));
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

function readBytes(socket, count) {
  return new Promise((resolve, reject) => {
    let buffer = Buffer.alloc(0);
    const onData = (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length < count) return;
      socket.removeListener('data', onData);
      socket.removeListener('error', onError);
      const extra = buffer.slice(count);
      if (extra.length) socket.unshift(extra);
      resolve(buffer.slice(0, count));
    };
    const onError = (error) => {
      socket.removeListener('data', onData);
      reject(error);
    };
    socket.on('data', onData);
    socket.on('error', onError);
  });
}

async function socks5Connect({ proxyPort, targetHost, targetPort, username, password }) {
  const socket = net.connect(proxyPort, '127.0.0.1');
  await new Promise((resolve, reject) => {
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

function waitFor(predicate, timeoutMs = 4000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const tick = () => {
      let result;
      try {
        result = predicate();
      } catch (error) {
        reject(error);
        return;
      }
      if (result) return resolve(result);
      if (Date.now() > deadline) return reject(new Error('waitFor: timeout'));
      setTimeout(tick, 25);
    };
    tick();
  });
}

async function freePort() {
  const server = net.createServer();
  const port = await listen(server);
  await closeServer(server);
  return port;
}

function httpGet({ port, path: requestPath, headers = {} }) {
  return new Promise((resolve, reject) => {
    const request = http.request({ host: '127.0.0.1', port, path: requestPath, headers }, (response) => {
      let body = '';
      response.on('data', (chunk) => {
        body += chunk;
      });
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body }));
    });
    request.on('error', reject);
    request.end();
  });
}

function readAll(socket) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve(Buffer.concat(chunks).toString());
    };
    socket.on('data', (chunk) => chunks.push(chunk));
    socket.on('end', finish);
    socket.on('close', finish);
    socket.on('error', reject);
  });
}

module.exports = {
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
