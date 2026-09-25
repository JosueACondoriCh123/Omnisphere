import { useEffect, useState } from "react";
import { fetchStages, FALLBACK_STAGES } from "./stages.js";

export function useStageOptions({ enabled = true } = {}) {
  const [stages, setStages] = useState(FALLBACK_STAGES);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    const load = () => fetchStages().then((items) => {
      if (alive && items.length) setStages(items);
    });
    load();
    const timer = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [enabled]);
  return stages;
}
