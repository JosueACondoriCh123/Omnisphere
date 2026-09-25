'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createOutputManager } = require('../desktop/agent-b-outputs/manager.cjs');

const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: (value) => Buffer.from(value),
  decryptString: (buffer) => buffer.toString(),
};

test('an OBS probe failure stops the started stream, hides secrets, and permits restart', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'omnistage-output-rollback-'));
  const calls = [];
  let attempts = 0;
  const connectObs = async () => {
    attempts++;
    const failProbe = attempts === 1;
    return {
      request: async (name) => {
        calls.push([attempts, name]);
        if (name === 'GetSceneList') return { scenes: [] };
        if (name === 'GetInputList') return { inputs: [] };
        if (name === 'GetStreamStatus' && failProbe) {
          throw new Error('probe failed: stream-secret / obs-secret');
        }
        if (name === 'GetStreamStatus') return { outputActive: true };
        return {};
      },
      close: () => calls.push([attempts, 'close']),
    };
  };
  try {
    const manager = createOutputManager({ userData: folder, safeStorage, connectObs });
    await manager.configure('1', {
      destination: 'rtmp', lang: 'es', server: 'rtmps://example.com/live',
      stream_key: 'stream-secret', obs_password: 'obs-secret', obs_port: 4455,
    });
    const failed = await manager.start('1');
    assert.equal(failed.state, 'error');
    assert.equal(JSON.stringify(failed).includes('stream-secret'), false);
    assert.equal(JSON.stringify(failed).includes('obs-secret'), false);
    assert.deepEqual(calls.filter(([, name]) => ['StartStream', 'StopStream', 'close'].includes(name)), [
      [1, 'StartStream'], [1, 'StopStream'], [1, 'close'],
    ]);
    assert.equal((await manager.stop('1')).state, 'configured');
    assert.equal((await manager.start('1')).state, 'streaming');
    assert.equal(attempts, 2);
    await manager.close();
  } finally {
    fs.rmSync(folder, { recursive: true, force: true });
  }
});
