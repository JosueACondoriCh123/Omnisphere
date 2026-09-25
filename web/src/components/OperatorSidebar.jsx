import { Link, NavLink, useLocation } from "react-router-dom";

const sections = [
  ["/operator", "Resumen"],
  ["/operator/rooms", "Salas"],
  ["/operator/broadcasts", "Transmisiones"],
  ["/operator/archive", "Archivo"],
  ["/operator/integrations", "Integraciones"],
  ["/operator/system", "Sistema y operadores"],
  ["/operator/setup", "Primeros pasos"],
];

export default function OperatorSidebar({ user, onLogout }) {
  const location = useLocation();

  return <aside className="operator-sidebar">
    <div className="operator-sidebar-brand">
      <Link className="wordmark" to="/operator">OMNI<span>STAGE</span></Link>
      <p>Centro de operaciones</p>
    </div>
    <nav className="operator-nav" aria-label="Operación">
      <p className="operator-nav-caption">Espacio de trabajo</p>
      {sections.map(([url, label], index) =>
        <NavLink key={url} to={url} end={url === "/operator"}
          className={({ isActive }) => isActive || (url === "/operator" && location.pathname === "/admin") ? "active" : ""}>
          <span className="operator-nav-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
          <span>{label}</span>
        </NavLink>)}
    </nav>
    <div className="operator-sidebar-footer">
      {user ? <>
        <span className="operator-account-label">Operador activo</span>
        <strong title={user.email}>{user.email}</strong>
        <button className="glass-button glass-button-quiet" type="button" onClick={onLogout}>Cerrar sesión</button>
      </> : <Link className="glass-button glass-button-quiet" to="/operator">← Volver al panel</Link>}
    </div>
  </aside>;
}
