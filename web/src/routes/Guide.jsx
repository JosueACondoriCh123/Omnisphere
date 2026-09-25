import { useEffect } from "react";
import { Link } from "react-router-dom";
import { PublicFooter, PublicHeader } from "../components/PublicChrome.jsx";
import { useSurfaceClass } from "../lib/stages.js";

const steps = [
  { number: "01", title: "Elegí una sala", copy: "Entrá al catálogo y abrí el escenario que querés seguir. Podés cambiar de sala después, desde la vista de subtítulos." },
  { number: "02", title: "Seleccioná el idioma", copy: "Elegí español o inglés. El selector está arriba de los subtítulos y podés cambiarlo en cualquier momento." },
  { number: "03", title: "Ajustá la lectura", copy: "Usá el selector de tamaño de letra y la opción de alto contraste para adaptar el texto a tu pantalla." },
];

export default function Guide() {
  useSurfaceClass("home");
  useEffect(() => { document.title = "Guía de uso | OmniStage"; }, []);

  return <main className="home-root public-page guide-page" id="top">
    <PublicHeader />
    <div className="public-page-content">
      <header className="public-page-intro guide-intro">
        <p className="section-index">GUÍA / SUBTÍTULOS EN VIVO</p>
        <h1>Seguí cada idea<br /><em>a tu manera.</em></h1>
        <p>OmniStage reúne las salas de Nerdearla y sus subtítulos en una pantalla sencilla. Empezar lleva tres pasos.</p>
        <Link className="hero-action" to="/salas">Elegir una sala <span aria-hidden="true">↗</span></Link>
      </header>

      <section className="guide-steps" aria-labelledby="guide-steps-title">
        <div className="public-section-heading"><div><p className="section-index">CÓMO EMPEZAR</p><h2 id="guide-steps-title">Tres pasos<span>.</span></h2></div></div>
        <div className="guide-step-grid">{steps.map((step) => <article key={step.number}><span>{step.number} / 03</span><h3>{step.title}</h3><p>{step.copy}</p></article>)}</div>
      </section>

      <section className="guide-details" aria-labelledby="guide-details-title">
        <div><p className="section-index">PARA LEER MEJOR</p><h2 id="guide-details-title">Todo bajo<br /><em>tu control.</em></h2></div>
        <div className="guide-detail-list">
          <article><span>ES / EN</span><div><h3>Idioma</h3><p>La vista de cada sala permite alternar entre español e inglés.</p></div></article>
          <article><span>S / XL</span><div><h3>Tamaño</h3><p>Elegí entre cuatro tamaños de texto según tu distancia de lectura.</p></div></article>
          <article><span>◐</span><div><h3>Contraste</h3><p>Activá alto contraste para resaltar las palabras sobre el fondo.</p></div></article>
        </div>
      </section>

      <section className="guide-status" aria-labelledby="guide-status-title">
        <div><p className="section-index">ESTADO DE LAS SALAS</p><h2 id="guide-status-title">¿Qué significa cada estado?</h2></div>
        <dl><div><dt>Subtítulos activos</dt><dd>La sala informa audio y proveedor de subtítulos disponibles.</dd></div><div><dt>Sesión abierta</dt><dd>El equipo preparó la charla; el audio o los subtítulos pueden empezar más tarde.</dd></div><div><dt>En espera</dt><dd>La sala todavía no tiene una sesión abierta.</dd></div><div><dt>Estado no disponible</dt><dd>La conexión con el servicio público no está lista. Podés abrir una muestra de la interfaz.</dd></div></dl>
      </section>

      <section className="guide-final"><div><p className="section-index">LISTO PARA EMPEZAR</p><h2>La conversación<br /><em>te espera.</em></h2></div><div><Link className="hero-action" to="/salas">Explorar salas ↗</Link><Link className="landing-secondary-action" to="/app?mock=1">Ver una muestra ↗</Link></div></section>
    </div>
    <PublicFooter />
  </main>;
}
