import { Link } from "react-router-dom";
import { useSurfaceClass } from "../lib/stages.js";

export default function NotFound() {
  useSurfaceClass("home");
  return <main className="landing-not-found"><Link className="wordmark" to="/">OMNI<span>STAGE</span></Link><div><p className="section-index">404 / PÁGINA NO DISPONIBLE</p><h1>Nos vemos en<br /><em>el escenario.</em></h1><p>La página que buscás no está disponible.</p><Link className="hero-action" to="/">Volver al inicio <span aria-hidden="true">↗</span></Link></div></main>;
}
