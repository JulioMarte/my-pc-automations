// Limite de conexiones concurrentes por usuario (tenant).
export interface ConnectionLimiterOptions {
  // 0 o negativo = ilimitado.
  max?: number;
}

export class ConnectionLimiter {
  readonly max: number;
  private readonly counts = new Map<string, number>();
  private active = 0;

  constructor(options: ConnectionLimiterOptions = {}) {
    this.max = Math.max(0, options.max ?? 0);
  }

  // true si se admite la conexion; false si el usuario alcanzo su limite.
  acquire(user: string): boolean {
    if (this.max > 0 && (this.counts.get(user) ?? 0) >= this.max) return false;
    this.counts.set(user, (this.counts.get(user) ?? 0) + 1);
    this.active += 1;
    return true;
  }

  release(user: string): void {
    const current = this.counts.get(user);
    if (current === undefined) return;
    if (current <= 1) this.counts.delete(user);
    else this.counts.set(user, current - 1);
    if (this.active > 0) this.active -= 1;
  }

  count(user: string): number {
    return this.counts.get(user) ?? 0;
  }

  total(): number {
    return this.active;
  }

  stats(): Record<string, number> {
    return Object.fromEntries(this.counts);
  }
}
