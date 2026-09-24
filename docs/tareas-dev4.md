# Tareas Dev 4 — superficies (OmniStage / Vibeathon Nerdearla)

Repo: `Documents/nerdearla`. Carril 4: las cinco superficies + exports + `docker compose` del front.

**Regla dura:** ninguna tarea edita `contracts/events.py`. Ese archivo está congelado.

**Sobre WebSocket (frontera Dev 3 ↔ Dev 4):** un solo envelope `{type, ...}`. Debe coincidir carácter por carácter con la tarea 3 de `docs/tareas-dev3.md`. El cliente solo baja su sala y su idioma.

```json
{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }
```

Otros `type` que ya define el dominio de streams: `stream_started`, `stream_stopped`, `worker_error`. Se agrega `snapshot`: backlog de captions ya `committed` al conectar (reconexión sin perder texto).

**Qué NO se construye** (antialcance del plan): glosario interactivo · ondas de audio en vivo · reinicio de streams desde el admin · idiomas más allá de es/en · memoria compartida para PCM · autenticación · persistencia más allá de los archivos de export.

## Tabla de tareas

| # | Tarea | Depende de | Est. | Archivos principales |
|---|---|---|---|---|
| 1 | Esqueleto `web/` + `useCaptions` + reconciler JS | — | 2.0 h | `web/`, `web/src/lib/reconciler.js`, `web/src/lib/useCaptions.js` |
| 2 | `/app` PWA audiencia (draft gris → commit sólido) | 1 | 3.0 h | `web/src/routes/App.jsx` |
| 3 | `/overlay/:stageId` Browser Source OBS | 1 | 2.0 h | `web/src/routes/Overlay.jsx` |
| 4 | `/admin` matriz + latencia por salto + alarmas | 1 | 2.5 h | `web/src/routes/Admin.jsx` |
| 5 | `/captions/clean` proyector | 1 | 1.5 h | `web/src/routes/Clean.jsx` |
| 6 | `/archive/:stageId` SRT/VTT/TXT | 1 | 2.0 h | `web/src/lib/export.js`, `web/src/routes/Archive.jsx` |
| 7 | Reconexión WS sin perder committed | 1 + Dev3#3 | 1.5 h | `web/src/lib/useCaptions.js` |
| 8 | `docker compose` sirve el front (nginx) | 2 | 2.0 h | `web/Dockerfile`, `compose.yaml` |

Orden sugerido: 1 → (2 ∥ 3 ∥ 5 ∥ 6) → 4 → 7 → 8. La 7 espera el `snapshot` del Dev 3; hasta entonces mockear el `snapshot` en tests.

---

## Tarea 1 — Esqueleto web + useCaptions + reconciler

```text
Rol: sos Dev 4 del proyecto OmniStage (Vibeathon Nerdearla 2026). Carril 4 = superficies React. Repo en Documents/nerdearla. El backend ya tiene contratos y un reconciliador Python; vos portás la regla al cliente y abrís el WS.

Leé primero (sin editar todavía):
- contracts/events.py  (HOPS, CaptionEvent.state: "draft"|"committed" — NO LO TOQUES)
- carril2/reconciler.py  (regla: commit borra drafts que solapen; draft con t1_ms <= watermark se descarta; NUNCA comparar texto)
- docs/contracts.md  (ruta WS: /ws/stages/{stage_id}/{lang})
- app/main.py  (endpoints existentes; el WS hoy manda hello/ping — el sobre de caption es el de abajo)
- compose.yaml

Contrato que no se toca: contracts/events.py.

Sobre WS congelado (idéntico a Dev3 tarea 3). Un solo envelope {type,...}. caption es la proyección a un idioma:

{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }

También: stream_started, stream_stopped, worker_error, y snapshot (array de captions committed al conectar).

Qué hay que hacer:
1. Crear web/ con Vite + React (JSX, sin TypeScript). Router con rutas placeholder: /app, /overlay/:stageId, /admin, /captions/clean, /archive/:stageId.
2. Implementar web/src/lib/reconciler.js portando la regla de carril2/reconciler.py tal cual:
   - lista ordenada por (t0_ms, t1_ms)
   - apply(caption): si state==="committed", borrar TODO draft cuyo [t0,t1] solape; marcar watermark = max(watermark, t1_ms); lo committed es inmutable
   - si state==="draft" y t1_ms <= watermark → descartar
   - draft nuevo reemplaza drafts que solapen
   - NUNCA comparar strings para decidir reemplazos
3. Implementar web/src/lib/useCaptions.js: abre ws://<host>/ws/stages/{stageId}/{lang}, aplica cada caption al reconciler, expone { segments, status, error }.
4. Test unitario (Vitest o node:test) con eventos sintéticos FUERA DE ORDEN: draft A, draft B que solapa A, commit que solapa A+B, draft tardío con t1 <= watermark. La vista final = solo el commit; cero parpadeo de texto por diff.

Criterio de aceptación (correr y pegar la salida):
  cd web && npm test -- --run
  El test "reconciler out-of-order converges" pasa e imprime exactamente:
  PASS reconciler out-of-order converges
  final=[committed] count=1 text="COMMIT_OK"

Qué NO hacer:
- No editar contracts/events.py
- No construir glosario, ondas de audio, auth, idiomas fuera de es/en, reinicio de streams desde UI
- No implementar las pantallas visuales completas (van en tareas 2–6); solo esqueleto + hook + reconciler
```

---

## Tarea 2 — /app PWA audiencia

```text
Rol: sos Dev 4 de OmniStage (Nerdearla 2026). Carril 4. Repo Documents/nerdearla. Esta tarea es el plano más memorable del video demo: draft en gris que se solidifica al commit.

Leé primero:
- web/src/lib/useCaptions.js y web/src/lib/reconciler.js (tarea 1; si no existen, hacé la tarea 1 primero)
- contracts/events.py (solo lectura: state draft|committed; HOPS)
- config/stages.json (salas disponibles)
- app/main.py rutas /api/stages y /ws/stages/{id}/{lang}

Contrato que no se toca: contracts/events.py.

Sobre WS (no inventes otro shape):

{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }

Qué hay que hacer:
1. Implementar web/src/routes/App.jsx montada en /app.
2. Controles: selector de sala (desde GET /api/stages o config/stages.json como fallback), selector de idioma es|en, tamaño de fuente (S/M/L/XL), toggle alto contraste.
3. Render de segments de useCaptions: state==="draft" → color gris atenuado; state==="committed" → color sólido de alto contraste.
4. Transición visual impecable gris→sólido al llegar el commit (CSS transition de color/opacity ~200–300ms; respetar prefers-reduced-motion). El commit reemplaza drafts solapados vía reconciler — no fades de texto distinto por string match.
5. Manifest PWA mínimo (nombre OmniStage, display standalone, icono simple) + meta viewport.
6. Si no hay backend vivo, incluir un modo ?mock=1 que inyecte drafts y un commit a los 800ms para demo visual.

Criterio de aceptación:
  cd web && npm run build && npm run preview -- --host 127.0.0.1 --port 5173
  Abrir http://127.0.0.1:5173/app?mock=1
  En la consola del navegador (o un script Playwright si lo agregás) debe lograrse:
  - un nodo [data-state=draft] visible con color gris
  - tras el commit mock, ese tramo pasa a [data-state=committed] y getComputedStyle().color deja de ser el gris de draft
  Imprimir al validar: APP_OK draft_to_commit_solidified=1

Qué NO hacer:
- No editar contracts/events.py
- No agregar glosario, ondas, auth, ni más idiomas que es/en
- No tocar el backend Python
```

---

## Tarea 3 — /overlay/:stageId (OBS Browser Source)

```text
Rol: sos Dev 4 de OmniStage. Carril 4. Repo Documents/nerdearla. Esta ruta se usa como Browser Source en OBS real: fondo transparente, lower-third, márgenes seguros de broadcast.

Leé primero:
- web/src/lib/useCaptions.js
- web/src/routes/App.jsx (solo como referencia de tipografía/contraste; no copies el chrome de audiencia)
- docs/contracts.md (WS path)

Contrato que no se toca: contracts/events.py.

Sobre WS:

{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }

Qué hay que hacer:
1. Implementar web/src/routes/Overlay.jsx en /overlay/:stageId.
2. html/body/#root con background transparent (sin color de página). Sin nav, sin selectores.
3. Lower-third: bloque de captions anclado abajo, tipografía legible sobre video, sombra/halo mínimo para legibilidad.
4. Márgenes seguros de broadcast: dejar ~5% del viewport libre en cada borde (safe area); el texto no invade esquinas.
5. Params por URL: ?theme=obs|light|dark (default obs), ?lang=es|en, ?size=sm|md|lg. stageId viene de la ruta.
6. Documentar en un comentario al tope del archivo el URL de ejemplo para OBS:
   http://localhost:8080/overlay/1?theme=obs&lang=es&size=md
   (o el host que use el proxy de la tarea 8).

Criterio de aceptación:
  cd web && npm run build
  Servir el build y abrir /overlay/1?theme=obs&lang=es&size=md&mock=1
  Verificar con DevTools:
  - getComputedStyle(document.documentElement).backgroundColor es rgba(0, 0, 0, 0) o transparent
  - el contenedor de captions tiene padding/inset >= 5vh o 5vw respecto a los bordes
  Imprimir: OVERLAY_OK transparent=1 safe_margins=1
  (La prueba en OBS real Browser Source queda para el dueño del video; el criterio automatizable es transparencia + márgenes.)

Qué NO hacer:
- No editar contracts/events.py
- No agregar UI de control, auth, ni fondos opacos "por si acaso"
- No implementar reinicio de streams
```

---

## Tarea 4 — /admin matriz + latencia por salto + alarmas

```text
Rol: sos Dev 4 de OmniStage. Carril 4. Repo Documents/nerdearla. /admin es el cockpit de ops: matriz de salas, latencia POR SALTO (orden HOPS), alarmas.

Leé primero:
- contracts/events.py  → constante HOPS (orden fijo; NO editar el archivo)
- carril2/tracing.py
- app/main.py  → GET /api/stages y GET /api/metrics/stages/{id} (alarms: audio_signal_down, latency_over_1500ms, transcriber_socket_down)
- web/src/lib/useCaptions.js (para opcionalmente estampar hop "render" en el cliente si el evento trae traces)

Contrato que no se toca: contracts/events.py.

Sobre WS (para leer traces de captions cuando lleguen):

{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }

Qué hay que hacer:
1. Implementar web/src/routes/Admin.jsx en /admin.
2. Polling cada 2s a GET /api/stages (o /api/metrics/stages). Matriz: una fila por stage_id con stream_up, audio_up, worker_state, alarms.
3. Latencia por salto: a partir de traces[] de los últimos captions (y/o campos del API si Dev3 ya expone hops), mostrar columnas en el ORDEN EXACTO de HOPS:
   ingest → vad → tier1 → tier2a → tier2b → reconciler → fanout → render
   Cada celda = delta ms respecto al hop anterior (o "—" si falta). NUNCA mostrar solo un total opaco como única métrica; el total puede existir como suma, pero los saltos son obligatorios.
4. Alarmas visibles (badge/rojo) cuando el API traiga:
   - audio_signal_down (caída de señal de audio)
   - latency_over_1500ms (latencia > 1.5 s)
   - transcriber_socket_down (etiqueta UI: "Gemini/transcriber socket down")
5. Si el API no trae traces aún, mockear una fila de demo con hops incompletos para que el layout no se rompa; documentar el fallback en un comentario.

Criterio de aceptación:
  Con el backend arriba (o mock de /api/stages que incluya alarms:[{code:"audio_signal_down"}]):
  Abrir /admin y confirmar que en <5s tras inyectar la alarma (script o DevTools fetch mock) aparece el badge.
  Comando sugerido de smoke (ajustá host):
  node -e "fetch('http://127.0.0.1:5173/admin').then(r=>console.log('ADMIN_HTTP',r.status))"
  Y un test que parsea el HTML/JSX o un data-testid:
  Imprimir: ADMIN_OK hops_columns=8 alarm_visible=1

Qué NO hacer:
- No editar contracts/events.py
- No agregar botón de reinicio de streams
- No agregar auth, glosario, ni ondas de audio
```

---

## Tarea 5 — /captions/clean proyector

```text
Rol: sos Dev 4 de OmniStage. Carril 4. Repo Documents/nerdearla. /captions/clean es salida a pantalla completa para el proyector de sala: cero chrome, máxima legibilidad.

Leé primero:
- web/src/lib/useCaptions.js
- web/src/routes/App.jsx (reutilizar solo la lógica de render draft/commit, no los controles)

Contrato que no se toca: contracts/events.py.

Sobre WS:

{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }

Qué hay que hacer:
1. Implementar web/src/routes/Clean.jsx en /captions/clean.
2. Query params: ?stage=1&lang=es (defaults razonables).
3. Pantalla completa: tipografía grande, fondo negro o alto contraste, sin nav, sin selectores, sin scrollbars visibles.
4. Layout estable: al llegar un commit, el texto no debe saltar de posición (reservar bloque / usar bottom-anchored queue de las últimas N líneas). Sin scroll automático agresivo que mueva todo el viewport.
5. Draft gris → commit sólido, misma regla visual que /app.

Criterio de aceptación:
  Abrir /captions/clean?stage=1&lang=es&mock=1 en viewport 1920x1080.
  Verificar:
  - document.querySelectorAll('nav,button,select').length === 0
  - el contenedor de texto no tiene overflow scroll (scrollHeight ≈ clientHeight o overflow:hidden)
  - al commit mock, la posición Y del bloque committed no cambia más de 8px
  Imprimir: CLEAN_OK fullscreen=1 no_chrome=1 no_jump=1

Qué NO hacer:
- No editar contracts/events.py
- No meter controles de settings en esta ruta
- No idiomas fuera de es/en
```

---

## Tarea 6 — /archive/:stageId export SRT/VTT/TXT

```text
Rol: sos Dev 4 de OmniStage. Carril 4. Repo Documents/nerdearla. /archive/:stageId descarga .srt, .vtt y .txt desde el buffer committed, con el mismo algoritmo de timestamps que to_srt en Python.

Leé primero:
- carril2/reconciler.py  → funciones to_srt y to_vtt (copiá el algoritmo de timestamps exactamente)
- web/src/lib/reconciler.js / useCaptions.js (fuente del buffer committed)
- contracts/events.py (solo lectura)

Contrato que no se toca: contracts/events.py.

Sobre WS:

{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }

Qué hay que hacer:
1. Implementar web/src/lib/export.js:
   - ms → SRT timestamp: HH:MM:SS,mmm (coma)
   - toSrt(segments, lang), toVtt(segments, lang) espejo de carril2/reconciler.py (VTT = WEBVTT + timestamps con punto)
   - toTxt(segments, lang): una cláusula por línea
   - Solo segmentos state==="committed"
2. Nombre de archivo normalizado:
   nerdearla_2026_stage{stageId}_sesion{session}.srt|.vtt|.txt
   session sale de context (?session=3 o config/stages.json field session; default 1). Ejemplo: nerdearla_2026_stage1_sesion3.srt
3. Ruta /archive/:stageId con botones Descargar SRT / VTT / TXT (lang desde ?lang=).
4. Test unitario: dado un committed {t0_ms:842300,t1_ms:843100,text:"Hola"}, el SRT contiene:
   00:14:02,300 --> 00:14:03,100

Criterio de aceptación:
  cd web && npm test -- --run
  El test "export srt timestamps match to_srt" pasa e imprime:
  PASS export srt timestamps match to_srt
  sample=nerdearla_2026_stage1_sesion3.srt
  cue=00:14:02,300 --> 00:14:03,100
  (Verificación manual posterior: abrir el .srt en VLC con el audio original — no bloquea el merge si el test unitario pasa.)

Qué NO hacer:
- No editar contracts/events.py
- No persistir exports en servidor (solo descarga en el cliente)
- No auth
```

---

## Tarea 7 — Reconexión WS sin perder committed

```text
Rol: sos Dev 4 de OmniStage. Carril 4. Repo Documents/nerdearla. Si cae el socket, el buffer committed NO se borra; al volver, el snapshot del servidor rellena el hueco.

Leé primero:
- web/src/lib/useCaptions.js
- web/src/lib/reconciler.js
- app/main.py websocket handler (hoy manda hello; Dev3 tarea 3 agrega snapshot)
- docs/tareas-dev3.md tarea 3 si existe (shape de snapshot)

Contrato que no se toca: contracts/events.py.

Sobre WS:

{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }

Shape de snapshot (lo emite el servidor al conectar / reconectar):
{ "type": "snapshot", "stage_id": "1", "lang": "es",
  "captions": [ /* solo committed, mismo shape que type=caption con state=committed */ ] }

Qué hay que hacer:
1. En useCaptions: al close/error del WS, NO resetear segments committed. Podés limpiar drafts efímeros o marcar status="reconnecting".
2. Backoff de reconexión (p.ej. 0.5s, 1s, 2s, máx 5s).
3. Al recibir snapshot: apply cada caption committed al reconciler (idempotente ante duplicados de misma ventana/revisión).
4. Test de integración (mock WS):
   - recibir 3 commits
   - simular drop
   - confirmar que committed.length === 3 durante el drop
   - al reconnect, snapshot trae esos 3 (+ opcionalmente uno nuevo)
   - vista final sin cláusulas faltantes

Criterio de aceptación:
  cd web && npm test -- --run
  Test "ws reconnect keeps committed buffer" imprime:
  PASS ws reconnect keeps committed buffer
  during_drop_committed=3
  after_snapshot_committed=3
  missing_clauses=0
  (Prueba manual con backend: matar plumbing 15s durante una charla y verificar en /app — complementaria.)

Qué NO hacer:
- No editar contracts/events.py
- No borrar el buffer "para empezar limpio" al reconnect
- No auth ni persistencia en disco
```

---

## Tarea 8 — docker compose sirve el front

```text
Rol: sos Dev 4 de OmniStage. Carril 4. Repo Documents/nerdearla. Desde máquina limpia, docker compose up -d debe levantar también el front y /app debe cargar y recibir subtítulos.

Leé primero:
- compose.yaml (servicios mediamtx + plumbing hoy)
- Dockerfile (imagen Python del backend — no lo rompas)
- .dockerignore (docs/ ya está excluido; no lo saques)
- web/ (build Vite de las tareas anteriores)

Contrato que no se toca: contracts/events.py.

Sobre WS (el proxy debe reenviar el mismo envelope):

{ "type": "caption", "stage_id": "1", "t0_ms": 842300, "t1_ms": 843100,
  "state": "draft", "revision": 2, "tier": 1, "lang": "es",
  "text": "...", "original": "...", "emitted_at_ms": 843420,
  "traces": [{"hop": "tier1", "t_wall_ms": 843180}] }

Qué hay que hacer:
1. Crear web/Dockerfile multi-stage: node build → nginx:alpine sirviendo dist/.
2. nginx.conf: try_files para SPA; proxy_pass de /api/ y /ws/ hacia el servicio plumbing:8080 (Upgrade headers para WebSocket).
3. Agregar servicio web en compose.yaml:
   - build: ./web
   - ports: "8088:80" (o "80:80" si no choca)
   - depends_on: plumbing
   - misma network nerdearla
4. El cliente debe usar URLs relativas (/ws/..., /api/...) para que el proxy funcione sin hardcodear localhost:8080.
5. Actualizar README.md con una línea: docker compose up -d → abrir http://localhost:8088/app

Criterio de aceptación:
  docker compose up -d --build
  curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8088/app
  debe imprimir 200
  curl -s http://127.0.0.1:8088/api/stages | findstr /i stage_id
  (o jq) debe mostrar JSON de salas
  Imprimir: COMPOSE_OK app_http=200 api_proxied=1

Qué NO hacer:
- No editar contracts/events.py
- No meter docs/ dentro de la imagen
- No agregar autenticación ni servicios extra no pedidos (Redis lo pone Dev3 si aplica)
```

---

## Responsabilidad fuera de código — video demo

Dev 4 es **dueño del video demo** (ventana **10:00–13:00 UTC** del cronograma). No es una tarea de código de esta lista.

Incluye:
- Grabar 1–2 min mostrando ~90% las superficies (`/app` transición gris→sólido, `/overlay` en OBS, `/admin` hops, `/captions/clean`, export).
- Generar los subtítulos en **inglés** del video **con el propio sistema** (`/archive` → `.srt`/`.vtt` en `lang=en`) y muxearlos al upload de YouTube.

Si el `snapshot` del Dev 3 aún no está listo al grabar, usar el mock de la tarea 7 solo para la toma de reconexión; el resto del video debe ser audio real end-to-end.
