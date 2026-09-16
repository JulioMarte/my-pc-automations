import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { readEnv, watchEnv } from '../src/env.ts';
import { waitFor } from './helpers.ts';

test('readEnv: parsea claves, ignora comentarios/vacias y quita comillas', (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'local-proxy-env-'));
  const file = path.join(directory, '.env');
  fs.writeFileSync(
    file,
    [
      '# comentario',
      '',
      'PLAIN=value',
      "SINGLE='uno'",
      'DOUBLE="dos"',
      'WITH_SPACES = spaced',
      '  INDENTED=ok',
    ].join('\n'),
  );
  t.after(() => {
    fs.rmSync(directory, { recursive: true, force: true });
  });
  const values = readEnv(file);
  assert.equal(values.PLAIN, 'value');
  assert.equal(values.SINGLE, 'uno');
  assert.equal(values.DOUBLE, 'dos');
  assert.equal(values.WITH_SPACES, 'spaced');
  assert.equal(values.INDENTED, 'ok');
  assert.equal(values['# comentario'], undefined);
  // readEnv NO debe mutar process.env.
  assert.equal(process.env.PLAIN, undefined);
});

test('readEnv: archivo inexistente devuelve objeto vacio', () => {
  const file = path.join(
    os.tmpdir(),
    `local-proxy-env-missing-${process.pid}-${Date.now()}`,
    '.env',
  );
  assert.deepEqual(readEnv(file), {});
});

test('watchEnv: notifica los valores nuevos al cambiar el archivo', async (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'local-proxy-env-watch-'));
  const file = path.join(directory, '.env');
  fs.writeFileSync(file, 'PROXY_USERS=agent:secret\n');
  const received: Array<Record<string, string>> = [];
  const watcher = watchEnv(
    file,
    (values) => {
      received.push(values);
    },
    undefined,
    20,
  );
  t.after(() => {
    watcher?.close();
    fs.rmSync(directory, { recursive: true, force: true });
  });
  fs.writeFileSync(file, 'PROXY_USERS=otro:clave\n');
  await waitFor(() => received.length > 0);
  assert.equal(received[0]?.PROXY_USERS, 'otro:clave');
});
