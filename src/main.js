const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  Notification,
  ipcMain,
  nativeImage,
  powerMonitor,
} = require('electron');
const path = require('path');
const fs = require('fs');

const MIN_MINUTES = 1;
const MAX_MINUTES = 600;
const DEFAULT_MINUTES = 45;
const RENUDGE_MS = 60 * 1000; // re-assert the alert this often while unconfirmed

// For testing: --fast (or STRETCH_FAST=1) makes one "minute" last one second.
const FAST = process.argv.includes('--fast') || Boolean(process.env.STRETCH_FAST);
const MINUTE_MS = FAST ? 1000 : 60 * 1000;
// Keep fast-mode settings (and its single-instance lock) apart from the real ones.
if (FAST) app.setPath('userData', path.join(app.getPath('appData'), 'Stretch Timer (fast)'));

let win = null;
let tray = null;
let quitting = false;

// ---------- settings ----------

const settingsPath = () => path.join(app.getPath('userData'), 'settings.json');

function loadSettings() {
  try {
    return JSON.parse(fs.readFileSync(settingsPath(), 'utf8'));
  } catch {
    return {};
  }
}

function saveSettings() {
  try {
    fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
    fs.writeFileSync(settingsPath(), JSON.stringify(settings, null, 2));
  } catch (err) {
    console.error('Could not save settings:', err);
  }
}

let settings = {};

function todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

function stretchesToday() {
  return settings.stretchDay === todayKey() ? settings.stretchCount || 0 : 0;
}

// ---------- timer ----------

// status: 'running' | 'locked' | 'alerting' | 'paused' (paused by the user; lock/unlock don't change it)
const timer = {
  status: 'running',
  cycleStart: Date.now(),
  since: 'start', // what started the current cycle: 'start' | 'unlock' | 'resume' | 'stretch'
  alertedAt: null,
  lastNudge: 0,
};

const intervalMs = () => settings.minutes * MINUTE_MS;

function startCycle(reason) {
  timer.status = 'running';
  timer.cycleStart = Date.now();
  timer.since = reason;
  clearAlert();
  broadcast();
}

function lock() {
  if (timer.status === 'paused') return;
  timer.status = 'locked';
  clearAlert();
  broadcast();
}

function togglePause() {
  if (timer.status === 'paused') {
    startCycle('pause');
  } else {
    timer.status = 'paused';
    clearAlert();
    broadcast();
  }
  updateTray();
  rebuildTrayMenu();
}

function unlock(reason) {
  if (timer.status !== 'paused') startCycle(reason);
}

function tick() {
  if (timer.status === 'running' && Date.now() - timer.cycleStart >= intervalMs()) {
    raiseAlert();
  } else if (timer.status === 'alerting' && Date.now() - timer.lastNudge >= RENUDGE_MS) {
    nudge();
  }
  broadcast();
}

function raiseAlert() {
  timer.status = 'alerting';
  timer.alertedAt = Date.now();
  if (Notification.isSupported()) {
    const n = new Notification({
      title: 'Time to stretch!',
      body: `You've been at it for ${settings.minutes} min. Stand up, stretch, then confirm in the app.`,
      icon: makeIcon(64, [230, 90, 60]),
    });
    n.on('click', showWindow);
    n.show();
  }
  nudge();
  updateTray();
}

// Bring the window forward and flash it. Called when the alert starts and
// periodically until the user confirms. Uses showInactive so it never steals
// keyboard focus: a stray keypress while typing must not count as a stretch.
function nudge() {
  timer.lastNudge = Date.now();
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.setAlwaysOnTop(true, 'screen-saver');
  win.showInactive();
  win.flashFrame(true);
}

function clearAlert() {
  timer.alertedAt = null;
  if (win) {
    win.flashFrame(false);
    win.setAlwaysOnTop(false);
  }
  updateTray();
}

function confirmStretch() {
  if (timer.status !== 'alerting') return;
  const day = todayKey();
  settings.stretchCount = settings.stretchDay === day ? (settings.stretchCount || 0) + 1 : 1;
  settings.stretchDay = day;
  saveSettings();
  startCycle('stretch');
}

function setMinutes(value) {
  const m = Math.round(Number(value));
  if (!Number.isFinite(m) || m < MIN_MINUTES || m > MAX_MINUTES) return false;
  settings.minutes = m;
  saveSettings();
  // If the new interval is shorter than what has already elapsed, the next tick
  // raises the alert. Restart the cycle instead so changing the setting never
  // triggers an alert out of the blue.
  if (timer.status === 'running' && Date.now() - timer.cycleStart >= intervalMs()) {
    startCycle(timer.since);
  }
  broadcast();
  return true;
}

function snapshot() {
  const now = Date.now();
  return {
    status: timer.status,
    minutes: settings.minutes,
    intervalMs: intervalMs(),
    cycleStart: timer.cycleStart,
    since: timer.since,
    elapsedMs: now - timer.cycleStart,
    remainingMs: Math.max(0, intervalMs() - (now - timer.cycleStart)),
    alertedAt: timer.alertedAt,
    stretchesToday: stretchesToday(),
    openAtLogin: app.getLoginItemSettings(loginItemOptions()).openAtLogin,
    fast: FAST,
    minMinutes: MIN_MINUTES,
    maxMinutes: MAX_MINUTES,
  };
}

function broadcast() {
  if (win && !win.isDestroyed()) win.webContents.send('state', snapshot());
  updateTrayTooltip();
}

// ---------- icons & tray ----------

// Draws a simple ring icon so the app needs no image assets.
function makeIcon(size, [r, g, b]) {
  const buf = Buffer.alloc(size * size * 4);
  const c = (size - 1) / 2;
  const outer = size / 2 - 0.5;
  const inner = outer * 0.55;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const d = Math.hypot(x - c, y - c);
      // cheap anti-aliasing on both edges
      const a = Math.max(0, Math.min(1, outer - d + 0.5)) * Math.max(0, Math.min(1, d - inner + 0.5));
      const i = (y * size + x) * 4;
      buf[i] = b; // BGRA
      buf[i + 1] = g;
      buf[i + 2] = r;
      buf[i + 3] = Math.round(a * 255);
    }
  }
  return nativeImage.createFromBitmap(buf, { width: size, height: size });
}

const ICON_OK = [46, 170, 140];
const ICON_ALERT = [230, 90, 60];
const ICON_PAUSED = [140, 140, 150];

function iconColor() {
  if (timer.status === 'alerting') return ICON_ALERT;
  if (timer.status === 'locked' || timer.status === 'paused') return ICON_PAUSED;
  return ICON_OK;
}

function formatRemaining(ms) {
  const total = Math.ceil(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

let lastTrayColor = null;

function updateTray() {
  if (!tray) return;
  const color = iconColor();
  if (color !== lastTrayColor) {
    tray.setImage(makeIcon(16, color));
    lastTrayColor = color;
  }
  updateTrayTooltip();
}

function updateTrayTooltip() {
  if (!tray) return;
  const s = snapshot();
  const text =
    s.status === 'alerting'
      ? 'Stretch Timer — time to stretch!'
      : s.status === 'paused'
        ? 'Stretch Timer — paused'
        : s.status === 'locked'
          ? 'Stretch Timer — paused (locked)'
          : `Stretch Timer — ${formatRemaining(s.remainingMs)} left`;
  tray.setToolTip(text);
}

function rebuildTrayMenu() {
  if (!tray) return;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: 'Show', click: showWindow },
      { label: timer.status === 'paused' ? 'Resume timer' : 'Pause timer', click: togglePause },
      { label: 'Restart timer', click: () => startCycle('start') },
      { type: 'separator' },
      {
        label: 'Quit',
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
}

function createTray() {
  tray = new Tray(makeIcon(16, ICON_OK));
  lastTrayColor = ICON_OK;
  rebuildTrayMenu();
  tray.on('click', showWindow);
  updateTrayTooltip();
}

// ---------- window ----------

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function createWindow() {
  win = new BrowserWindow({
    width: 360,
    height: 480,
    minWidth: 300,
    minHeight: 420,
    title: 'Stretch Timer',
    icon: makeIcon(64, ICON_OK),
    backgroundColor: '#14171c',
    autoHideMenuBar: true,
    show: !process.argv.includes('--hidden'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.setMenu(null);
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // Closing the window hides it to the tray; the timer keeps running.
  win.on('close', (e) => {
    if (!quitting) {
      e.preventDefault();
      win.hide();
    }
  });
  win.on('focus', () => win.flashFrame(false));
  win.webContents.on('did-finish-load', broadcast);
}

// When running unpackaged (npm start), the executable is electron.exe itself,
// so the app folder has to be passed as an argument.
function loginItemOptions() {
  const args = app.isPackaged ? [] : [app.getAppPath()];
  return { path: process.execPath, args: [...args, '--hidden'] };
}

// ---------- app lifecycle ----------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showWindow);

  app.whenReady().then(() => {
    app.setAppUserModelId('no.vince.stretch-timer');

    settings = loadSettings();
    if (!Number.isFinite(settings.minutes)) settings.minutes = DEFAULT_MINUTES;

    ipcMain.on('confirm-stretch', confirmStretch);
    ipcMain.handle('set-minutes', (_e, value) => setMinutes(value));
    ipcMain.on('restart', () => startCycle('start'));
    ipcMain.on('toggle-pause', togglePause);
    ipcMain.on('set-open-at-login', (_e, on) => {
      app.setLoginItemSettings({ ...loginItemOptions(), openAtLogin: Boolean(on) });
      broadcast();
    });

    powerMonitor.on('lock-screen', lock);
    powerMonitor.on('unlock-screen', () => unlock('unlock'));
    powerMonitor.on('suspend', lock);
    // Some machines resume without a lock screen; treat resume like an unlock.
    powerMonitor.on('resume', () => {
      if (timer.status === 'locked') unlock('resume');
    });

    createWindow();
    createTray();
    setInterval(tick, 1000);
  });

  app.on('before-quit', () => {
    quitting = true;
  });
  app.on('window-all-closed', () => {
    // Stay alive in the tray.
  });
}
