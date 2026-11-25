// Runner generico del manifiesto declarativo de suites (tests/suites.json).
//
// Uso:
//   node scripts/run-suite.mjs list
//   node scripts/run-suite.mjs resolve <selector>
//   node scripts/run-suite.mjs select <policy>          # pr|merge|nightly|manual
//   node scripts/run-suite.mjs run <selector|all|policy:pr> [--allow-sudo] [--dry-run] [--force]
//
// Sin dependencias: solo modulos built-in de Node. Multiplataforma (Windows/Linux).

import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { REPO_ROOT, loadAndValidate } from './validate-suites.mjs';

const POLICY_NAMES = ['pr', 'merge', 'nightly', 'manual'];

function fail(message) {
  console.error(message);
  process.exit(1);
}

function printUsage() {
  console.log(
    [
      'Uso: node scripts/run-suite.mjs <comando> [args]',
      '',
      'Comandos:',
      '  list                          Lista los selectores registrados.',
      '  resolve <selector>            Muestra la suite como JSON.',
      '  select <policy>               Selectores con esa politica activa (pr|merge|nightly|manual).',
      '  run <target> [opciones]       Ejecuta suites. target: <selector>|all|policy:<policy>.',
      '',
      'Opciones de run:',
      '  --allow-sudo                  Permite suites con requires_sudo (solo tiene efecto en Linux).',
      '  --dry-run                     No ejecuta; solo planifica.',
      '  --force                       Ignora la deteccion de herramientas faltantes (docker/sudo).',
    ].join('\n'),
  );
}

// Carga y valida el manifiesto; aborta si es invalido.
function loadManifest() {
  const { data, errors } = loadAndValidate(REPO_ROOT);
  if (errors.length > 0) {
    console.error('Manifiesto de suites invalido:');
    for (const error of errors) console.error(`  - ${error}`);
    process.exit(1);
  }
  return data;
}

function dockerAvailable() {
  try {
    const probe = spawnSync('docker', ['--version'], { encoding: 'utf8', shell: false });
    return probe.status === 0;
  } catch {
    return false;
  }
}

// Resuelve el conjunto de suites segun el target del comando run.
function selectSuites(manifest, target) {
  if (target === 'all') return manifest.suites;

  if (target.startsWith('policy:')) {
    const policy = target.slice('policy:'.length);
    if (!POLICY_NAMES.includes(policy)) {
      fail(`Politica desconocida: "${policy}". Validas: ${POLICY_NAMES.join(', ')}.`);
    }
    return manifest.suites.filter((suite) => suite.policy && suite.policy[policy] === true);
  }

  const suite = manifest.suites.find((item) => item.selector === target);
  if (!suite) fail(`Selector desconocido: "${target}". Usa "list" para ver los disponibles.`);
  return [suite];
}

function writeEvidence(namespace, logText, summary) {
  const dir = path.join(REPO_ROOT, 'results', namespace);
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, 'log.txt'), logText, 'utf8');
  writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n', 'utf8');
  return dir;
}

function runSuite(suite, options) {
  const cwd = path.resolve(REPO_ROOT, suite.cwd);
  const started = Date.now();
  const header = [
    `# suite: ${suite.selector}`,
    `# owner: ${suite.owner}`,
    `# tier: ${suite.tier}`,
    `# cwd: ${cwd}`,
    `# command: ${suite.command}`,
    `# timeout_seconds: ${suite.timeout_seconds}`,
    '',
  ].join('\n');

  if (options.dryRun) {
    const logText = header + '[dry-run] no se ejecuto el comando.\n';
    const summary = {
      selector: suite.selector,
      status: 'DRYRUN',
      exit_code: null,
      duration_ms: 0,
      command: suite.command,
      cwd,
      skipped_reason: null,
    };
    const dir = writeEvidence(suite.artifact_namespace, logText, summary);
    return { status: 'DRYRUN', selector: suite.selector, exitCode: null, durationMs: 0, dir };
  }

  const result = spawnSync(suite.command, {
    cwd,
    shell: true,
    timeout: suite.timeout_seconds * 1000,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });

  const durationMs = Date.now() - started;
  const stdout = result.stdout || '';
  const stderr = result.stderr || '';
  const timedOut = result.error && (result.error.code === 'ETIMEDOUT' || result.signal === 'SIGTERM');
  const exitCode = typeof result.status === 'number' ? result.status : 1;
  const passed = !timedOut && exitCode === 0 && !result.error;

  const logText =
    header +
    stdout +
    (stderr ? `\n[stderr]\n${stderr}` : '') +
    (result.error ? `\n[error] ${result.error.message}\n` : '') +
    (timedOut ? `\n[timeout] superado tras ${suite.timeout_seconds}s\n` : '');

  const summary = {
    selector: suite.selector,
    status: passed ? 'PASS' : 'FAIL',
    exit_code: exitCode,
    duration_ms: durationMs,
    command: suite.command,
    cwd,
    timed_out: Boolean(timedOut),
    skipped_reason: null,
  };
  const dir = writeEvidence(suite.artifact_namespace, logText, summary);
  return { status: passed ? 'PASS' : 'FAIL', selector: suite.selector, exitCode, durationMs, dir };
}

function skipSuite(suite, reason) {
  const header = [
    `# suite: ${suite.selector}`,
    `# command: ${suite.command}`,
    `# SKIP: ${reason}`,
    '',
  ].join('\n');
  const summary = {
    selector: suite.selector,
    status: 'SKIP',
    exit_code: null,
    duration_ms: 0,
    command: suite.command,
    cwd: path.resolve(REPO_ROOT, suite.cwd),
    skipped_reason: reason,
  };
  const dir = writeEvidence(suite.artifact_namespace, header, summary);
  return { status: 'SKIP', selector: suite.selector, reason, dir };
}

function parseFlags(args) {
  return {
    allowSudo: args.includes('--allow-sudo'),
    dryRun: args.includes('--dry-run'),
    force: args.includes('--force'),
  };
}

function main() {
  const [command, ...rest] = process.argv.slice(2);

  if (!command || command === 'help' || command === '--help' || command === '-h') {
    printUsage();
    process.exit(command ? 0 : 1);
  }

  const manifest = loadManifest();

  if (command === 'list') {
    for (const suite of manifest.suites) {
      const state = suite.enabled ? 'enabled ' : 'disabled';
      console.log(`${suite.selector}\t${state}\t${suite.tier}\t${suite.owner}`);
    }
    return;
  }

  if (command === 'resolve') {
    const selector = rest[0];
    if (!selector) fail('Falta el selector. Uso: resolve <selector>.');
    const suite = manifest.suites.find((item) => item.selector === selector);
    if (!suite) fail(`Selector desconocido: "${selector}".`);
    console.log(JSON.stringify(suite, null, 2));
    return;
  }

  if (command === 'select') {
    const policy = rest[0];
    if (!POLICY_NAMES.includes(policy)) {
      fail(`Politica invalida: ${JSON.stringify(policy)}. Validas: ${POLICY_NAMES.join(', ')}.`);
    }
    const selectors = manifest.suites
      .filter((suite) => suite.policy && suite.policy[policy] === true)
      .map((suite) => suite.selector);
    console.log(JSON.stringify(selectors, null, 2));
    return;
  }

  if (command === 'run') {
    const target = rest.find((arg) => !arg.startsWith('--')) || 'all';
    const options = parseFlags(rest);
    const suites = selectSuites(manifest, target);
    const dockerOk = dockerAvailable();
    const isLinux = process.platform === 'linux';

    console.log(`Ejecutando target "${target}" (${suites.length} suite(s))...`);
    if (options.dryRun) console.log('Modo dry-run: no se ejecutaran comandos.');

    const results = [];
    for (const suite of suites) {
      if (!suite.enabled) {
        results.push(skipSuite(suite, 'deshabilitada (enabled=false)'));
        continue;
      }
      if (suite.requires_sudo && !options.allowSudo) {
        results.push(skipSuite(suite, 'requires_sudo=true y falta --allow-sudo'));
        continue;
      }
      if (suite.requires_sudo && !isLinux && !options.force) {
        results.push(skipSuite(suite, 'requires_sudo y la plataforma no es Linux'));
        continue;
      }
      if (suite.requires_docker && !dockerOk && !options.force) {
        results.push(skipSuite(suite, 'requires_docker y Docker no esta disponible'));
        continue;
      }
      results.push(runSuite(suite, options));
    }

    const totals = { pass: 0, fail: 0, skip: 0, dryrun: 0 };
    console.log('\nResumen:');
    for (const result of results) {
      if (result.status === 'PASS') totals.pass += 1;
      else if (result.status === 'FAIL') totals.fail += 1;
      else if (result.status === 'DRYRUN') totals.dryrun += 1;
      else totals.skip += 1;

      const extra =
        result.status === 'SKIP'
          ? ` (${result.reason})`
          : result.status === 'DRYRUN'
            ? ''
            : ` (exit=${result.exitCode}, ${result.durationMs}ms)`;
      console.log(`  [${result.status}] ${result.selector}${extra}`);
    }
    console.log(
      `  total: PASS=${totals.pass} FAIL=${totals.fail} SKIP=${totals.skip} DRYRUN=${totals.dryrun}`,
    );

    const runSummary = {
      generated_at: new Date().toISOString(),
      target,
      allow_sudo: options.allowSudo,
      dry_run: options.dryRun,
      totals,
      suites: results.map((result) => ({
        selector: result.selector,
        status: result.status,
        skipped_reason: result.reason || null,
      })),
    };
    mkdirSync(path.join(REPO_ROOT, 'results'), { recursive: true });
    writeFileSync(
      path.join(REPO_ROOT, 'results', 'run-summary.json'),
      JSON.stringify(runSummary, null, 2) + '\n',
      'utf8',
    );

    process.exit(totals.fail > 0 ? 1 : 0);
  }

  fail(`Comando desconocido: "${command}". Usa "help" para ver el uso.`);
}

main();
