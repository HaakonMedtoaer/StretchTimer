# Stretch Timer

A small Electron app that counts down from when you unlock your computer and,
when the time is up, flashes until you confirm **"I stood up and stretched"**.

## Behaviour

- The countdown starts when the app starts, and **restarts every time you unlock** the
  computer (or wake it from sleep). While the screen is locked the timer is paused.
- When it reaches zero, the app:
  - shows a Windows notification,
  - brings the window on top and flashes it (the window alternates orange/yellow, and its taskbar button flashes),
  - re-raises itself every minute until you click the confirm button.
- The alert does **not** take keyboard focus, so a keypress while typing can't confirm it.
  You have to click the button.
- Confirming starts a new countdown. Locking the screen also clears the alert (you walked away).
- **Pause** (button or tray menu) stops the timer until you click **Resume**, which starts a fresh countdown. Locking and unlocking don't change a manual pause.
- Closing the window hides it to the system tray; the timer keeps running. Quit from the tray menu.
  The tray icon is green while counting, grey while locked and orange when it's time to stretch.
- The interval (1–600 minutes) is saved in `%APPDATA%\Stretch Timer\settings.json`.
- "Start with Windows" launches the app hidden in the tray at login.

## Development

```sh
npm install
npm start            # run the app
npm run start:fast   # test mode: 1 "minute" = 1 second, separate settings
```

npm 11 blocks install scripts unless they are allowed. Electron's download script is
allowed in `package.json` (`allowScripts`). If `node_modules/electron/dist` is still
missing, run `node node_modules/electron/install.js`.

## Build an installer

```sh
npm run dist         # -> dist/Stretch Timer Setup 1.0.0.exe (per-user, one-click)
npm run icon         # regenerate build/icon.png
```

Enable "Start with Windows" from the installed app rather than from `npm start`.
Otherwise the login entry points at the dev copy.

## Python edition (no EXE)

`python/stretch_timer.pyw` is a standard-library-only port (tkinter) for machines that
block unsigned EXEs. It has the same behaviour and reads the same `settings.json`.

```sh
pythonw python/stretch_timer.pyw          # or double-click the file
python python/stretch_timer.pyw --fast    # test mode
```

Differences from the Electron version: no tray icon (closing the window minimises it to the
taskbar; use **Quit** to exit), and the alert is the on-top flashing window, taskbar flash and a
beep rather than a Windows toast.

The Python edition also serves a read-only status page on `127.0.0.1:3330` (`/health`, JSON; override
with `STRETCH_PORT`) so Server Viewer can show it and start/stop it. Server Viewer entry:
port `3330`, health path `/health`, command `C:\Python312\pythonw.exe stretch_timer.pyw`, working
directory the `python` folder.
