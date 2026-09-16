import fs from 'node:fs';
import path from 'node:path';

const DEFAULT_ENV_FILE = path.join(import.meta.dirname, '..', '.env');

export function loadEnv(file: string = DEFAULT_ENV_FILE): void {
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
      if (process.env[key] === undefined) process.env[key] = value;
    }
  } catch {
    // .env ausente o ilegible: seguimos con el entorno del proceso.
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
