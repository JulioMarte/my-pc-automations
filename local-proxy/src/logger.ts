// Logger estructurado (JSON por defecto) con redaccion de campos sensibles.
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';
export type LogFormat = 'json' | 'text';

export interface Logger {
  debug?(message: string, fields?: Record<string, unknown>): void;
  info?(message: string, fields?: Record<string, unknown>): void;
  log?(message: string, fields?: Record<string, unknown>): void;
  warn?(message: string, fields?: Record<string, unknown>): void;
  error?(message: string, fields?: Record<string, unknown>): void;
}

export interface LoggerOptions {
  level?: LogLevel;
  format?: LogFormat;
  role?: string;
  name?: string;
  fields?: Record<string, unknown>;
  out?: (line: string) => void;
  err?: (line: string) => void;
  now?: () => Date;
}

const LEVELS: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };
const SENSITIVE = /(proxy-?authorization|authorization|cookie|password|passwd|pass|token|secret|api-?key)/i;
const REDACTED = '[redacted]';

export function parseLogLevel(value: unknown): LogLevel {
  const text = String(value ?? '').toLowerCase();
  if (text === 'debug' || text === 'info' || text === 'warn' || text === 'error') return text;
  return 'info';
}

export function parseLogFormat(value: unknown): LogFormat {
  return String(value ?? '').toLowerCase() === 'text' ? 'text' : 'json';
}

function redact(fields: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(fields)) {
    if (SENSITIVE.test(key)) {
      result[key] = REDACTED;
    } else if (value instanceof Error) {
      result[key] = { name: value.name, message: value.message };
    } else if (value && typeof value === 'object' && !Array.isArray(value)) {
      result[key] = redact(value as Record<string, unknown>);
    } else {
      result[key] = value;
    }
  }
  return result;
}

function formatTextValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function createLogger(options: LoggerOptions = {}): Logger {
  const threshold = LEVELS[options.level ?? 'info'];
  const format = options.format ?? 'json';
  const base: Record<string, unknown> = { ...(options.fields ?? {}) };
  if (options.role) base.role = options.role;
  if (options.name) base.name = options.name;
  const now = options.now ?? (() => new Date());
  const out = options.out ?? ((line: string) => { process.stdout.write(`${line}\n`); });
  const err = options.err ?? ((line: string) => { process.stderr.write(`${line}\n`); });

  const emit = (level: LogLevel, message: string, fields?: Record<string, unknown>): void => {
    if (LEVELS[level] < threshold) return;
    const data = { ...base, ...redact(fields ?? {}) };
    const ts = now().toISOString();
    let line: string;
    if (format === 'text') {
      const extras = Object.entries(data)
        .map(([key, value]) => `${key}=${formatTextValue(value)}`)
        .join(' ');
      line = `${ts} ${level.toUpperCase()} ${message}${extras ? ` ${extras}` : ''}`;
    } else {
      line = JSON.stringify({ ts, level, msg: message, ...data });
    }
    if (level === 'warn' || level === 'error') err(line);
    else out(line);
  };

  return {
    debug: (message, fields) => emit('debug', message, fields),
    info: (message, fields) => emit('info', message, fields),
    log: (message, fields) => emit('info', message, fields),
    warn: (message, fields) => emit('warn', message, fields),
    error: (message, fields) => emit('error', message, fields),
  };
}
