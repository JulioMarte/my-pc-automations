import fs from 'node:fs';
import path from 'node:path';

const DEFAULT_ENV_FILE = path.join(import.meta.dirname, '..', '.env');

// Lee un .env y devuelve sus claves/valores SIN tocar process.env.
export function readEnv(file: string = DEFAULT_ENV_FILE): Record<string, string> {
  const result: Record<string, string> = {};
  try {
    const text = fs.readFileSync(file, 'utf8');
    for (const line of text.split(/\r?\n/)) {
      const match = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/.exec(line);
      if (!match) continue;
      const key = match[1] as string;
      let value = match[2] as string;
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      result[key] = value;
    }
  } catch {
    // .env ausente o ilegible.
  }
  return result;
}

export function loadEnv(file: string = DEFAULT_ENV_FILE): void {
  for (const [key, value] of Object.entries(readEnv(file))) {
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

export interface EnvWatcherLogger {
  info?(message: string, fields?: Record<string, unknown>): void;
  warn?(message: string, fields?: Record<string, unknown>): void;
}

// Vigila el .env (debounced) y entrega los valores crudos al cambiar.
export function watchEnv(
  file: string = DEFAULT_ENV_FILE,
  onChange: (values: Record<string, string>) => void,
  logger?: EnvWatcherLogger,
  debounceMs = 300,
): fs.FSWatcher | null {
  let timer: NodeJS.Timeout | null = null;
  const schedule = (): void => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      try {
        onChange(readEnv(file));
      } catch (error) {
        logger?.warn?.('no pude recargar .env', {
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }, debounceMs);
    timer.unref?.();
  };
  try {
    const directory = path.dirname(file);
    const base = path.basename(file);
    const watcher = fs.watch(directory, (eventType, filename) => {
      if (!filename || path.basename(String(filename)) === base) schedule();
    });
    watcher.on('error', () => {});
    watcher.unref?.();
    return watcher;
  } catch {
    return null;
  }
}

export function envString(name: string, fallback = ''): string {
  const value = process.env[name];
  return value === undefined || value === '' ? fallback : value;
}

export function envNumber(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

export function envBool(name: string, fallback: boolean): boolean {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  return /^(1|true|yes|on)$/i.test(raw.trim());
}

export function envList(name: string): string[] {
  return envString(name)
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
}
