# Stretch Timer

A small Python app (standard library only, tkinter) that counts down from when you unlock your
computer and, when the time is up, flashes until you confirm **"I stood up and stretched"**.

No installer or EXE: it runs as a plain Python process, which helps on machines that block
unsigned executables.

## Requirements

Windows with Python 3.8+ (the python.org installer includes tkinter).

## Run

```sh
pythonw python/stretch_timer.pyw          # or double-click the file
python python/stretch_timer.pyw --fast    # test mode: 1 "minute" = 1 second, separate settings
```

## Behaviour

- The countdown starts when the app starts, and **restarts every time you unlock** the
  computer (or wake it from sleep). While the screen is locked the timer is paused.
- When it reaches zero, the app brings its window on top and flashes it (orange/yellow), flashes
  its taskbar button and beeps. It re-raises itself every minute until you click the confirm button.
- The alert does **not** take keyboard focus, so a keypress while typing can't confirm it.
  You have to click the button.
- Confirming starts a new countdown. Locking the screen also clears the alert (you walked away).
- **Pause** stops the timer until you click **Resume**, which starts a fresh countdown.
  Locking and unlocking don't change a manual pause.
- Closing the window minimises it to the taskbar; the timer keeps running. Use **Quit** to exit.
- The interval (1–600 minutes) is saved in `%APPDATA%\Stretch Timer\settings.json`.
- "Start with Windows" adds a login entry that runs the script with `pythonw` in the background.

## Status endpoint

The app serves a read-only status page on `127.0.0.1:3330` (`/health`, JSON; override
with `STRETCH_PORT`) so Server Viewer can show it and start/stop it. Server Viewer entry:
port `3330`, health path `/health`, command `C:\Python312\pythonw.exe stretch_timer.pyw`, working
directory the `python` folder.
