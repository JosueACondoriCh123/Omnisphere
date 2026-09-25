import { useEffect, useMemo, useState } from "react";
import { hasLiveBackend, publicApiUrl } from "./publicBackend.js";
import { FALLBACK_STAGES } from "./stages.js";

export function buildStageCatalog(items = []) {
  const byId = new Map(
    items
      .filter((stage) => /^(?:[1-9]|10)$/.test(String(stage?.stage_id)))
      .map((stage) => [String(stage.stage_id), stage]),
  );
  return FALLBACK_STAGES.map((fallback) => {
    const current = byId.get(fallback.stage_id);
    return {
      ...fallback,
      ...current,
      stage_id: fallback.stage_id,
      hasSession: Boolean(current?.session_id || current?.active_session_id || current?.session),
    };
  });
}

export function publicStageStatus(stage, connectionStatus) {
  if (connectionStatus === "loading") return "Consultando estado";
  if (connectionStatus !== "ready") return "Estado no disponible";
  if (stage.audio_up && stage.provider_ready) return "Subtítulos activos";
  return stage.hasSession ? "Sesión abierta" : "En espera";
}

export function usePublicStages() {
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState(hasLiveBackend ? "loading" : "unavailable");
  const [updatedAt, setUpdatedAt] = useState(null);

  useEffect(() => {
    if (!hasLiveBackend) return undefined;
    let alive = true;
    const load = async () => {
      try {
        const response = await fetch(publicApiUrl("/api/stages"), { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!Array.isArray(body.items)) throw new Error("Respuesta de salas inválida");
        if (alive) {
          setItems(body.items);
          setStatus("ready");
          setUpdatedAt(new Date());
        }
      } catch {
        if (alive) {
          setItems([]);
          setStatus("unavailable");
        }
      }
    };
    load();
    const timer = setInterval(load, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const catalog = useMemo(() => buildStageCatalog(items), [items]);
  return { items, catalog, status, updatedAt };
}
