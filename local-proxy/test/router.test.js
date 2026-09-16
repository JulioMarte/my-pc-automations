const test = require('node:test');
const assert = require('node:assert/strict');
const { parseUser, parseUsers, createAuthenticator, ExitPool } = require('../src/router');

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
  assert.equal(auth('julio', 'pa:ss').base, 'julio');
  assert.equal(auth('julio', 'pa'), null);
});

test('authenticator: acepta solo credenciales validas', () => {
  const auth = createAuthenticator(parseUsers('julio:clave,otro:clave2'));
  assert.equal(auth('julio-session-x', 'clave').base, 'julio');
  assert.equal(auth('julio', 'mala'), null);
  assert.equal(auth('nadie', 'clave'), null);
  assert.equal(auth('', ''), null);
});

test('ExitPool: rota exits sanos en orden', () => {
  const pool = new ExitPool([
    { name: 'a', host: 'h', port: 1 },
    { name: 'b', host: 'h', port: 2 },
  ]);
  assert.equal(pool.candidates({ base: 'u' })[0].name, 'a');
  assert.equal(pool.candidates({ base: 'u' })[0].name, 'b');
  assert.equal(pool.candidates({ base: 'u' })[0].name, 'a');
});

test('ExitPool: sticky mantiene el exit y expira con TTL', async () => {
  const exits = [
    { name: 'a', host: 'h', port: 1 },
    { name: 'b', host: 'h', port: 2 },
  ];
  const pool = new ExitPool(exits, { sessionTtlMs: 5 });
  const parsed = { base: 'u', session: 's' };
  const first = pool.candidates(parsed)[0];
  pool.commit(parsed, first);
  assert.equal(pool.candidates(parsed)[0].name, first.name);
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
  pool.commit(parsed, pool.candidates(parsed)[0]);
  const rotated = pool.candidates({ ...parsed, rotate: true });
  assert.ok(rotated.length > 0);
});

test('ExitPool: failover descarta sesion en exit no sano', () => {
  const pool = new ExitPool([
    { name: 'a', host: 'h', port: 1 },
    { name: 'b', host: 'h', port: 2 },
  ]);
  const parsed = { base: 'u', session: 's' };
  const a = pool.exits.find((exit) => exit.name === 'a');
  pool.commit(parsed, a);
  pool.recordFailure(a);
  pool.recordFailure(a);
  assert.equal(a.healthy, false);
  assert.equal(pool.candidates(parsed)[0].name, 'b');
});

test('ExitPool: reload conserva salud y limpia sesiones huerfanas', () => {
  const pool = new ExitPool([{ name: 'a', host: 'h', port: 1 }]);
  const a = pool.exits[0];
  pool.recordFailure(a);
  const parsed = { base: 'u', session: 's' };
  pool.commit(parsed, a);
  pool.reload([
    { name: 'a', host: 'h', port: 1 },
    { name: 'b', host: 'h', port: 2 },
  ]);
  assert.equal(pool.exits.find((exit) => exit.name === 'a').failures, 1);
  assert.equal(pool.sessions.size, 1);
  pool.reload([{ name: 'b', host: 'h', port: 2 }]);
  assert.equal(pool.sessions.size, 0);
});
