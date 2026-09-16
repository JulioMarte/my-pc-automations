const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { ExitPool } = require('../src/router');
const { watchExits } = require('../src/gateway');
const { waitFor } = require('./helpers');

test('watchExits: recarga exits.json al cambiar el archivo', async (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'local-proxy-reload-'));
  const file = path.join(directory, 'exits.json');
  fs.writeFileSync(file, JSON.stringify([{ name: 'a', host: '127.0.0.1', port: 1 }]));
  const pool = new ExitPool([{ name: 'a', host: '127.0.0.1', port: 1 }]);
  const watcher = watchExits(file, pool, { log() {}, error() {} });
  t.after(() => {
    watcher?.close();
    fs.rmSync(directory, { recursive: true, force: true });
  });
  fs.writeFileSync(
    file,
    JSON.stringify([
      { name: 'a', host: '127.0.0.1', port: 1 },
      { name: 'b', host: '127.0.0.1', port: 2 },
    ]),
  );
  await waitFor(() => pool.exits.length === 2);
  assert.deepEqual(
    pool.exits.map((exit) => exit.name),
    ['a', 'b'],
  );
});

test('watchExits: ignora un archivo invalido y mantiene los exits previos', async (t) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'local-proxy-reload-'));
  const file = path.join(directory, 'exits.json');
  fs.writeFileSync(file, JSON.stringify([{ name: 'a', host: '127.0.0.1', port: 1 }]));
  const pool = new ExitPool([{ name: 'a', host: '127.0.0.1', port: 1 }]);
  const watcher = watchExits(file, pool, { log() {}, error() {} });
  t.after(() => {
    watcher?.close();
    fs.rmSync(directory, { recursive: true, force: true });
  });
  fs.writeFileSync(file, '{ esto no es json');
  await new Promise((resolve) => setTimeout(resolve, 800));
  assert.equal(pool.exits.length, 1);
  assert.equal(pool.exits[0].name, 'a');
});
