import { expect, test } from "vitest";
import { archiveFilename, toSrt, toTxt, toVtt } from "./export.js";

test("export srt timestamps match to_srt", () => {
  const segments = [
    {
      t0_ms: 842300,
      t1_ms: 843100,
      state: "committed",
      text: "Hola",
    },
    {
      t0_ms: 100,
      t1_ms: 200,
      state: "draft",
      text: "ignored",
    },
  ];
  const srt = toSrt(segments, "es");
  const name = archiveFilename("1", 3, "srt");
  const cue = "00:14:02,300 --> 00:14:03,100";

  console.log("PASS export srt timestamps match to_srt");
  console.log(`sample=${name}`);
  console.log(`cue=${cue}`);

  expect(name).toBe("nerdearla_2026_stage1_sesion3.srt");
  expect(srt).toContain(cue);
  expect(srt).toContain("Hola");
  expect(srt).not.toContain("ignored");
  expect(toVtt(segments, "es")).toMatch(/^WEBVTT\n\n/);
  expect(toVtt(segments, "es")).toContain("00:14:02.300 --> 00:14:03.100");
  expect(toTxt(segments, "es").trim()).toBe("Hola");
});
