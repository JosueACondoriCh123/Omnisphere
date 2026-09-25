import { useEffect } from "react";
import { hasLiveBackend, publicApiUrl } from "./publicBackend.js";

export const FALLBACK_STAGES = Array.from({ length: 10 }, (_, index) => ({
  stage_id: String(index + 1), name: `Sala ${index + 1}`, session: "",
  languages: ["es", "en"],
}));

export async function fetchStages() {
  if (!hasLiveBackend) return FALLBACK_STAGES;
  try {
    const response = await fetch(publicApiUrl("/api/stages"));
    if (!response.ok) throw new Error("stages http");
    const data = await response.json();
    const items = data.items ?? [];
    if (items.length) return items;
  } catch {
    /* /api/stages is empty until a room is live; local fallback keeps selectors usable. */
  }
  return FALLBACK_STAGES;
}

export function useSurfaceClass(name) {
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.surface = name;
    document.body.dataset.surface = name;
    return () => {
      delete root.dataset.surface;
      delete document.body.dataset.surface;
    };
  }, [name]);
}
