import { useEffect } from "react";

export const FALLBACK_STAGES = [
  { stage_id: "1", name: "Stage 1", session: "1", languages: ["es", "en"] },
];

export async function fetchStages() {
  try {
    const response = await fetch("/api/stages");
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
