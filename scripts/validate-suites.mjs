// Validador del manifiesto declarativo de suites (tests/suites.json).
//
// Uso:  node scripts/validate-suites.mjs
//
// Sin dependencias: solo modulos built-in de Node. La logica de validacion vive
// en la funcion pura `validateManifest`, reutilizable por los tests de
// gobernanza; el `process.exit` solo ocurre bajo el guard de "modulo principal".

import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(HERE, '..');
export const MANIFEST_PATH = path.join(REPO_ROOT, 'tests', 'suites.json');

const TIERS = new Set(['unit', 'integration', 'e2e', 'stress', 'architecture']);
const COSTS = new Set(['small', 'medium', 'large']);
const OWNERS = new Set(['local-proxy', 'vps-disaster-recovery']);

function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function isBoolean(value) {
  return typeof value === 'boolean';
}

function isPositiveInteger(value) {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

// Valida un manifiesto ya parseado y devuelve la lista de errores (vacia = OK).
// `root` permite inyectar la raiz del repo (por defecto, la del modulo).
export function validateManifest(data, root = REPO_ROOT) {
  const errors = [];

  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    return ['El manifiesto debe ser un objeto JSON.'];
  }

  if (data.version !== 1) {
    errors.push(`version debe ser 1 (recibido: ${JSON.stringify(data.version)}).`);
  }

  if (!Array.isArray(data.suites)) {
    errors.push('suites debe ser un arreglo.');
    return errors;
  }

  if (data.suites.length === 0) {
    errors.push('suites no puede estar vacio.');
  }

  const selectors = new Set();
  const namespaces = new Set();

  data.suites.forEach((suite, index) => {
    const where = `suites[${index}]`;

    if (suite === null || typeof suite !== 'object' || Array.isArray(suite)) {
      errors.push(`${where}: debe ser un objeto.`);
      return;
    }

    if (!isNonEmptyString(suite.selector)) {
      errors.push(`${where}.selector debe ser un string no vacio.`);
    } else if (selectors.has(suite.selector)) {
      errors.push(`${where}.selector duplicado: "${suite.selector}".`);
    } else {
      selectors.add(suite.selector);
    }

    if (!isNonEmptyString(suite.description)) {
      errors.push(`${where}.description debe ser un string no vacio.`);
    }

    if (!OWNERS.has(suite.owner)) {
      errors.push(`${where}.owner invalido: ${JSON.stringify(suite.owner)}.`);
    }

    if (!TIERS.has(suite.tier)) {
      errors.push(`${where}.tier invalido: ${JSON.stringify(suite.tier)}.`);
    }

    if (!isNonEmptyString(suite.cwd)) {
      errors.push(`${where}.cwd debe ser un string no vacio.`);
    } else if (!existsSync(path.resolve(root, suite.cwd))) {
      errors.push(`${where}.cwd no existe relativo a la raiz: "${suite.cwd}".`);
    }

    if (!isNonEmptyString(suite.command)) {
      errors.push(`${where}.command debe ser un string no vacio.`);
    }

    const policy = suite.policy;
    if (policy === null || typeof policy !== 'object' || Array.isArray(policy)) {
      errors.push(`${where}.policy debe ser un objeto.`);
    } else {
      for (const key of ['pr', 'merge', 'nightly', 'manual']) {
        if (!isBoolean(policy[key])) {
          errors.push(`${where}.policy.${key} debe ser booleano.`);
        }
      }
    }

    if (!COSTS.has(suite.cost)) {
      errors.push(`${where}.cost invalido: ${JSON.stringify(suite.cost)}.`);
    }

    if (!isBoolean(suite.requires_sudo)) {
      errors.push(`${where}.requires_sudo debe ser booleano.`);
    }

    if (!isBoolean(suite.requires_docker)) {
      errors.push(`${where}.requires_docker debe ser booleano.`);
    }

    if (!isPositiveInteger(suite.timeout_seconds)) {
      errors.push(`${where}.timeout_seconds debe ser un entero positivo.`);
    }

    if (!isNonEmptyString(suite.artifact_namespace)) {
      errors.push(`${where}.artifact_namespace debe ser un string no vacio.`);
    } else if (namespaces.has(suite.artifact_namespace)) {
      errors.push(`${where}.artifact_namespace duplicado: "${suite.artifact_namespace}".`);
    } else {
      namespaces.add(suite.artifact_namespace);
    }

    if (!isBoolean(suite.enabled)) {
      errors.push(`${where}.enabled debe ser booleano.`);
    }
  });

  return errors;
}

// Carga y valida el manifiesto del repo. Devuelve { data, errors }.
export function loadAndValidate(root = REPO_ROOT) {
  const manifestPath = path.join(root, 'tests', 'suites.json');
  if (!existsSync(manifestPath)) {
    return { data: null, errors: [`No existe el manifiesto: ${manifestPath}`] };
  }

  let data;
  try {
    data = JSON.parse(readFileSync(manifestPath, 'utf8'));
  } catch (error) {
    return { data: null, errors: [`JSON invalido en ${manifestPath}: ${error.message}`] };
  }

  return { data, errors: validateManifest(data, root) };
}

function isMain() {
  if (!process.argv[1]) return false;
  return import.meta.url === pathToFileURL(process.argv[1]).href;
}

if (isMain()) {
  const { data, errors } = loadAndValidate();

  if (errors.length > 0) {
    console.error(`SUITES INVALIDO (${errors.length} error(es)):`);
    for (const error of errors) {
      console.error(`  - ${error}`);
    }
    process.exit(1);
  }

  console.log(`SUITES OK (${data.suites.length} suites)`);
}
