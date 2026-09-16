import test from 'node:test';
import assert from 'node:assert/strict';
import { ConnectionLimiter } from '../src/limits.ts';

test('limits: max 0 significa ilimitado', () => {
  const limiter = new ConnectionLimiter({ max: 0 });
  for (let index = 0; index < 1000; index += 1) {
    assert.equal(limiter.acquire('agent'), true);
  }
  assert.equal(limiter.count('agent'), 1000);
  assert.equal(limiter.total(), 1000);
});

test('limits: sin opciones tambien es ilimitado', () => {
  const limiter = new ConnectionLimiter();
  assert.equal(limiter.acquire('agent'), true);
  assert.equal(limiter.acquire('agent'), true);
  assert.equal(limiter.count('agent'), 2);
});

test('limits: max 3 rechaza la cuarta y release libera cupo', () => {
  const limiter = new ConnectionLimiter({ max: 3 });
  assert.equal(limiter.acquire('agent'), true);
  assert.equal(limiter.acquire('agent'), true);
  assert.equal(limiter.acquire('agent'), true);
  assert.equal(limiter.count('agent'), 3);
  assert.equal(limiter.total(), 3);
  assert.equal(limiter.acquire('agent'), false);
  assert.equal(limiter.count('agent'), 3);
  limiter.release('agent');
  assert.equal(limiter.count('agent'), 2);
  assert.equal(limiter.total(), 2);
  assert.equal(limiter.acquire('agent'), true);
  assert.equal(limiter.count('agent'), 3);
});

test('limits: usuarios son independientes entre si', () => {
  const limiter = new ConnectionLimiter({ max: 2 });
  assert.equal(limiter.acquire('agent'), true);
  assert.equal(limiter.acquire('agent'), true);
  assert.equal(limiter.acquire('otro'), true);
  assert.equal(limiter.count('agent'), 2);
  assert.equal(limiter.count('otro'), 1);
  assert.equal(limiter.total(), 3);
  assert.equal(limiter.acquire('agent'), false);
  assert.equal(limiter.acquire('otro'), true);
});

test('limits: release de usuario desconocido es no-op', () => {
  const limiter = new ConnectionLimiter({ max: 5 });
  limiter.acquire('agent');
  limiter.release('nadie');
  assert.equal(limiter.count('nadie'), 0);
  assert.equal(limiter.count('agent'), 1);
  assert.equal(limiter.total(), 1);
});

test('limits: stats refleja los conteos por usuario', () => {
  const limiter = new ConnectionLimiter({ max: 10 });
  limiter.acquire('agent');
  limiter.acquire('agent');
  limiter.acquire('otro');
  assert.deepEqual(limiter.stats(), { agent: 2, otro: 1 });
  limiter.release('agent');
  assert.deepEqual(limiter.stats(), { agent: 1, otro: 1 });
  limiter.release('agent');
  limiter.release('otro');
  assert.deepEqual(limiter.stats(), {});
  assert.equal(limiter.total(), 0);
});
