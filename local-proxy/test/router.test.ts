import test from 'node:test';
import assert from 'node:assert/strict';
import { parseUser, parseUsers, parseCredentials, createAuthenticator, createAuthLimiter, ExitPool } from '../src/router.ts';

test('parseUser: base, session, rotate, exit y loc', () => {
  assert.deepEqual(parseUser('julio'), { base: 'julio' });
  assert.deepEqual(parseUser('julio-session-abc'), { base: 'julio', session: 'abc' });
  assert.deepEqual(parseUser('julio-rotate'), { base: 'julio', rotate: true });
  assert.deepEqual(parseUser('julio-exit-exit-b'), { base: 'julio', exit: 'exit-b' });
  assert.deepEqual(parseUser('julio-loc-do-santiago'), { base: 'julio', location: 'do-santiago' });
  assert.deepEqual(parseUser('julio-session-abc-123'), { base: 'julio', session: 'abc-123' });
});

test('parseUsers: acepta ":" dentro del password', () => {
  const users = parseUsers('julio:pa:ss,otro:clave');
  assert.equal(users.get('julio'), 'pa:ss');
  assert.equal(users.get('otro'), 'clave');
  const auth = createAuthenticator(users);
  assert.equal(auth('julio', 'pa:ss')?.base, 'julio');
  assert.equal(auth('julio', 'pa'), null);
});

test('parseCredentials: vacio o undefined devuelve lista vacia', () => {
  assert.deepEqual(parseCredentials(undefined), []);
  assert.deepEqual(parseCredentials(''), []);
});

test('parseCredentials: acepta una o varias credenciales', () => {
  assert.deepEqual(parseCredentials('a:1'), [{ user: 'a', pass: '1' }]);
  assert.deepEqual(parseCredentials('a:1,b:2'), [
    { user: 'a', pass: '1' },
    { user: 'b', pass: '2' },
  ]);
});

test('parseCredentials: conserva usuario repetido con distinta clave (rotacion)', () => {
  assert.deepEqual(parseCredentials('a:1,a:2'), [
    { user: 'a', pass: '1' },
    { user: 'a', pass: '2' },
  ]);
});

test('parseCredentials: acepta ":" dentro del password', () => {
  assert.deepEqual(parseCredentials('a:1:2'), [{ user: 'a', pass: '1:2' }]);
});

test('parseCredentials: ignora entradas malformadas', () => {
  assert.deepEqual(parseCredentials('sinclave,:x,,a:1'), [{ user: 'a', pass: '1' }]);
});

test('parseCredentials: recorta espacios del usuario', () => {
  assert.deepEqual(parseCredentials(' a :1'), [{ user: 'a', pass: '1' }]);
});

test('authenticator: acepta solo credenciales validas', () => {
  const auth = createAuthenticator(parseUsers('julio:clave,otro:clave2'));
  assert.equal(auth('julio-session-x', 'clave')?.base, 'julio');
  assert.equal(auth('julio', 'mala'), null);
  assert.equal(auth('nadie', 'clave'), null);
  assert.equal(auth('', ''), null);
});

test('ExitPool: rota exits sanos en orden', () => {
  const pool = new ExitPool([
    { name: 'a', host: 'h', port: 1 },
    { name: 'b', host: 'h', port: 2 },
  ]);
  assert.equal(pool.candidates({ base: 'u' })[0]?.name, 'a');
  assert.equal(pool.candidates({ base: 'u' })[0]?.name, 'b');
  assert.equal(pool.candidates({ base: 'u' })[0]?.name, 'a');
});

test('ExitPool: sticky mantiene el exit y expira con TTL', async () => {
  const exits = [
    { name: 'a', host: 'h', port: 1 },
    { name: 'b', host: 'h', port: 2 },
  ];
  const pool = new ExitPool(exits, { sessionTtlMs: 5 });
  const parsed = { base: 'u', session: 's' };
  const first = pool.candidates(parsed)[0]!;
  pool.commit(parsed, first);
  assert.equal(pool.candidates(parsed)[0]?.name, first.name);
  await new Promise((resolve) => setTimeout(resolve, 20));
  pool.sweep();
  assert.equal(pool.sessions.size, 0);
});

test('ExitPool: forced exit, filtro por location y sesion rota', () => {
  const pool = new ExitPool([
    { name: 'a', location: 'do', host: 'h', port: 1 },
    { name: 'b', location: 'us', host: 'h', port: 2 },
  ]);
  assert.deepEqual(pool.candidates({ base: 'u', exit: 'b' }).map((exit) => exit.name), ['b']);
  assert.deepEqual(pool.candidates({ base: 'u', exit: 'noexiste' }), []);
  const us = pool.candidates({ base: 'u', location: 'us' });
  assert.ok(us.every((exit) => exit.location === 'us'));
  const parsed = { base: 'u', session: 's' };
  pool.commit(parsed, pool.candidates(parsed)[0]!);
  const rotated = pool.candidates({ ...parsed, rotate: true });
  assert.ok(rotated.length > 0);
});

test('ExitPool: failover descarta sesion en exit no sano', () => {
  const pool = new ExitPool([
    { name: 'a', host: 'h', port: 1 },
    { name: 'b', host: 'h', port: 2 },
  ]);
  const parsed = { base: 'u', session: 's' };
  const a = pool.exits.find((exit) => exit.name === 'a')!;
  pool.commit(parsed, a);
  pool.recordFailure(a);
  pool.recordFailure(a);
  assert.equal(a.healthy, false);
  assert.equal(pool.candidates(parsed)[0]?.name, 'b');
});

test('ExitPool: reload conserva salud y limpia sesiones huerfanas', () => {
  const pool = new ExitPool([{ name: 'a', host: 'h', port: 1 }]);
  const a = pool.exits[0]!;
  pool.recordFailure(a);
  const parsed = { base: 'u', session: 's' };
  pool.commit(parsed, a);
  pool.reload([
    { name: 'a', host: 'h', port: 1 },
    { name: 'b', host: 'h', port: 2 },
  ]);
  assert.equal(pool.exits.find((exit) => exit.name === 'a')!.failures, 1);
  assert.equal(pool.sessions.size, 1);
  pool.reload([{ name: 'b', host: 'h', port: 2 }]);
  assert.equal(pool.sessions.size, 0);
});

test('ExitPool: reload actualiza la credencial y conserva salud/fallos/circuito', () => {
  const pool = new ExitPool([{ name: 'a', host: 'h', port: 1, user: 'viejo', pass: 'p1' }]);
  const a = pool.exits[0]!;
  pool.recordFailure(a);
  pool.recordFailure(a);
  pool.recordFailure(a);
  assert.equal(a.healthy, false);
  assert.equal(a.failures, 3);
  assert.equal(a.circuit, 'open');
  pool.reload([{ name: 'a', host: 'h2', port: 2, user: 'nuevo', pass: 'p2' }]);
  const updated = pool.exits.find((exit) => exit.name === 'a')!;
  assert.equal(updated.user, 'nuevo');
  assert.equal(updated.pass, 'p2');
  assert.equal(updated.host, 'h2');
  assert.equal(updated.port, 2);
  assert.equal(updated.healthy, false);
  assert.equal(updated.failures, 3);
  assert.equal(updated.circuit, 'open');
});

test('ExitPool: circuit breaker abre tras 3 fallos y medio-abre tras el backoff', () => {
  let clock = 0;
  const pool = new ExitPool([{ name: 'a', host: 'h', port: 1 }], {
    now: () => clock,
    unhealthyThreshold: 10,
    circuitThreshold: 3,
    circuitBaseMs: 1000,
    circuitMaxMs: 1000,
  });
  const a = pool.exits[0]!;
  pool.recordFailure(a);
  pool.recordFailure(a);
  assert.equal(a.circuit, 'closed');
  assert.equal(pool.healthyExits().length, 1);
  pool.recordFailure(a);
  assert.equal(a.circuit, 'open');
  assert.equal(pool.healthyExits().length, 0);
  clock += 100000;
  assert.equal(pool.healthyExits().length, 1);
  assert.equal(a.circuit, 'halfOpen');
  pool.recordSuccess(a);
  assert.equal(a.circuit, 'halfOpen');
  pool.recordSuccess(a);
  assert.equal(a.circuit, 'closed');
});

test('ExitPool: maxSessions desaloja la sesion mas antigua', () => {
  let clock = 0;
  const pool = new ExitPool([{ name: 'a', host: 'h', port: 1 }], { maxSessions: 2, now: () => clock });
  const exit = pool.exits[0]!;
  pool.commit({ base: 'u', session: 's1' }, exit);
  clock += 1;
  pool.commit({ base: 'u', session: 's2' }, exit);
  clock += 1;
  pool.commit({ base: 'u', session: 's3' }, exit);
  assert.equal(pool.sessions.size, 2);
  assert.equal(pool.sessions.has('u:s1'), false);
  assert.equal(pool.sessions.has('u:s2'), true);
  assert.equal(pool.sessions.has('u:s3'), true);
});

test('createAuthLimiter: bloquea tras N fallos y desbloquea tras blockMs', () => {
  let clock = 0;
  const limiter = createAuthLimiter({ maxFailures: 3, windowMs: 1000, blockMs: 500, now: () => clock });
  assert.equal(limiter.allowed('k'), true);
  limiter.recordFailure('k');
  limiter.recordFailure('k');
  assert.equal(limiter.allowed('k'), true);
  limiter.recordFailure('k');
  assert.equal(limiter.allowed('k'), false);
  assert.deepEqual(limiter.stats(), { tracked: 1, blocked: 1 });
  clock += 499;
  assert.equal(limiter.allowed('k'), false);
  clock += 1;
  assert.equal(limiter.allowed('k'), true);
});

test('createAuthLimiter: recordSuccess limpia el registro', () => {
  let clock = 0;
  const limiter = createAuthLimiter({ maxFailures: 2, windowMs: 1000, blockMs: 500, now: () => clock });
  limiter.recordFailure('k');
  limiter.recordFailure('k');
  assert.equal(limiter.allowed('k'), false);
  limiter.recordSuccess('k');
  assert.equal(limiter.allowed('k'), true);
  assert.deepEqual(limiter.stats(), { tracked: 0, blocked: 0 });
});
