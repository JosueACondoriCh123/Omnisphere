import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PublicFooter, PublicHeader } from "../components/PublicChrome.jsx";
import PublicStageCard from "../components/PublicStageCard.jsx";
import { usePublicStages } from "../lib/publicStages.js";
import { useSurfaceClass } from "../lib/stages.js";

export default function Rooms() {
  useSurfaceClass("home");
  const { catalog, status } = usePublicStages();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [lang, setLang] = useState("es");

  useEffect(() => { document.title = "Salas | OmniStage"; }, []);

  const visible = useMemo(() => catalog.filter((stage) => {
    if (filter === "open" && !stage.hasSession) return false;
    const haystack = `${stage.stage_id} ${stage.name} ${stage.session || ""}`.toLocaleLowerCase("es");
    return haystack.includes(query.trim().toLocaleLowerCase("es"));
  }), [catalog, filter, query]);

  return <main className="home-root public-page rooms-page" id="top">
    <PublicHeader />
    <div className="public-page-content">
      <header className="public-page-intro">
        <p className="section-index">NERDEARLA 2026 / ESCENARIOS</p>
        <h1>Encontrá tu <em>sala.</em></h1>
        <p>Explorá los diez escenarios. Cuando el equipo abra una sesión, vas a ver el nombre de la charla aquí.</p>
      </header>

      <section className="rooms-controls" aria-label="Buscar y filtrar salas">
        <label className="rooms-search">Buscar sala o charla
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ej.: Sala 3" />
        </label>
        <div className="rooms-filters" role="group" aria-label="Filtrar salas">
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>Todas</button>
          <button type="button" aria-pressed={filter === "open"} onClick={() => setFilter("open")}>Con sesión</button>
        </div>
        <label className="rooms-language">Idioma inicial
          <select value={lang} onChange={(event) => setLang(event.target.value)}><option value="es">Español</option><option value="en">English</option></select>
        </label>
      </section>

      <div className="rooms-result-line"><span role="status">{visible.length} {visible.length === 1 ? "sala" : "salas"}</span><span>{status === "ready" ? "Estado actualizado cada 5 segundos" : status === "loading" ? "Consultando el estado…" : "Sin conexión con el estado en vivo"}</span></div>
      {status === "unavailable" && <div className="rooms-notice" role="status">Todavía podés abrir cualquier sala o <Link to="/app?mock=1">probar una muestra</Link>. El estado de las sesiones aparecerá cuando se conecte el servicio público.</div>}
      {visible.length ? <div className="public-stage-grid rooms-grid">{visible.map((stage) => <PublicStageCard key={stage.stage_id} stage={stage} status={status} lang={lang} />)}</div>
        : <div className="rooms-empty"><h2>No encontramos esa sala</h2><p>Probá con otro nombre o volvé a ver todas.</p><button type="button" onClick={() => { setQuery(""); setFilter("all"); }}>Mostrar todas</button></div>}

      <section className="rooms-help"><div><p className="section-index">¿PRIMERA VEZ?</p><h2>Leé a tu manera.</h2><p>Dentro de cada sala podés cambiar idioma, tamaño de letra y contraste.</p></div><Link to="/guia">Ver la guía ↗</Link></section>
    </div>
    <PublicFooter />
  </main>;
}
