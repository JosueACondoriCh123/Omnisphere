import { Link } from "react-router-dom";
import { publicStageStatus } from "../lib/publicStages.js";

export default function PublicStageCard({ stage, status, lang = "es" }) {
  const label = publicStageStatus(stage, status);
  const active = label === "Subtítulos activos";
  const room = String(stage.stage_id).padStart(2, "0");
  return <article className={`public-stage-card${stage.hasSession ? " has-session" : ""}`}>
    <div className="public-stage-top"><span>SALA / {room}</span><span className={active ? "public-stage-live" : "public-stage-muted"}>{label}</span></div>
    <div className="public-stage-content">
      <span className="public-stage-number" aria-hidden="true">{room}</span>
      <h3>{stage.name || `Sala ${stage.stage_id}`}</h3>
      <p>{status === "ready" && stage.session ? stage.session : "La próxima charla aparecerá cuando se abra la sesión."}</p>
    </div>
    <Link to={`/app?stage=${encodeURIComponent(stage.stage_id)}&lang=${lang}`}>Abrir subtítulos <span aria-hidden="true">↗</span></Link>
  </article>;
}
