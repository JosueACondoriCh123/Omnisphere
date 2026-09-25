# OmniStage — superficies (carril 4)

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

El cliente usa rutas relativas: `/api/*` y
`/ws/stages/{stageId}/{lang}`. Vite las proxifica a `127.0.0.1:8080` durante
desarrollo. En Docker: `docker compose up -d` desde la raíz del repo y abrir
`http://localhost:8088/app`.
