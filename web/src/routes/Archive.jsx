import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { archiveFilename, downloadText, toSrt, toTxt, toVtt } from "../lib/export.js";
import { useSurfaceClass } from "../lib/stages.js";
import { useCaptions } from "../lib/useCaptions.js";
import OperatorSidebar from "../components/OperatorSidebar.jsx";

export default function Archive() {
  useSurfaceClass("archive");
  const { stageId = "1", sessionId } = useParams();
  const [params, setParams] = useSearchParams();
  const lang = params.get("lang") === "en" ? "en" : "es";
  const session = params.get("session") || "1";
  const mock = params.get("mock") === "1";
  const { committed, status } = useCaptions({ stageId, lang, mock, enabled: mock });
  const [saved, setSaved] = useState([]);
  const [details, setDetails] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (mock || !sessionId) return undefined;
    let live = true;
    fetch(`/api/operator/sessions/${encodeURIComponent(sessionId)}/captions?lang=${lang}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 401 ? "Iniciá sesión de operador para consultar el archivo." : `HTTP ${response.status}`);
        return response.json();
      })
      .then((body) => { if (live) { setSaved(body.captions); setDetails(body.session); setError(""); } })
      .catch((exc) => { if (live) setError(exc.message); });
    return () => { live = false; };
  }, [mock, sessionId, lang]);
  const items = mock ? committed : saved;
  const preview = useMemo(() => toSrt(items, lang), [items, lang]);

  function save(ext, factory, mime) {
    downloadText(archiveFilename(stageId, session, ext), factory(items, lang), mime);
  }

  return (
    <div className="archive-root redesigned-archive operator-shell">
      <OperatorSidebar />
      <main className="operator-content archive-content">
      <header className="archive-header">
        <span className="operator-header-eyebrow">ARCHIVO / OPERACIÓN</span>
        <Link to="/operator">← Volver al panel</Link>
      </header>
      <div className="archive-title">
        <p className="section-index">ARCHIVO / SESIÓN</p>
        <h1>{details?.title || `Archivo sala ${stageId}`}</h1>
        <p>
          Sala {details?.stage_id || stageId} · {items.length} cláusulas · {mock ? status : details?.ended_at ? "Finalizada" : "En curso"}
        </p>
      </div>
      {error && <p className="surface-error" role="alert">{error} <Link to="/operator">Ir al acceso</Link></p>}
      <label className="archive-language">Idioma <select value={lang} onChange={(event) => {
        const next = new URLSearchParams(params); next.set("lang", event.target.value);
        setParams(next);
      }}><option value="es">Español</option><option value="en">English</option></select></label>
      <div className="archive-actions">
        {[["srt", toSrt, "application/x-subrip"], ["vtt", toVtt, "text/vtt"], ["txt", toTxt, "text/plain"]].map(([ext, factory, mime]) => mock ?
          <button className={`glass-button ${ext === "srt" ? "glass-button-primary" : "glass-button-secondary"}`} key={ext} type="button" onClick={() => save(ext, factory, mime)}>Descargar {ext.toUpperCase()}</button> :
          <a className={`glass-button ${ext === "srt" ? "glass-button-primary" : "glass-button-secondary"}`} key={ext} href={`/api/operator/sessions/${encodeURIComponent(sessionId)}/export?lang=${lang}&format=${ext}`}>Descargar {ext.toUpperCase()}</a>
        )}
      </div>
      <pre className="srt-preview">{preview || "Todavía no hay cláusulas committed."}</pre>
      </main>
    </div>
  );
}
