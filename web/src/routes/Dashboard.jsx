import { useEffect } from "react";
import { Link } from "react-router-dom";
import { PublicFooter, PublicHeader } from "../components/PublicChrome.jsx";
import PublicStageCard from "../components/PublicStageCard.jsx";
import { usePublicStages } from "../lib/publicStages.js";
import { useSurfaceClass } from "../lib/stages.js";

export default function Dashboard() {
  useSurfaceClass("home");
  const { catalog, status, updatedAt } = usePublicStages();
  const opened = catalog.filter((stage) => stage.hasSession);
  const featured = (opened.length ? opened : catalog).slice(0, 3);

  useEffect(() => { document.title = "Dashboard de salas | OmniStage"; }, []);

  return <main className="home-root public-page dashboard-page" id="top">
    <PublicHeader />
    <div className="public-page-content">
      <section className="dashboard-hero" aria-labelledby="dashboard-title">
        <div>
          <p className="section-index">NERDEARLA 2026 / VISTA GENERAL</p>
          <h1 id="dashboard-title">Todo el evento,<br /><em>de un vistazo.</em></h1>
          <p>Encontrá una sala, comprobá si tiene una sesión abierta y entrá a sus subtítulos en español o inglés.</p>
          <div className="dashboard-hero-actions">
            <Link className="hero-action" to="/salas">Explorar salas <span aria-hidden="true">↗</span></Link>
            <Link className="landing-secondary-action" to="/guia">Cómo usar OmniStage ↗</Link>
          </div>
        </div>
        <aside className="dashboard-pulse" aria-label="Estado del tablero">
          <div className="dashboard-pulse-top"><span>ESTADO DEL EVENTO</span><span className="dashboard-pulse-orbit" aria-hidden="true">✳</span></div>
          <p className="dashboard-pulse-number">{status === "ready" ? String(opened.length).padStart(2, "0") : "—"}</p>
          <h2>{status === "ready" ? opened.length === 1 ? "sesión abierta" : "sesiones abiertas" : "Esperando conexión"}</h2>
          <p>{status === "ready" ? "El tablero consulta las salas cada cinco segundos." : "El estado de las salas aparecerá cuando se conecte el servicio público."}</p>
          <span className="dashboard-pulse-status" role="status">{status === "ready" ? `Actualizado a las ${updatedAt?.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" }) || "—"}` : status === "loading" ? "Consultando salas…" : "Estado no disponible"}</span>
        </aside>
      </section>

      <section className="dashboard-metrics" aria-label="Resumen de salas">
        <div><span>SALAS DISPONIBLES</span><strong>10</strong><p>Elegí cualquier sala para abrir su vista de subtítulos.</p></div>
        <div><span>SESIONES ABIERTAS</span><strong>{status === "ready" ? opened.length : "—"}</strong><p>{status === "ready" ? "Sesiones preparadas por el equipo de operación." : "Se mostrará al conectar la API."}</p></div>
        <div><span>IDIOMAS</span><strong>ES / EN</strong><p>Cambiá el idioma desde la vista de cada sala.</p></div>
      </section>

      <section className="dashboard-section" aria-labelledby="dashboard-rooms-title">
        <div className="public-section-heading"><div><p className="section-index">ACCESO RÁPIDO</p><h2 id="dashboard-rooms-title">{opened.length && status === "ready" ? "Sesiones abiertas" : "Empezá por una sala"}<span>.</span></h2></div><Link to="/salas">Ver las 10 salas ↗</Link></div>
        <div className="public-stage-grid">{featured.map((stage) => <PublicStageCard key={stage.stage_id} stage={stage} status={status} />)}</div>
      </section>

      <section className="dashboard-next" aria-labelledby="dashboard-next-title">
        <div><p className="section-index">TU PANTALLA, TU RITMO</p><h2 id="dashboard-next-title">Una charla.<br /><em>Dos idiomas.</em></h2></div>
        <div><p>Abrí una sala para leer en español o inglés, cambiar el tamaño de letra y activar alto contraste. También podés probar una muestra antes de que haya transmisiones.</p><Link to="/app?mock=1">Probar la muestra ↗</Link></div>
      </section>
    </div>
    <PublicFooter />
  </main>;
}
