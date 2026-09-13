const config = require('./config');
const { launchContext, getPage, saveState } = require('./browser');
const { answerSecurityQuestions } = require('./security');
const { answerCardCode } = require('./card');
const { readOtpFromEmail } = require('./email');
const { humanClick, humanType, humanScroll, pause } = require('./human');

async function bodyText(page) {
  try {
    return (
      await page.evaluate(() => (document.body ? document.body.innerText : '') || '')
    ).toLowerCase();
  } catch (error) {
    return '';
  }
}

async function detectState(page) {
  try {
    return await detectStateInner(page);
  } catch (error) {
    return 'unknown';
  }
}

async function detectStateInner(page) {
  if (config.selectors.loggedIn) {
    const count = await page.locator(config.selectors.loggedIn).count().catch(() => 0);
    if (count > 0) return 'logged';
  }
  const text = await bodyText(page);
  if (config.cardHints.some((hint) => text.includes(hint.toLowerCase()))) return 'card';
  const hasOtp = await page
    .locator(
      '#otpCode, ibp-token-otp, #otp-method-email, input[autocomplete="one-time-code"]',
    )
    .count()
    .catch(() => 0);
  if (hasOtp > 0) return 'otp';
  if (config.otpHints.some((hint) => text.includes(hint.toLowerCase()))) return 'otp';
  if (config.securityHints.some((hint) => text.includes(hint.toLowerCase()))) return 'security';
  const hasPassword = await page
    .locator('#password, input[name="password"], input[type="password"]')
    .count()
    .catch(() => 0);
  if (hasPassword > 0) return 'login';
  const hasContinue = await page
    .locator(
      'button:has-text("Continuar"), button:has-text("Aceptar"), button:has-text("Entendido"), button:has-text("Acceder")',
    )
    .count()
    .catch(() => 0);
  if (hasContinue > 0) return 'notice';
  if (config.loggedHints.some((hint) => text.includes(hint.toLowerCase()))) return 'logged';
  return 'unknown';
}

async function fillCredentials(page) {
  if (!config.user || !config.password) {
    throw new Error('Faltan BHD_USER y BHD_PASSWORD en el archivo .env');
  }
  const userField = config.selectors.user
    ? page.locator(config.selectors.user)
    : page
        .locator(
          '#userName, input[name="userName"], input[type="text"], input[type="email"], input[name*="usuario" i], input[id*="usuario" i], input[name*="user" i], input[id*="user" i]',
        )
        .first();
  const passwordField = config.selectors.password
    ? page.locator(config.selectors.password)
    : page.locator('#password, input[name="password"], input[type="password"]').first();

  await userField.waitFor({ state: 'visible', timeout: 30000 });
  await humanType(page, userField, config.user);
  await humanType(page, passwordField, config.password);
  await pause(page, 250, 700);
  await humanScroll(page);

  if (config.selectors.submit) {
    await humanClick(page, page.locator(config.selectors.submit));
    return;
  }
  const submit = page
    .locator(
      'button[type="submit"], input[type="submit"], button:has-text("Entrar"), button:has-text("Iniciar"), button:has-text("Ingresar"), button:has-text("Acceder")',
    )
    .first();
  if ((await submit.count()) > 0) {
    await humanClick(page, submit);
  } else {
    await page.keyboard.press('Enter');
  }
}

async function waitForState(page, states, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let last = 'unknown';
  while (Date.now() < deadline) {
    try {
      last = await detectState(page);
      if (states.includes(last)) return last;
    } catch (error) {}
    await page.waitForTimeout(500).catch(() => {});
  }
  return last;
}

async function attemptLogin(page) {
  let state = await waitForState(
    page,
    ['login', 'logged', 'security', 'card', 'otp', 'notice'],
    30000,
  );
  if (state === 'login') {
    await fillCredentials(page);
    state = await waitForState(page, ['logged', 'security', 'card', 'otp', 'notice'], 60000);
  }
  return state;
}

async function ensureSecureDevice(page) {
  const checkbox = page.locator('#saveSecureDevice');
  if ((await checkbox.count().catch(() => 0)) === 0) return;
  const checked = await checkbox.isChecked().catch(() => false);
  if (!checked) await humanClick(page, checkbox).catch(() => {});
}

async function clickContinue(page) {
  const button = page
    .locator(
      'button:has-text("Continuar"), button:has-text("Aceptar"), button:has-text("Entendido"), button:has-text("Acceder")',
    )
    .first();
  if ((await button.count().catch(() => 0)) > 0) {
    await humanClick(page, button).catch(() => {});
    return true;
  }
  return false;
}

async function waitForLoggedIn(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const state = await detectState(page);
    if (state === 'logged') return 'logged';
    if (state === 'notice') await clickContinue(page);
    await page.waitForTimeout(1000).catch(() => {});
  }
  return 'unknown';
}

async function selectEmailDelivery(page) {
  const emailOption = page.locator('#otp-method-email');
  if ((await emailOption.count().catch(() => 0)) === 0) return false;
  await humanClick(page, emailOption).catch(() => {});
  await pause(page, 250, 600);
  await clickContinue(page);
  await page.waitForTimeout(2500);
  return true;
}

async function fillOtpCode(page, code) {
  const inputs = page.locator('#otpCode input');
  await inputs.first().waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});
  const count = await inputs.count().catch(() => 0);
  if (count === 0) return false;
  for (let index = 0; index < Math.min(count, code.length); index += 1) {
    await humanType(page, inputs.nth(index), code[index]);
  }
  return true;
}

async function handleOtp(page, { allowManual }) {
  await selectEmailDelivery(page);

  if (config.emailOtp) {
    const code = await readOtpFromEmail(page.context()).catch(() => null);
    if (code) {
      console.log('Codigo OTP obtenido del correo.');
      const filled = await fillOtpCode(page, code);
      if (filled) {
        await ensureSecureDevice(page);
        await pause(page, 300, 800);
        await clickContinue(page);
        const state = await waitForLoggedIn(page, 25000);
        if (state === 'logged') return 'logged';
      }
    }
  }

  if (!allowManual) return 'otp';
  await ensureSecureDevice(page);
  console.log('Ingresa el codigo OTP en la ventana. Esperando...');
  return waitForLoggedIn(page, config.securityTimeoutMs);
}

async function resolveVerification(page, { allowManual }) {
  const states = ['logged', 'security', 'card', 'otp', 'notice'];
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const state = await detectState(page);
    if (state === 'logged') return 'logged';
    if (state === 'otp') {
      return handleOtp(page, { allowManual });
    }
    if (state === 'notice') {
      const clicked = await clickContinue(page);
      if (!clicked) break;
    } else if (state === 'card') {
      const result = await answerCardCode(page).catch(() => ({ answered: 0, total: 0 }));
      console.log(`Tarjeta de clave: ${result.answered}/${result.total} codigos ingresados.`);
      if (!result.answered) break;
    } else if (state === 'security') {
      const result = await answerSecurityQuestions(page).catch(() => ({ answered: 0, total: 0 }));
      console.log(
        `Preguntas de seguridad: ${result.answered}/${result.total} respondidas automaticamente.`,
      );
      if (!result.answered) break;
    } else {
      break;
    }
    const next = await waitForState(page, states, 20000);
    if (next === 'logged') return 'logged';
  }
  if (!allowManual) return 'pending';
  console.log('Completa la verificacion en la ventana. Esperando...');
  return waitForLoggedIn(page, config.securityTimeoutMs);
}

async function login({ mode = config.mode } = {}) {
  let context = await launchContext({ mode });
  let page = await getPage(context);
  await page.goto(config.loginUrl, { waitUntil: 'domcontentloaded' });
  let state = await attemptLogin(page);
  const allowManual = mode === 'visible';

  if (['security', 'card', 'otp', 'notice'].includes(state)) {
    state = await resolveVerification(page, { allowManual });
  }

  if (state !== 'logged' && !allowManual) {
    await saveState(context);
    await context.close();
    console.log('Se requiere verificacion manual. Abriendo el navegador...');
    context = await launchContext({ mode: 'visible' });
    page = await getPage(context);
    await page.goto(config.loginUrl, { waitUntil: 'domcontentloaded' });
    state = await attemptLogin(page);
    if (['security', 'card', 'otp', 'notice'].includes(state)) {
      state = await resolveVerification(page, { allowManual: true });
    }
  }

  if (state === 'logged') {
    await saveState(context);
    console.log('Sesion iniciada. Perfil y cookies guardados.');
  } else {
    console.log(`No se pudo confirmar la sesion (estado: ${state}).`);
  }
  return { context, page, state };
}

module.exports = { login, detectState, waitForState, fillCredentials };
