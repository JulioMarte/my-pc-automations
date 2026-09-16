import test from 'node:test';
import assert from 'node:assert/strict';
import { createLogger, parseLogLevel, parseLogFormat } from '../src/logger.ts';

const TS = '2026-01-02T03:04:05.000Z';

function capture() {
  const out: string[] = [];
  const err: string[] = [];
  return { out, err, outFn: (line: string) => out.push(line), errFn: (line: string) => err.push(line) };
}

test('logger: formato JSON con ts, level, msg y campos fusionados', () => {
  const { out, outFn, errFn } = capture();
  const logger = createLogger({ out: outFn, err: errFn, now: () => new Date(TS), role: 'gateway', name: 'g1' });
  logger.info?.('hola', { foo: 'bar' });
  assert.equal(out.length, 1);
  const parsed = JSON.parse(out[0]!) as Record<string, unknown>;
  assert.equal(parsed.ts, TS);
  assert.equal(parsed.level, 'info');
  assert.equal(parsed.msg, 'hola');
  assert.equal(parsed.foo, 'bar');
  assert.equal(parsed.role, 'gateway');
  assert.equal(parsed.name, 'g1');
});

test('logger: filtrado por nivel warn', () => {
  const { out, err, outFn, errFn } = capture();
  const logger = createLogger({ level: 'warn', out: outFn, err: errFn, now: () => new Date(TS) });
  logger.debug?.('d');
  logger.info?.('i');
  logger.warn?.('w');
  logger.error?.('e');
  assert.deepEqual(out, []);
  assert.equal(err.length, 2);
  assert.equal((JSON.parse(err[0]!) as { level: string }).level, 'warn');
  assert.equal((JSON.parse(err[1]!) as { level: string }).level, 'error');
});

test('logger: log() se comporta como info()', () => {
  const { out, outFn, errFn } = capture();
  const logger = createLogger({ out: outFn, err: errFn, now: () => new Date(TS) });
  logger.log?.('mensaje');
  assert.equal(out.length, 1);
  const parsed = JSON.parse(out[0]!) as { level: string; msg: string };
  assert.equal(parsed.level, 'info');
  assert.equal(parsed.msg, 'mensaje');
});

test('logger: redaccion de campos sensibles y anidados', () => {
  const { out, outFn, errFn } = capture();
  const logger = createLogger({ out: outFn, err: errFn, now: () => new Date(TS) });
  logger.info?.('redact', {
    authorization: 'Bearer x',
    'proxy-authorization': 'Basic y',
    password: 'p',
    token: 't',
    cookie: 'c',
    secret: 's',
    safe: 'ok',
    nested: { token: 'z', safe: 1 },
  });
  const parsed = JSON.parse(out[0]!) as Record<string, unknown>;
  assert.equal(parsed.authorization, '[redacted]');
  assert.equal(parsed['proxy-authorization'], '[redacted]');
  assert.equal(parsed.password, '[redacted]');
  assert.equal(parsed.token, '[redacted]');
  assert.equal(parsed.cookie, '[redacted]');
  assert.equal(parsed.secret, '[redacted]');
  assert.equal(parsed.safe, 'ok');
  assert.deepEqual(parsed.nested, { token: '[redacted]', safe: 1 });
});

test('logger: un Error se serializa como name y message', () => {
  const { err, outFn, errFn } = capture();
  const logger = createLogger({ out: outFn, err: errFn, now: () => new Date(TS) });
  logger.error?.('fallo', { cause: new Error('boom') });
  const parsed = JSON.parse(err[0]!) as { cause: { name: string; message: string } };
  assert.deepEqual(parsed.cause, { name: 'Error', message: 'boom' });
});

test('logger: warn/error van a err y info/debug a out', () => {
  const { out, err, outFn, errFn } = capture();
  const logger = createLogger({ level: 'debug', out: outFn, err: errFn, now: () => new Date(TS) });
  logger.debug?.('d');
  logger.info?.('i');
  logger.warn?.('w');
  logger.error?.('e');
  assert.equal(out.length, 2);
  assert.equal(err.length, 2);
  assert.equal((JSON.parse(out[0]!) as { level: string }).level, 'debug');
  assert.equal((JSON.parse(out[1]!) as { level: string }).level, 'info');
  assert.equal((JSON.parse(err[0]!) as { level: string }).level, 'warn');
  assert.equal((JSON.parse(err[1]!) as { level: string }).level, 'error');
});

test('logger: formato text incluye nivel, mensaje y key=value', () => {
  const { out, outFn, errFn } = capture();
  const logger = createLogger({ format: 'text', out: outFn, err: errFn, now: () => new Date(TS), role: 'gateway' });
  logger.info?.('hola', { foo: 'bar' });
  assert.equal(out.length, 1);
  const line = out[0]!;
  assert.ok(line.includes(TS));
  assert.ok(line.includes('INFO'));
  assert.ok(line.includes('hola'));
  assert.ok(line.includes('foo=bar'));
  assert.ok(line.includes('role=gateway'));
});

test('logger: parseLogLevel acepta validos y usa info por defecto', () => {
  assert.equal(parseLogLevel('debug'), 'debug');
  assert.equal(parseLogLevel('INFO'), 'info');
  assert.equal(parseLogLevel('warn'), 'warn');
  assert.equal(parseLogLevel('Error'), 'error');
  assert.equal(parseLogLevel(undefined), 'info');
  assert.equal(parseLogLevel('desconocido'), 'info');
  assert.equal(parseLogLevel(42), 'info');
});

test('logger: parseLogFormat acepta text y usa json por defecto', () => {
  assert.equal(parseLogFormat('text'), 'text');
  assert.equal(parseLogFormat('TEXT'), 'text');
  assert.equal(parseLogFormat('json'), 'json');
  assert.equal(parseLogFormat(undefined), 'json');
  assert.equal(parseLogFormat('otro'), 'json');
});
