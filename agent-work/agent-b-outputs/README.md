# Agente externo B: salidas en tiempo real

La implementación inicial está en `desktop/agent-b-outputs/`. Trabajá en esa carpeta y en módulos de transporte separados; no edites las vistas React ni el controlador principal de Electron. Entregá cambios en tu propia carpeta de trabajo antes de integrarlos. Cada sala admite un solo destino activo y las tres salas deben funcionar a la vez.

## Contrato de entrega

- `configure(stage, config)`, `start(stage)`, `stop(stage)` y `status()` devuelven estados observables por sala.
- Configuraciones: destino `youtube`, `rtmp`, `zoom` o `meet`; idioma `es`/`en`; subtítulos visibles y nativos cuando corresponda.
- Las salidas consumen solo subtítulos confirmados, identificados por `session_id`, `clause_id` e idioma; reconexiones no duplican envíos.
- YouTube/RTMP usan OBS por sala y controles WebSocket; Zoom admite su URL de subtítulos; Zoom/Meet usan una pestaña local de audio y video que el operador comparte manualmente.
- Claves RTMP, contraseñas OBS y URL firmadas se guardan cifradas mediante el almacén acordado con el integrador. Ninguna ruta pública LAN sirve controles.

Entregá pruebas de tres salas simultáneas, reconexión, corte de red, permisos, aislamiento de audio/video y recepción de subtítulos en las plataformas. Indicá prerequisitos de OBS, Chrome, cuentas y hardware.

Estado inicial: control OBS, subtítulos Zoom/YouTube, configuración cifrada y pestañas de reuniones conectados. Quedan por ensayar con OBS, cuentas reales y tres reuniones simultáneas en la PC final.
