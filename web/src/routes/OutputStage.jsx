import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { CaptionLane } from '../components/CaptionLane.jsx';
import { useCaptions } from '../lib/useCaptions.js';

export default function OutputStage() {
  const { stageId = '1' } = useParams();
  const [params] = useSearchParams();
  const lang = params.get('lang') === 'en' ? 'en' : 'es';
  const burnIn = params.get('burn') !== '0';
  const [operator, setOperator] = useState(null);
  const [checked, setChecked] = useState(false);
  const { segments } = useCaptions({ stageId, lang, enabled: Boolean(operator) });

  useEffect(() => {
    fetch('/api/operator/me', { credentials: 'same-origin' })
      .then((response) => response.ok ? response.json() : null)
      .then(setOperator)
      .catch(() => setOperator(null))
      .finally(() => setChecked(true));
  }, []);

  if (!/^[123]$/.test(stageId)) return <main className="output-access">Sala inválida.</main>;
  if (!checked) return <main className="output-access">Verificando acceso…</main>;
  if (!operator) return <main className="output-access"><h1>Salida protegida</h1><p>Iniciá sesión como operador en este navegador y volvé a abrir la salida.</p><Link to="/operator">Ingresar</Link></main>;

  return <main className="output-stage" aria-label={`Salida de sala ${stageId}`}>
    <div className="output-stage-video">
      <iframe
        title={`Audio y video sala ${stageId}`}
        src={`http://127.0.0.1:8888/live/stage-${stageId}?muted=false&controls=true`}
        allow="autoplay; fullscreen"
      />
      <div className="output-stage-slate" aria-hidden="true">OMNISTAGE · SALA {stageId}</div>
    </div>
    {burnIn && <div className="output-stage-captions"><CaptionLane segments={segments.slice(-3)} /></div>}
  </main>;
}
