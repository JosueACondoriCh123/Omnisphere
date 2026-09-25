function pad(value, width) {
  return String(value).padStart(width, "0");
}

export function formatSrtTime(ms) {
  const safe = Math.max(ms, 0);
  const h = Math.floor(safe / 3_600_000);
  const remH = safe % 3_600_000;
  const m = Math.floor(remH / 60_000);
  const remM = remH % 60_000;
  const s = Math.floor(remM / 1000);
  const milli = remM % 1000;
  return `${pad(h, 2)}:${pad(m, 2)}:${pad(s, 2)},${pad(milli, 3)}`;
}

function cueText(seg, lang) {
  if (lang && seg[lang]) return String(seg[lang]).trim();
  return String(seg.text ?? seg.original ?? "").trim();
}

export function toSrt(segments, lang = "es") {
  const lines = [];
  let index = 1;
  for (const seg of segments) {
    if (seg.state && seg.state !== "committed") continue;
    const text = cueText(seg, lang);
    if (!text) continue;
    lines.push(
      `${index}\n${formatSrtTime(seg.t0_ms)} --> ${formatSrtTime(seg.t1_ms)}\n${text}\n`,
    );
    index += 1;
  }
  return lines.join("\n");
}

export function toVtt(segments, lang = "es") {
  const body = toSrt(segments, lang).replaceAll(",", ".");
  return `WEBVTT\n\n${body}`;
}

export function toTxt(segments, lang = "es") {
  return segments
    .filter((seg) => !seg.state || seg.state === "committed")
    .map((seg) => cueText(seg, lang))
    .filter(Boolean)
    .join("\n");
}

export function archiveFilename(stageId, session = 1, ext = "srt") {
  const stage = String(stageId).replace(/^stage-?/i, "");
  const sesion = String(session).replace(/\D+/g, "") || "1";
  return `nerdearla_2026_stage${stage}_sesion${sesion}.${ext}`;
}

export function downloadText(filename, contents, mime = "text/plain") {
  const blob = new Blob([contents], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
