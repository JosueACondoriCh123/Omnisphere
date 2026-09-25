import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CaptionLane } from "../components/CaptionLane.jsx";
import { statusLabel } from "../lib/status.js";
import { useOnline } from "../lib/online.js";
import { useSurfaceClass } from "../lib/stages.js";
import { useCaptions } from "../lib/useCaptions.js";
import { useStageOptions } from "../lib/useStageOptions.js";
import { hasLiveBackend } from "../lib/publicBackend.js";

const SIZES = ["S", "M", "L", "XL"];

function useCommitAnnouncements(segments, stageId, lang) {
  const seen = useRef(new Set());
  const [text, setText] = useState("");
  const signature = useMemo(
    () =>
      segments
        .filter((segment) => segment.state === "committed")
        .map((segment) => `${stageId}:${lang}:${segment.session_id || ""}:${segment.uid}:${segment.text}`)
        .join("|"),
    [segments, stageId, lang],
  );

  useEffect(() => {
    const fresh = segments.filter(
      (segment) =>
        segment.state === "committed" &&
        segment.uid != null &&
        !seen.current.has(`${stageId}:${lang}:${segment.session_id || ""}:${segment.uid}`),
    );
    if (!fresh.length) return;
    for (const segment of fresh) seen.current.add(`${stageId}:${lang}:${segment.session_id || ""}:${segment.uid}`);
    setText(fresh.map((segment) => segment.text).filter(Boolean).join(" "));
  }, [segments, signature, stageId, lang]);

  return text;
}

export default function App() {
  useSurfaceClass("app");
  const [params, setParams] = useSearchParams();
  const stageId = params.get("stage") || "1";
  const lang = params.get("lang") === "en" ? "en" : "es";
  const size = SIZES.includes(params.get("size")?.toUpperCase())
    ? params.get("size").toUpperCase()
    : "L";
  const contrast = params.get("contrast") === "1";
  const mock = params.get("mock") === "1";
  const online = useOnline();
  const stages = useStageOptions({ enabled: !mock && hasLiveBackend });
  const stageOptions = stages.some(
    (stage) => String(stage.stage_id) === String(stageId),
  )
    ? stages
    : [{ stage_id: stageId, name: `Sala ${stageId}` }, ...stages];

  const set = (key, value) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };

  const { segments, status } = useCaptions({ stageId, lang, mock });
  const live = useMemo(
    () => segments.filter((s) => s.state === "draft" || s.state === "committed"),
    [segments],
  );
  const announcement = useCommitAnnouncements(segments, stageId, lang);
  const reachableOnLan = !mock && status === "open";
  const connectionAvailable = online || reachableOnLan;
  const currentStage = stages.find((stage) => String(stage.stage_id) === String(stageId));
  const displayStatus = !connectionAvailable ? "offline"
    : !mock && status === "open" && currentStage?.active_session_id && !currentStage.audio_up
      ? "no-signal"
      : !mock && status === "open" && currentStage?.audio_up && currentStage.provider_ready === false
        ? "provider-error" : status;
  const displayLabel = displayStatus === "no-signal" ? "Sin señal de audio"
    : displayStatus === "provider-error" ? "Proveedor no disponible"
      : displayStatus === "offline" ? "Sin conexión; los subtítulos en vivo están pausados"
        : statusLabel(displayStatus);

  return (
    <main
      className={`audience size-${size.toLowerCase()}${contrast ? " contrast" : ""}`}
      data-mock={mock ? "1" : "0"}
    >
      <header className="audience-bar">
        <div className="brand-lockup">
          <span className="live-dot" aria-hidden="true" />
          <p className="mark">OmniStage</p>
        </div>
        <label htmlFor="stage-select">
          Sala
          <select
            id="stage-select"
            value={stageId}
            onChange={(e) => set("stage", e.target.value)}
          >
            {stageOptions.map((stage) => (
              <option key={stage.stage_id} value={stage.stage_id}>
                {stage.name ?? `Sala ${stage.stage_id}`}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor="lang-select">
          Idioma
          <select
            id="lang-select"
            value={lang}
            onChange={(e) => set("lang", e.target.value)}
          >
            <option value="es">es</option>
            <option value="en">en</option>
          </select>
        </label>
        <label htmlFor="size-select">
          Tamaño
          <select
            id="size-select"
            value={size}
            onChange={(e) => set("size", e.target.value)}
          >
            {SIZES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="toggle" htmlFor="contrast-toggle">
          <input
            id="contrast-toggle"
            type="checkbox"
            checked={contrast}
            onChange={(e) => set("contrast", e.target.checked ? "1" : "0")}
          />
          Alto contraste
        </label>
        <p className="status" data-status={displayStatus} role="status">
          <span aria-hidden="true" />
          {displayLabel}
        </p>
        <Link className="back-link" to="/salas">Todas las salas ↗</Link>
      </header>
      <section className="prompter" aria-label="Subtítulos en vivo">
        <p className="eyebrow" aria-hidden="true">
          {stageOptions.find((stage) => String(stage.stage_id) === String(stageId))?.name || `Sala ${stageId}`} · {lang.toUpperCase()}
        </p>
        <CaptionLane segments={live} />
      </section>
      <div className="sr-only" aria-live="polite" data-testid="commit-announcer">
        {announcement}
      </div>
    </main>
  );
}
