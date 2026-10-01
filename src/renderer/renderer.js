const $ = (id) => document.getElementById(id);

const els = {
  remaining: $('remaining'),
  caption: $('caption'),
  progress: $('progress'),
  since: $('since'),
  count: $('count'),
  form: $('settings'),
  minutes: $('minutes'),
  save: $('save'),
  error: $('error'),
  login: $('login'),
  restart: $('restart'),
  pause: $('pause'),
  alert: $('alert'),
  overdue: $('overdue'),
  confirm: $('confirm'),
};

const CIRCUMFERENCE = 2 * Math.PI * Number(els.progress.getAttribute('r'));
els.progress.style.strokeDasharray = String(CIRCUMFERENCE);

const SINCE_LABELS = {
  start: 'started',
  unlock: 'unlocked',
  resume: 'woke from sleep',
  stretch: 'last stretch',
  pause: 'resumed',
};

let state = null;

function fmt(ms) {
  const total = Math.ceil(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function clock(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function render(s) {
  const firstState = state === null;
  state = s;

  document.body.classList.toggle('locked', s.status === 'locked' || s.status === 'paused');

  els.pause.textContent = s.status === 'paused' ? 'Resume' : 'Pause';

  if (s.status === 'paused') {
    els.remaining.textContent = fmt(s.intervalMs);
    els.caption.textContent = 'paused';
    els.progress.style.strokeDashoffset = '0';
    els.since.textContent = 'Click Resume to start a new countdown.';
  } else if (s.status === 'locked') {
    els.remaining.textContent = fmt(s.intervalMs);
    els.caption.textContent = 'paused — screen locked';
    els.progress.style.strokeDashoffset = '0';
    els.since.textContent = 'The timer restarts when you unlock.';
  } else {
    els.remaining.textContent = fmt(s.remainingMs);
    els.caption.textContent = s.fast ? 'until stretch (fast mode)' : 'until stretch';
    const fraction = s.intervalMs ? s.remainingMs / s.intervalMs : 0;
    els.progress.style.strokeDashoffset = String(CIRCUMFERENCE * (1 - fraction));
    els.since.textContent = `Since ${SINCE_LABELS[s.since] || 'started'} at ${clock(s.cycleStart)}`;
  }

  els.count.textContent = `${s.stretchesToday} today`;

  const alerting = s.status === 'alerting';
  els.alert.hidden = !alerting;
  if (alerting) {
    const over = Date.now() - s.alertedAt;
    els.overdue.textContent = over >= 1000 ? `Waiting for ${fmt(over)}` : `${s.minutes} minutes are up`;
  }

  els.minutes.min = s.minMinutes;
  els.minutes.max = s.maxMinutes;
  // Don't clobber what the user is typing.
  if (firstState || document.activeElement !== els.minutes) {
    if (els.save.disabled) els.minutes.value = s.minutes;
  }
  updateSaveButton();

  els.login.checked = s.openAtLogin;
}

function updateSaveButton() {
  if (!state) return;
  els.save.disabled = Number(els.minutes.value) === state.minutes || els.minutes.value === '';
}

els.minutes.addEventListener('input', () => {
  els.error.hidden = true;
  updateSaveButton();
});

els.minutes.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    els.minutes.value = state.minutes;
    els.error.hidden = true;
    updateSaveButton();
    els.minutes.blur();
  }
});

els.form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const ok = await window.stretch.setMinutes(els.minutes.value);
  if (ok) {
    els.error.hidden = true;
    els.minutes.blur();
  } else {
    els.error.textContent = `Enter a whole number between ${state.minMinutes} and ${state.maxMinutes}.`;
    els.error.hidden = false;
  }
});

els.login.addEventListener('change', () => window.stretch.setOpenAtLogin(els.login.checked));
els.pause.addEventListener('click', () => window.stretch.togglePause());
els.restart.addEventListener('click', () => window.stretch.restart());
els.confirm.addEventListener('click', () => window.stretch.confirm());

window.stretch.onState(render);
