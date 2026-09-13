const config = require('./config');

function random(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

async function pause(page, min = 120, max = 450) {
  if (!config.human) return;
  await page.waitForTimeout(random(min, max)).catch(() => {});
}

async function humanClick(page, locator) {
  if (!config.human) {
    await locator.click();
    return;
  }
  const box = await locator.boundingBox().catch(() => null);
  if (!box) {
    await locator.click().catch(() => {});
    return;
  }
  const x = box.x + box.width * (0.3 + Math.random() * 0.4);
  const y = box.y + box.height * (0.3 + Math.random() * 0.4);
  await page.mouse.move(x, y, { steps: random(12, 28) }).catch(() => {});
  await pause(page, 80, 220);
  await page.mouse.down().catch(() => {});
  await pause(page, 40, 120);
  await page.mouse.up().catch(() => {});
}

async function humanType(page, locator, text) {
  if (!config.human) {
    await locator.fill(text);
    return;
  }
  await locator.click().catch(() => {});
  await pause(page, 100, 250);
  await locator.fill('').catch(() => {});
  for (const char of String(text)) {
    await page.keyboard.type(char, { delay: random(40, 140) }).catch(() => {});
    if (Math.random() < 0.08) await pause(page, 120, 400);
  }
  await pause(page, 80, 220);
}

async function humanScroll(page) {
  if (!config.human) return;
  await page.mouse.wheel(0, random(60, 240)).catch(() => {});
  await pause(page, 100, 300);
}

module.exports = { humanClick, humanType, humanScroll, pause, random };
