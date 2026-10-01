const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('stretch', {
  onState: (cb) => ipcRenderer.on('state', (_e, state) => cb(state)),
  confirm: () => ipcRenderer.send('confirm-stretch'),
  togglePause: () => ipcRenderer.send('toggle-pause'),
  restart: () => ipcRenderer.send('restart'),
  setMinutes: (minutes) => ipcRenderer.invoke('set-minutes', minutes),
  setOpenAtLogin: (on) => ipcRenderer.send('set-open-at-login', on),
});
