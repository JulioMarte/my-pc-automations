import { randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

interface ExitEntry {
  name: string;
  location?: string;
  host?: string;
  port?: number;
  user?: string;
  pass?: string;
  [key: string]: unknown;
}

interface CliArgs {
  name: string | undefined;
  user: string | undefined;
  apply: boolean;
}

const exitsPath = path.join(import.meta.dirname, '..', 'exits.json');

function usage(): void {
  console.error('Uso: node scripts/rotate-cred.ts <exitName> [--user <nuevoUsuario>] [--apply]');
}

function parseArgs(argv: string[]): CliArgs {
  let name: string | undefined;
  let user: string | undefined;
  let apply = false;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === undefined) continue;
    if (arg === '--apply') {
      apply = true;
    } else if (arg === '--user') {
      user = argv[i + 1];
      i += 1;
    } else if (arg.startsWith('--user=')) {
      user = arg.slice('--user='.length);
    } else if (arg.startsWith('-')) {
      console.error(`Opcion desconocida: ${arg}`);
      usage();
      process.exit(1);
    } else if (name === undefined) {
      name = arg;
    } else {
      console.error(`Argumento inesperado: ${arg}`);
      usage();
      process.exit(1);
    }
  }
  return { name, user, apply };
}

function readRaw(): string {
  try {
    return readFileSync(exitsPath, 'utf8');
  } catch {
    console.error(`No se pudo leer ${exitsPath}`);
    process.exit(1);
  }
}

function parseExits(raw: string): ExitEntry[] {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    console.error(`${exitsPath} no es JSON valido`);
    process.exit(1);
  }
  if (!Array.isArray(data)) {
    console.error(`${exitsPath} debe contener un array de exits`);
    process.exit(1);
  }
  return data as ExitEntry[];
}

// Conserva el estilo de indentacion actual (2 o 4 espacios, o tabs).
function detectIndent(raw: string): string {
  const match = raw.match(/\n([ \t]+)\S/);
  const whitespace = match?.[1];
  if (!whitespace) return '    ';
  if (whitespace.includes('\t')) return '\t';
  return whitespace;
}

function main(): void {
  const { name, user, apply } = parseArgs(process.argv.slice(2));
  if (!name) {
    usage();
    process.exit(1);
  }

  const raw = readRaw();
  const data = parseExits(raw);
  const exit = data.find((entry) => entry.name === name);
  if (!exit) {
    console.error(`No existe un exit llamado "${name}" en ${exitsPath}`);
    const names = data.map((entry) => entry.name).join(', ');
    if (names) console.error(`Exits disponibles: ${names}`);
    process.exit(1);
  }

  const newPass = randomBytes(24).toString('base64url');
  const currentUser = typeof exit.user === 'string' ? exit.user : '';
  const currentPass = typeof exit.pass === 'string' ? exit.pass : '';
  const newUser = user && user.length > 0 ? user : currentUser || `exit-${exit.name}`;

  const currentCredential = currentUser ? `${currentUser}:${currentPass}` : '';
  const newCredential = `${newUser}:${newPass}`;
  const overlapValue =
    currentCredential && currentCredential !== newCredential
      ? `${currentCredential},${newCredential}`
      : newCredential;

  const gatewayHost = process.env.GATEWAY_HOST ?? '100.110.109.28';
  const gatewayPort = process.env.GATEWAY_HTTP_PORT ?? '8888';
  const exitHost = typeof exit.host === 'string' ? exit.host : '<IP-exit>';
  const exitPort = typeof exit.port === 'number' ? String(exit.port) : '8899';
  const location = typeof exit.location === 'string' ? ` (${exit.location})` : '';

  console.log('============================================================');
  console.log(` Rotacion de credenciales - exit "${exit.name}"`);
  console.log('============================================================');
  console.log('');
  console.log('ADVERTENCIA: los valores siguientes son SECRETOS. No los pegues en');
  console.log('logs, tickets, chats ni capturas. Borra esta salida al terminar.');
  console.log('');
  console.log(`Exit:                          ${exit.name}${location}`);
  console.log(`Endpoint:                      ${exitHost}:${exitPort}`);
  console.log(`Credencial nueva:              ${newCredential}`);
  console.log(`EXIT_USERS (con superposicion): ${overlapValue}`);
  console.log('');
  console.log('Runbook (overlap, cero downtime):');
  console.log('');
  console.log('  Paso 1 - Agrega la credencial nueva al exit SIN quitar la actual.');
  console.log('    En la maquina del exit edita .env y pon:');
  console.log(`      EXIT_USERS=${overlapValue}`);
  console.log('    y reinicia el exit:');
  console.log('      Linux/VPS:');
  console.log("        pkill -f 'dist/exit.js' || true");
  console.log('        ~/local-proxy/scripts/exit-daemon.sh');
  console.log('      Windows:');
  console.log('        Get-CimInstance Win32_Process -Filter "Name=\'node.exe\'" |');
  console.log("          Where-Object { $_.CommandLine -match 'exit.js' } |");
  console.log('          ForEach-Object { Stop-Process -Id $_.ProcessId -Force }');
  console.log('        Start-ScheduledTask local-proxy-autostart');
  console.log('');
  console.log('  Paso 2 - Verifica que el exit acepta la credencial nueva (desde la');
  console.log('    maquina del gateway, unica autorizada por EXIT_ALLOW):');
  console.log(`      curl -x http://${newCredential}@${exitHost}:${exitPort} https://api.ipify.org`);
  console.log('');
  console.log('  Paso 3 - Actualiza exits.json (user/pass de este exit).');
  if (apply) {
    exit.user = newUser;
    exit.pass = newPass;
    const indent = detectIndent(raw);
    const trailing = raw.endsWith('\n') ? '\n' : '';
    writeFileSync(exitsPath, JSON.stringify(data, null, indent) + trailing, 'utf8');
    console.log(`    HECHO: ${exitsPath} actualizado; el gateway lo recargara en caliente`);
    console.log('    (hot reload) sin reiniciar.');
  } else {
    console.log(`      Ejecuta:  node scripts/rotate-cred.ts ${exit.name} --apply`);
    console.log('    Asi el gateway empieza a usar la credencial nueva.');
  }
  console.log('');
  console.log('  Paso 4 - Verifica a traves del gateway forzando este exit:');
  console.log(
    `      curl -x http://USUARIO-exit-${exit.name}:CLAVE@${gatewayHost}:${gatewayPort} https://api.ipify.org`,
  );
  console.log('    (USUARIO:CLAVE son las credenciales de PROXY_USERS del gateway).');
  console.log('');
  console.log('  Paso 5 - Quita la credencial vieja: deja solo la nueva en EXIT_USERS:');
  console.log(`      EXIT_USERS=${newCredential}`);
  console.log('    y reinicia el exit (mismos comandos del paso 1).');
  console.log('');

  if (!apply) {
    console.log('NOTA: modo dry-run; no se modifico ningun archivo. Cuando el paso 1');
    console.log(`y su verificacion funcionen, re-ejecuta con --apply para actualizar`);
    console.log('exits.json (paso 3).');
  }

  process.exit(0);
}

main();
