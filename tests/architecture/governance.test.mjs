// Tests de gobernanza (solo lectura, sin comandos pesados).
//
// Verifican que el manifiesto declarativo de suites sea valido y que existan
// los limites de AGENTS.md, los adaptadores y la documentacion de referencia.
// Importan la funcion pura `validateManifest` para no depender de `process.exit`.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';

import { REPO_ROOT, MANIFEST_PATH, validateManifest } from '../../scripts/validate-suites.mjs';

const AGENTS_BOUNDARIES = [
  'local-proxy/AGENTS.md',
  'vps-disaster-recovery/AGENTS.md',
  'tests/AGENTS.md',
  'scripts/AGENTS.md',
  '.github/AGENTS.md',
];

const ADAPTER_FILES = [
  'CLAUDE.md',
  'GEMINI.md',
  'local-proxy/CLAUDE.md',
  'local-proxy/GEMINI.md',
  'vps-disaster-recovery/CLAUDE.md',
  'vps-disaster-recovery/GEMINI.md',
  'tests/CLAUDE.md',
  'tests/GEMINI.md',
  '.github/copilot-instructions.md',
];

test('el manifiesto de suites valida sin errores', () => {
  assert.ok(existsSync(MANIFEST_PATH), `falta el manifiesto: ${MANIFEST_PATH}`);
  const data = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const errors = validateManifest(data, REPO_ROOT);
  assert.deepEqual(errors, [], `errores de validacion:\n${errors.join('\n')}`);
});

test('existen todos los limites anidados de AGENTS.md', () => {
  for (const relative of AGENTS_BOUNDARIES) {
    const absolute = path.join(REPO_ROOT, relative);
    assert.ok(existsSync(absolute), `falta ${relative}`);
  }
});

test('los adaptadores existen y referencian AGENTS.md', () => {
  for (const relative of ADAPTER_FILES) {
    const absolute = path.join(REPO_ROOT, relative);
    assert.ok(existsSync(absolute), `falta el adaptador ${relative}`);
    const content = readFileSync(absolute, 'utf8');
    assert.ok(
      content.includes('AGENTS.md'),
      `el adaptador ${relative} no contiene la referencia literal "AGENTS.md"`,
    );
  }
});

test('existe la documentacion de referencia docs/README.md', () => {
  const readme = path.join(REPO_ROOT, 'docs', 'README.md');
  assert.ok(existsSync(readme), 'falta docs/README.md');
});

const GUARANTEES_PATH = path.join(REPO_ROOT, 'tests', 'guarantees.json');
const SEVERITIES = new Set(['critical', 'high', 'medium']);

function loadJson(absolute, label) {
  assert.ok(existsSync(absolute), `falta ${label}`);
  return JSON.parse(readFileSync(absolute, 'utf8'));
}

test('el inventario de garantias es valido', () => {
  const data = loadJson(GUARANTEES_PATH, 'tests/guarantees.json');
  assert.equal(data.version, 1, 'version debe ser 1');
  assert.ok(Array.isArray(data.guarantees), 'guarantees debe ser un arreglo');
  assert.ok(data.guarantees.length > 0, 'guarantees no puede estar vacio');

  const ids = new Set();
  for (const guarantee of data.guarantees) {
    assert.ok(
      guarantee !== null && typeof guarantee === 'object' && !Array.isArray(guarantee),
      'cada garantia debe ser un objeto',
    );
    assert.equal(
      typeof guarantee.id,
      'string',
      `la garantia ${JSON.stringify(guarantee.id)} debe tener un id string`,
    );
    assert.match(guarantee.id, /^G-[A-Z0-9-]+$/, `id invalido: ${JSON.stringify(guarantee.id)}`);
    assert.ok(!ids.has(guarantee.id), `id duplicado: "${guarantee.id}"`);
    ids.add(guarantee.id);

    assert.ok(
      typeof guarantee.statement === 'string' && guarantee.statement.trim().length > 0,
      `la garantia ${guarantee.id} debe tener un statement no vacio`,
    );
    assert.ok(
      SEVERITIES.has(guarantee.severity),
      `la garantia ${guarantee.id} tiene severity invalida: ${JSON.stringify(guarantee.severity)}`,
    );
    assert.ok(
      Array.isArray(guarantee.proven_by) && guarantee.proven_by.length > 0,
      `la garantia ${guarantee.id} debe tener proven_by no vacio`,
    );
    for (const selector of guarantee.proven_by) {
      assert.ok(
        typeof selector === 'string' && selector.trim().length > 0,
        `la garantia ${guarantee.id} tiene un selector no string en proven_by`,
      );
    }
  }
});

test('todo proven_by referencia selectores existentes en el manifiesto', () => {
  const manifest = loadJson(MANIFEST_PATH, 'tests/suites.json');
  const selectors = new Set(manifest.suites.map((suite) => suite.selector));
  const data = loadJson(GUARANTEES_PATH, 'tests/guarantees.json');

  for (const guarantee of data.guarantees) {
    for (const selector of guarantee.proven_by) {
      assert.ok(
        selectors.has(selector),
        `la garantia ${guarantee.id} referencia el selector inexistente "${selector}"`,
      );
    }
  }
});

test('los selectores del manifiesto son unicos', () => {
  const manifest = loadJson(MANIFEST_PATH, 'tests/suites.json');
  const seen = new Set();
  for (const suite of manifest.suites) {
    assert.ok(!seen.has(suite.selector), `selector duplicado en el manifiesto: "${suite.selector}"`);
    seen.add(suite.selector);
  }
});
