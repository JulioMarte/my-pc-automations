import net from 'node:net';

const SOCKS_VERSION = 0x05;
const AUTH_NONE = 0x00;
const AUTH_USERPASS = 0x02;
const CMD_CONNECT = 0x01;
const ATYP_IPV4 = 0x01;
const ATYP_DOMAIN = 0x03;
const ATYP_IPV6 = 0x04;

export function createSocks5Server(options: {
  auth: (username: string, password: string) => boolean;
  connect: (args: {
    username: string;
    password: string;
    host: string;
    port: number;
    client: net.Socket;
  }) => Promise<net.Socket>;
}): net.Server {
  const { auth, connect } = options;
  const server = net.createServer((socket) => {
    socket.setNoDelay(true);
    let stage: 'greeting' | 'auth' | 'request' = 'greeting';
    let buffer = Buffer.alloc(0);
    let username = '';
    let password = '';
    let chain: Promise<void> = Promise.resolve();
    const hasAuth = Boolean(auth);

    const reply = (code: number): void => {
      socket.write(Buffer.from([SOCKS_VERSION, code, 0x00, ATYP_IPV4, 0, 0, 0, 0, 0, 0]));
    };

    const process = async (): Promise<void> => {
      for (;;) {
        if (stage === 'greeting') {
          if (buffer.length < 2) return;
          if (buffer.readUInt8(0) !== SOCKS_VERSION) {
            socket.destroy();
            return;
          }
          const methodsCount = buffer.readUInt8(1);
          if (buffer.length < 2 + methodsCount) return;
          const methods = buffer.subarray(2, 2 + methodsCount);
          buffer = buffer.subarray(2 + methodsCount);
          if (hasAuth && methods.includes(AUTH_USERPASS)) {
            socket.write(Buffer.from([SOCKS_VERSION, AUTH_USERPASS]));
            stage = 'auth';
            continue;
          }
          if (!hasAuth) {
            socket.write(Buffer.from([SOCKS_VERSION, AUTH_NONE]));
            stage = 'request';
            continue;
          }
          socket.write(Buffer.from([SOCKS_VERSION, 0xff]));
          socket.destroy();
          return;
        }

        if (stage === 'auth') {
          if (buffer.length < 2) return;
          const userLength = buffer.readUInt8(1);
          if (buffer.length < 2 + userLength + 1) return;
          const passLength = buffer.readUInt8(2 + userLength);
          if (buffer.length < 2 + userLength + 1 + passLength) return;
          username = buffer.subarray(2, 2 + userLength).toString();
          password = buffer.subarray(2 + userLength + 1, 2 + userLength + 1 + passLength).toString();
          buffer = buffer.subarray(2 + userLength + 1 + passLength);
          if (!auth(username, password)) {
            socket.write(Buffer.from([0x01, 0x01]));
            socket.destroy();
            return;
          }
          socket.write(Buffer.from([0x01, 0x00]));
          stage = 'request';
          continue;
        }

        if (stage === 'request') {
          if (buffer.length < 4) return;
          const command = buffer.readUInt8(1);
          const atyp = buffer.readUInt8(3);
          let host = '';
          let offset = 4;
          if (atyp === ATYP_IPV4) {
            if (buffer.length < 4 + 4 + 2) return;
            host = `${buffer.readUInt8(4)}.${buffer.readUInt8(5)}.${buffer.readUInt8(6)}.${buffer.readUInt8(7)}`;
            offset = 8;
          } else if (atyp === ATYP_DOMAIN) {
            if (buffer.length < 5) return;
            const length = buffer.readUInt8(4);
            if (buffer.length < 5 + length + 2) return;
            host = buffer.subarray(5, 5 + length).toString();
            offset = 5 + length;
          } else if (atyp === ATYP_IPV6) {
            if (buffer.length < 4 + 16 + 2) return;
            const parts: string[] = [];
            for (let index = 0; index < 16; index += 2) {
              parts.push(buffer.readUInt16BE(4 + index).toString(16));
            }
            host = parts.join(':');
            offset = 20;
          } else {
            reply(0x08);
            socket.destroy();
            return;
          }
          const port = buffer.readUInt16BE(offset);
          buffer = buffer.subarray(offset + 2);
          if (command !== CMD_CONNECT) {
            reply(0x07);
            socket.destroy();
            return;
          }
          try {
            const remote = await connect({ username, password, host, port, client: socket });
            reply(0x00);
            if (buffer.length) remote.write(buffer);
            socket.removeListener('data', onData);
            socket.pipe(remote);
            remote.pipe(socket);
            socket.on('error', () => remote.destroy());
            remote.on('error', () => socket.destroy());
          } catch (error) {
            const code = (error as NodeJS.ErrnoException).code;
            if (code === 'ECONNREFUSED') reply(0x05);
            else if (code === 'ENETUNREACH') reply(0x03);
            else if (code === 'EHOSTUNREACH') reply(0x04);
            else if (code === 'EACCES') reply(0x02);
            else reply(0x01);
            socket.destroy();
          }
          return;
        }

        return;
      }
    };

    const onData = (chunk: Buffer): void => {
      if (buffer.length + chunk.length > 65536) {
        socket.destroy();
        return;
      }
      buffer = Buffer.concat([buffer, chunk]);
      chain = chain.then(process).catch(() => {
        socket.destroy();
      });
    };

    socket.on('data', onData);
    socket.on('error', () => {});
  });
  return server;
}
