const config = require('./config');
const { humanClick, humanType } = require('./human');

function loadCard() {
  const codes = config.cardCodes || {};
  if (!Object.keys(codes).length) return null;
  return { cardNumber: config.cardNumber || '', codes };
}

function extractPositions(text) {
  const positions = [];
  const source = (text || '').replace(/\s+/g, ' ');
  const add = (value) => {
    const position = Number(value);
    if (position >= 1 && position <= 40 && !positions.includes(position)) {
      positions.push(position);
    }
  };
  const primary =
    /(?:posici[oó]n(?:es)?|claves?|c[oó]digos?|n[uú]meros?)\s*(?:no\.?|n[°º]|#)?\s*(\d{1,2})(?!\d)/gi;
  let match = primary.exec(source);
  while (match) {
    add(match[1]);
    const after = source.slice(match.index + match[0].length, match.index + match[0].length + 60);
    const extra = /(?:y|e|,)\s*(?:no\.?|n[°º]|#)?\s*(\d{1,2})(?!\d)/gi;
    let extraMatch = extra.exec(after);
    while (extraMatch) {
      add(extraMatch[1]);
      extraMatch = extra.exec(after);
    }
    match = primary.exec(source);
  }
  return positions;
}

async function answerCardCode(page) {
  const card = loadCard();
  if (!card) return { total: 0, answered: 0, positions: [] };

  const text = await page
    .evaluate(() => (document.body ? document.body.innerText : '') || '')
    .catch(() => '');
  const positions = extractPositions(text);
  if (!positions.length) return { total: 0, answered: 0, positions: [] };

  const inputLocator = page.locator(
    'input:visible:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="submit"]):not([type="button"]):not([type="search"])',
  );
  const inputCount = await inputLocator.count().catch(() => 0);
  const total = Math.min(inputCount, positions.length);
  let answered = 0;

  for (let index = 0; index < total; index += 1) {
    const code = card.codes[String(positions[index])];
    if (!code) continue;
    await humanType(page, inputLocator.nth(index), code)
      .then(() => {
        answered += 1;
      })
      .catch(() => {});
  }

  if (total > 0 && answered === total) {
    const button = page
      .locator(
        'button:has-text("Continuar"), button:has-text("Enviar"), button:has-text("Aceptar"), input[type="submit"], input[type="button"][value*="Continuar" i]',
      )
      .first();
    if ((await button.count()) > 0) await humanClick(page, button).catch(() => {});
  }

  return { total, answered, positions };
}

module.exports = { answerCardCode, loadCard, extractPositions };
