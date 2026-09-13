const config = require('./config');
const { humanClick, humanType } = require('./human');

function normalize(value) {
  return (value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[¿?.,:;!¡"'()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function loadAnswers() {
  return (config.securityAnswers || [])
    .filter((item) => item.answer)
    .map((item) => ({
      question: normalize(item.question),
      answer: String(item.answer),
    }));
}

function findAnswer(answers, question) {
  const normalized = normalize(question);
  if (!normalized) return null;
  const exact = answers.find((item) => item.question === normalized);
  if (exact) return exact.answer;
  const partial = answers.find(
    (item) => item.question.includes(normalized) || normalized.includes(item.question),
  );
  return partial ? partial.answer : null;
}

async function extractFields(page) {
  return page.evaluate(() => {
    const isVisible = (el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };

    const inputs = Array.from(
      document.querySelectorAll(
        'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="submit"]):not([type="button"]):not([type="search"]), textarea',
      ),
    ).filter((el) => isVisible(el) && !el.disabled && !el.readOnly);

    const all = Array.from(document.querySelectorAll('*'));
    const indexOf = new Map(all.map((el, index) => [el, index]));

    const questionElements = [];
    for (const el of all) {
      if (!isVisible(el)) continue;
      if (el.tagName === 'SELECT' && el.selectedOptions && el.selectedOptions[0]) {
        const text = el.selectedOptions[0].textContent.trim();
        if (text.includes('?')) questionElements.push({ el, text });
        continue;
      }
      const ownText = Array.from(el.childNodes)
        .filter((node) => node.nodeType === 3)
        .map((node) => node.textContent)
        .join(' ')
        .trim();
      if (ownText.includes('?') && ownText.length < 200) {
        questionElements.push({ el, text: ownText });
      }
    }

    return inputs.map((input, index) => {
      input.setAttribute('data-bhd-index', String(index));
      let question = '';
      let best = Infinity;
      for (const candidate of questionElements) {
        if (candidate.el.contains(input)) continue;
        const position = candidate.el.compareDocumentPosition(input);
        if (!(position & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
        const distance = (indexOf.get(input) ?? 0) - (indexOf.get(candidate.el) ?? 0);
        if (distance > 0 && distance < best) {
          best = distance;
          question = candidate.text;
        }
      }
      return {
        index,
        question,
        placeholder: input.placeholder || '',
        ariaLabel: input.getAttribute('aria-label') || '',
      };
    });
  });
}

async function answerSecurityQuestions(page) {
  const answers = loadAnswers();
  if (!answers.length) return { total: 0, answered: 0, questions: [] };

  await page
    .locator('input:not([type="hidden"]), textarea')
    .first()
    .waitFor({ state: 'visible', timeout: 20000 })
    .catch(() => {});

  const fields = await extractFields(page).catch(() => []);
  let answered = 0;
  const questions = [];

  for (const field of fields) {
    const question = field.question || field.placeholder || field.ariaLabel;
    questions.push(question);
    const answer = findAnswer(answers, question);
    if (!answer) continue;
    await humanType(page, page.locator(`[data-bhd-index="${field.index}"]`), answer)
      .then(() => {
        answered += 1;
      })
      .catch(() => {});
  }

  const total = fields.length;
  if (total > 0 && answered === total) {
    const button = page
      .locator(
        'button:has-text("Continuar"), input[type="submit"], input[type="button"][value*="Continuar" i]',
      )
      .first();
    if ((await button.count()) > 0) await humanClick(page, button).catch(() => {});
  }

  return { total, answered, questions };
}

module.exports = { answerSecurityQuestions, loadAnswers, findAnswer };
