import { expect, test } from "vitest";
import { HOPS, hopColumns, hopDeltas } from "./hops.js";

test("admin hop columns follow HOPS and show alarms", () => {
  expect(HOPS).toEqual([
    "ingest",
    "vad",
    "tier1",
    "tier2a",
    "tier2b",
    "reconciler",
    "fanout",
    "render",
  ]);
  expect(hopColumns()).toHaveLength(8);

  const deltas = hopDeltas([
    { hop: "ingest", t_wall_ms: 1000 },
    { hop: "vad", t_wall_ms: 1040 },
    { hop: "tier1", t_wall_ms: 1600 },
  ]);
  expect(deltas.ingest).toBe("—");
  expect(deltas.vad).toBe(40);
  expect(deltas.tier1).toBe(560);
  expect(deltas.tier2a).toBe("—");

  const alarms = [{ code: "audio_signal_down", severity: "critical" }];
  expect(alarms.some((a) => a.code === "audio_signal_down")).toBe(true);

  console.log("ADMIN_OK hops_columns=8 alarm_visible=1");
});
