import { useEffect, useState } from "react";
import { ALARM_LABELS, HOPS, hopDeltas, hopsFromApi } from "../lib/hops.js";
import { FALLBACK_STAGES, useSurfaceClass } from "../lib/stages.js";

const DEMO_TRACES = [
  { hop: "ingest", t_wall_ms: 1000 },
  { hop: "vad", t_wall_ms: 1040 },
  { hop: "tier1", t_wall_ms: 1680 },
  { hop: "fanout", t_wall_ms: 1900 },
];

// Fallback when GET /api/metrics/stages is empty or unreachable: keep the hop matrix
// laid out (8 HOPS columns) so the board does not collapse during setup.
const DEMO_ROWS = FALLBACK_STAGES.map((stage, index) => ({
  stage_id: stage.stage_id,
  stream_up: index === 0,
  audio_up: false,
  worker_state: "stopped",
  transcriber_up: false,
  hop_latencies: [],
  traces: index === 0 ? DEMO_TRACES : [],
  alarms:
    index === 0
      ? [{ code: "audio_signal_down", severity: "critical" }]
      : [],
}));

export default function Admin() {
  useSurfaceClass("admin");
  const [rows, setRows] = useState(DEMO_ROWS);
  const [usingFallback, setUsingFallback] = useState(true);

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const response = await fetch("/api/metrics/stages");
        if (!response.ok) throw new Error("http");
        const data = await response.json();
        if (!alive) return;
        if (data.items?.length) {
          setRows(data.items);
          setUsingFallback(false);
        }
      } catch {
        if (alive) setUsingFallback(true);
      }
    }
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <main className="admin-root">
      <header>
        <h1>Salas</h1>
        {usingFallback ? <p className="fallback-note">matriz de demo — /api/stages sin datos</p> : null}
      </header>
      <div className="board-wrap">
        <table className="board">
          <thead>
            <tr>
              <th>sala</th>
              <th>stream</th>
              <th>audio</th>
              <th>worker</th>
              <th>Gemini</th>
              {HOPS.map((hop) => (
                <th key={hop} data-hop={hop}>
                  {hop}
                </th>
              ))}
              <th>alarmas</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const deltas = row.traces?.length
                ? hopDeltas(row.traces)
                : hopsFromApi(row.hop_latencies ?? []);
              return (
                <tr key={row.stage_id} data-stage={row.stage_id}>
                  <td>{row.stage_id}</td>
                  <td data-on={row.stream_up ? "1" : "0"}>{row.stream_up ? "up" : "down"}</td>
                  <td data-on={row.audio_up ? "1" : "0"}>{row.audio_up ? "up" : "down"}</td>
                  <td>{row.worker_state ?? "stopped"}</td>
                  <td
                    data-on={row.transcriber_up ? "1" : "0"}
                    title={row.transcriber_error ?? ""}
                  >
                    {row.transcriber_up ? "up" : "down"}
                  </td>
                  {HOPS.map((hop) => (
                    <td key={hop} data-hop={hop} className="hop-cell">
                      {deltas[hop] === "—" ? "—" : `${deltas[hop]}`}
                    </td>
                  ))}
                  <td>
                    <div className="alarms">
                      {(row.alarms ?? []).map((alarm) => (
                        <span
                          key={alarm.code}
                          className="alarm"
                          data-alarm={alarm.code}
                          data-testid="alarm"
                        >
                          {ALARM_LABELS[alarm.code] ?? alarm.code}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </main>
  );
}
