'use strict';

const { createHash, randomUUID } = require('node:crypto');

function sha(value) { return createHash('sha256').update(value).digest('base64'); }

class ObsClient {
  constructor(socket) {
    this.socket = socket;
    this.pending = new Map();
    this.closeHandlers = [];
    socket.addEventListener('message', (event) => {
      let packet;
      try { packet = JSON.parse(String(event.data)); } catch { return; }
      if (packet.op !== 7) return;
      const slot = this.pending.get(packet.d?.requestId);
      if (!slot) return;
      this.pending.delete(packet.d.requestId);
      clearTimeout(slot.timer);
      if (packet.d.requestStatus?.result) slot.resolve(packet.d.responseData || {});
      else slot.reject(new Error(`OBS rechazó ${packet.d.requestType || 'la solicitud'} (${packet.d.requestStatus?.code || 'error'}).`));
    });
    socket.addEventListener('close', () => {
      for (const handler of this.closeHandlers) handler();
      for (const slot of this.pending.values()) { clearTimeout(slot.timer); slot.reject(new Error('Se perdió la conexión con OBS.')); }
      this.pending.clear();
    });
  }

  static async connect(port, password, Socket = WebSocket) {
    const socket = new Socket(`ws://127.0.0.1:${port}`);
    const ready = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('OBS no respondió por WebSocket.')), 5000);
      let identified = false;
      socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('No se pudo conectar con OBS.')); });
      socket.addEventListener('message', (event) => {
        let packet;
        try { packet = JSON.parse(String(event.data)); } catch { return; }
        if (packet.op === 0) {
          const auth = packet.d?.authentication;
          if (auth && !password) { clearTimeout(timer); reject(new Error('OBS requiere contraseña WebSocket.')); return; }
          const identification = { rpcVersion: 1 };
          if (auth) identification.authentication = sha(sha(password + auth.salt) + auth.challenge);
          socket.send(JSON.stringify({ op: 1, d: identification }));
        } else if (packet.op === 2 && !identified) {
          identified = true;
          clearTimeout(timer);
          resolve(new ObsClient(socket));
        }
      });
      socket.addEventListener('close', () => { clearTimeout(timer); if (!identified) reject(new Error('OBS cerró la conexión.')); });
    });
    try { return await ready; } catch (error) { socket.close(); throw error; }
  }

  request(requestType, requestData = {}) {
    const requestId = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error(`OBS tardó demasiado en responder a ${requestType}.`));
      }, 6000);
      this.pending.set(requestId, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ op: 6, d: { requestType, requestId, requestData } }));
    });
  }

  close() { this.socket.close(); }
  onClose(handler) { this.closeHandlers.push(handler); }
}

module.exports = { ObsClient };
