const config = require('./config');

function extractCode(text) {
  if (!text) return null;
  const normalized = String(text).replace(/\s+/g, ' ');
  const near = normalized.match(
    /(?:c[oó]digo|code|otp|verificaci[oó]n|clave)[^0-9]{0,40}(\d{4,8})/i,
  );
  if (near) return near[1];
  const any = normalized.match(/\b(\d{6})\b/);
  return any ? any[1] : null;
}

async function readOtpFromEmail(context) {
  const page = await context.newPage();
  try {
    await page.goto(config.emailUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(6000);

    const loginForm = await page
      .locator('input[type="email"], input[name="loginfmt"], input[type="password"]')
      .count()
      .catch(() => 0);
    if (loginForm > 0) {
      console.log('Sesion de correo no iniciada o expirada. Corre "npm run hotmail" una vez.');
      return null;
    }

    const rows = page.locator(
      '[role="option"], [role="listitem"], div[role="main"] [aria-label*="mensaje" i]',
    );
    await rows.first().waitFor({ state: 'visible', timeout: 30000 }).catch(() => {});

    const count = Math.min(await rows.count().catch(() => 0), 12);
    let target = null;
    for (let index = 0; index < count; index += 1) {
      const row = rows.nth(index);
      const text = ((await row.innerText().catch(() => '')) || '').toLowerCase();
      if (text.includes(config.otpSender)) {
        target = row;
        break;
      }
    }

    if (!target) {
      console.log('No encontre un correo reciente del banco en la bandeja.');
      return null;
    }

    await target.click().catch(() => {});
    await page.waitForTimeout(3000);
    const body = await page
      .evaluate(() => (document.body ? document.body.innerText : '') || '')
      .catch(() => '');
    const code = extractCode(body);
    if (!code) console.log('No pude extraer el codigo del correo.');
    return code;
  } finally {
    await page.close().catch(() => {});
  }
}

module.exports = { readOtpFromEmail, extractCode };
