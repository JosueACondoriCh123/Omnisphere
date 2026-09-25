# Contratos de integración

## Ingesta

Cada sala publica a un path único:

```text
rtmp://<servidor>:1935/live/stage-<id>
```

`id` admite letras ASCII, números, guion y guion bajo. MediaMTX expone la API de
control sólo dentro de la red de Compose; el orquestador consulta
`GET /v3/paths/list` y transforma un path `ready` en `stream_started`.

## Contexto

Antes de crear el worker, el orquestador pide:

```http
GET {CONTEXT_URL_TEMPLATE}
```

La plantilla recibe `stage_id`, por ejemplo
`http://context/api/stages/{stage_id}/context`. Sin servicio remoto usa
`config/stages.json`. Respuesta:

```json
{
  "name": "Stage 1",
  "session": "Sesión principal",
  "languages": ["es", "en"],
  "glossary": ["Nerdearla"],
  "speakers": []
}
```

## Segmentos hacia el transcriptor

La vía principal entre carriles es Redis:

```text
stage:{stage_id}:audio      AudioSegment producido por Carril 3
stage:{stage_id}:captions   CaptionEvent producido por Carril 2
```

`AudioSegment` contiene la ventana `t0_ms/t1_ms`, PCM s16le 16 kHz mono en
base64, `rms_dbfs`, `is_clause_end` y las trazas `ingest`/`vad`. El fanout de
Carril 3 consume `CaptionEvent`, agrega la traza `fanout` y sólo entrega por WS
el idioma solicitado.

### Puente HTTP opcional

Si `TRANSCRIBER_URL` está definido, el worker hace un `POST` por segmento con
body PCM s16le mono 16 kHz y estos headers:

```text
Content-Type: audio/L16;rate=16000;channels=1
X-Stage-Id: 1
X-Is-Clause-End: true
X-Stage-Context: <json-base64url>
```

`is_clause_end=true` significa que Silero observó cierre por silencio. Si el
segmento se corta al límite de seguridad (`MAX_SEGMENT_SECONDS`), vale `false`.
El transcriptor puede devolver eventos para publicar:

```json
{
  "events": [
    {"lang": "es", "type": "draft", "text": "texto parcial", "seq": 41},
    {"lang": "es", "type": "commit", "text": "Texto final.", "seq": 42,
     "is_clause_end": true}
  ]
}
```

Mientras una cláusula sigue abierta, el worker publica snapshots solapados cada
`PARTIAL_SEGMENT_SECONDS` (1,5 s por defecto). Todos conservan el mismo `t0_ms`
y aumentan `t1_ms`; el cierre de Silero publica el commit final sobre la misma
ventana. El consumidor reconcilia exclusivamente por timestamps, nunca por texto.

También se puede publicar directamente con el token interno:

```http
POST /internal/stages/{stage_id}/{lang}/events
X-Internal-Token: ...
Content-Type: application/json
```

## WebSocket de clientes

```text
ws://<servidor>:8080/ws/stages/{stage_id}/{lang}
```

La suscripción queda indexada por la tupla `(stage_id, lang)`: un evento de otra
sala o idioma no se entrega. El único sobre de caption es:

```json
{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
```

Al conectar, antes de cualquier evento en vivo, se recibe sólo el backlog
`committed` de esa partición:

```json
{ "type": "snapshot", "stage_id": "1", "lang": "es", "captions": [] }
```

Los demás tipos públicos son `stream_started`, `stream_stopped` y
`worker_error`. No existen mensajes de aplicación `hello`, `ping` o `pong`;
WebSocket ya provee control frames para mantener la conexión.

## Métricas

- `GET /api/metrics/stages/{id}`: estado y latencias JSON por sala.
- `GET /api/metrics/stages`: todas las salas conocidas.
- `GET /metrics`: formato Prometheus.
- `GET /readyz`: responde 200 sólo con MediaMTX, Redis y Gemini/transcriber
  listos. `GET /healthz` sigue siendo liveness.
- Alarma `audio_signal_down`: stream listo sin PCM fresco durante 5 s.
- Alarma `latency_over_1500ms`: red + inferencia supera 1.5 s.
- Alarma `transcriber_socket_down`: worker degradado o fallido en transcripción.

La latencia de red es el RTT HTTP observado por el nodo de captura. La latencia
de inferencia mide cada llamada del worker al transcriptor. Las trazas se
ordenan según `HOPS`; el servicio expone p50, p95 y cantidad de muestras para
cada par observado. También publica backlog del VAD, tiempo de publicación a
Redis, reinicios de FFmpeg y clientes WebSocket por sala.
