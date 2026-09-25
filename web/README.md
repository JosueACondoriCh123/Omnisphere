# OmniStage — superficies (carril 4)

## Sitio público en Vercel

La landing y las vistas de audiencia usan los mismos componentes y estilos que
la app de escritorio. El proyecto de Vercel debe tener **Root Directory `web`**.
`web/vercel.json` ejecuta `npm run build:vercel`, publica `dist/` y habilita las
rutas `/`, `/dashboard`, `/salas`, `/guia`, `/app`, `/overlay/:stageId` y `/captions/clean`. El panel de operador y
el archivo privado no se incluyen en ese despliegue.

1. Importar el repositorio en Vercel y configurar **Root Directory: `web`**.
2. Desplegar. Sin backend conectado, la landing muestra un estado de espera y
   la vista de muestra (`/app?mock=1`) funciona sin credenciales.
3. Para subtítulos reales, publicar **solo el origen público `8088`** del
   backend mediante un dominio HTTPS. No usar `localhost` ni la API de
   operación `8080` como URL pública.
4. En Vercel, definir `VITE_PUBLIC_API_ORIGIN=https://tu-origen-publico`
   (sin ruta final). Si el WebSocket usa otro origen, añadir
   `VITE_PUBLIC_WS_ORIGIN=wss://tu-origen-websocket`. Ambas variables quedan
   incorporadas al build; cambiar cualquiera exige un nuevo despliegue.
5. En el proceso del backend público, definir
   `OMNISTAGE_PUBLIC_CORS_ORIGINS=https://tu-sitio.vercel.app` (o el dominio
   final). Para varias URLs exactas, separarlas con comas. Reiniciar el backend.

El origen público debe responder a `GET /api/stages` y a
`WSS /ws/stages/{stageId}/{lang}`. Vercel aloja el frontend estático: la
captura, transcripción y publicación siguen ejecutándose en la PC de operación.
No incluir claves Gemini ni otros secretos en variables `VITE_*`.

Comprobación local del build público:

```bash
npm ci
npm run build:vercel
npm run preview
```

Abrir `/`, `/dashboard`, `/salas`, `/guia`, `/app?mock=1` y
`/overlay/1?mock=1`. En el entorno real, comprobar
además que `/api/stages` del origen público responde desde el navegador y que
los subtítulos conectan por WSS.

## Desarrollo local

```bash
npm install
npm test -- --run
npm run build
npm run dev
```

## Demo sin backend

- Audiencia: `http://localhost:5173/app?mock=1`
- Overlay OBS: `http://localhost:5173/overlay/1?theme=obs&lang=es&size=md&mock=1`

El mock reproduce dos drafts y un commit a los 800 ms. En audiencia, el mismo
nodo pasa de gris atenuado a texto sólido; el overlay conserva fondo alfa 0 y
márgenes seguros del 5%.

## Backend

El backend SQLite incluido en `web/server/` guarda operadores, accesos,
sesiones, permisos, configuración del proveedor y subtítulos confirmados. La
base se crea automáticamente en `web/data/omnistage.sqlite` (ignorada por Git).
Requiere Node 22 o posterior con `node:sqlite` disponible.

En dos terminales, desde `web/`:

```bash
npm run db:serve
npm run dev
```

Abrir `http://localhost:5173/operator`. El primer acceso crea el operador
inicial; la contraseña debe tener al menos 12 caracteres. Vite envía `/api/*`
y `/ws/*` al servidor local en `127.0.0.1:8080`. La API pública de audiencia
escucha en `127.0.0.1:8088` y solo ofrece `/healthz`, `/api/time`,
`/api/stages` y `/ws/stages/{stageId}/{lang}`. Las rutas de operador requieren
cookie de sesión y token CSRF; no se sirven desde el puerto público.

Para cambiar las rutas de datos o puertos, definir `OMNISTAGE_DB_PATH`,
`OMNISTAGE_PORT` y `OMNISTAGE_PUBLIC_PORT`. Para publicar el origen de audiencia
en otra máquina, definir `OMNISTAGE_PUBLIC_HOST=0.0.0.0`, terminar HTTPS/WSS
en un proxy y configurar `OMNISTAGE_PUBLIC_CORS_ORIGINS` con los orígenes HTTPS
exactos, separados por comas. Mantener la API de operador en la red local.

El endpoint `POST /api/operator/sessions/{id}/captions` recibe cláusulas
confirmadas del proceso de transcripción. Requiere la cookie del operador y
`X-CSRF-Token`; el cuerpo JSON contiene `clause_id`, `lang` (`es` o `en`),
`t0_ms`, `t1_ms`, `text` y opcionalmente `original`, `provider`, `revision`,
`tier`, `emitted_at_ms` y `audio_end_wall_ms`. Cada cláusula se guarda una sola
vez por sesión e idioma y se envía a los espectadores conectados. Las sesiones
sin permiso de conservación borran sus subtítulos al finalizar; las que lo
tienen los conservan por 30 días. La captura y transcripción de audio necesitan
un proceso aparte que envíe esas cláusulas.

Comprobar la persistencia y la API:

```bash
npm run test:db
```
