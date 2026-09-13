const path = require('path');
const config = require('./config');
const { saveState, launchContext, getPage } = require('./browser');
const { login } = require('./login');
const { startRecording } = require('./recorder');
const { replay, loadRecording } = require('./replayer');
const { collectMovements } = require('./movements');

const args = process.argv.slice(2);
const command = args[0];
const headed = args.includes('--headed');

const usage = `
Uso:
  npm run login [-- --headed]          Inicia sesion (oculto; --headed para ver)
  npm run record                       Abre el navegador y graba tu sesion manual
  npm run record -- --login            Inicia sesion automatico y luego graba
  npm run movements [-- --headed]      Entra y captura los movimientos de la cuenta
  npm run hotmail                      Abre Outlook para iniciar sesion una vez
  npm run replay -- <archivo.json>     Repite una grabacion (--headed para verlo)
  npm run cookies                      Exporta las cookies de la sesion
`.trim();

function resolveMode(forceVisible = false) {
  if (forceVisible || headed) return 'visible';
  return config.mode;
}

async function ensureLoggedIn(options = {}) {
  const result = await login({ mode: options.mode || resolveMode() });
  if (result.state !== 'logged') {
    throw new Error(`No se pudo iniciar sesion (estado: ${result.state})`);
  }
  return result;
}

async function main() {
  if (command === 'login') {
    const { context } = await ensureLoggedIn();
    await context.close();
    return;
  }

  if (command === 'record') {
    const autoLogin = args.includes('--login');
    let context;
    if (autoLogin) {
      ({ context } = await ensureLoggedIn({ mode: 'visible' }));
    } else {
      context = await launchContext({ mode: 'visible' });
    }
    const recorder = await startRecording(context);
    if (!autoLogin) {
      const page = await getPage(context);
      await page.goto(config.loginUrl, { waitUntil: 'domcontentloaded' }).catch(() => {});
    }
    console.log('Grabando. Inicia sesion/navega normalmente y cierra el navegador para guardar.');
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      recorder.save();
    };
    process.on('SIGINT', () => {
      finish();
      process.exit(0);
    });
    await new Promise((resolve) => context.on('close', resolve));
    finish();
    return;
  }

  if (command === 'movements') {
    const file = await collectMovements({ mode: resolveMode() });
    if (!file) process.exitCode = 1;
    return;
  }

  if (command === 'hotmail') {
    const context = await launchContext({ mode: 'visible' });
    const page = await getPage(context);
    await page.goto(config.emailUrl, { waitUntil: 'domcontentloaded' }).catch(() => {});
    console.log('Inicia sesion en tu correo. Cuando termines, cierra el navegador.');
    await new Promise((resolve) => context.on('close', resolve));
    return;
  }

  if (command === 'replay') {
    const file = args.slice(1).find((arg) => !arg.startsWith('--'));
    if (!file) {
      throw new Error('Indica el archivo: npm run replay -- recordings/rec-....json');
    }
    const recording = loadRecording(file);
    const { context } = await ensureLoggedIn();
    await replay(context, recording.steps, { pauseMs: 400 });
    await saveState(context);
    if (resolveMode() === 'visible') {
      console.log('Replay terminado. Cierra el navegador para salir.');
      await new Promise((resolve) => context.on('close', resolve));
    } else {
      await context.close();
    }
    return;
  }

  if (command === 'cookies') {
    const { context } = await ensureLoggedIn();
    await saveState(context);
    console.log(`Cookies guardadas en ${path.join(config.stateDir, 'cookies.json')}`);
    await context.close();
    return;
  }

  console.log(usage);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
