import { useEffect, useState } from "react";
import { fetchStages, FALLBACK_STAGES } from "./stages.js";

export function useStageOptions({ enabled = true } = {}) {
  const [stages, setStages] = useState(FALLBACK_STAGES);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    fetchStages().then((items) => {
      if (alive && items.length) setStages(items);
    });
    return () => {
      alive = false;
    };
  }, [enabled]);
  return stages;
}
