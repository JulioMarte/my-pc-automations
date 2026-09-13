const fs = require('fs');
const path = require('path');
const config = require('./config');
const { login } = require('./login');
const { humanClick } = require('./human');

async function dismissNotices(page) {
  for (let index = 0; index < 3; index += 1) {
    const button = page
      .locator(
        'button:has-text("Continuar"), button:has-text("Aceptar"), button:has-text("Entendido"), button:has-text("Acceder")',
      )
      .first();
    if ((await button.count().catch(() => 0)) === 0) return;
    await humanClick(page, button).catch(() => {});
    await page.waitForTimeout(1500);
  }
}

async function openAccountMovements(page) {
  await dismissNotices(page);

  const button = page.getByText('Ver estados y movimientos', { exact: false }).first();
  if ((await button.count().catch(() => 0)) === 0) {
    const account = page.getByText(config.accountName, { exact: false }).first();
    await account.waitFor({ state: 'visible', timeout: 30000 }).catch(() => {});
    if ((await account.count().catch(() => 0)) === 0) {
      console.log(`No encontre la cuenta "${config.accountName}" en pantalla.`);
      return false;
    }
    await account.scrollIntoViewIfNeeded().catch(() => {});
    await humanClick(page, account).catch(() => {});
    await button.waitFor({ state: 'visible', timeout: 30000 }).catch(() => {});
  }

  if ((await button.count().catch(() => 0)) === 0) {
    console.log('No encontre el boton "Ver estados y movimientos".');
    return false;
  }
  await button.scrollIntoViewIfNeeded().catch(() => {});
  await humanClick(page, button).catch(() => {});
  return true;
}

async function selectAllMovements(page) {
  const all = page.getByText('Todos', { exact: true }).first();
  if ((await all.count().catch(() => 0)) === 0) return;
  await humanClick(page, all).catch(() => {});
  await page.waitForTimeout(4000);
}

async function selectRange(page, range) {
  if (!range) return;
  const selects = page.locator('p-select');
  const count = await selects.count().catch(() => 0);
  for (let index = 0; index < count; index += 1) {
    const text = ((await selects.nth(index).innerText().catch(() => '')) || '').toLowerCase();
    if (!text.includes('mes') && !text.includes('rango')) continue;
    await humanClick(page, selects.nth(index)).catch(() => {});
    await page.waitForTimeout(1500);
    const option = page.locator('.p-select-option', { hasText: range }).first();
    if ((await option.count().catch(() => 0)) > 0) {
      await humanClick(page, option).catch(() => {});
      await page.waitForTimeout(5000);
    }
    return;
  }
}

async function scrollTableToEnd(page) {
  const table = page.locator('table').first();
  if ((await table.count().catch(() => 0)) === 0) return;
  const box = await table.boundingBox().catch(() => null);
  if (!box) return;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2).catch(() => {});
  let previous = -1;
  for (let index = 0; index < 15; index += 1) {
    const count = await table.locator('tbody tr').count().catch(() => 0);
    if (count === previous) break;
    previous = count;
    await page.mouse.wheel(0, 1400).catch(() => {});
    await page.waitForTimeout(1200);
  }
}

function csvCell(value) {
  const text = String(value ?? '');
  return `"${text.replace(/"/g, '""')}"`;
}

async function extractTable(page) {
  return page.evaluate(() => {
    const table = Array.from(document.querySelectorAll('table')).find((item) =>
      item.querySelector('tbody tr'),
    );
    if (!table) return null;
    const headers = Array.from(table.querySelectorAll('thead th, thead td')).map((cell) =>
      cell.innerText.trim(),
    );
    const rows = Array.from(table.querySelectorAll('tbody tr'))
      .map((row) => Array.from(row.querySelectorAll('td')).map((cell) => cell.innerText.trim()))
      .filter((cells) => cells.length >= 3 && cells.some((cell) => cell));
    return { headers, rows };
  });
}

async function collectMovements({ mode = config.mode } = {}) {
  const { context, page, state } = await login({ mode });
  if (state !== 'logged') {
    console.log(`No se pudo iniciar sesion (estado: ${state}).`);
    await context.close().catch(() => {});
    return null;
  }

  const captured = [];
  const onResponse = async (response) => {
    try {
      const request = response.request();
      const type = request.resourceType();
      if (type !== 'xhr' && type !== 'fetch') return;
      const url = response.url();
      if (!url.includes('ibp-api.bhd.com.do')) return;
      const contentType = (response.headers()['content-type'] || '').toLowerCase();
      if (!contentType.includes('json')) return;
      const body = await response.json().catch(() => null);
      if (body === null) return;
      captured.push({
        url,
        method: request.method(),
        status: response.status(),
        ts: Date.now(),
        body,
      });
    } catch (error) {}
  };
  context.on('response', onResponse);

  const opened = await openAccountMovements(page);
  await page.waitForTimeout(4000);
  await selectRange(page, config.movementsRange);
  await selectAllMovements(page);
  await scrollTableToEnd(page);
  await page.waitForTimeout(3000);
  context.off('response', onResponse);

  const table = await extractTable(page).catch(() => null);

  fs.mkdirSync(config.stateDir, { recursive: true });
  const stamp = Date.now();

  if (!opened) console.log('Aviso: no confirme la navegacion, intento leer la tabla igual.');

  const looksLikeMovements =
    table &&
    table.rows.length > 0 &&
    table.headers.some((header) => /fecha/i.test(header)) &&
    table.headers.some((header) => /balance|d[eé]bito|cr[eé]dito/i.test(header));

  if (!looksLikeMovements) {
    if (captured.length) {
      const apiFile = path.join(config.stateDir, `api-${stamp}.json`);
      fs.writeFileSync(apiFile, JSON.stringify(captured, null, 2));
      console.log(`Respuestas de la API (encriptadas) guardadas en ${apiFile}`);
    }
    console.log('No pude leer la tabla de movimientos correcta en pantalla.');
    await context.close().catch(() => {});
    return null;
  }

  const jsonFile = path.join(config.stateDir, `movements-${stamp}.json`);
  fs.writeFileSync(
    jsonFile,
    JSON.stringify(
      {
        account: config.accountName,
        scrapedAt: new Date().toISOString(),
        headers: table.headers,
        rows: table.rows,
      },
      null,
      2,
    ),
  );

  const csvFile = path.join(config.stateDir, `movements-${stamp}.csv`);
  const lines = [table.headers, ...table.rows].map((cells) => cells.map(csvCell).join(','));
  fs.writeFileSync(csvFile, `\uFEFF${lines.join('\r\n')}`);

  console.log(`Movimientos: ${table.rows.length} filas guardadas en:`);
  console.log(`  ${jsonFile}`);
  console.log(`  ${csvFile}`);

  await context.close().catch(() => {});
  return jsonFile;
}

module.exports = { collectMovements, openAccountMovements, dismissNotices };
