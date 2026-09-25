import { useEffect } from "react";
import { Link } from "react-router-dom";
import { PublicFooter, PublicHeader } from "../components/PublicChrome.jsx";
import { usePublicStages } from "../lib/publicStages.js";
import { useSurfaceClass } from "../lib/stages.js";

const features = [
  { number: "01", title: "Cada escenario, en un lugar", copy: "Entrá a la sala que querés seguir y quedate con el contexto de la charla, incluso si cambiás de dispositivo." },
  { number: "02", title: "Español o inglés", copy: "Cambiá de idioma al instante. El texto se actualiza a medida que avanza la conversación." },
  { number: "03", title: "Hecho para leer mejor", copy: "Ajustá el tamaño de letra y activá alto contraste desde la vista de subtítulos." },
];

export default function Home() {
  useSurfaceClass("home");
  const { items: stages, status: stageState } = usePublicStages();
  useEffect(() => { document.title = "OmniStage | Subtítulos en vivo para Nerdearla 2026"; }, []);

  return (
    <main className="home-root landing-page" id="top">
      <PublicHeader />

      <section className="hero landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <p className="eyebrow-home"><span className="landing-spark" aria-hidden="true" /> NERDEARLA 2026 / SUBTÍTULOS EN VIVO</p>
          <h1 id="landing-title">Cada palabra<br />nos <em>encuentra.</em></h1>
          <p className="hero-copy">Seguí cada charla desde tu pantalla. Elegí un escenario, leé los subtítulos en español o inglés y no te pierdas la conversación.</p>
          <div className="landing-actions"><a className="hero-action" href="#salas">Explorar escenarios <span aria-hidden="true">↗</span></a><Link className="landing-secondary-action" to="/app?mock=1">Ver una muestra <span aria-hidden="true">↗</span></Link></div>
          <p className="landing-hero-note">La muestra contiene subtítulos de demostración.</p>
        </div>
        <div className="hero-preview landing-preview" aria-label="Vista previa ilustrativa de subtítulos">
          <div className="hero-preview-top"><span><i aria-hidden="true" /> VISTA PREVIA</span><span>OMNISTAGE / ES + EN</span></div>
          <div className="hero-preview-body"><span className="hero-preview-label">UNA CHARLA · DOS IDIOMAS</span><p>Las ideas no<br /><strong>se quedan atrás.</strong></p><div className="hero-preview-wave" aria-hidden="true">{Array.from({ length: 15 }, (_, index) => <span key={index} />)}</div></div>
          <div className="hero-preview-bottom"><span>ESPAÑOL</span><span>ENGLISH</span><span>SUBTÍTULOS EN TU PANTALLA</span></div>
        </div>
        <span className="landing-orbit landing-orbit-one" aria-hidden="true" /><span className="landing-orbit landing-orbit-two" aria-hidden="true" />
      </section>

      <section className="landing-proof" aria-label="Características principales"><span>01 — ELEGÍ TU SALA</span><span>02 — CAMBIÁ DE IDIOMA</span><span>03 — SEGUÍ LA CHARLA</span></section>

      <section className="landing-experience" id="experiencia" aria-labelledby="experience-heading">
        <div className="landing-section-intro"><p className="section-index">LA EXPERIENCIA</p><h2 id="experience-heading">Estar ahí, desde<br /><em>donde estés.</em></h2><p>Una forma clara de seguir lo que pasa en cada escenario, pensada para quienes están en el evento y para quienes acompañan a distancia.</p></div>
        <div className="landing-feature-grid">{features.map((feature) => <article className="landing-feature" key={feature.number}><span>{feature.number} / 03</span><h3>{feature.title}</h3><p>{feature.copy}</p></article>)}</div>
      </section>

      <section className="stage-section landing-stages" id="salas" aria-labelledby="stage-heading">
        <div className="section-heading"><div><p className="section-index">EN EL EVENTO</p><h2 id="stage-heading">Escenarios<span>.</span></h2></div><p>Elegí una sala. Vos decidís cómo escucharla y leerla.</p></div>
        {stageState === "loading" && <div className="landing-stage-message" role="status"><span className="landing-stage-icon" aria-hidden="true">⌁</span><div><h3>Buscando escenarios…</h3><p>Estamos consultando la programación en vivo.</p></div></div>}
        {stageState === "unavailable" && <div className="landing-stage-message" role="status"><span className="landing-stage-icon" aria-hidden="true">⌁</span><div><h3>Los escenarios se publicarán aquí</h3><p>La programación en vivo aparecerá cuando se conecte la transmisión. Mientras tanto, podés explorar una muestra de la interfaz.</p><Link to="/app?mock=1">Abrir muestra <span aria-hidden="true">↗</span></Link></div></div>}
        {stageState === "ready" && stages.length === 0 && <div className="landing-stage-message" role="status"><span className="landing-stage-icon" aria-hidden="true">⌁</span><div><h3>Próximamente, en vivo</h3><p>Todavía no hay salas publicadas. Volvé cuando empiecen las charlas.</p></div></div>}
        {stageState === "ready" && stages.length > 0 && <div className="stage-grid">{stages.map((stage, index) => <Link className="stage-card" to={`/app?stage=${encodeURIComponent(stage.stage_id)}&lang=es`} key={stage.stage_id}><div className="stage-card-top"><span>ESCENARIO {String(index + 1).padStart(2, "0")}</span><span className={stage.audio_up && stage.provider_ready ? "live-pill" : "quiet-pill"}>{stage.audio_up && stage.provider_ready ? "EN VIVO" : stage.session_id || stage.active_session_id || stage.session ? "SESIÓN ABIERTA" : "EN ESPERA"}</span></div><h3>{stage.name || `Sala ${stage.stage_id}`}</h3><p>{stage.session || "La próxima charla aparecerá aquí."}</p><div className="stage-card-bottom"><span>ESPAÑOL / ENGLISH</span><span aria-hidden="true">↗</span></div></Link>)}</div>}
      </section>

      <section className="landing-closing"><p className="section-index">OMNISTAGE / NERDEARLA 2026</p><h2>La charla sigue.<br /><em>Vos también.</em></h2><a className="hero-action" href="#salas">Elegir escenario <span aria-hidden="true">↗</span></a></section>
      <PublicFooter />
    </main>
  );
}
