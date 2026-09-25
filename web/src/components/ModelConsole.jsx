import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const gb = (bytes) => (bytes / 1024 ** 3).toLocaleString("es-AR", { maximumFractionDigits: 1 });

export default function ModelConsole({ desktop, status, provider, onMode, onChanged }) {
  const [progress, setProgress] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [input, setInput] = useState("");
  const [target, setTarget] = useState("en");
  const [result, setResult] = useState("");

  useEffect(() => {
    if (!desktop) return undefined;
    const refresh = () => desktop.setupStatus().then((value) => setProgress(value.modelDownload || null)).catch(() => {});
    const initial = setTimeout(refresh, 0);
    const timer = setInterval(refresh, 10000);
    const unsubscribe = desktop.onModelProgress?.(setProgress);
    return () => { clearTimeout(initial); clearInterval(timer); unsubscribe?.(); };
  }, [desktop]);

  const models = status?.models || {};
  const services = status?.services || {};
  const downloading = ["downloading", "verifying"].includes(progress?.phase);
  const installed = Boolean(models.asr && models.gemma);

  async function action(name, task) {
    setBusy(name); setError(""); setNotice("");
    try {
      const value = await task();
      if (value) await onChanged();
      return value;
    } catch (exc) {
      setError(String(exc.message).replace(/^Error invoking remote method '[^']+': (Error: )?/, ""));
      return null;
    } finally { setBusy(""); }
  }

  async function importModels() {
    const value = await action("import", () => desktop.importModels());
    if (value) setNotice("Modelos verificados e instalados. El motor se inicia automáticamente.");
  }

  async function downloadModels() {
    const value = await action("download", () => desktop.downloadModels());
    if (value) setNotice("Descarga terminada. Los modelos están instalados.");
  }

  async function startModel() {
    const value = await action("start", () => desktop.startLocalModels());
    if (value) setNotice("Gemma está iniciando. El estado se actualizará en unos segundos.");
  }

  async function testModel(event) {
    event.preventDefault();
    setResult("");
    setBusy("test"); setError(""); setNotice("");
    try { setResult(await desktop.testLocalModel(input, target)); }
    catch (exc) { setError(String(exc.message).replace(/^Error invoking remote method '[^']+': (Error: )?/, "")); }
    finally { setBusy(""); }
  }

  return <div className="model-console">
    <section className="operator-panel model-hero">
      <p className="section-index">MOTOR LOCAL / GEMMA 4</p>
      <div className="model-hero-top"><div><h2>Modelos listos para operar</h2><p className="input-hint">Instalá, iniciá y probá la traducción local desde un mismo lugar. Los modelos se descargan aparte del instalador.</p></div><strong className="model-count">{Number(Boolean(models.asr)) + Number(Boolean(models.gemma))}<small>/ 2 instalados</small></strong></div>
      <div className="model-status-grid">
        <article data-ready={models.asr ? "1" : "0"}><span>01 · TRANSCRIPCIÓN</span><h3>faster-whisper</h3><p>{models.asr ? "Instalado" : "Falta instalar"} · {services.backend ? "backend activo" : "backend sin respuesta"}</p></article>
        <article data-ready={models.gemma && services.gemma ? "1" : "0"}><span>02 · TRADUCCIÓN</span><h3>Gemma 4 E2B</h3><p>{!models.gemma ? "Falta instalar" : services.gemma ? "Motor activo" : "Instalado · iniciando o sin respuesta"}</p></article>
      </div>
      {status?.gpu && <p className="model-gpu">GPU detectada: <strong>{status.gpu}</strong></p>}
      {!desktop && <p className="input-hint">Abrí OmniStage de escritorio para instalar y ejecutar los modelos.</p>}
    </section>

    <section className="operator-panel">
      <p className="section-index">PREPARACIÓN</p><h2>Instalar y arrancar</h2>
      <p className="input-hint">Podés importar una carpeta de modelos verificada sin internet o descargarlos desde la app. Al terminar, Gemma se inicia automáticamente.</p>
      {downloading && <div className="setup-progress"><progress max="100" value={progress.total ? Math.floor(progress.received / progress.total * 100) : 0} aria-label="Progreso de modelos" /><span>{progress.phase === "verifying" ? "Verificando" : "Descargando"} {progress.file} · {gb(progress.received || 0)} de {gb(progress.total || 0)} GB</span></div>}
      {progress?.phase === "cancelled" && <p className="input-hint">Descarga pausada; se puede reanudar.</p>}
      <div className="model-actions">
        {!installed && <>
          <button type="button" className="glass-button glass-button-primary" onClick={importModels} disabled={!desktop || Boolean(busy) || downloading}>Importar carpeta de modelos</button>
          {downloading ? <button type="button" className="glass-button glass-button-secondary" onClick={() => desktop.cancelModelDownload()}>Pausar descarga</button>
            : <button type="button" className="glass-button glass-button-secondary" onClick={downloadModels} disabled={!desktop || Boolean(busy)}>Descargar modelos</button>}
        </>}
        {models.gemma && <button type="button" className="glass-button glass-button-live" onClick={startModel} disabled={!desktop || Boolean(busy)}>{services.gemma ? "Reiniciar Gemma" : "Iniciar Gemma"}</button>}
        <Link className="glass-button glass-button-quiet" to="/operator/setup">Ver todos los primeros pasos</Link>
      </div>
      {notice && <p className="model-notice" role="status">{notice}</p>}
      {error && <p className="surface-error" role="alert">{error}</p>}
    </section>

    <section className="operator-panel">
      <p className="section-index">PRUEBA LOCAL</p><h2>Probá una traducción</h2>
      <p className="input-hint">La frase se envía sólo al motor Gemma de esta computadora. Es una prueba breve de funcionamiento, no una medición de latencia de la demo.</p>
      <form className="model-test" onSubmit={testModel}>
        <label>Frase de prueba<textarea value={input} onChange={(event) => setInput(event.target.value)} maxLength={500} placeholder="Escribí una frase corta…" required /></label>
        <div className="model-test-actions"><label>Traducir a<select value={target} onChange={(event) => setTarget(event.target.value)}><option value="en">Inglés</option><option value="es">Español</option></select></label><button className="glass-button glass-button-primary" type="submit" disabled={!desktop || !services.gemma || Boolean(busy) || !input.trim()}>{busy === "test" ? "Traduciendo…" : "Ejecutar prueba"}</button></div>
      </form>
      {result && <div className="model-result" role="status"><span>RESULTADO</span><p>{result}</p></div>}
      <div className="model-mode"><label>Modo para las salas<select value={provider.mode || "auto"} onChange={(event) => onMode(event.target.value)}><option value="auto">Automático</option><option value="local">Gemma local</option><option value="cloud">Nube preferida</option></select></label><p className="input-hint">La prueba de arriba usa siempre Gemma local. Este selector controla las sesiones de las salas.</p></div>
    </section>
  </div>;
}
