const fs = require('fs');
const path = require('path');
const config = require('./config');

function loadRecording(file) {
  const resolved = path.isAbsolute(file) ? file : path.join(config.root, file);
  return JSON.parse(fs.readFileSync(resolved, 'utf8'));
}

async function resolveLocator(page, step) {
  const candidates = [];
  if (step.selector) candidates.push(page.locator(step.selector));
  if (step.text) candidates.push(page.getByText(step.text, { exact: false }).first());
  for (const candidate of candidates) {
    try {
      if ((await candidate.count()) > 0) return candidate;
    } catch (error) {}
  }
  return null;
}

async function replay(context, steps, options = {}) {
  const page = context.pages()[0] || (await context.newPage());
  const pause = options.pauseMs || 400;

  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index];
    const label = `Paso ${index + 1}/${steps.length} (${step.type})`;

    if (step.type === 'goto') {
      if (page.url() !== step.url) {
        await page.goto(step.url, { waitUntil: 'domcontentloaded' }).catch(() => {});
      }
      continue;
    }

    if (step.type === 'fill') {
      if (step.secret) {
        console.log(`${label}: campo secreto omitido (${step.selector})`);
        continue;
      }
      const locator = await resolveLocator(page, step);
      if (!locator) {
        console.log(`${label}: no encontrado ${step.selector}`);
        continue;
      }
      await locator.fill(step.value || '').catch((error) => console.log(`${label}: ${error.message}`));
      continue;
    }

    if (step.type === 'select') {
      const locator = await resolveLocator(page, step);
      if (locator) await locator.selectOption(step.value).catch(() => {});
      continue;
    }

    if (step.type === 'press') {
      if (step.key === 'Enter') await page.keyboard.press('Enter');
      continue;
    }

    if (step.type === 'click') {
      const locator = await resolveLocator(page, step);
      if (!locator) {
        console.log(`${label}: no encontrado ${step.selector} (${step.text || ''})`);
        continue;
      }
      await locator
        .click({ timeout: 15000 })
        .catch((error) => console.log(`${label}: click fallo (${error.message})`));
      await page.waitForLoadState('domcontentloaded', { timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(pause);
    }
  }
}

module.exports = { replay, loadRecording };
