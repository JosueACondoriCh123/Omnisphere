import { useEffect, useRef, useState } from "react";
import { Reconciler } from "./reconciler.js";
import { playMockCaptions } from "./mockCaptions.js";
import { hasLiveBackend, publicSocketUrl } from "./publicBackend.js";

export function captionsSocketUrl(stageId, lang) {
  return publicSocketUrl(`/ws/stages/${encodeURIComponent(stageId)}/${encodeURIComponent(lang)}`);
}

const BACKOFF_MS = [500, 1000, 2000, 5000];

export function applyEnvelope(reconciler, message) {
  if (!message || typeof message !== "object") return false;
  if (message.type === "snapshot" && Array.isArray(message.captions)) {
    reconciler.setSession(message.session_id);
    for (const caption of message.captions) {
      reconciler.apply({ ...caption, state: caption.state || "committed" });
    }
    return true;
  }
  if (message.type === "caption") {
    reconciler.apply(message);
    return true;
  }
  if (message.type === "stream_started") {
    reconciler.setSession(message.session_id);
    return true;
  }
  if (message.type === "stream_stopped") {
    reconciler.dropDrafts();
    return true;
  }
  return false;
}

export function createCaptionClient({
  stageId,
  lang,
  createSocket = (url) => new WebSocket(url),
  delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  onChange,
} = {}) {
  const reconciler = new Reconciler(stageId);
  let stopped = false;
  let attempt = 0;
  let socket = null;
  let status = "connecting";

  function emit() {
    onChange?.({
      segments: reconciler.view(),
      status,
      error: status === "error" ? "socket closed" : null,
    });
  }

  function handleMessage(event) {
    try {
      const raw = event.data;
      const message = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (message?.type === "stream_stopped") {
        reconciler.dropDrafts();
        status = "stopped";
        emit();
        return;
      }
      if (!applyEnvelope(reconciler, message)) return;
      attempt = 0;
      status = "open";
      emit();
    } catch {
      status = "error";
      emit();
    }
  }

  async function connect() {
    if (stopped) return;
    status = attempt === 0 ? "connecting" : "reconnecting";
    emit();
    let sock;
    try {
      sock = createSocket(captionsSocketUrl(stageId, lang));
    } catch {
      status = "error";
      emit();
      const ms = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
      attempt += 1;
      await delay(ms);
      if (!stopped) connect();
      return;
    }
    socket = sock;
    sock.onopen = () => {
      status = "open";
      emit();
    };
    sock.onmessage = handleMessage;
    sock.onerror = () => {
      status = "error";
      emit();
    };
    sock.onclose = async () => {
      reconciler.dropDrafts();
      emit();
      if (stopped) return;
      const ms = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
      attempt += 1;
      status = "reconnecting";
      emit();
      await delay(ms);
      if (!stopped && socket === sock) connect();
    };
  }

  connect();

  return {
    view: () => reconciler.view(),
    committed: () => reconciler.committed(),
    status: () => status,
    stop() {
      stopped = true;
      socket?.close?.();
    },
  };
}

export function useCaptions({
  stageId = "1",
  lang = "es",
  mock = false,
  enabled = true,
} = {}) {
  const [segments, setSegments] = useState([]);
  const [status, setStatus] = useState(mock ? "mock" : hasLiveBackend ? "connecting" : "unavailable");
  const [error, setError] = useState(null);
  const clientRef = useRef(null);

  useEffect(() => {
    if (!enabled) return undefined;
    if (mock) {
      const reconciler = new Reconciler(stageId);
      const stop = playMockCaptions(stageId, lang, (message) => {
        applyEnvelope(reconciler, message);
        setSegments(reconciler.view());
        setStatus("mock");
        setError(null);
      });
      return stop;
    }

    if (!hasLiveBackend) return undefined;

    const client = createCaptionClient({
      stageId,
      lang,
      onChange: (next) => {
        setSegments(next.segments);
        setStatus(next.status);
        setError(next.error);
      },
    });
    clientRef.current = client;
    return () => {
      client.stop();
      clientRef.current = null;
    };
  }, [stageId, lang, mock, enabled]);

  return { segments, status, error, committed: segments.filter((s) => s.state === "committed") };
}
