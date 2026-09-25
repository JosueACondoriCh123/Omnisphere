import { Link, NavLink } from "react-router-dom";

export function PublicHeader() {
  return <header className="site-header landing-header public-header">
    <Link className="wordmark" to="/" aria-label="OmniStage, inicio">OMNI<span>STAGE</span></Link>
    <nav aria-label="Principal">
      <NavLink to="/" end>Inicio</NavLink>
      <NavLink to="/dashboard">Dashboard</NavLink>
      <NavLink to="/salas">Salas</NavLink>
      <NavLink to="/guia">Guía</NavLink>
    </nav>
    <Link className="landing-header-cta" to="/salas">Ver salas <span aria-hidden="true">↗</span></Link>
  </header>;
}

export function PublicFooter() {
  return <footer className="site-footer landing-footer public-footer">
    <Link className="wordmark" to="/">OMNI<span>STAGE</span></Link>
    <span>Subtítulos para encontrarnos en cada idea.</span>
    <a href="#top">Volver arriba ↑</a>
  </footer>;
}
