import crypto from 'node:crypto';

const OPTION_KEYS = new Set(['session', 'exit', 'loc', 'rotate']);

export interface ParsedUser {
  base: string;
  session?: string;
  exit?: string;
  location?: string;
  rotate?: boolean;
}

export interface ExitConfig {
  name: string;
  location?: string;
  host: string;
  port?: number;
  user?: string;
  pass?: string;
}

export type CircuitState = 'closed' | 'open' | 'halfOpen';

export interface Exit {
  name: string;
  location: string;
  host: string;
  port: number;
  user: string;
  pass: string;
  healthy: boolean;
  failures: number;
  successes: number;
  connections: number;
  bytesUp: number;
  bytesDown: number;
  circuit: CircuitState;
  openedAt: number;
  backoffMs: number;
}

export interface ExitPoolOptions {
  sessionTtlMs?: number;
  maxSessions?: number;
  unhealthyThreshold?: number;
  healthyThreshold?: number;
  circuitThreshold?: number;
  circuitBaseMs?: number;
  circuitMaxMs?: number;
  now?: () => number;
}

export interface Session {
  exitName: string;
  expiresAt: number;
}

export function safeEqual(left: unknown, right: unknown): boolean {
  const a = Buffer.from(String(left));
  const b = Buffer.from(String(right));
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

export function parseUser(raw: unknown): ParsedUser {
  const parts = String(raw ?? '').split('-');
  const base = parts.shift() ?? '';
  const parsed: ParsedUser = { base };
  let index = 0;
  while (index < parts.length) {
    const key = parts[index] as string;
    if (!OPTION_KEYS.has(key)) {
      index += 1;
      continue;
    }
    if (key === 'rotate') {
      parsed.rotate = true;
      index += 1;
      continue;
    }
    const value = parts.slice(index + 1).join('-');
    if (value) {
      if (key === 'loc') parsed.location = value;
      else if (key === 'session') parsed.session = value;
      else if (key === 'exit') parsed.exit = value;
    }
    break;
  }
  return parsed;
}

export function parseUsers(text: unknown): Map<string, string> {
  return new Map(
    String(text ?? '')
      .split(',')
      .map((entry): [string, string] | null => {
        const index = entry.indexOf(':');
        if (index === -1) return null;
        return [entry.slice(0, index), entry.slice(index + 1)];
      })
      .filter((pair): pair is [string, string] => Boolean(pair && pair[0] && pair[1])),
  );
}

export interface Credential {
  user: string;
  pass: string;
}

// Lista de credenciales (a diferencia de parseUsers, admite usuario repetido con
// distinta clave, necesario para rotar sin downtime).
export function parseCredentials(text: unknown): Credential[] {
  return String(text ?? '')
    .split(',')
    .map((entry): Credential | null => {
      const index = entry.indexOf(':');
      if (index === -1) return null;
      const user = entry.slice(0, index).trim();
      if (!user) return null;
      return { user, pass: entry.slice(index + 1) };
    })
    .filter((credential): credential is Credential => credential !== null);
}

export function decodeBasic(header: unknown): { username: string; password: string } | null {
  if (!header || !String(header).startsWith('Basic ')) return null;
  const decoded = Buffer.from(String(header).slice(6), 'base64').toString();
  const index = decoded.indexOf(':');
  if (index === -1) return null;
  return { username: decoded.slice(0, index), password: decoded.slice(index + 1) };
}

export function createAuthenticator(users: Map<string, string>) {
  return (username: string, password: string): ParsedUser | null => {
    const parsed = parseUser(username);
    if (!parsed.base) return null;
    const expected = users.get(parsed.base);
    if (expected === undefined) return null;
    if (!safeEqual(expected, password)) return null;
    return parsed;
  };
}

export class ExitPool {
  readonly sessionTtlMs: number;
  readonly maxSessions: number;
  readonly unhealthyThreshold: number;
  readonly healthyThreshold: number;
  readonly circuitThreshold: number;
  readonly circuitBaseMs: number;
  readonly circuitMaxMs: number;
  readonly now: () => number;
  sessions: Map<string, Session>;
  roundRobin: number;
  exits: Exit[];

  constructor(exits: ExitConfig[] = [], options: ExitPoolOptions = {}) {
    this.sessionTtlMs = options.sessionTtlMs ?? 600000;
    this.maxSessions = options.maxSessions ?? 10000;
    this.unhealthyThreshold = options.unhealthyThreshold ?? 2;
    this.healthyThreshold = options.healthyThreshold ?? 2;
    this.circuitThreshold = options.circuitThreshold ?? 3;
    this.circuitBaseMs = options.circuitBaseMs ?? 5000;
    this.circuitMaxMs = options.circuitMaxMs ?? 60000;
    this.now = options.now ?? (() => Date.now());
    this.sessions = new Map();
    this.roundRobin = 0;
    this.exits = [];
    this.reload(exits);
  }

  private toExit(config: ExitConfig): Exit {
    return {
      name: config.name,
      location: config.location ?? '',
      host: config.host,
      port: Number(config.port ?? 8899),
      user: config.user ?? '',
      pass: config.pass ?? '',
      healthy: true,
      failures: 0,
      successes: 0,
      connections: 0,
      bytesUp: 0,
      bytesDown: 0,
      circuit: 'closed',
      openedAt: 0,
      backoffMs: 0,
    };
  }

  reload(next: ExitConfig[]): void {
    const previous = new Map(this.exits.map((exit) => [exit.name, exit]));
    this.exits = next.map((config) => {
      const fresh = this.toExit(config);
      const old = previous.get(fresh.name);
      if (!old) return fresh;
      return {
        ...fresh,
        healthy: old.healthy,
        failures: old.failures,
        successes: old.successes,
        connections: old.connections,
        bytesUp: old.bytesUp,
        bytesDown: old.bytesDown,
        circuit: old.circuit,
        openedAt: old.openedAt,
        backoffMs: old.backoffMs,
      };
    });
    const names = new Set(this.exits.map((exit) => exit.name));
    for (const [key, value] of this.sessions) {
      if (!names.has(value.exitName)) this.sessions.delete(key);
    }
  }

  private circuitAllows(exit: Exit): boolean {
    if (exit.circuit === 'closed') return true;
    if (exit.circuit === 'halfOpen') return true;
    if (this.now() - exit.openedAt >= exit.backoffMs) {
      exit.circuit = 'halfOpen';
      return true;
    }
    return false;
  }

  private usable(exit: Exit, location: string | null): boolean {
    if (!exit.healthy) return false;
    if (location && String(exit.location).toLowerCase() !== location) return false;
    return this.circuitAllows(exit);
  }

  healthyExits(location?: string): Exit[] {
    const wanted = location ? String(location).toLowerCase() : null;
    return this.exits.filter((exit) => this.usable(exit, wanted));
  }

  sessionKey(parsed: ParsedUser): string | null {
    return parsed.session ? `${parsed.base}:${parsed.session}` : null;
  }

  candidates(parsed: ParsedUser): Exit[] {
    if (parsed.exit) {
      const exact = this.exits.find((exit) => exit.name === parsed.exit);
      return exact ? [exact] : [];
    }
    const ordered: Exit[] = [];
    const key = this.sessionKey(parsed);
    const session = key && !parsed.rotate ? this.sessions.get(key) : undefined;
    if (session && session.expiresAt > this.now()) {
      const exit = this.exits.find(
        (item) => item.name === session.exitName && this.usable(item, parsed.location ? String(parsed.location).toLowerCase() : null),
      );
      if (exit) ordered.push(exit);
    }
    const pool = this.healthyExits(parsed.location).filter((exit) => !ordered.includes(exit));
    if (pool.length) {
      const start = this.roundRobin % pool.length;
      this.roundRobin = (this.roundRobin + 1) % pool.length;
      for (let offset = 0; offset < pool.length; offset += 1) {
        const exit = pool[(start + offset) % pool.length];
        if (exit) ordered.push(exit);
      }
    }
    return ordered;
  }

  commit(parsed: ParsedUser, exit: Exit): void {
    const key = this.sessionKey(parsed);
    if (!key) return;
    if (!this.sessions.has(key) && this.sessions.size >= this.maxSessions) {
      const oldest = this.sessions.keys().next();
      if (!oldest.done) this.sessions.delete(oldest.value);
    }
    this.sessions.set(key, { exitName: exit.name, expiresAt: this.now() + this.sessionTtlMs });
  }

  recordSuccess(exit: Exit): void {
    exit.successes += 1;
    exit.failures = 0;
    if (exit.successes >= this.healthyThreshold) {
      exit.healthy = true;
      exit.circuit = 'closed';
      exit.openedAt = 0;
      exit.backoffMs = 0;
    }
  }

  recordFailure(exit: Exit): void {
    exit.failures += 1;
    exit.successes = 0;
    if (exit.failures >= this.unhealthyThreshold) exit.healthy = false;
    if (exit.failures >= this.circuitThreshold) {
      exit.circuit = 'open';
      exit.openedAt = this.now();
      const steps = Math.min(exit.failures - this.circuitThreshold, 6);
      const raw = Math.min(this.circuitMaxMs, this.circuitBaseMs * 2 ** steps);
      exit.backoffMs = Math.round(raw * (0.5 + Math.random() * 0.5));
    }
  }

  sweep(now: number = this.now()): void {
    for (const [key, value] of this.sessions) {
      if (value.expiresAt <= now) this.sessions.delete(key);
    }
  }

  stats() {
    return {
      exits: this.exits.map((exit) => ({
        name: exit.name,
        location: exit.location || '',
        healthy: exit.healthy,
        circuit: exit.circuit,
        failures: exit.failures,
        connections: exit.connections,
        bytesUp: exit.bytesUp,
        bytesDown: exit.bytesDown,
      })),
      sessions: [...this.sessions.entries()].map(([key, value]) => ({
        key,
        exit: value.exitName,
        expiresInMs: Math.max(0, value.expiresAt - this.now()),
      })),
    };
  }
}

export interface AuthLimiterOptions {
  maxFailures?: number;
  windowMs?: number;
  blockMs?: number;
  maxKeys?: number;
  now?: () => number;
}

interface AuthRecord {
  failures: number;
  firstAt: number;
  blockedUntil: number;
}

export interface AuthLimiter {
  allowed(key: string): boolean;
  recordFailure(key: string): void;
  recordSuccess(key: string): void;
  stats(): { tracked: number; blocked: number };
}

export function createAuthLimiter(options: AuthLimiterOptions = {}): AuthLimiter {
  const maxFailures = options.maxFailures ?? 10;
  const windowMs = options.windowMs ?? 60000;
  const blockMs = options.blockMs ?? 60000;
  const maxKeys = options.maxKeys ?? 5000;
  const now = options.now ?? (() => Date.now());
  const records = new Map<string, AuthRecord>();

  function prune(): void {
    const current = now();
    for (const [key, record] of records) {
      if (record.blockedUntil <= current && current - record.firstAt > windowMs) records.delete(key);
    }
    if (records.size > maxKeys) {
      const excess = records.size - maxKeys;
      let removed = 0;
      for (const key of records.keys()) {
        records.delete(key);
        if (++removed >= excess) break;
      }
    }
  }

  return {
    allowed(key: string): boolean {
      const record = records.get(key);
      if (!record) return true;
      return record.blockedUntil <= now();
    },
    recordFailure(key: string): void {
      const current = now();
      const record = records.get(key);
      if (!record || current - record.firstAt > windowMs) {
        records.set(key, { failures: 1, firstAt: current, blockedUntil: 0 });
      } else {
        record.failures += 1;
        if (record.failures >= maxFailures) {
          record.blockedUntil = current + blockMs;
          record.failures = 0;
          record.firstAt = current;
        }
      }
      if (records.size > maxKeys) prune();
    },
    recordSuccess(key: string): void {
      records.delete(key);
    },
    stats(): { tracked: number; blocked: number } {
      const current = now();
      let blocked = 0;
      for (const record of records.values()) if (record.blockedUntil > current) blocked += 1;
      return { tracked: records.size, blocked };
    },
  };
}
