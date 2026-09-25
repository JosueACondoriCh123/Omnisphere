import { useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { archiveFilename, downloadText, toSrt, toTxt, toVtt } from "../lib/export.js";
import { useSurfaceClass } from "../lib/stages.js";
import { useCaptions } from "../lib/useCaptions.js";

export default function Archive() {
  useSurfaceClass("archive");
  const { stageId = "1" } = useParams();
  const [params] = useSearchParams();
  const lang = params.get("lang") === "en" ? "en" : "es";
  const session = params.get("session") || "1";
  const mock = params.get("mock") === "1";
  const { committed, status } = useCaptions({ stageId, lang, mock });
  const preview = useMemo(() => toSrt(committed, lang), [committed, lang]);

  function save(ext, factory, mime) {
    downloadText(archiveFilename(stageId, session, ext), factory(committed, lang), mime);
  }

  return (
    <main className="archive-root">
      <header>
        <h1>Archivo sala {stageId}</h1>
        <p>
          {archiveFilename(stageId, session, "srt")} · {committed.length} cláusulas · {status}
        </p>
      </header>
      <div className="archive-actions">
        <button type="button" onClick={() => save("srt", toSrt, "application/x-subrip")}>
          Descargar SRT
        </button>
        <button type="button" onClick={() => save("vtt", toVtt, "text/vtt")}>
          Descargar VTT
        </button>
        <button type="button" onClick={() => save("txt", toTxt, "text/plain")}>
          Descargar TXT
        </button>
      </div>
      <pre className="srt-preview">{preview || "Todavía no hay cláusulas committed."}</pre>
    </main>
  );
}
