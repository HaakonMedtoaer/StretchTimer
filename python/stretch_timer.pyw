"""Stretch Timer (Python edition).

Counts down from when you unlock your computer and flashes until you confirm
that you stood up and stretched. Behaves like the Electron version, but needs
nothing beyond the standard library (Python 3.8+ on Windows, with tkinter).

Run:   pythonw stretch_timer.pyw          (no console window)
Test:  python stretch_timer.pyw --fast    (1 "minute" = 1 second)
"""

import ctypes
import json
import os
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import winreg
    import winsound
except ImportError:  # not Windows
    sys.exit('Stretch Timer only runs on Windows.')

APP_NAME = 'Stretch Timer'
MIN_MINUTES, MAX_MINUTES, DEFAULT_MINUTES = 1, 600, 45
RENUDGE_S = 60  # re-assert the alert this often while unconfirmed
SLEEP_GAP_S = 10  # a tick gap longer than this means the machine slept

FAST = '--fast' in sys.argv or bool(os.environ.get('STRETCH_FAST'))
HIDDEN = '--hidden' in sys.argv
MINUTE_S = 1 if FAST else 60
# Local status port so Server Viewer can see whether the app is running.
STATUS_PORT = int(os.environ.get('STRETCH_PORT', 3330)) + (1 if FAST else 0)

BG, PANEL, TEXT, MUTED = '#14171c', '#1d2128', '#e8eaed', '#8b929c'
ACCENT, PAUSED, ERROR, FIELD_BORDER = '#2eaa8c', '#8c8c96', '#ff7b6b', '#333a44'
ALERT_A, ALERT_B = '#e65a3c', '#f2b13c'

SINCE_LABELS = {
    'start': 'started',
    'unlock': 'unlocked',
    'resume': 'woke from sleep',
    'stretch': 'last stretch',
    'pause': 'resumed',
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


# ---------- settings (same file and keys as the Electron version) ----------

SETTINGS_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')),
                            APP_NAME + (' (fast)' if FAST else ''))
SETTINGS_PATH = os.path.join(SETTINGS_DIR, 'settings.json')


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding='utf8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_PATH, 'w', encoding='utf8') as f:
            json.dump(settings, f, indent=2)
    except OSError as err:
        print('Could not save settings:', err, file=sys.stderr)


# ---------- Windows helpers ----------


def screen_is_locked():
    """The input desktop is the lock screen (not 'Default') while locked."""
    DESKTOP_SWITCHDESKTOP = 0x0100
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    h = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not h:
        return True  # can't open the input desktop: secure desktop is showing
    try:
        return not user32.SwitchDesktop(h)
    finally:
        user32.CloseDesktop(h)


class FLASHWINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('hwnd', wintypes.HWND), ('dwFlags', wintypes.DWORD),
                ('uCount', wintypes.UINT), ('dwTimeout', wintypes.DWORD)]


def flash_taskbar(hwnd, on):
    # FLASHW_ALL | FLASHW_TIMERNOFG: flash until the window is brought forward.
    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 15 if on else 0, 0, 0)
    user32.FlashWindowEx(ctypes.byref(info))


def single_instance():
    """Returns False (after raising the running copy) if one is already running."""
    name = 'Local\\no.vince.stretch-timer' + ('.fast' if FAST else '')
    handle = kernel32.CreateMutexW(None, False, name)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        hwnd = user32.FindWindowW(None, APP_NAME)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return False
    single_instance.handle = handle  # keep alive for the process lifetime
    return True


RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def login_command():
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
    if os.path.basename(exe).lower() == 'python.exe' and os.path.exists(pythonw):
        exe = pythonw
    return f'"{exe}" "{os.path.abspath(__file__)}" --hidden'


def open_at_login():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, APP_NAME)[0] == login_command()
    except OSError:
        return False


def set_open_at_login(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, login_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError as err:
        print('Could not update login item:', err, file=sys.stderr)


def fmt(seconds):
    total = int(-(-seconds // 1))  # ceil
    h, m, s = total // 3600, total % 3600 // 60, total % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


def clock(ts):
    return datetime.fromtimestamp(ts).strftime('%H:%M')


# ---------- status endpoint (read-only, loopback only) ----------


def start_status_server(get_status):
    allowed = {f'127.0.0.1:{STATUS_PORT}', f'localhost:{STATUS_PORT}'}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Reject foreign Host headers (DNS rebinding) and anything but / and /health.
            if self.headers.get('Host') not in allowed or self.path not in ('/', '/health'):
                self.send_error(403 if self.headers.get('Host') not in allowed else 404)
                return
            body = json.dumps(get_status()).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    try:
        server = ThreadingHTTPServer(('127.0.0.1', STATUS_PORT), Handler)
    except OSError as err:
        print(f'Status endpoint disabled (port {STATUS_PORT}): {err}', file=sys.stderr)
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()


# ---------- app ----------


class StretchTimer:
    def __init__(self):
        self.settings = load_settings()
        minutes = self.settings.get('minutes')
        if not isinstance(minutes, (int, float)) or isinstance(minutes, bool):
            self.settings['minutes'] = DEFAULT_MINUTES

        # status: 'running' | 'locked' | 'alerting' | 'paused' (paused by the user;
        # lock/unlock don't change it)
        self.status = 'running'
        self.cycle_start = time.time()
        self.since = 'start'
        self.alerted_at = None
        self.last_nudge = 0.0
        self.last_tick = time.time()
        self.flash_phase = False

        self.build_window()
        self.start_cycle('start')
        start_status_server(self.status_info)
        self.tick()

    # ----- timer logic -----

    @property
    def interval(self):
        return self.settings['minutes'] * MINUTE_S

    def start_cycle(self, reason):
        self.status = 'running'
        self.cycle_start = time.time()
        self.since = reason
        self.clear_alert()
        self.render()

    def lock(self):
        if self.status == 'paused':
            return
        self.status = 'locked'
        self.clear_alert()
        self.render()

    def unlock(self, reason):
        if self.status != 'paused':
            self.start_cycle(reason)

    def toggle_pause(self):
        if self.status == 'paused':
            self.start_cycle('pause')
        else:
            self.status = 'paused'
            self.clear_alert()
            self.render()

    def confirm_stretch(self):
        if self.status != 'alerting':
            return
        today = date.today().isoformat()
        s = self.settings
        s['stretchCount'] = (s.get('stretchCount') or 0) + 1 if s.get('stretchDay') == today else 1
        s['stretchDay'] = today
        save_settings(s)
        self.start_cycle('stretch')

    def stretches_today(self):
        s = self.settings
        return (s.get('stretchCount') or 0) if s.get('stretchDay') == date.today().isoformat() else 0

    def set_minutes(self, value):
        try:
            m = round(float(value))
        except ValueError:
            return False
        if not MIN_MINUTES <= m <= MAX_MINUTES:
            return False
        self.settings['minutes'] = m
        save_settings(self.settings)
        # Never let changing the setting raise an alert out of the blue.
        if self.status == 'running' and time.time() - self.cycle_start >= self.interval:
            self.start_cycle(self.since)
        self.render()
        return True

    def tick(self):
        now = time.time()
        slept = now - self.last_tick > SLEEP_GAP_S
        self.last_tick = now

        locked = screen_is_locked()
        if locked and self.status in ('running', 'alerting'):
            self.lock()
        elif not locked and self.status == 'locked':
            self.unlock('unlock')
        elif slept and self.status in ('running', 'alerting'):
            self.start_cycle('resume')  # woke from sleep without a lock screen

        if self.status == 'running' and now - self.cycle_start >= self.interval:
            self.raise_alert()
        elif self.status == 'alerting' and now - self.last_nudge >= RENUDGE_S:
            self.nudge()
        self.render()
        self.root.after(1000, self.tick)

    def status_info(self):
        now = time.time()
        remaining = max(0.0, self.interval - (now - self.cycle_start))
        return {
            'app': APP_NAME,
            'status': self.status,
            'minutes': self.settings['minutes'],
            'remainingSec': round(remaining) if self.status in ('running', 'alerting') else None,
            'stretchesToday': self.stretches_today(),
        }

    # ----- alert -----

    def raise_alert(self):
        self.status = 'alerting'
        self.alerted_at = time.time()
        self.nudge()
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except RuntimeError:
            pass
        self.flash_alert()

    # Bring the window forward and flash it, without taking keyboard focus: a stray
    # keypress while typing must not count as a stretch.
    def nudge(self):
        self.last_nudge = time.time()
        hwnd = self.hwnd()
        self.root.wm_attributes('-topmost', True)
        if self.root.state() in ('iconic', 'withdrawn'):
            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        self.root.lift()
        flash_taskbar(hwnd, True)

    def clear_alert(self):
        self.alerted_at = None
        if hasattr(self, 'root'):
            self.root.wm_attributes('-topmost', False)
            flash_taskbar(self.hwnd(), False)

    def flash_alert(self):
        if self.status != 'alerting':
            return
        self.flash_phase = not self.flash_phase
        color = ALERT_A if self.flash_phase else ALERT_B
        for w in (self.alert, self.alert_title, self.alert_sub):
            w.configure(bg=color)
        self.root.after(500, self.flash_alert)

    # ----- window -----

    def hwnd(self):
        return user32.GetParent(self.root.winfo_id())

    def build_window(self):
        root = self.root = tk.Tk()
        root.title(APP_NAME)
        root.configure(bg=BG)
        root.geometry('360x500')
        root.minsize(320, 480)
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'icon.png')
        try:
            self.icon = tk.PhotoImage(file=icon)
            root.iconphoto(True, self.icon)
        except tk.TclError:
            pass
        root.protocol('WM_DELETE_WINDOW', root.iconify)  # closing minimises; Quit exits
        try:  # dark title bar (Windows 10 2004+/11)
            root.update_idletasks()
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(self.hwnd(), 20, ctypes.byref(on), 4)
        except (OSError, AttributeError):
            pass

        main = tk.Frame(root, bg=BG, padx=20, pady=16)
        main.pack(fill='both', expand=True)

        header = tk.Frame(main, bg=BG)
        header.pack(fill='x')
        tk.Label(header, text=APP_NAME, bg=BG, fg=TEXT, font=('Segoe UI Semibold', 12)).pack(side='left')
        self.count = tk.Label(header, bg=PANEL, fg=MUTED, font=('Segoe UI', 9), padx=10)
        self.count.pack(side='right')

        self.dial = tk.Canvas(main, width=220, height=220, bg=BG, highlightthickness=0)
        self.dial.pack(pady=(10, 0))
        box = (10, 10, 210, 210)
        self.dial.create_oval(*box, outline=PANEL, width=10)
        self.arc = self.dial.create_arc(*box, start=90, extent=0, style='arc', outline=ACCENT, width=10)
        self.remaining = self.dial.create_text(110, 100, text='--:--', fill=TEXT, font=('Segoe UI Light', 36))
        self.caption = self.dial.create_text(110, 142, text='until stretch', fill=MUTED, font=('Segoe UI', 10))

        self.since_label = tk.Label(main, bg=BG, fg=MUTED, font=('Segoe UI', 9))
        self.since_label.pack(pady=(6, 10))

        panel = tk.Frame(main, bg=PANEL, padx=14, pady=12)
        panel.pack(fill='x')
        tk.Label(panel, text='Remind me every', bg=PANEL, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w')
        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill='x', pady=(6, 0))
        self.minutes_var = tk.StringVar(value=str(self.settings['minutes']))
        self.entry = tk.Entry(row, textvariable=self.minutes_var, width=6, font=('Segoe UI', 12), bg=BG, fg=TEXT,
                              insertbackground=TEXT, relief='flat', highlightthickness=1,
                              highlightbackground=FIELD_BORDER, highlightcolor=ACCENT)
        self.entry.pack(side='left', ipady=3)
        tk.Label(row, text='min', bg=PANEL, fg=MUTED).pack(side='left', padx=8)
        self.save_btn = tk.Button(row, text='Set', command=self.submit_minutes, relief='flat', bd=0, padx=14, pady=4,
                                  bg=ACCENT, fg='#fff', activebackground=ACCENT, activeforeground='#fff',
                                  disabledforeground=MUTED, cursor='hand2')
        self.save_btn.pack(side='right')
        self.error = tk.Label(panel, bg=PANEL, fg=ERROR, font=('Segoe UI', 9), anchor='w')
        self.minutes_var.trace_add('write', lambda *_: self.on_minutes_edit())
        self.entry.bind('<Return>', lambda _e: self.submit_minutes())
        self.entry.bind('<Escape>', lambda _e: self.reset_minutes())

        footer = tk.Frame(main, bg=BG)
        footer.pack(side='bottom', fill='x')
        self.login_var = tk.BooleanVar(value=open_at_login())
        tk.Checkbutton(footer, text='Start with Windows', variable=self.login_var, command=self.toggle_login,
                       bg=BG, fg=MUTED, activebackground=BG, activeforeground=TEXT, selectcolor=PANEL,
                       font=('Segoe UI', 9), bd=0, highlightthickness=0).pack(side='left')
        self.link(footer, 'Quit', self.quit).pack(side='right')
        self.link(footer, 'Restart timer', lambda: self.start_cycle('start')).pack(side='right', padx=10)
        self.pause_btn = self.link(footer, 'Pause', self.toggle_pause)
        self.pause_btn.pack(side='right')

        # Alert overlay: covers the whole window while it's time to stretch.
        self.alert = tk.Frame(root, bg=ALERT_A)
        body = tk.Frame(self.alert, bg=ALERT_A)
        body.place(relx=0.5, rely=0.5, anchor='center')
        self.alert_title = tk.Label(body, text='Time to stretch!', bg=ALERT_A, fg='#1a1a1a',
                                    font=('Segoe UI', 22, 'bold'))
        self.alert_title.pack()
        self.alert_sub = tk.Label(body, bg=ALERT_A, fg='#1a1a1a', font=('Segoe UI', 10))
        self.alert_sub.pack(pady=(0, 24))
        tk.Button(body, text='I stood up and stretched', command=self.confirm_stretch, relief='flat', bd=0,
                  bg='#1a1a1a', fg='#fff', activebackground='#000', activeforeground='#fff',
                  font=('Segoe UI Semibold', 13), padx=22, pady=14, cursor='hand2', takefocus=False).pack()

        if HIDDEN:
            root.iconify()

    @staticmethod
    def link(parent, text, command):
        return tk.Button(parent, text=text, command=command, bg=BG, fg=MUTED, activebackground=BG,
                         activeforeground=TEXT, relief='flat', bd=0, font=('Segoe UI', 9, 'underline'),
                         cursor='hand2', takefocus=False)

    def on_minutes_edit(self):
        self.error.pack_forget()
        self.update_save_button()

    def update_save_button(self):
        text = self.minutes_var.get().strip()
        unchanged = text == '' or text == str(self.settings['minutes'])
        self.save_btn.configure(state='disabled' if unchanged else 'normal', bg=FIELD_BORDER if unchanged else ACCENT)

    def reset_minutes(self):
        self.minutes_var.set(str(self.settings['minutes']))
        self.root.focus_set()

    def submit_minutes(self):
        if self.set_minutes(self.minutes_var.get()):
            self.error.pack_forget()
            self.minutes_var.set(str(self.settings['minutes']))
            self.root.focus_set()
        else:
            self.error.configure(text=f'Enter a whole number between {MIN_MINUTES} and {MAX_MINUTES}.')
            self.error.pack(fill='x', pady=(6, 0))
        self.update_save_button()

    def toggle_login(self):
        set_open_at_login(self.login_var.get())

    def quit(self):
        self.root.destroy()

    # ----- drawing -----

    def render(self):
        status, now = self.status, time.time()
        inactive = status in ('locked', 'paused')
        remaining = max(0.0, self.interval - (now - self.cycle_start))

        if status == 'paused':
            shown, caption, fraction = self.interval, 'paused', 1.0
            since = 'Click Resume to start a new countdown.'
        elif status == 'locked':
            shown, caption, fraction = self.interval, 'paused — screen locked', 1.0
            since = 'The timer restarts when you unlock.'
        else:
            shown, caption = remaining, 'until stretch (fast mode)' if FAST else 'until stretch'
            fraction = remaining / self.interval if self.interval else 0
            since = f'Since {SINCE_LABELS.get(self.since, "started")} at {clock(self.cycle_start)}'

        self.dial.itemconfigure(self.remaining, text=fmt(shown), fill=MUTED if inactive else TEXT)
        self.dial.itemconfigure(self.caption, text=caption)
        # Tk arcs can't draw a full circle, so cap just below 360 degrees.
        self.dial.itemconfigure(self.arc, extent=-min(fraction * 360, 359.99),
                                outline=PAUSED if inactive else ACCENT)
        self.since_label.configure(text=since)
        self.count.configure(text=f'{self.stretches_today()} today')
        self.pause_btn.configure(text='Resume' if status == 'paused' else 'Pause')

        if status == 'alerting':
            over = now - self.alerted_at
            self.alert_sub.configure(text=f'Waiting for {fmt(over)}' if over >= 1
                                     else f'{self.settings["minutes"]} minutes are up')
            self.alert.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            self.alert.place_forget()
        self.update_save_button()


def main():
    try:  # crisp text on high-DPI screens
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        pass
    if not single_instance():
        return
    StretchTimer().root.mainloop()


if __name__ == '__main__':
    main()
