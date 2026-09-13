const fs = require('fs');
const path = require('path');
const config = require('./config');

const recordingsDir = config.recordingsDir;

function latestRecording() {
  if (!fs.existsSync(recordingsDir)) return null;
  const files = fs
    .readdirSync(recordingsDir)
    .filter((file) => file.endsWith('.json'))
    .sort();
  return files.length ? path.join(recordingsDir, files[files.length - 1]) : null;
}

function shortUrl(value) {
  try {
    const url = new URL(value);
    return url.pathname + url.search;
  } catch (error) {
    return value;
  }
}

function main() {
  const arg = process.argv[2];
  const file = arg ? path.resolve(arg) : latestRecording();
  if (!file) {
    console.log('No hay grabaciones en recordings/. Corre primero: npm run record');
    return;
  }

  const data = JSON.parse(fs.readFileSync(file, 'utf8'));
  const steps = data.steps || [];
  const requests = data.requests || [];
  const responses = data.responses || [];

  console.log(`Archivo: ${file}`);
  console.log(`Inicio: ${data.startedAt}`);
  console.log(`Pasos: ${steps.length} | Requests: ${requests.length} | Respuestas API: ${responses.length}`);

  console.log('\n=== Navegaciones ===');
  for (const step of steps.filter((item) => item.type === 'goto')) {
    console.log(`  ${shortUrl(step.url)}`);
  }

  console.log('\n=== Acciones ===');
  for (const step of steps.filter((item) => item.type !== 'goto')) {
    if (step.type === 'click') {
      console.log(`  click  ${step.text || '(sin texto)'}  ->  ${step.selector}`);
    } else if (step.type === 'fill') {
      console.log(`  fill   ${step.selector}  ${step.secret ? '(secreto)' : `= ${step.value}`}`);
    } else {
      console.log(`  ${step.type}  ${step.selector || ''} ${step.value || step.key || ''}`.trimEnd());
    }
  }

  console.log('\n=== Endpoints unicos ===');
  const seen = new Set();
  for (const request of requests) {
    const key = `${request.method} ${request.url}`;
    if (seen.has(key)) continue;
    seen.add(key);
    console.log(`  ${key}`);
  }

  if (responses.length) {
    console.log('\n=== Respuestas API capturadas ===');
    for (const response of responses.slice(0, 40)) {
      console.log(`  ${response.status} ${response.method} ${shortUrl(response.url)}`);
    }
  }
}

if (require.main === module) {
  main();
}
