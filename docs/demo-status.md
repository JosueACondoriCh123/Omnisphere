# Estado medido de la demo final

Fecha de corte: 24 de septiembre de 2026. Estado de aceptación: **pendiente**.
Este documento registra únicamente comprobaciones ejecutadas; no sustituye
el informe de la hora simultánea de cada ruta.

| Comprobación | Resultado observado |
| --- | --- |
| Pruebas Python | 91 aprobadas; 2 avisos de deprecación de dependencias |
| Pruebas unitarias frontend | 16 aprobadas con `--maxWorkers=1` en la corrida final |
| Pruebas de navegador escritorio/móvil | 20 aprobadas con Chromium Playwright; incluyen navegación de operación y salida protegida de reuniones |
| Credenciales Gemini | 1 prueba Node aprobada: clave ausente, validación, reemplazo rechazado y borrado sin exponer secretos. Falta una clave real |
| Salidas externas | 3 pruebas Node aprobadas: validación de destinos, aislamiento de tres salas y envío único de cláusulas confirmadas a Zoom simulado |
| Linter Python y frontend | sin errores |
| FFmpeg y MediaMTX descargados | ejecutables responden a consulta de versión; SHA256 en `desktop/vendor/manifest.json` |
| Gemma 4 E2B Q4_0 en RTX 4050 | servidor inicia y devuelve una traducción corta válida con razonamiento desactivado; memoria observada del modelo cercana a 1,7 GB en esa prueba |
| faster-whisper-small en CUDA | carga local completada |
| Inferencia CUDA del backend congelado | una cláusula PCM sintética de 1 s atravesó faster-whisper en GPU con las DLL CUDA/cuDNN empaquetadas; sin error de transcripción. No mide calidad ni latencia real |
| API Python congelada | arranca sin invocar Python del entorno; `/healthz`, `/api/time` y `/api/stages` devuelven 200; con ambos modelos `transcriber_up=true` |
| Worker Python congelado | ejecutable arranca y muestra sus argumentos |
| Separación LAN | la ruta de operador devolvió 404 en el origen público de prueba; `netstat` mostró a MediaMTX escuchando solo en `127.0.0.1:1935`, `:8554` y `:9997` tras desactivar MoQ y RTSP UDP |
| Tres flujos sintéticos simultáneos | tres tonos generados por FFmpeg llegaron por RTMP a MediaMTX; el backend con workers congelados informó `stream_up=true` y `audio_up=true` en las tres salas. Esta prueba solo cubre transporte y supervisión, sin subtítulos ni fuentes físicas |
| Salida HLS para reuniones | un flujo H.264/AAC sintético produjo una lista HLS en `127.0.0.1:8888` con HTTP 200; falta compartirlo en Zoom/Meet reales |
| Renovación Live | prueba simulada de cierre y nueva sesión aprobada; falta prueba con cuenta real |
| Colector visible | abrió seis vistas Chromium (tres salas × dos idiomas) contra una fuente sintética y guardó dos captions por sala, uno por idioma; no es una medición del piloto |
| App Electron empaquetada actual | arrancó MediaMTX y backend en un perfil limpio fuera del sandbox, mostró el panel de operación y expuso salud interna/pública 200; API de MediaMTX 200 y ruta de operador en origen público 404 |
| Importación offline de modelos | desde la interfaz empaquetada verificó los cinco SHA256, importó faster-whisper y Gemma en un perfil aislado y mostró ambos instalados |
| Instalador Windows NSIS actual | `desktop/dist/OmniStage Setup 0.1.0.exe`, 928.481.184 bytes, SHA256 `D3C66AC6EA7DF6AFA2E729CCBE0E38E6B4093FA9109A2C81D8B97F9D33610851`; firma de código: no presente |
| Instalación limpia temporal actual | NSIS salió con código 0 y extrajo 4.811 archivos, incluido el backend, medios y cuDNN. La app actual inició desde `win-unpacked` con salud interna/pública 200; el desinstalador temporal salió con código 0 y retiró la carpeta y su entrada de registro. Falta instalar en la PC definitiva |

## Criterios aún sin medición

- No se recibió la clave Gemini en la PC de demo, por lo que no se ejecutó una
  transcripción Live real ni se verificaron minutos y costo facturado.
- No se recibieron las tres grabaciones autorizadas, sus referencias humanas,
  evidencias de permiso ni el ponente para el micrófono. No hay WER, revisión
  bilingüe ni medición de tres salas durante una hora por ruta.
- La prueba de un corte y retorno de Internet, el reinicio durante captura y
  la instalación en la PC definitiva siguen pendientes.
- El p95 visible ≤5 segundos **no está demostrado** para nube ni local. La
  prueba corta de Gemma y la carga de ASR no determinan la decisión de hardware.
- Faltan OBS Studio y cuentas de YouTube/Zoom/Meet en este entorno; los
  adaptadores pasaron pruebas simuladas, pero no se comprobaron tres salidas
  RTMP ni tres reuniones de video reales.
- El adaptador LoRA no se entrenó ni se incorporó; requiere el conjunto
  autorizado, separación por charla y ponente y una GPU externa apta.

El procedimiento y el comando que generan el informe completo a partir de
grabaciones y observaciones medidas están en [demo-final.md](demo-final.md).
