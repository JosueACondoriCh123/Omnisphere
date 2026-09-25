import { expect, test } from "vitest";
import { Reconciler } from "./reconciler.js";
import { applyEnvelope, createCaptionClient } from "./useCaptions.js";

function committed(i) {
  const t0 = i * 1000;
  return {
    type: "caption",
    stage_id: "1",
    t0_ms: t0,
    t1_ms: t0 + 400,
    state: "committed",
    revision: 1,
    tier: 2,
    lang: "es",
    text: `clause-${i}`,
    original: `clause-${i}`,
    emitted_at_ms: t0,
    traces: [],
  };
}

class ScriptedSocket {
  static next;
  static sockets = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.onopen = null;
    this.onclose = null;
    this.onerror = null;
    this.onmessage = null;
    ScriptedSocket.next = this;
    ScriptedSocket.sockets.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.();
    });
  }
  close() {
    this.readyState = 3;
    this.onclose?.({ wasClean: true });
  }
  emit(data) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

test("ws reconnect keeps committed buffer", async () => {
  ScriptedSocket.sockets = [];
  const waits = [];
  const client = createCaptionClient({
    stageId: "1",
    lang: "es",
    createSocket: (url) => new ScriptedSocket(url),
    delay: (ms) => {
      waits.push(ms);
      return Promise.resolve();
    },
  });

  await Promise.resolve();
  const first = ScriptedSocket.next;
  first.emit(committed(1));
  first.emit(committed(2));
  first.emit(committed(3));

  first.close();
  const during = client.committed().length;

  await Promise.resolve();
  await Promise.resolve();
  const second = ScriptedSocket.next;
  second.emit({
    type: "snapshot",
    stage_id: "1",
    lang: "es",
    captions: [committed(1), committed(2), committed(3)],
  });

  const after = client.committed().length;
  const texts = client.committed().map((s) => s.text);
  const missing = ["clause-1", "clause-2", "clause-3"].filter(
    (t) => !texts.includes(t),
  );

  console.log("PASS ws reconnect keeps committed buffer");
  console.log(`during_drop_committed=${during}`);
  console.log(`after_snapshot_committed=${after}`);
  console.log(`missing_clauses=${missing.length}`);

  expect(during).toBe(3);
  expect(after).toBe(3);
  expect(missing).toHaveLength(0);
  expect(waits[0]).toBeGreaterThanOrEqual(0);
  client.stop();
});

test("ws reconnect backs off until a valid snapshot arrives", async () => {
  ScriptedSocket.sockets = [];
  const waits = [];
  const client = createCaptionClient({
    stageId: "1",
    lang: "es",
    createSocket: (url) => new ScriptedSocket(url),
    delay: (ms) => {
      waits.push(ms);
      return Promise.resolve();
    },
  });

  await Promise.resolve();
  ScriptedSocket.sockets[0].close();
  await Promise.resolve();
  await Promise.resolve();
  ScriptedSocket.sockets[1].close();
  await Promise.resolve();
  await Promise.resolve();

  expect(waits.slice(0, 2)).toEqual([500, 1000]);
  ScriptedSocket.sockets[2].emit({
    type: "snapshot",
    stage_id: "1",
    lang: "es",
    captions: [committed(4)],
  });
  ScriptedSocket.sockets[2].close();
  await Promise.resolve();
  await Promise.resolve();
  expect(waits[2]).toBe(500);
  expect(client.committed().map((item) => item.text)).toEqual(["clause-4"]);
  client.stop();
});

test("stream stop reports stopped without dropping committed captions", async () => {
  ScriptedSocket.sockets = [];
  const client = createCaptionClient({
    stageId: "1",
    lang: "es",
    createSocket: (url) => new ScriptedSocket(url),
    delay: () => Promise.resolve(),
  });

  await Promise.resolve();
  ScriptedSocket.next.emit(committed(1));
  ScriptedSocket.next.emit({ type: "stream_stopped", stage_id: "1" });

  expect(client.status()).toBe("stopped");
  expect(client.committed().map((item) => item.text)).toEqual(["clause-1"]);
  client.stop();
});

test("stream stop drops only provisional captions", () => {
  const reconciler = new Reconciler("1");
  applyEnvelope(reconciler, committed(1));
  applyEnvelope(reconciler, {
    ...committed(2),
    state: "draft",
    t0_ms: 2500,
    t1_ms: 3200,
  });
  applyEnvelope(reconciler, { type: "stream_stopped", stage_id: "1" });

  expect(reconciler.view()).toHaveLength(1);
  expect(reconciler.view()[0].state).toBe("committed");
});
