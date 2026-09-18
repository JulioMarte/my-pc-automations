// Tests de contrato de arquitectura (solo lectura, sin comandos pesados).
//
// Protegen invariantes estructurales HARD del repositorio: ausencia de
// dependencias de runtime en local-proxy, fin de linea LF en los scripts de
// shell, la regla de .gitattributes y la existencia de los workflows de CI.
// Solo usan modulos built-in de Node.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import path from 'node:path';

import { REPO_ROOT } from '../../scripts/validate-suites.mjs';

// Recolecta recursivamente los *.sh bajo `dir`, saltando node_modules.
function collectShellScripts(dir) {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules') continue;
    const absolute = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...collectShellScripts(absolute));
    } else if (entry.isFile() && entry.name.endsWith('.sh')) {
      found.push(absolute);
    }
  }
  return found;
}

test('local-proxy no declara dependencias de runtime', () => {
  const packagePath = path.join(REPO_ROOT, 'local-proxy', 'package.json');
  assert.ok(existsSync(packagePath), 'falta local-proxy/package.json');

  const pkg = JSON.parse(readFileSync(packagePath, 'utf8'));
  const dependencies = pkg.dependencies;
  const hasNoRuntimeDeps =
    dependencies === undefined ||
    (dependencies !== null &&
      typeof dependencies === 'object' &&
      !Array.isArray(dependencies) &&
      Object.keys(dependencies).length === 0);

  assert.ok(
    hasNoRuntimeDeps,
    'local-proxy/package.json declara paquetes en "dependencies": el invariante HARD ' +
      '"sin dependencias de runtime en local-proxy" prohibe dependencias de produccion ' +
      '(solo se permiten devDependencies).',
  );
});

test('todos los *.sh de vps-disaster-recovery usan LF', () => {
  const root = path.join(REPO_ROOT, 'vps-disaster-recovery');
  assert.ok(existsSync(root), 'falta el directorio vps-disaster-recovery');

  const scripts = collectShellScripts(root);
  assert.ok(scripts.length > 0, 'no se encontraron scripts *.sh bajo vps-disaster-recovery');

  for (const absolute of scripts) {
    const relative = path.relative(REPO_ROOT, absolute);
    const content = readFileSync(absolute, 'utf8');
    assert.ok(
      !content.includes('\r'),
      `${relative} contiene un caracter de retorno de carro (CR): shebang CRLF rompe en Linux.`,
    );
  }
});

test('.gitattributes fija los *.sh a LF', () => {
  const gitattributesPath = path.join(REPO_ROOT, '.gitattributes');
  assert.ok(existsSync(gitattributesPath), 'falta .gitattributes');

  const content = readFileSync(gitattributesPath, 'utf8');
  assert.ok(
    content.includes('*.sh text eol=lf'),
    '.gitattributes no contiene la regla "*.sh text eol=lf".',
  );
});

test('existen los tres workflows de CI', () => {
  const workflows = ['ci.yml', 'vps-dr-ci.yml', 'governance.yml'];
  for (const name of workflows) {
    const absolute = path.join(REPO_ROOT, '.github', 'workflows', name);
    assert.ok(existsSync(absolute), `falta .github/workflows/${name}`);
  }
});
