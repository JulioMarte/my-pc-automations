const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const config = require('./config');

function loadEngine() {
  const preferred = (config.engine || 'patchright').toLowerCase();
  if (preferred !== 'playwright') {
    try {
      return require('patchright');
    } catch (error) {
      console.log('patchright no esta disponible; uso playwright.');
    }
  }
  return require('playwright');
}

const { chromium } = loadEngine();

function minimizeWindow() {
  if (process.platform !== 'win32') return;
  const marker = path.basename(path.dirname(config.profileDir));
  const script = [
    `$procs = Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | Where-Object { $_.CommandLine -like '*${marker}*' -and $_.CommandLine -like '*--user-data-dir*' };`,
    `Add-Type -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);' -Name Win -Namespace Native -ErrorAction SilentlyContinue;`,
    'foreach ($p in $procs) { $proc = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue; if ($proc -and $proc.MainWindowHandle -ne 0) { [Native.Win]::ShowWindowAsync($proc.MainWindowHandle, 6) | Out-Null } }',
  ].join(' ');
  try {
    execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
      windowsHide: true,
      stdio: 'ignore',
      timeout: 20000,
    });
  } catch (error) {}
}

async function launchContext({ mode = config.mode } = {}) {
  fs.mkdirSync(config.profileDir, { recursive: true });
  const headed = mode !== 'headless';
  const options = {
    headless: !headed,
    viewport: headed ? null : { width: 1366, height: 768 },
    locale: 'es-DO',
    timezoneId: 'America/Santo_Domingo',
    args: [
      '--disable-blink-features=AutomationControlled',
      '--no-first-run',
      '--no-default-browser-check',
    ],
  };
  if (mode === 'visible') options.args.push('--window-position=80,80');
  if (mode === 'offscreen') options.args.push('--window-position=-32000,-32000');
  let context;
  try {
    context = await chromium.launchPersistentContext(config.profileDir, {
      ...options,
      channel: config.channel,
    });
  } catch (error) {
    if (!config.channel) throw error;
    context = await chromium.launchPersistentContext(config.profileDir, options);
  }
  if (mode === 'hidden') {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    minimizeWindow();
  }
  return context;
}

async function getPage(context) {
  const page = context.pages()[0] || (await context.newPage());
  return page;
}

async function saveState(context) {
  fs.mkdirSync(config.stateDir, { recursive: true });
  await context.storageState({ path: path.join(config.stateDir, 'storage-state.json') });
  const cookies = await context.cookies();
  fs.writeFileSync(
    path.join(config.stateDir, 'cookies.json'),
    JSON.stringify(cookies, null, 2),
  );
}

module.exports = { launchContext, getPage, saveState };
