# OmniStage — piloto híbrido Windows

OmniStage sirve al público salas, subtítulos en español o inglés, overlay OBS y
proyector. La app de operación usa cuentas individuales, sesiones con referencia
documental de permisos, archivo SQLite y exportaciones SRT/VTT/TXT. El runtime
nativo no requiere Redis ni Docker Desktop. El puerto 8080 se liga a loopback
para operar; el puerto 8088 es de lectura para la LAN de esta demo.

El catálogo y los controles admiten hasta **diez salas** (`stage-1` a `stage-10`).
La concurrencia real de subtítulos y salidas en diez salas sigue pendiente de una
prueba de carga en el equipo final; el piloto documentado de tres salas tampoco
equivale a esa validación.

La ruta de nube usa `gemini-3.5-transcribe-live` con PCM continuo y
`gemini-3.5-flash-lite` para traducción. La ruta local usa faster-whisper para
ASR y Gemma 4 E2B cuantizado para corrección/traducción. El modo automático
cambia a local tras fallo de nube. Los subtítulos confirmados se persisten
antes de emitirse y se conservan 30 días por defecto. Las claves se guardan en
el almacén seguro de Windows de Electron.

- [Instalador Windows y recursos requeridos](desktop/README.md)
- [Landing y frontend público preparados para Vercel](web/README.md)
- [Guía de ejecución de la demo](docs/demo-final.md)
- [Estado medido y criterios pendientes](docs/demo-status.md)
- [Matriz de validación y manifiesto de grabaciones](docs/piloto.md)
- [Preparación legal del ajuste LoRA](training/README.md)
- [Datasets prioritarios para el ajuste](training/DATASETS.md)

El sistema **todavía no está certificado para el piloto**: la demo LAN requiere
un instalador probado, modelos cargados, una cuenta Gemini facturable y
grabaciones con permisos y referencias humanas. El objetivo de tres salas con
p95 visible ≤5 s sigue siendo un criterio de aceptación pendiente de medir en
hardware real. La landing para Vercel está preparada; conectar el origen público
mediante un dominio HTTPS o Cloudflare Tunnel queda para una fase posterior.

- [Guía de cierre de la demo LAN](docs/demo-final.md)

## Stack anterior para desarrollo (Compose)

El contenido siguiente describe el stack anterior de desarrollo con Redis y
Docker. Puede usarse para regresión, pero no representa el instalador nativo.

# Nerdearla 2026 — Carril 3: plomería

Plomería de audio en vivo por sala: ingesta RTMP, normalización FFmpeg, Silero
VAD, workers aislados, bus Redis, WebSocket particionado, métricas y nodo de
captura auto-registrable.

## Arranque

```bash
cp .env.example .env
# completar GEMINI_API_KEY en .env
docker compose up -d
curl http://localhost:8080/readyz
```

El front (PWA, overlay, admin, proyector y archivo) queda en
`http://localhost:8088/app`. Nginx proxea `/api` y `/ws` al servicio de plomería.

Esto levanta Redis, MediaMTX, plomería, el transcriptor Gemini y el front. Los
puntos principales son:

| Uso | Dirección |
|---|---|
| Publicar sala 1 | `rtmp://localhost:1935/live/stage-1` |
| WS español sala 1 | `ws://localhost:8080/ws/stages/1/es` |
| Métricas sala 1 | `http://localhost:8080/api/metrics/stages/1` |
| Métricas Prometheus | `http://localhost:8080/metrics` |
| HLS de diagnóstico | `http://localhost:8888/live/stage-1/index.m3u8` |
| OpenAPI | `http://localhost:8080/docs` |
| PWA audiencia | `http://localhost:8088/app` |
| Overlay OBS | `http://localhost:8088/overlay/1?theme=obs&lang=es&size=md` |
| Admin | `http://localhost:8088/admin` |
| Proyector | `http://localhost:8088/captions/clean?stage=1&lang=es` |
| Archivo SRT/VTT/TXT | `http://localhost:8088/archive/1?lang=es&session=3` |

El orquestador consulta MediaMTX una vez por segundo. Cuando ve
`live/stage-1`, carga contexto y crea un proceso worker exclusivo para sala 1.
Si la publicación desaparece, conserva el worker durante 15 s y FFmpeg intenta
reconectar dentro del mismo proceso. Un corte de 10 s mantiene el mismo PID y
retoma sin duplicar la sala.

`/healthz` indica que la API está viva; `/readyz` exige además MediaMTX, Redis y
el transcriptor Gemini. Si falta o falla la credencial, el front sigue accesible
y `/admin` muestra `Gemini/transcriber socket down`.

## Prueba sin hardware

Este comando suma un emisor sintético que se registra solo y publica en sala 1:

```bash
docker compose --profile demo up -d
docker compose logs -f plumbing demo-publisher
```

Comprobar el resultado:

```bash
curl http://localhost:8080/api/metrics/stages/1
```

El ruido rosa valida señal, FFmpeg, registro y métricas. No pretende activar el
VAD de voz. Para probar segmentación, publicar una voz real con OBS o FFmpeg.

## Nodo de captura en un comando

Desde una máquina Linux con ALSA y acceso al servidor:

```bash
docker compose --profile capture run --rm capture-node \
  --stage 1 --server rtmp://SERVIDOR:1935 \
  --api-url http://SERVIDOR:8080 --input-format alsa --source hw:0
```

El nodo se registra en `/api/capture-nodes/register`, envía heartbeat y su RTT,
y publica AAC a `live/stage-1`. Para una fuente PulseAudio, usar
`--input-format pulse --source default`. En macOS usar `avfoundation`; en una
captura nativa de Windows, `dshow`. Si el contenedor no tiene acceso al
dispositivo del host, ejecutar el módulo en Python local o publicar desde OBS.

OBS no necesita el nodo: Server `rtmp://SERVIDOR:1935/live` y Stream Key
`stage-1`.

La configuración de firewall, bindeos y el comando para otra máquina están en
[docs/captura.md](docs/captura.md).

## Cadena de audio

Cada worker ejecuta exactamente:

```text
highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11:linear=true
→ PCM s16le · 16 kHz · mono
→ Silero VAD streaming (frames de 512 muestras)
```

Silero marca `is_clause_end=true` cuando detecta el silencio que cierra un
segmento. Durante el habla se publican drafts solapados cada 1,5 s desde el mismo
inicio de cláusula; el commit final reemplaza esos drafts por timestamps. Un
corte forzado por duración máxima queda en `false`, para no confundir un límite
operativo con un cierre lingüístico.

## Integración con transcripción

Carril 3 publica cada `AudioSegment` a `stage:{id}:audio`. Carril 2 publica sus
`CaptionEvent` a `stage:{id}:captions`; el fanout los convierte al idioma
pedido por cada WS. `TRANSCRIBER_URL` queda como puente HTTP opcional para una
integración externa. Los contratos están en [docs/contracts.md](docs/contracts.md).

## Configuración

Copiar `.env.example` a `.env` y cambiar al menos `INTERNAL_TOKEN` antes de
exponer el servicio. Las salas, idiomas, glosario y speakers locales viven en
`config/stages.json`; `CONTEXT_URL_TEMPLATE` permite reemplazarlos por un
servicio remoto.

## Pruebas

```bash
docker compose run --rm --no-deps plumbing pytest -q
docker compose config --quiet
```

Prueba escalonada con los WAV del corpus y reporte de CPU, backlog VAD, Redis y
p95 `ingest→fanout`:

```bash
python scripts/loadtest.py --rooms 6,8,10 --duration 45
```

El resultado queda en `loadtest-report.md`; `--dry-run` permite inspeccionar
todos los comandos FFmpeg sin publicar.

## Validación real con OBS

En OBS usar servicio personalizado, Server `rtmp://localhost:1935/live` y Stream
Key `stage-1`. La fuente de navegador del overlay es
`http://localhost:8088/overlay/1?theme=obs&lang=es&size=md`. Con la transmisión
iniciada, ejecutar:

```powershell
.\.venv\Scripts\python.exe scripts\validate_live_demo.py --stage 1 --langs es,en
```

Hablar durante tres segundos y hacer una pausa. El comando exige un draft y un
commit solapados en ambos idiomas y comprueba que el commit reaparece en el
snapshot de reconexión; no acepta eventos generados con `?mock=1`.
