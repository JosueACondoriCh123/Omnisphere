import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useSurfaceClass } from "../lib/stages.js";

export default function Home() {
  useSurfaceClass("home");
  const [stages, setStages] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const response = await fetch("/api/stages");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (live) {
          setStages(body.items || []);
          setError("");
        }
      } catch {
        if (live) setError("No se puede consultar el estado de las salas.");
      }
    }
    load();
    const timer = setInterval(load, 5000);
    return () => { live = false; clearInterval(timer); };
  }, []);

  return (
    <main className="home-root">
      <header className="site-header">
        <Link className="wordmark" to="/">OMNI<span>STAGE</span></Link>
        <span className="header-kicker">SUBTÍTULOS EN VIVO · ES / EN</span>
      </header>
      <section className="hero">
        <div>
          <p className="eyebrow-home">UNA VOZ · DOS IDIOMAS · CADA ESCENARIO</p>
          <h1>La conversación<br /><em>no se detiene.</em></h1>
          <p className="hero-copy">Elegí una sala y seguí la charla en español o inglés. Los subtítulos se actualizan en vivo, también en la red local del evento.</p>
          <a className="hero-action" href="#salas">Explorar salas <span aria-hidden="true">↗</span></a>
        </div>
        <div className="hero-art" aria-hidden="true"><span>O</span><span>O</span><span>O</span></div>
      </section>
      <section className="stage-section" id="salas" aria-labelledby="stage-heading">
        <div className="section-heading">
          <div><p className="section-index">01 / EN DIRECTO</p><h2 id="stage-heading">Escenarios</h2></div>
          <p>Seleccioná el idioma en la sala.</p>
        </div>
        {error && <p className="surface-error" role="status">{error}</p>}
        <div className="stage-grid">
          {stages.map((stage, index) => (
            <Link className="stage-card" to={`/app?stage=${encodeURIComponent(stage.stage_id)}&lang=es`} key={stage.stage_id}>
              <div className="stage-card-top"><span>ESCENARIO {String(index + 1).padStart(2, "0")}</span><span className={stage.audio_up && stage.provider_ready ? "live-pill" : "quiet-pill"}>{stage.audio_up ? stage.provider_ready ? "EN VIVO" : "PROVEEDOR CAÍDO" : stage.active_session_id ? "SIN SEÑAL" : "EN ESPERA"}</span></div>
              <h3>{stage.name || `Sala ${stage.stage_id}`}</h3>
              <p>{stage.session || "La próxima charla aparecerá aquí."}</p>
              <div className="stage-card-bottom"><span>ESPAÑOL / ENGLISH</span><span aria-hidden="true">↗</span></div>
            </Link>
          ))}
          {!stages.length && !error && <p className="empty-stage">Todavía no hay salas configuradas.</p>}
        </div>
      </section>
      <footer className="site-footer"><span>OMNISTAGE</span><span>El evento, en tus palabras.</span></footer>
    </main>
  );
}
