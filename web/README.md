# OmniStage — superficies (carril 4)

## Sitio público en Vercel

La landing y las vistas de audiencia usan los mismos componentes y estilos que
la app de escritorio. El proyecto de Vercel debe tener **Root Directory `web`**.
`web/vercel.json` ejecuta `npm run build:vercel`, publica `dist/` y habilita las
rutas `/`, `/app`, `/overlay/:stageId` y `/captions/clean`. El panel de operador y
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

Abrir `/`, `/app?mock=1` y `/overlay/1?mock=1`. En el entorno real, comprobar
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

En desarrollo, el cliente usa rutas relativas: `/api/*` y
`/ws/stages/{stageId}/{lang}`. Vite las proxifica a `127.0.0.1:8080` durante
desarrollo. En Docker: `docker compose up -d` desde la raíz del repo y abrir
`http://localhost:8088/app`.
