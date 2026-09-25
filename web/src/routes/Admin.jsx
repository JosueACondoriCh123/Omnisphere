import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { ALARM_LABELS } from "../lib/hops.js";
import { useSurfaceClass } from "../lib/stages.js";
import BroadcastPanel from "../components/BroadcastPanel.jsx";

async function api(path, options = {}, csrf = "") {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "content-type": "application/json" } : {}),
      ...(csrf ? { "x-csrf-token": csrf } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

const permissionLabels = [
  ["capture", "Captura"], ["transcribe", "Transcripción"],
  ["translate", "Traducción"], ["cloud", "Enviar a Google"],
  ["publish", "Publicar"], ["retain", "Conservar 30 días"],
  ["train", "Entrenamiento"],
];

function Access({ onLogin }) {
  const [setup, setSetup] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/api/operator/bootstrap-status").then((value) => setSetup(value.needs_setup)).catch(() => {});
  }, []);

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      if (setup) await api("/api/operator/bootstrap", {
        method: "POST", body: JSON.stringify({ email, password }),
      });
      const user = await api("/api/operator/login", {
        method: "POST", body: JSON.stringify({ email, password }),
      });
      onLogin(user);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="operator-access">
    <div className="access-panel">
      <p className="section-index">OMNISTAGE / OPERACIÓN</p>
      <h1>{setup ? "Crear operador inicial" : "Acceso de operadores"}</h1>
      <p>Las sesiones, exportaciones y controles de audio están disponibles solo en esta computadora.</p>
      <form onSubmit={submit} className="field-stack">
        <label>Correo electrónico<input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
        <label>Contraseña<input type="password" minLength={12} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error && <p className="surface-error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Verificando…" : setup ? "Crear cuenta" : "Ingresar"}</button>
      </form>
    </div>
  </main>;
}

function SessionForm({ csrf, onCreated, desktop }) {
  const [stageId, setStageId] = useState("1");
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("obs");
  const [permission, setPermission] = useState({});
  const [evidence, setEvidence] = useState("");
  const [microphones, setMicrophones] = useState([]);
  const [microphone, setMicrophone] = useState("");
  const [error, setError] = useState("");
  const [recordingPath, setRecordingPath] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    desktop?.listMicrophones?.().then((names) => {
      setMicrophones(names);
      if (names.length) setMicrophone(names[0]);
    }).catch(() => {});
  }, [desktop]);

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    let result;
    try {
      if (source === "microphone" && !microphone) throw new Error("No se detectó un micrófono disponible.");
      result = await api("/api/operator/sessions", {
        method: "POST",
        body: JSON.stringify({
          stage_id: stageId, title, source_type: source,
          permissions: {
            ...Object.fromEntries(permissionLabels.map(([key]) => [key, Boolean(permission[key])])),
            evidence_reference: evidence,
          },
        }),
      }, csrf);
      if (source === "file") {
        if (!desktop) throw new Error("La importación requiere la app de escritorio.");
        const started = await desktop.startFile(stageId);
        if (!started) throw new Error("No se eligió un archivo.");
      }
      if (source === "microphone") {
        if (!desktop) throw new Error("El micrófono requiere la app de escritorio.");
        const started = await desktop.startMicrophone(stageId, microphone);
        if (!started) throw new Error("No se eligió dónde guardar la grabación original.");
        setRecordingPath(started.recording_path || "");
      }
      setTitle(""); setPermission({}); setEvidence("");
      onCreated(result);
    } catch (exc) {
      if (result && source !== "obs") {
        await api(`/api/operator/sessions/${result.id}/end`, { method: "POST" }, csrf).catch(() => {});
      }
      setError(exc.message);
    } finally { setBusy(false); }
  }

  return <form className="operator-panel session-form" onSubmit={submit}>
    <div className="panel-heading"><div><p className="section-index">PREPARACIÓN</p><h2>Nueva sesión</h2></div><span>01</span></div>
    <div className="form-grid">
      <label>Sala<select value={stageId} onChange={(event) => setStageId(event.target.value)}><option value="1">Sala 1</option><option value="2">Sala 2</option><option value="3">Sala 3</option></select></label>
      <label>Charla<input required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Nombre de la charla" /></label>
      <label>Fuente<select value={source} onChange={(event) => setSource(event.target.value)}><option value="obs">OBS</option><option value="file">Grabación</option><option value="microphone">Micrófono</option></select></label>
      {source === "microphone" && <label>Dispositivo<select value={microphone} onChange={(event) => setMicrophone(event.target.value)}>{microphones.map((name) => <option key={name}>{name}</option>)}</select></label>}
    </div>
    <fieldset className="permission-grid"><legend>Autorizaciones verificadas</legend>
      {permissionLabels.map(([key, label]) => <label key={key}><input type="checkbox" checked={Boolean(permission[key])} onChange={(event) => setPermission({ ...permission, [key]: event.target.checked })} />{label}</label>)}
    </fieldset>
    <label>Referencia del permiso<input required value={evidence} onChange={(event) => setEvidence(event.target.value)} placeholder="Contrato, formulario o expediente" /></label>
    {source === "obs" && <p className="input-hint">OBS: servidor <code>rtmp://localhost:1935/live</code> · clave <code>stage-{stageId}</code></p>}
    {error && <p className="surface-error" role="alert">{error}</p>}
    {recordingPath && <p className="input-hint">Original de micrófono guardado en: {recordingPath}</p>}
    <button type="submit" disabled={busy}>{busy ? "Preparando…" : "Preparar sesión"}</button>
  </form>;
}

function Operations({ user, onLogout }) {
  const location = useLocation();
  const page = location.pathname.split('/')[2] || 'overview';
  const [rows, setRows] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [provider, setProvider] = useState({ mode: "auto", stages: {} });
  const [loadError, setLoadError] = useState("");
  const [desktopStatus, setDesktopStatus] = useState(null);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [cloudKey, setCloudKey] = useState({ state: 'missing', configured: false });
  const desktop = globalThis.omniDesktop;

  const refresh = useCallback(async () => {
    try {
      const [metrics, history, engine] = await Promise.all([
        api("/api/metrics/stages"), api("/api/operator/sessions"), api("/api/operator/provider"),
      ]);
      setRows(metrics.items || []);
      setSessions(history.items || []);
      setProvider(engine);
      setLoadError("");
    } catch (exc) { setLoadError(exc.message); }
  }, []);

  useEffect(() => {
    const initial = setTimeout(refresh, 0);
    const timer = setInterval(refresh, 2000);
    return () => { clearTimeout(initial); clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    if (!desktop) return undefined;
    desktop.status().then(setDesktopStatus).catch(() => {});
    desktop.cloudKeyStatus?.().then(setCloudKey).catch(() => {});
    const timer = setInterval(() => desktop.status().then(setDesktopStatus).catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [desktop]);

  async function setMode(mode) {
    try {
      setProvider(await api("/api/operator/provider", {
        method: "PUT", body: JSON.stringify({ mode }),
      }, user.csrf_token));
    } catch (exc) { setLoadError(exc.message); }
  }

  async function addOperator(event) {
    event.preventDefault();
    try {
      await api("/api/operator/users", {
        method: "POST", body: JSON.stringify({ email: newEmail, password: newPassword }),
      }, user.csrf_token);
      setNewEmail(""); setNewPassword("");
    } catch (exc) { setLoadError(exc.message); }
  }

  async function endSession(session) {
    try {
      if (desktop && session.source_type !== "obs") await desktop.stopSource(session.stage_id);
      await api(`/api/operator/sessions/${session.id}/end`, { method: "POST" }, user.csrf_token);
      await refresh();
    } catch (exc) { setLoadError(exc.message); }
  }

  async function saveIntegration(event) {
    event.preventDefault();
    try {
      if (!desktop) throw new Error("Configurá las claves desde la app de escritorio.");
      if (apiKey.trim()) {
        setCloudKey({ ...cloudKey, state: 'validating' });
        const result = await desktop.saveApiKey(apiKey);
        setCloudKey(result);
        if (result.state !== 'ready') throw new Error(result.error || 'No se pudo validar la clave.');
      }
      setApiKey("");
      setLoadError("");
    } catch (exc) { setLoadError(exc.message); }
  }

  async function removeIntegration() {
    try {
      if (!desktop) throw new Error('Abrí OmniStage de escritorio.');
      setCloudKey(await desktop.removeApiKey());
      setLoadError('');
    } catch (exc) { setLoadError(exc.message); }
  }

  async function importModels() {
    try {
      const result = await desktop.importModels();
      if (result) setDesktopStatus(await desktop.status());
      setLoadError("");
    } catch (exc) { setLoadError(exc.message); }
  }

  const titles = {
    overview: ['Resumen del evento', 'Señal, proveedor y alertas de las tres salas.'],
    rooms: ['Salas y sesiones', 'Prepará las fuentes y verificá los permisos.'],
    broadcasts: ['Transmisiones', 'Una salida externa por sala, con idioma elegido.'],
    archive: ['Archivo', 'Consultá y exportá las cláusulas confirmadas.'],
    integrations: ['Integraciones', 'Configurá Gemini, el proveedor y los modelos.'],
    system: ['Sistema y operadores', 'Servicios, equipo y cuentas individuales.'],
  };
  const heading = titles[page] || titles.overview;
  const sessionList = <section className="operator-panel"><div className="panel-heading"><div><p className="section-index">REGISTRO</p><h2>Sesiones y archivo</h2></div><span>{sessions.length}</span></div>
    {!sessions.length && <p className="empty-state">Las sesiones confirmadas aparecerán aquí.</p>}
    <div className="session-list">{sessions.map((session) => <div className="session-entry" key={session.id}><Link to={`/operator/archive/${session.id}?lang=es`}><span>{session.title}</span><small>Sala {session.stage_id} · {session.ended_at ? 'Finalizada' : 'Activa'}</small><b>↗</b></Link>{!session.ended_at && page === 'rooms' && <button type="button" onClick={() => endSession(session)}>Finalizar</button>}</div>)}</div>
  </section>;
  const providerPanel = <section className="operator-panel"><p className="section-index">MOTOR</p><h2>Proveedor</h2>
    {page === 'integrations' && <label>Modo<select value={provider.mode} onChange={(event) => setMode(event.target.value)}><option value="auto">Automático</option><option value="cloud">Nube preferida</option><option value="local">Gemma local</option></select></label>}
    <p className="input-hint">El modo automático usa el motor local cuando la nube no está disponible.</p>
    <dl className="system-status">{Object.entries(provider.stages || {}).map(([stage, value]) => <div key={stage}><dt>Sala {stage} · {value.provider}{value.ready ? ' · listo' : ' · no disponible'}</dt><dd>{value.cloud_audio_minutes || 0} min · ~USD {Number(value.cloud_cost_usd_estimate || 0).toFixed(3)}{value.dropped_clauses ? ` · ${value.dropped_clauses} perdidas` : ''}</dd></div>)}</dl>
  </section>;

  return <main className="operator-root">
    <header className="operator-header"><Link className="wordmark" to="/">OMNI<span>STAGE</span></Link><div><span>OPERACIÓN · {user.email}</span><button type="button" onClick={onLogout}>Salir</button></div></header>
    <nav className="operator-nav" aria-label="Operación">
      {[["/operator", "Resumen"], ["/operator/rooms", "Salas"], ["/operator/broadcasts", "Transmisiones"], ["/operator/archive", "Archivo"], ["/operator/integrations", "Integraciones"], ["/operator/system", "Sistema y operadores"]].map(([url, label]) =>
        <NavLink key={url} to={url} end={url === '/operator'}>{label}</NavLink>)}
    </nav>
    <div className="operator-intro"><div><p className="section-index">PILOTO OPERATIVO / TRES SALAS</p><h1>{heading[0]}<span>.</span></h1></div><p>{heading[1]}</p></div>
    {loadError && <p className="surface-error" role="alert">{loadError}</p>}
    <div className="operator-layout" data-page={page}>
      <div className="operator-main">
        {(page === 'overview' || page === 'rooms') && <section className="operator-panel">
          <div className="panel-heading"><div><p className="section-index">EN VIVO</p><h2>Estado de las salas</h2></div><span>{rows.length.toString().padStart(2, '0')}</span></div>
          {!rows.length && <p className="empty-state">No hay salas transmitiendo. Prepará una sesión y conectá OBS, un archivo o un micrófono.</p>}
          <div className="room-list">{rows.map((row) => <article className="room-status" key={row.stage_id}
            data-state={!row.stream_up || !row.audio_up ? 'no-signal' : !row.transcriber_up ? 'provider-error' : 'processing'}>
            <div className="room-number">{row.stage_id}</div>
            <div className="room-details"><h3>Sala {row.stage_id}</h3><p>{!row.stream_up || !row.audio_up ? 'Sin señal' : !row.transcriber_up ? 'Proveedor no disponible' : 'Procesando'} · {row.provider || 'sin proveedor'}</p></div>
            <div className="room-indicators"><span data-on={row.stream_up ? '1' : '0'}>● Stream</span><span data-on={row.audio_up ? '1' : '0'}>● Audio</span><span data-on={row.transcriber_up ? '1' : '0'}>● Modelo</span></div>
            <strong title="Tiempo interno estimado; el p95 visible se mide en el piloto">{row.latency_ms == null ? '—' : `~${Math.round(row.latency_ms)} ms`}</strong>
            {(row.alarms || []).length > 0 && <div className="room-alarms">{row.alarms.map((alarm) => <span key={alarm.code} data-alarm={alarm.code}>{ALARM_LABELS[alarm.code] || alarm.code}</span>)}</div>}
          </article>)}</div>
        </section>}
        {page === 'rooms' && <><SessionForm csrf={user.csrf_token} onCreated={refresh} desktop={desktop} />{sessionList}</>}
        {page === 'archive' && sessionList}
        {page === 'broadcasts' && <BroadcastPanel desktop={desktop} />}
        {page === 'integrations' && <section className="operator-panel"><p className="section-index">GEMINI</p><h2>Clave de nube</h2>
          <p className="input-hint">Estado: <strong>{cloudKey.configured && ['invalid', 'offline'].includes(cloudKey.state)
            ? 'Clave anterior activa; nueva clave sin validar'
            : ({ missing: 'Sin clave', validating: 'Validando…', ready: 'Clave validada', invalid: 'Clave rechazada', offline: 'Sin conexión a Gemini' })[cloudKey.state] || 'Sin comprobar'}</strong>. El motor local funciona sin clave.</p>
          <form className="field-stack" onSubmit={saveIntegration}><label>Clave de Gemini facturable<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label><button type="submit" disabled={!desktop || !apiKey.trim() || cloudKey.state === 'validating'}>Validar y guardar</button></form>
          {cloudKey.configured && <button type="button" onClick={removeIntegration}>Borrar clave guardada</button>}
          {cloudKey.error && <p className="surface-error" role="alert">{cloudKey.error}</p>}
          <p className="input-hint">La clave se guarda cifrada en el perfil de Windows y no se muestra a la audiencia.</p>
        </section>}
        {page === 'system' && <section className="operator-panel"><p className="section-index">SISTEMA</p><h2>Instalación y estado</h2>
          {desktopStatus ? <dl className="system-status">{Object.entries(desktopStatus.services || {}).map(([name, value]) => <div key={name}><dt>{name}</dt><dd data-on={value ? '1' : '0'}>{value ? 'Activo' : 'Inactivo'}</dd></div>)}{Object.entries(desktopStatus.models || {}).map(([name, value]) => <div key={name}><dt>Modelo {name}</dt><dd data-on={value ? '1' : '0'}>{value ? 'Instalado' : 'Falta instalar'}</dd></div>)}</dl> : <p className="input-hint">Abrí OmniStage de escritorio para controlar fuentes y servicios.</p>}
          {desktopStatus?.gpu && <p className="input-hint">GPU: {desktopStatus.gpu}</p>}
          {desktopStatus?.lanUrls?.map((url) => <p className="input-hint" key={url}>Audiencia LAN: <a href={url} target="_blank" rel="noreferrer">{url}</a></p>)}
        </section>}
      </div>
      <aside className="operator-side">
        {(page === 'overview' || page === 'integrations') && providerPanel}
        {page === 'integrations' && <section className="operator-panel"><p className="section-index">MODELOS</p><h2>Motor local</h2>
          {desktopStatus ? <dl className="system-status">{Object.entries(desktopStatus.models || {}).map(([name, value]) => <div key={name}><dt>{name}</dt><dd data-on={value ? '1' : '0'}>{value ? 'Instalado' : 'Falta instalar'}</dd></div>)}</dl> : <p className="input-hint">Estado disponible desde la app de escritorio.</p>}
          {desktop && <button type="button" onClick={importModels}>Importar paquete de modelos</button>}
        </section>}
        {page === 'integrations' && <section className="operator-panel"><p className="section-index">OBS</p><h2>Salidas de video</h2>
          <p className="input-hint">Instalación en la ruta habitual: {desktopStatus?.obsInstalled ? 'Detectada' : 'No detectada'}. Para tres salidas RTMP, abrí tres instancias OBS con perfiles y puertos WebSocket distintos.</p>
          <a href="https://obsproject.com/download" target="_blank" rel="noreferrer">Descargar OBS Studio ↗</a>
        </section>}
        {page === 'system' && <section className="operator-panel"><p className="section-index">EQUIPO</p><h2>Agregar operador</h2><form className="field-stack" onSubmit={addOperator}><label>Correo<input type="email" required value={newEmail} onChange={(event) => setNewEmail(event.target.value)} /></label><label>Contraseña inicial<input type="password" minLength={12} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label><button type="submit">Crear cuenta</button></form></section>}
      </aside>
    </div>
  </main>;
}

export default function Admin() {
  useSurfaceClass("admin");
  const [user, setUser] = useState(null);
  useEffect(() => { api("/api/operator/me").then(setUser).catch(() => {}); }, []);
  async function logout() {
    try { await api("/api/operator/logout", { method: "POST" }, user.csrf_token); }
    finally { setUser(null); }
  }
  return user ? <Operations user={user} onLogout={logout} /> : <Access onLogin={setUser} />;
}
