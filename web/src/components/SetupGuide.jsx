import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

const gb = (bytes) => (bytes / 1024 ** 3).toLocaleString("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const MODEL_BYTES = 3835728628;

function Step({ index, title, state, children }) {
  const label = { done: "Listo", pending: "Pendiente", optional: "Opcional", info: "Referencia" }[state];
  return <li className="setup-step" data-state={state}>
    <span className="setup-step-index" aria-hidden="true">{state === "done" ? "✓" : String(index).padStart(2, "0")}</span>
    <div className="setup-step-body">
      <h3>{title} <small>{label}</small></h3>
      {children}
    </div>
  </li>;
}

export default function SetupGuide({ desktop, desktopStatus, cloudKey, onChanged }) {
  const [setup, setSetup] = useState(null);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState("");

  const refresh = useCallback(() => desktop.setupStatus().then((value) => {
    setSetup(value);
    if (["downloading", "verifying"].includes(value.modelDownload?.phase)) setProgress(value.modelDownload);
  }).catch(() => {}), [desktop]);

  useEffect(() => {
    const initial = setTimeout(refresh, 0);
    const timer = setInterval(refresh, 10000);
    const unsubscribe = desktop.onModelProgress?.(setProgress);
    return () => { clearTimeout(initial); clearInterval(timer); unsubscribe?.(); };
  }, [desktop, refresh]);

  async function download() {
    setError("");
    try {
      const result = await desktop.downloadModels();
      if (result) await onChanged();
    } catch (exc) { setError(exc.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, "")); }
  }

  async function importFolder() {
    setError("");
    try {
      const result = await desktop.importModels();
      if (result) await onChanged();
    } catch (exc) { setError(exc.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, "")); }
  }

  const models = desktopStatus?.models || {};
  const modelsReady = Boolean(models.asr && models.gemma);
  const services = desktopStatus?.services || {};
  const servicesReady = Object.values(services).length > 0 && Object.values(services).every(Boolean);
  const publicNetwork = (setup?.networkCategories || []).includes("Public");
  const lanReady = Boolean(setup?.firewall) && !publicNetwork;
  const busy = ["downloading", "verifying"].includes(progress?.phase);
  const required = [true, modelsReady, servicesReady, lanReady];
  const percent = progress?.total ? Math.floor((progress.received / progress.total) * 100) : 0;

  return <section className="operator-panel setup-guide" aria-labelledby="setup-guide-title">
    <div className="panel-heading"><div><p className="section-index">INSTALACIÓN</p><h2 id="setup-guide-title">Primeros pasos</h2></div><span>{required.filter(Boolean).length}/{required.length}</span></div>
    <p className="input-hint">Completá estos pasos una sola vez en esta computadora. Los pasos opcionales se pueden hacer después.</p>
    {error && <p className="surface-error" role="alert">{error}</p>}
    <ol className="setup-steps">
      <Step index={1} title="Cuenta de operador" state="done">
        <p className="input-hint">Creada. Para sumar más operadores, entrá en <Link to="/operator/system">Sistema y operadores</Link>.</p>
      </Step>
      <Step index={2} title="Modelos locales" state={modelsReady ? "done" : "pending"}>
        <p className="input-hint">Para ver el estado y probar Gemma, abrí <Link to="/operator/models">Modelos locales</Link>.</p>
        {modelsReady ? <p className="input-hint">faster-whisper y Gemma 4 E2B instalados y verificados.</p> : <>
          <p className="input-hint">Hacen falta para transcribir y traducir sin internet. Son {gb(MODEL_BYTES)} GB desde Hugging Face y se verifica el SHA256 de cada archivo. Si la descarga se corta, retoma desde donde quedó.</p>
          {busy && <div className="setup-progress">
            <progress max="100" value={percent} aria-label="Descarga de modelos" />
            <span>{progress.phase === "verifying" ? "Verificando" : "Descargando"} {progress.file} · {gb(progress.received)} de {gb(progress.total)} GB ({percent} %)</span>
          </div>}
          {progress?.phase === "cancelled" && <p className="input-hint">Descarga pausada. Al reanudar se conserva lo ya bajado.</p>}
          <div className="setup-actions">
            {busy
              ? <button className="glass-button glass-button-secondary" type="button" onClick={() => desktop.cancelModelDownload()}>Pausar descarga</button>
              : <button className="glass-button glass-button-primary" type="button" onClick={download}>{progress?.phase === "cancelled" || progress?.phase === "error" ? "Reanudar descarga" : "Descargar modelos"}</button>}
            <button className="glass-button glass-button-quiet" type="button" onClick={importFolder} disabled={busy}>Importar desde una carpeta (sin internet)</button>
          </div>
        </>}
      </Step>
      <Step index={3} title="Servicios" state={servicesReady ? "done" : "pending"}>
        <dl className="system-status">{Object.entries(services).map(([name, value]) => <div key={name}><dt>{name}</dt><dd data-on={value ? "1" : "0"}>{value ? "Activo" : "Inactivo"}</dd></div>)}</dl>
        {!servicesReady && <p className="input-hint">Gemma arranca cuando los modelos están instalados y puede tardar hasta un minuto. Si no arranca, revisá el driver NVIDIA o usá la ruta de nube de Gemini.</p>}
      </Step>
      <Step index={4} title="Acceso del público por la red local" state={lanReady ? "done" : "pending"}>
        {desktopStatus?.lanUrls?.length > 0 && <p className="input-hint">El público abre {desktopStatus.lanUrls.map((url, i) => <span key={url}>{i > 0 && " o "}<code>{url}</code></span>)} desde un celular en la misma red Wi-Fi.</p>}
        {setup && !setup.firewall && <p className="input-hint">Falta la regla de firewall para el puerto 8088. La crea el instalador; reinstalá OmniStage o ejecutá <code>setup-firewall.ps1</code> como administrador.</p>}
        {publicNetwork && <>
          <p className="input-hint">Windows marcó esta red como <strong>Pública</strong> y bloquea al público. Cambiala a <strong>Privada</strong> en Configuración → Red e Internet → Propiedades.</p>
          <div className="setup-actions"><button className="glass-button glass-button-secondary" type="button" onClick={() => desktop.openNetworkSettings()}>Abrir configuración de red</button></div>
        </>}
        {!setup && <p className="input-hint">Comprobando firewall y red…</p>}
      </Step>
      <Step index={5} title="Gemini en la nube" state={cloudKey?.state === "ready" ? "done" : "optional"}>
        <p className="input-hint">Mejora la calidad con internet y es el respaldo sin GPU. Cargá la clave en <Link to="/operator/integrations">Integraciones</Link>.</p>
      </Step>
      <Step index={6} title="Conectar el audio" state="info">
        <p className="input-hint">En <Link to="/operator/rooms">Salas</Link> preparás la sesión con micrófono o grabación. Desde OBS: servidor <code>rtmp://127.0.0.1:1935/live</code> y clave <code>stage-N</code>, donde N va de 1 a 10.</p>
      </Step>
    </ol>
  </section>;
}
