// Registro Prometheus minimo (sin dependencias). Formato de exposicion texto 0.0.4.
export type Labels = Record<string, string | number>;

export const DEFAULT_BUCKETS: readonly number[] = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10];

interface Metric {
  readonly name: string;
  render(): string;
}

function escapeLabelValue(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/"/g, '\\"');
}

function formatLabels(labels: Labels): string {
  const keys = Object.keys(labels).sort();
  if (keys.length === 0) return '';
  const parts = keys.map((key) => `${key}="${escapeLabelValue(String(labels[key]))}"`);
  return `{${parts.join(',')}}`;
}

function normalize(labels: Labels, labelNames: readonly string[]): Labels {
  const result: Labels = {};
  for (const name of labelNames) {
    const value = labels[name];
    if (value !== undefined) result[name] = value;
  }
  return result;
}

function seriesKey(labelNames: readonly string[], labels: Labels): string {
  return labelNames.map((name) => String(labels[name] ?? '')).join('\u0000');
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '0';
  return String(value);
}

function header(name: string, help: string, type: string): string[] {
  return [`# HELP ${name} ${help}`, `# TYPE ${name} ${type}`];
}

interface CounterEntry {
  labels: Labels;
  value: number;
}

export class Counter implements Metric {
  readonly name: string;
  private readonly help: string;
  private readonly labelNames: readonly string[];
  private readonly values = new Map<string, CounterEntry>();

  constructor(name: string, help: string, labelNames: readonly string[] = []) {
    this.name = name;
    this.help = help;
    this.labelNames = labelNames;
  }

  inc(labels: Labels = {}, value = 1): void {
    const normalized = normalize(labels, this.labelNames);
    const key = seriesKey(this.labelNames, normalized);
    const entry = this.values.get(key);
    if (entry) entry.value += value;
    else this.values.set(key, { labels: normalized, value });
  }

  render(): string {
    const lines = header(this.name, this.help, 'counter');
    if (this.values.size === 0 && this.labelNames.length === 0) {
      lines.push(`${this.name} 0`);
      return lines.join('\n');
    }
    for (const entry of this.values.values()) {
      lines.push(`${this.name}${formatLabels(entry.labels)} ${formatNumber(entry.value)}`);
    }
    return lines.join('\n');
  }
}

export class Gauge implements Metric {
  readonly name: string;
  private readonly help: string;
  private readonly labelNames: readonly string[];
  private readonly values = new Map<string, CounterEntry>();

  constructor(name: string, help: string, labelNames: readonly string[] = []) {
    this.name = name;
    this.help = help;
    this.labelNames = labelNames;
  }

  private entry(labels: Labels): CounterEntry {
    const normalized = normalize(labels, this.labelNames);
    const key = seriesKey(this.labelNames, normalized);
    let value = this.values.get(key);
    if (!value) {
      value = { labels: normalized, value: 0 };
      this.values.set(key, value);
    }
    return value;
  }

  set(value: number, labels: Labels = {}): void {
    this.entry(labels).value = value;
  }

  inc(labels: Labels = {}, value = 1): void {
    this.entry(labels).value += value;
  }

  dec(labels: Labels = {}, value = 1): void {
    this.entry(labels).value -= value;
  }

  render(): string {
    const lines = header(this.name, this.help, 'gauge');
    if (this.values.size === 0 && this.labelNames.length === 0) {
      lines.push(`${this.name} 0`);
      return lines.join('\n');
    }
    for (const entry of this.values.values()) {
      lines.push(`${this.name}${formatLabels(entry.labels)} ${formatNumber(entry.value)}`);
    }
    return lines.join('\n');
  }
}

interface HistogramEntry {
  labels: Labels;
  counts: number[];
  sum: number;
  count: number;
}

export class Histogram implements Metric {
  readonly name: string;
  private readonly help: string;
  private readonly buckets: readonly number[];
  private readonly labelNames: readonly string[];
  private readonly values = new Map<string, HistogramEntry>();

  constructor(name: string, help: string, buckets: readonly number[] = DEFAULT_BUCKETS, labelNames: readonly string[] = []) {
    this.name = name;
    this.help = help;
    this.buckets = [...buckets].sort((a, b) => a - b);
    this.labelNames = labelNames;
  }

  observe(value: number, labels: Labels = {}): void {
    const normalized = normalize(labels, this.labelNames);
    const key = seriesKey(this.labelNames, normalized);
    let entry = this.values.get(key);
    if (!entry) {
      entry = { labels: normalized, counts: new Array<number>(this.buckets.length).fill(0), sum: 0, count: 0 };
      this.values.set(key, entry);
    }
    entry.sum += value;
    entry.count += 1;
    for (let index = 0; index < this.buckets.length; index += 1) {
      const bucket = this.buckets[index];
      if (bucket !== undefined && value <= bucket) {
        entry.counts[index] = (entry.counts[index] ?? 0) + 1;
        break;
      }
    }
  }

  render(): string {
    const lines = header(this.name, this.help, 'histogram');
    for (const entry of this.values.values()) {
      let cumulative = 0;
      for (let index = 0; index < this.buckets.length; index += 1) {
        cumulative += entry.counts[index] ?? 0;
        const le = formatNumber(this.buckets[index] as number);
        lines.push(`${this.name}_bucket${formatLabels({ ...entry.labels, le })} ${cumulative}`);
      }
      lines.push(`${this.name}_bucket${formatLabels({ ...entry.labels, le: '+Inf' })} ${entry.count}`);
      lines.push(`${this.name}_sum${formatLabels(entry.labels)} ${formatNumber(entry.sum)}`);
      lines.push(`${this.name}_count${formatLabels(entry.labels)} ${entry.count}`);
    }
    return lines.join('\n');
  }
}

export class Registry {
  private readonly metrics: Metric[] = [];
  private readonly names = new Set<string>();

  private register<T extends Metric>(metric: T): T {
    if (this.names.has(metric.name)) throw new Error(`metrica duplicada: ${metric.name}`);
    this.names.add(metric.name);
    this.metrics.push(metric);
    return metric;
  }

  counter(name: string, help: string, labelNames: readonly string[] = []): Counter {
    return this.register(new Counter(name, help, labelNames));
  }

  gauge(name: string, help: string, labelNames: readonly string[] = []): Gauge {
    return this.register(new Gauge(name, help, labelNames));
  }

  histogram(name: string, help: string, buckets: readonly number[] = DEFAULT_BUCKETS, labelNames: readonly string[] = []): Histogram {
    return this.register(new Histogram(name, help, buckets, labelNames));
  }

  render(): string {
    return `${this.metrics.map((metric) => metric.render()).join('\n')}\n`;
  }
}

export function startTimer(): bigint {
  return process.hrtime.bigint();
}

export function elapsedSeconds(start: bigint): number {
  return Number(process.hrtime.bigint() - start) / 1e9;
}
