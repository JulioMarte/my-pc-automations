const fs = require('fs');
const path = require('path');
const config = require('./config');

const INIT_SCRIPT = `
(() => {
  if (window.__bhdRecorderInstalled) return;
  window.__bhdRecorderInstalled = true;

  const escape = (value) =>
    window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');

  const selectorFor = (el) => {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) return '#' + escape(el.id);
    const testid = el.getAttribute('data-testid') || el.getAttribute('data-test-id') || el.getAttribute('data-qa');
    if (testid) return el.tagName.toLowerCase() + '[data-testid="' + testid + '"]';
    if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
    const aria = el.getAttribute('aria-label');
    if (aria) return el.tagName.toLowerCase() + '[aria-label="' + aria + '"]';
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      let part = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
        if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      if (node.id) {
        parts[0] = '#' + escape(node.id);
        break;
      }
      node = parent;
    }
    return parts.join(' > ');
  };

  const send = (payload) => {
    try {
      if (window.__bhdRecord) window.__bhdRecord(payload);
    } catch (error) {}
  };

  const labelOf = (el) =>
    ((el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '') + '')
      .trim()
      .slice(0, 120);

  document.addEventListener(
    'click',
    (event) => {
      const target =
        event.target && event.target.closest
          ? event.target.closest('a,button,input,select,textarea,[role="button"],[onclick]') || event.target
          : event.target;
      send({ type: 'click', selector: selectorFor(target), text: labelOf(target), url: location.href });
    },
    true,
  );

  document.addEventListener(
    'change',
    (event) => {
      const el = event.target;
      if (!el || el.tagName !== 'SELECT') return;
      send({ type: 'select', selector: selectorFor(el), value: el.value, url: location.href });
    },
    true,
  );

  let timer = null;
  const pending = new Map();
  document.addEventListener(
    'input',
    (event) => {
      const el = event.target;
      if (!el || !el.tagName || (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA')) return;
      const secret = el.type === 'password';
      pending.set(el, {
        type: 'fill',
        selector: selectorFor(el),
        value: secret ? null : el.value,
        secret,
        url: location.href,
      });
      clearTimeout(timer);
      timer = setTimeout(() => {
        pending.forEach((payload) => send(payload));
        pending.clear();
      }, 500);
    },
    true,
  );

  document.addEventListener(
    'keydown',
    (event) => {
      if (event.key !== 'Enter') return;
      send({ type: 'press', key: 'Enter', selector: selectorFor(event.target), url: location.href });
    },
    true,
  );
})();
`;

async function startRecording(context) {
  fs.mkdirSync(config.recordingsDir, { recursive: true });
  const session = {
    startedAt: new Date().toISOString(),
    steps: [],
    requests: [],
    responses: [],
  };
  let saved = false;

  const push = (step) => {
    const previous = session.steps[session.steps.length - 1];
    if (previous && previous.type === 'goto' && step.type === 'goto' && previous.url === step.url) {
      return;
    }
    session.steps.push(step);
  };

  const trackPage = (page) => {
    page.on('framenavigated', (frame) => {
      if (frame !== page.mainFrame()) return;
      const url = frame.url();
      if (!url || url === 'about:blank') return;
      push({ type: 'goto', url, ts: Date.now() });
    });
  };

  context.on('page', trackPage);
  context.pages().forEach(trackPage);

  const recordRequest = (request) => {
    const type = request.resourceType();
    if (type !== 'xhr' && type !== 'fetch' && type !== 'document') return;
    const url = request.url();
    if (!url.startsWith('http')) return;
    const previous = session.requests[session.requests.length - 1];
    if (previous && previous.method === request.method() && previous.url === url) return;
    session.requests.push({ method: request.method(), url, type, ts: Date.now() });
  };
  context.on('request', recordRequest);

  const recordResponse = async (response) => {
    try {
      if (session.responses.length >= 300) return;
      const request = response.request();
      const type = request.resourceType();
      if (type !== 'xhr' && type !== 'fetch') return;
      const url = response.url();
      if (!url.includes('ibp-api.bhd.com.do')) return;
      const contentType = (response.headers()['content-type'] || '').toLowerCase();
      if (!contentType.includes('json')) return;
      const body = await response.json().catch(() => null);
      if (body === null) return;
      session.responses.push({
        url,
        method: request.method(),
        status: response.status(),
        ts: Date.now(),
        body,
      });
    } catch (error) {}
  };
  context.on('response', recordResponse);

  await context.exposeBinding('__bhdRecord', (source, payload) => {
    push({ ...payload, ts: Date.now() });
  });
  await context.addInitScript(INIT_SCRIPT);

  const save = () => {
    if (saved) return null;
    saved = true;
    const file = path.join(config.recordingsDir, `rec-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify(session, null, 2));
    console.log(`Grabacion guardada en ${file} (${session.steps.length} pasos)`);
    return file;
  };

  return { session, save };
}

module.exports = { startRecording };
