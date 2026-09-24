# Tareas Dev 3 — plomería (OmniStage / Vibeathon Nerdearla)

Repo: `Documents/nerdearla`. Carril 3: ingesta, audio, VAD, fanout, métricas,
resiliencia y captura LAN.

**Regla dura:** ninguna tarea edita `contracts/events.py`. Ese archivo está
congelado. Si el código no coincide, se adapta el código consumidor.

**Frontera Dev 3 ↔ Dev 4 congelada:** un solo envelope `{type, ...}`. El cliente
sólo baja su sala e idioma.

```json
{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
```

Otros `type`: `stream_started`, `stream_stopped`, `worker_error` y `snapshot`.
El `snapshot` se manda al conectar y contiene sólo captions `committed`.

## Tabla de tareas

| # | Tarea | Depende de | Est. | Archivos principales |
|---|---|---|---:|---|
| 1 | FastAPI + lifespan + endpoints internos y captura | — | 2.5 h | `app/main.py` |
| 2 | Reloj de stream + `AudioSegment` a Redis | 1 | 3.0 h | `app/room_worker.py`, `compose.yaml`, `Dockerfile` |
| 3 | Fanout captions → WS + snapshot | 1, 2 | 2.5 h | `app/fanout.py`, `app/main.py`, `app/state.py` |
| 4 | Estado y métricas por salto | 1, 3 | 2.0 h | `app/main.py`, `app/metrics.py` |
| 5 | Histéresis RTMP y reconexión FFmpeg | 1, 2 | 2.0 h | `app/orchestrator.py`, `app/room_worker.py` |
| 6 | Carga escalonada de 6–10 salas | 4, 5 | 1.5 h | `scripts/loadtest.py` |
| 7 | Captura auto-registrable desde la LAN | 1 | 1.0 h | `compose.yaml`, `.env.example`, `docs/captura.md` |

Orden sugerido: 1 → 2 → 3 → 4 → 5 → 6; la 7 puede hacerse en paralelo desde
que termina la 1.

---

## Tarea 1 — FastAPI y costuras operativas

```text
Rol: sos Dev 3 de OmniStage para la Vibeathon Nerdearla 2026.
Tu carril es la plomería de audio y eventos en vivo.
El repo está en Documents/nerdearla y esta tarea crea la superficie FastAPI que une lo existente.

Leé primero (sin editar todavía):
- app/orchestrator.py
- app/state.py
- app/capture_node.py
- app/domain.py
- app/config.py
- Dockerfile
- compose.yaml
- contracts/events.py (sólo lectura)

Contrato que no se toca:
- NO editar contracts/events.py: AudioSegment, CaptionEvent, TraceStamp y HOPS están congelados.
- WS caption debe tener exactamente este shape:
  { "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
    "state": "draft", "revision": 2, "tier": 1, "lang": "es",
    "text": "...", "original": "...", "emitted_at_ms": 843420,
    "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
- Otros type públicos: stream_started, stream_stopped, worker_error y snapshot.

Qué hay que hacer:
1. Crear app/main.py con FastAPI y lifespan: al entrar arranca StageOrchestrator; al salir lo cierra limpiamente.
2. Exponer GET /healthz y GET /readyz. readyz debe reflejar MediaMTX y Redis, no devolver 200 si una dependencia requerida está caída.
3. Exponer POST /api/capture-nodes/register y POST /api/capture-nodes/{node_id}/heartbeat con los modelos existentes. La respuesta de registro devuelve stage, heartbeat_seconds, rtmp_path y rtmp_url.
4. Exponer POST /internal/workers/{stage_id}/heartbeat y POST /internal/stages/{stage_id}/{lang}/events. Ambos requieren x-internal-token con comparación contra Settings.
5. Exponer WS /ws/stages/{stage_id}/{lang} usando WebSocketHub. Validar stage/lang y no mezclar particiones.
6. Configurar CORS sólo para los métodos usados y shutdown ordenado.
7. Agregar tests con TestClient para health, token interno y partición WS.

Criterio de aceptación (correr y pegar la salida):
  docker compose up -d
  docker compose ps
  curl -fsS http://localhost:8080/healthz
  docker compose --profile demo up -d demo-publisher
El servicio plumbing aparece healthy, healthz imprime {"status":"ok"} y /api/stages contiene stage 1 con el nodo demo registrado.

Qué NO hacer:
- No editar contracts/events.py.
- No crear UI, glosario interactivo, ondas de audio, auth ni persistencia de captions.
- No implementar idiomas fuera de es/en ni reinicios de stream desde el admin.
- No meter lógica de transcripción o traducción en FastAPI.
```

## Tarea 2 — Reloj de stream y AudioSegment a Redis

```text
Rol: sos Dev 3 de OmniStage para la Vibeathon Nerdearla 2026.
Tu carril transporta audio normalizado y segmentado desde cada sala.
El repo está en Documents/nerdearla y esta tarea repara el contrato de salida del worker.

Leé primero (sin editar todavía):
- contracts/events.py (sólo lectura; AudioSegment.from_pcm y TraceStamp)
- app/room_worker.py
- app/config.py
- requirements.txt
- compose.yaml
- Dockerfile
- config/mediamtx.yml

Contrato que no se toca:
- NO editar contracts/events.py.
- Canal de salida: stage:{stage_id}:audio con AudioSegment serializado por to_json().
- WS caption futuro, que esta tarea no publica:
  { "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
    "state": "draft", "revision": 2, "tier": 1, "lang": "es",
    "text": "...", "original": "...", "emitted_at_ms": 843420,
    "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
- Otros type públicos: stream_started, stream_stopped, worker_error y snapshot.

Qué hay que hacer:
1. Mantener la cadena FFmpeg exacta: highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11:linear=true; salida pcm_s16le, 16000 Hz, mono.
2. Contar muestras PCM consumidas de manera monotónica por worker. Derivar t0_ms y t1_ms del número de muestras, nunca de datetime.now().
3. Alimentar Silero en frames de 512 muestras y conservar todos los bytes de la ventana. Un evento end produce is_clause_end=true; un corte por MAX_SEGMENT_SECONDS o interrupción produce false.
4. Construir AudioSegment.from_pcm(...) por ventana. Las ventanas consecutivas deben ser contiguas: siguiente t0_ms == anterior t1_ms, sin huecos ni superposición.
5. Estampar traces ingest y vad con TraceStamp y publicar JSON en Redis Pub/Sub, canal stage:{id}:audio.
6. Agregar Redis a requirements y compose; Dockerfile debe copiar contracts/ antes de arrancar.
7. Mantener el puente HTTP TRANSCRIBER_URL sólo como opción de compatibilidad, no como transporte primario.

Criterio de aceptación (correr y pegar la salida):
  docker compose up -d
  docker compose exec redis redis-cli SUBSCRIBE stage:1:audio
  docker compose --profile demo up -d demo-publisher
Redis imprime AudioSegment JSON con pcm_b64 no vacío, traces ingest/vad y ventanas consecutivas donde t0 del segmento N+1 coincide con t1 del N.

Qué NO hacer:
- No editar contracts/events.py.
- No usar memoria compartida para PCM ni persistir audio en disco.
- No sumar glosario, UI, autenticación ni idiomas fuera de es/en.
- No falsificar cierre de cláusula en un corte forzado.
```

## Tarea 3 — Fanout Redis a WebSocket y snapshot

```text
Rol: sos Dev 3 de OmniStage para la Vibeathon Nerdearla 2026.
Tu carril entrega captions del bus al navegador sin cruzar salas ni idiomas.
El repo está en Documents/nerdearla y esta tarea congela la frontera con Dev 4.

Leé primero (sin editar todavía):
- contracts/events.py (sólo lectura; CaptionEvent y TraceStamp)
- app/state.py
- app/main.py
- app/domain.py
- app/config.py
- docs/contracts.md

Contrato que no se toca:
- NO editar contracts/events.py.
- Consumir CaptionEvent desde stage:{stage_id}:captions.
- Proyectar exactamente este envelope, sin wrapper data/payload:
  { "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
    "state": "draft", "revision": 2, "tier": 1, "lang": "es",
    "text": "...", "original": "...", "emitted_at_ms": 843420,
    "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
- Otros type públicos: stream_started, stream_stopped y worker_error.
- Al conectar se manda {"type":"snapshot","stage_id":"1","lang":"es","captions":[...]} con sólo committed.

Qué hay que hacer:
1. Crear un suscriptor Redis que descubra stage:*:captions, deserialice CaptionEvent sin alterar el contrato y agregue el hop fanout.
2. Para cada idioma es/en crear la proyección text correspondiente; original conserva text.original.
3. Publicar sólo en WebSocketHub[(stage_id, lang)]. Un cliente de stage 1/es no recibe stage 2 ni en.
4. Guardar en RuntimeState un backlog acotado sólo de committed por (stage_id, lang), ordenado por t0_ms/t1_ms y con la mayor revision para una misma ventana.
5. Iniciar/cerrar el fanout en el lifespan de FastAPI.
6. Mandar snapshot inmediatamente después de aceptar el WS. No mandar hello/ping/pong JSON: los control frames pertenecen al protocolo WebSocket.
7. Agregar tests de partición, envelope exacto y reconexión.

Criterio de aceptación (correr y pegar la salida):
  wscat -c ws://localhost:8080/ws/stages/1/es
  docker compose exec redis redis-cli PUBLISH stage:1:captions '<CaptionEvent JSON válido>'
La primera conexión recibe snapshot; luego recibe caption con type/state y lang=es. Al reconectar, el snapshot incluye ese caption sólo si era committed y nunca incluye drafts.

Qué NO hacer:
- No editar contracts/events.py ni renegociar nombres de campos.
- No comparar texto para reconciliar ni entregar todos los idiomas al cliente.
- No agregar persistencia externa, auth, glosario interactivo u ondas.
- No construir las pantallas del Carril 4.
```

## Tarea 4 — Matriz de estado y métricas por salto

```text
Rol: sos Dev 3 de OmniStage para la Vibeathon Nerdearla 2026.
Tu carril debe volver observable el pipeline por sala y por salto.
El repo está en Documents/nerdearla y esta tarea alimenta el admin de Dev 4.

Leé primero (sin editar todavía):
- contracts/events.py (sólo lectura; orden HOPS)
- carril2/tracing.py si existe
- app/state.py
- app/main.py
- app/fanout.py
- app/room_worker.py

Contrato que no se toca:
- NO editar contracts/events.py ni reordenar HOPS.
- Envelope WS:
  { "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
    "state": "draft", "revision": 2, "tier": 1, "lang": "es",
    "text": "...", "original": "...", "emitted_at_ms": 843420,
    "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
- Otros type: stream_started, stream_stopped, worker_error y snapshot.

Qué hay que hacer:
1. Crear app/metrics.py con distribuciones acotadas por (stage_id, from_hop, to_hop). Calcular deltas sólo entre hops presentes y en el orden congelado de HOPS.
2. Exponer p50, p95 y n, tanto en JSON por sala como en /metrics formato Prometheus.
3. Exponer GET /api/stages y GET /api/metrics/stages[/{id}] con stream, audio, capture node, worker, latencia de red/inferencia, estado y alarmas.
4. Alarmas mínimas: audio_signal_down, latency_over_1500ms y transcriber_socket_down.
5. Reportar backlog VAD, último publish Redis, reinicios FFmpeg, segmentos producidos y clientes WS por sala para diagnosticar carga.
6. Observar trazas al hacer fanout, después de agregar el hop fanout.
7. Mantener muestras acotadas para no crecer sin límite y agregar tests de percentiles.

Criterio de aceptación (correr y pegar la salida):
  curl -fsS http://localhost:8080/api/metrics/stages/1
  curl -fsS http://localhost:8080/metrics | grep nerdearla_hop_latency_ms
Tras pasar captions por una sala, /metrics imprime series p50 y p95 para pares de hops con n > 0; el JSON incluye hop_latencies y alarmas deterministas.

Qué NO hacer:
- No editar contracts/events.py ni inventar hops.
- No agregar Grafana, base de series temporales, auth o control remoto de streams.
- No construir el admin visual.
- No esconder una dependencia caída devolviendo ceros como si fueran mediciones reales.
```

## Tarea 5 — Histéresis RTMP y reconexión sin cambiar PID

```text
Rol: sos Dev 3 de OmniStage para la Vibeathon Nerdearla 2026.
Tu carril mantiene una sala viva ante microcortes del publicador.
El repo está en Documents/nerdearla y esta tarea endurece orquestador y worker sin duplicarlos.

Leé primero (sin editar todavía):
- app/orchestrator.py
- app/room_worker.py
- app/config.py
- app/state.py
- config/mediamtx.yml
- contracts/events.py (sólo lectura)

Contrato que no se toca:
- NO editar contracts/events.py.
- Envelope WS estable:
  { "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
    "state": "draft", "revision": 2, "tier": 1, "lang": "es",
    "text": "...", "original": "...", "emitted_at_ms": 843420,
    "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
- Otros type: stream_started, stream_stopped, worker_error y snapshot.

Qué hay que hacer:
1. Agregar STREAM_GRACE_SECONDS configurable, default 15 s.
2. Cuando MediaMTX deja de listar una sala, marcar offline_since; no detener el worker hasta vencer el grace. Si vuelve antes, limpiar el timer y reutilizar el proceso existente.
3. Nunca crear un segundo worker para una sala cuyo proceso sigue vivo.
4. Dentro de RoomWorker, cargar Silero una sola vez y relanzar FFmpeg en loop con pausa configurable. El PID del worker y el reloj de muestras sobreviven al relanzamiento.
5. Al cortar, terminar FFmpeg hijo y cerrar Redis/HTTP ordenadamente. Reportar estado degraded y motivo mientras reconecta.
6. Vaciar de forma segura la ventana parcial al interrumpirse el stream con is_clause_end=false.
7. Agregar test asíncrono de grace y un contador ffmpeg_restarts en heartbeat/métricas.

Criterio de aceptación (correr y pegar la salida):
  PID_ANTES=$(docker compose exec plumbing pgrep -f 'app.room_worker.*--stage 1')
  # detener el publicador 10 segundos y volverlo a iniciar
  PID_DESPUES=$(docker compose exec plumbing pgrep -f 'app.room_worker.*--stage 1')
  test "$PID_ANTES" = "$PID_DESPUES"
El test termina con exit 0, existe un solo PID antes/después y /api/metrics/stages/1 vuelve a audio_up=true sin intervención manual.

Qué NO hacer:
- No editar contracts/events.py.
- No reiniciar todo Compose por una sala ni matar workers de otras salas.
- No resetear el reloj de stream en cada reconexión.
- No agregar controles de reinicio al admin, memoria PCM compartida o persistencia.
```

## Tarea 6 — Carga escalonada de 6, 8 y 10 salas

```text
Rol: sos Dev 3 de OmniStage para la Vibeathon Nerdearla 2026.
Tu carril debe declarar con evidencia dónde deja de sostener tiempo real.
El repo está en Documents/nerdearla y esta tarea crea una prueba operativa repetible.

Leé primero (sin editar todavía):
- app/main.py
- app/metrics.py
- app/room_worker.py
- evaluation/corpus/audio/
- compose.yaml
- contracts/events.py (sólo lectura)

Contrato que no se toca:
- NO editar contracts/events.py.
- Envelope WS observado indirectamente:
  { "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
    "state": "draft", "revision": 2, "tier": 1, "lang": "es",
    "text": "...", "original": "...", "emitted_at_ms": 843420,
    "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
- Otros type: stream_started, stream_stopped, worker_error y snapshot.

Qué hay que hacer:
1. Crear scripts/loadtest.py sin dependencias nuevas obligatorias.
2. Aceptar --rooms 6,8,10, --audio-dir, --duration, --rtmp-base, --api-base y --report.
3. Lanzar N FFmpeg concurrentes con -re y WAV reales en loop, uno por stage-load-N. Terminarlos siempre en finally.
4. Muestrear /api/metrics/stages y docker stats durante cada nivel.
5. Registrar p95 ingest→fanout, máximo backlog VAD, máximo publish Redis, CPU, RAM y cantidad de streams activos.
6. Definir umbrales por flags; marcar quiebre si faltan streams/muestras o se supera CPU, VAD o Redis.
7. Escribir tabla Markdown y una línea exacta 'Número de salas donde se rompe: N'. Agregar --dry-run para inspección sin publicar y tests de parsing/reporte.

Criterio de aceptación (correr y pegar la salida):
  python scripts/loadtest.py --rooms 6,8,10 --duration 45 --report loadtest-report.md
  type loadtest-report.md
El archivo contiene una fila para 6, 8 y 10 salas, columnas p95 ingest→fanout/CPU/backlog VAD/Redis y la línea que declara el primer número de salas donde se rompe (o 'no observado').

Qué NO hacer:
- No editar contracts/events.py.
- No inventar métricas cuando no hay samples: usar n/a y marcar quiebre.
- No generar carga sin -re ni dejar procesos FFmpeg huérfanos.
- No añadir dashboards, UI, auth ni datos persistentes.
```

## Tarea 7 — Captura auto-registrable desde otra máquina

```text
Rol: sos Dev 3 de OmniStage para la Vibeathon Nerdearla 2026.
Tu carril debe poder desplegar una laptop de captura con un solo comando.
El repo está en Documents/nerdearla y esta tarea deja lista la historia LAN.

Leé primero (sin editar todavía):
- app/capture_node.py
- app/main.py
- app/config.py
- compose.yaml
- .env.example
- config/mediamtx.yml
- contracts/events.py (sólo lectura)

Contrato que no se toca:
- NO editar contracts/events.py.
- Envelope WS que no cambia por este despliegue:
  { "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
    "state": "draft", "revision": 2, "tier": 1, "lang": "es",
    "text": "...", "original": "...", "emitted_at_ms": 843420,
    "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
- Otros type: stream_started, stream_stopped, worker_error y snapshot.

Qué hay que hacer:
1. Agregar PUBLIC_RTMP_HOST/PORT y bindeos RTMP/API configurables. Defaults 0.0.0.0 para puertos públicos; mantener RTSP, HLS y métricas MediaMTX en loopback.
2. Hacer que register devuelva rtmp://PUBLIC_RTMP_HOST:PORT/live/stage-{id}.
3. Verificar que capture_node se registra, recibe/usa la URL y envía heartbeat con RTT, estado FFmpeg y bytes.
4. Documentar en docs/captura.md la configuración .env, puertos 1935/8080, firewall limitado a la subred y diagnóstico.
5. Documentar un comando de una línea para PulseAudio/ALSA, variantes macOS/Windows, --demo y los campos Server/Stream Key de OBS.
6. Incluir comprobación curl de health y métricas de la sala.

Criterio de aceptación (correr y pegar la salida):
  python -m app.capture_node --stage 1 --server rtmp://IP_SERVIDOR:1935 --api-url http://IP_SERVIDOR:8080 --input-format pulse --source default
  curl -fsS http://IP_SERVIDOR:8080/api/metrics/stages/1
Desde otra máquina de la LAN el nodo se registra, RTMP llega a live/stage-1 y la métrica capture_node_up pasa a true con network_ms no nulo.

Qué NO hacer:
- No editar contracts/events.py.
- No exponer Redis, RTSP o la API interna de MediaMTX a toda la LAN.
- No sumar descubrimiento mDNS, autenticación, UI, glosario u ondas.
- No hardcodear una IP personal en compose ni en el código.
```
