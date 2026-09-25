import { useCallback, useEffect, useRef, useState } from 'react';

const empty = () => ({ destination: 'youtube', lang: 'es', burn_in: true, native_captions: true,
  server: '', stream_key: '', zoom_url: '', obs_port: 4455, obs_password: '' });

const STATE_LABELS = {
  idle: 'Sin configurar', configured: 'Configurada', preparing: 'Preparando',
  streaming: 'Transmitiendo', ready_to_share: 'Lista para compartir', error: 'Error',
};

export default function BroadcastPanel({ desktop }) {
  const [statuses, setStatuses] = useState({});
  const [forms, setForms] = useState({ 1: empty(), 2: empty(), 3: empty() });
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const hydrated = useRef(false);

  const refresh = useCallback(async () => {
    if (!desktop?.outputStatus) return;
    const next = await desktop.outputStatus();
    setStatuses(next);
    if (!hydrated.current) {
      hydrated.current = true;
      setForms((old) => Object.fromEntries(['1', '2', '3'].map((stage) =>
        [stage, { ...old[stage], ...next[stage]?.config, stream_key: '', zoom_url: '', obs_password: '' }])));
    }
  }, [desktop]);

  useEffect(() => {
    const initial = setTimeout(() => refresh().catch(() => {}), 0);
    const timer = setInterval(() => refresh().catch(() => {}), 3000);
    return () => { clearTimeout(initial); clearInterval(timer); };
  }, [refresh]);

  function update(stage, key, value) {
    setForms((old) => ({ ...old, [stage]: { ...old[stage], [key]: value } }));
  }

  async function action(stage, name) {
    setBusy(`${stage}:${name}`); setError('');
    try {
      if (!desktop) throw new Error('Abrí OmniStage de escritorio para operar las salidas.');
      if (name === 'save') await desktop.configureOutput(stage, forms[stage]);
      if (name === 'start') await desktop.startOutput(stage);
      if (name === 'stop') await desktop.stopOutput(stage);
      if (name === 'open') await desktop.openOutput(stage);
      await refresh();
    } catch (exc) { setError(`Sala ${stage}: ${exc.message}`); }
    finally { setBusy(''); }
  }

  return <section className="operator-panel broadcast-panel">
    <div className="panel-heading"><div><p className="section-index">DISTRIBUCIÓN</p><h2>Destinos por sala</h2></div><span>03</span></div>
    <p className="input-hint">Cada sala admite un destino externo activo. En Zoom y Meet, la app prepara una pestaña con audio y video; compartila desde la reunión.</p>
    {!desktop?.outputStatus && <p className="surface-error">Los controles de transmisión requieren la app de escritorio actualizada.</p>}
    {error && <p className="surface-error" role="alert">{error}</p>}
    <div className="broadcast-grid">{['1', '2', '3'].map((stage) => {
      const form = forms[stage];
      const entry = statuses[stage] || {};
      const running = ['preparing', 'streaming', 'ready_to_share', 'error'].includes(entry.state);
      const needsRtmp = ['youtube', 'rtmp'].includes(form.destination);
      return <article className="broadcast-room" key={stage}>
        <div className="broadcast-room-heading"><h3>Sala {stage}</h3><span data-on={entry.state === 'streaming' || entry.state === 'ready_to_share' ? '1' : '0'}>{STATE_LABELS[entry.state] || 'Sin configurar'}</span></div>
        <p className="input-hint">Destino guardado: {entry.config?.destination || 'ninguno'} · {entry.config?.lang?.toUpperCase() || '—'}</p>
        <div className="field-stack">
          <label>Destino<select value={form.destination} disabled={running} onChange={(event) => update(stage, 'destination', event.target.value)}><option value="youtube">YouTube Live</option><option value="rtmp">Otro RTMP/RTMPS</option><option value="zoom">Zoom</option><option value="meet">Google Meet</option></select></label>
          <label>Idioma<select value={form.lang} disabled={running} onChange={(event) => update(stage, 'lang', event.target.value)}><option value="es">Español</option><option value="en">English</option></select></label>
          <label className="check-row"><input type="checkbox" checked={form.burn_in} disabled={running} onChange={(event) => update(stage, 'burn_in', event.target.checked)} /> Subtítulos visibles en video</label>
          {form.destination !== 'meet' && form.destination !== 'rtmp' && <label className="check-row"><input type="checkbox" checked={form.native_captions} disabled={running} onChange={(event) => update(stage, 'native_captions', event.target.checked)} /> Subtítulos propios de la plataforma</label>}
          {needsRtmp && <>
            <label>Servidor RTMP/RTMPS<input value={form.server} disabled={running} onChange={(event) => update(stage, 'server', event.target.value)} placeholder="rtmps://…" /></label>
            <label>Clave de transmisión<input type="password" autoComplete="off" value={form.stream_key} disabled={running} onChange={(event) => update(stage, 'stream_key', event.target.value)} placeholder={entry.config?.has_stream_key ? 'Clave guardada: volver a ingresar para cambiar' : ''} /></label>
            <label>Puerto WebSocket de OBS<input type="number" min="1" max="65535" value={form.obs_port} disabled={running} onChange={(event) => update(stage, 'obs_port', Number(event.target.value))} /></label>
            <label>Contraseña WebSocket de OBS<input type="password" autoComplete="off" value={form.obs_password} disabled={running} onChange={(event) => update(stage, 'obs_password', event.target.value)} /></label>
          </>}
          {form.destination === 'zoom' && form.native_captions && <label>URL de subtítulos de Zoom<input type="password" autoComplete="off" value={form.zoom_url} disabled={running} onChange={(event) => update(stage, 'zoom_url', event.target.value)} /></label>}
        </div>
        {entry.error && <p className="surface-error" role="alert">{entry.error}</p>}
        <div className="broadcast-actions">
          <button type="button" disabled={!desktop || running || Boolean(busy)} onClick={() => action(stage, 'save')}>Guardar destino</button>
          <button type="button" disabled={!desktop || !entry.config || running || Boolean(busy)} onClick={() => action(stage, 'start')}>Iniciar</button>
          <button type="button" disabled={!desktop || !running || Boolean(busy)} onClick={() => action(stage, 'stop')}>Detener</button>
          {entry.share_url && <button type="button" disabled={!desktop || Boolean(busy)} onClick={() => action(stage, 'open')}>Abrir pestaña de reunión</button>}
        </div>
        {entry.share_url && <p className="input-hint">Si no se abre en Chrome, copiá esta URL en una pestaña de Chrome: <code>{entry.share_url}</code>. Activá el audio del reproductor y compartí esa pestaña con audio.</p>}
        {needsRtmp && <p className="input-hint">OBS usa la fuente local <code>rtsp://127.0.0.1:8554/live/stage-{stage}</code> y el overlay de esta sala. Cada salida necesita una instancia OBS con puerto WebSocket distinto.</p>}
      </article>;
    })}</div>
  </section>;
}
