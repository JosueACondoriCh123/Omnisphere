const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('omniDesktop', Object.freeze({
  status: () => ipcRenderer.invoke('omni:status'),
  listMicrophones: () => ipcRenderer.invoke('omni:microphones'),
  startFile: (stageId) => ipcRenderer.invoke('omni:start-file', stageId),
  startMicrophone: (stageId, name) => ipcRenderer.invoke('omni:start-microphone', stageId, name),
  stopSource: (stageId) => ipcRenderer.invoke('omni:stop-source', stageId),
  cloudKeyStatus: () => ipcRenderer.invoke('omni:cloud-key-status'),
  saveApiKey: (key) => ipcRenderer.invoke('omni:cloud-key-save', key),
  removeApiKey: () => ipcRenderer.invoke('omni:cloud-key-remove'),
  outputStatus: () => ipcRenderer.invoke('omni:outputs-status'),
  configureOutput: (stageId, config) => ipcRenderer.invoke('omni:outputs-configure', stageId, config),
  startOutput: (stageId) => ipcRenderer.invoke('omni:outputs-start', stageId),
  stopOutput: (stageId) => ipcRenderer.invoke('omni:outputs-stop', stageId),
  openOutput: (stageId) => ipcRenderer.invoke('omni:outputs-open-share', stageId),
  importModels: () => ipcRenderer.invoke('omni:import-models'),
  setupStatus: () => ipcRenderer.invoke('omni:setup-status'),
  downloadModels: () => ipcRenderer.invoke('omni:download-models'),
  cancelModelDownload: () => ipcRenderer.invoke('omni:cancel-model-download'),
  startLocalModels: () => ipcRenderer.invoke('omni:start-local-models'),
  testLocalModel: (text, target) => ipcRenderer.invoke('omni:test-local-model', text, target),
  openNetworkSettings: () => ipcRenderer.invoke('omni:open-network-settings'),
  onModelProgress: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('omni:models-progress', listener);
    return () => ipcRenderer.removeListener('omni:models-progress', listener);
  },
}));

contextBridge.exposeInMainWorld('omniSplash', Object.freeze({
  retry: () => ipcRenderer.invoke('omni:retry-startup'),
  onState: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('omni:startup-state', listener);
    return () => ipcRenderer.removeListener('omni:startup-state', listener);
  },
}));
