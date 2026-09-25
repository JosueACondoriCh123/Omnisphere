// Same order as contracts/events.py HOPS. Do not invent hops.
export const HOPS = [
  "ingest",
  "vad",
  "tier1",
  "tier2a",
  "tier2b",
  "reconciler",
  "fanout",
  "render",
];

export function hopColumns() {
  return [...HOPS];
}

/** Delta ms vs previous present hop. Missing hops stay "—". */
export function hopDeltas(traces = []) {
  const byHop = {};
  for (const stamp of traces) {
    if (HOPS.includes(stamp.hop) && Number.isFinite(stamp.t_wall_ms)) {
      byHop[stamp.hop] = stamp.t_wall_ms;
    }
  }
  const deltas = {};
  let previous = null;
  for (const hop of HOPS) {
    if (byHop[hop] == null) {
      deltas[hop] = "—";
      continue;
    }
    if (previous == null) {
      deltas[hop] = "—";
    } else {
      deltas[hop] = byHop[hop] - previous;
    }
    previous = byHop[hop];
  }
  return deltas;
}

export function hopsFromApi(hopLatencies = []) {
  const deltas = Object.fromEntries(HOPS.map((hop) => [hop, "—"]));
  for (let i = 0; i < HOPS.length - 1; i += 1) {
    const fromHop = HOPS[i];
    const toHop = HOPS[i + 1];
    const found = hopLatencies.find(
      (item) => item.from_hop === fromHop && item.to_hop === toHop,
    );
    if (found && Number.isFinite(found.p50_ms)) {
      deltas[toHop] = found.p50_ms;
    }
  }
  return deltas;
}

export const ALARM_LABELS = {
  audio_signal_down: "sin audio",
  latency_over_1500ms: "latencia > 1.5 s",
  transcriber_socket_down: "Gemini/transcriber socket down",
};
