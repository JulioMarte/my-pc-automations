import test from 'node:test';
import assert from 'node:assert/strict';
import { Registry, Counter, Gauge, Histogram } from '../src/metrics.ts';

test('metrics: Counter sin labels expone HELP/TYPE y el valor', () => {
  const registry = new Registry();
  const counter = registry.counter('peticiones_total', 'Total de peticiones');
  counter.inc();
  const lines = counter.render().split('\n');
  assert.equal(lines[0], '# HELP peticiones_total Total de peticiones');
  assert.equal(lines[1], '# TYPE peticiones_total counter');
  assert.equal(lines[2], 'peticiones_total 1');
});

test('metrics: Counter con labels los ordena y acumula', () => {
  const counter = new Counter('peticiones_total', 'Total de peticiones', ['a', 'b']);
  counter.inc({ b: 2, a: 1 });
  counter.inc({ b: 2, a: 1 }, 4);
  const series = counter.render().split('\n').find((line) => line.startsWith('peticiones_total{'));
  assert.equal(series, 'peticiones_total{a="1",b="2"} 5');
});

test('metrics: Counter con labels sin observaciones no emite series', () => {
  const counter = new Counter('peticiones_total', 'Total de peticiones', ['a']);
  const lines = counter.render().split('\n');
  assert.equal(lines.length, 2);
  assert.equal(lines[0], '# HELP peticiones_total Total de peticiones');
  assert.equal(lines[1], '# TYPE peticiones_total counter');
});

test('metrics: Gauge set/inc/dec', () => {
  const gauge = new Gauge('conexiones', 'Conexiones activas', ['exit']);
  gauge.set(10, { exit: 'a' });
  gauge.inc({ exit: 'a' }, 5);
  gauge.dec({ exit: 'a' }, 3);
  const series = gauge.render().split('\n').find((line) => line.startsWith('conexiones{'));
  assert.equal(series, 'conexiones{exit="a"} 12');
});

test('metrics: Gauge sin labels y sin set rinde 0', () => {
  const gauge = new Gauge('conexiones', 'Conexiones activas');
  const lines = gauge.render().split('\n');
  assert.equal(lines[1], '# TYPE conexiones gauge');
  assert.equal(lines[2], 'conexiones 0');
});

test('metrics: Histogram acumula buckets y cierra en _count', () => {
  const histogram = new Histogram('latencia_segundos', 'Latencia', [2, 1]);
  histogram.observe(0.5);
  histogram.observe(1.5);
  histogram.observe(3);
  const lines = histogram.render().split('\n');
  assert.deepEqual(lines, [
    '# HELP latencia_segundos Latencia',
    '# TYPE latencia_segundos histogram',
    'latencia_segundos_bucket{le="1"} 1',
    'latencia_segundos_bucket{le="2"} 2',
    'latencia_segundos_bucket{le="+Inf"} 3',
    'latencia_segundos_sum 5',
    'latencia_segundos_count 3',
  ]);
});

test('metrics: Histogram con label extra incluye le ordenado', () => {
  const histogram = new Histogram('latencia_segundos', 'Latencia', [1], ['route']);
  histogram.observe(0.5, { route: 'a' });
  const line = histogram.render().split('\n').find((l) => l.startsWith('latencia_segundos_bucket'));
  assert.equal(line, 'latencia_segundos_bucket{le="1",route="a"} 1');
});

test('metrics: los buckets acumulados son no decrecientes y cierran en _count', () => {
  const histogram = new Histogram('latencia_segundos', 'Latencia', [0.1, 0.5, 1]);
  for (const value of [0.05, 0.3, 0.3, 0.9, 5]) histogram.observe(value);
  const lines = histogram.render().split('\n');
  const finite = lines
    .filter((line) => line.includes('_bucket{le="') && !line.includes('+Inf'))
    .map((line) => Number(line.split(' ').at(-1)));
  assert.ok(finite.length > 0);
  for (let index = 1; index < finite.length; index += 1) {
    assert.ok(finite[index]! >= finite[index - 1]!);
  }
  const inf = Number(lines.find((line) => line.includes('_bucket{le="+Inf"}'))!.split(' ').at(-1));
  const count = Number(lines.find((line) => line.includes('_count'))!.split(' ').at(-1));
  assert.equal(inf, count);
});

test('metrics: escape de valores de label', () => {
  const counter = new Counter('esc_total', 'Escapado', ['path']);
  counter.inc({ path: 'a"b\\c\nd' });
  const line = counter.render().split('\n').find((l) => l.startsWith('esc_total{'));
  assert.equal(line, 'esc_total{path="a\\"b\\\\c\\nd"} 1');
});

test('metrics: Registry rechaza nombres duplicados', () => {
  const registry = new Registry();
  registry.counter('dup_total', 'Primera');
  assert.throws(() => registry.counter('dup_total', 'Segunda'), /metrica duplicada: dup_total/);
  assert.throws(() => registry.gauge('dup_total', 'Tercera'), /metrica duplicada: dup_total/);
});

test('metrics: Registry.render termina en salto de linea e incluye cada metrica', () => {
  const registry = new Registry();
  registry.counter('a_total', 'A');
  registry.gauge('b_actual', 'B');
  registry.histogram('c_segundos', 'C', [1]);
  const output = registry.render();
  assert.ok(output.endsWith('\n'));
  assert.ok(output.includes('# TYPE a_total counter'));
  assert.ok(output.includes('# TYPE b_actual gauge'));
  assert.ok(output.includes('# TYPE c_segundos histogram'));
});
