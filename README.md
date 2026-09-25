# OmniStage — Plataforma Híbrida de Subtitulado y Traducción en Vivo

OmniStage es una plataforma de subtitulado y traducción bilingüe en tiempo real (español e inglés) diseñada para conferencias técnicas y eventos en vivo con soporte de hasta **diez salas simultáneas** (`stage-1` a `stage-10`).

Cuenta con una **arquitectura híbrida de tolerancia total a fallos (zero-downtime)**: opera con **Google Gemini Live** en la nube para transcripción y traducción de ultra baja latencia, y conmuta automáticamente a inferencia local en GPU mediante **faster-whisper** y **Gemma 4 E2B** si se produce una desconexión o fallo de red.

---

## Arquitectura y Motor de IA

```text
[ Fuentes de Audio ] (OBS / Micrófonos / RTMP)
       │
       ▼
[ Plomería & VAD ] (MediaMTX + FFmpeg normalizado + Silero VAD)
       │
       ├──► [ Ruta Nube (Principal) ]
       │      ├─ Transcripción: Gemini Live (gemini-3.5-transcribe-live, streaming PCM continuo)
       │      └─ Traducción: Gemini 3.5 Flash Lite (preservación de glosario y Spanglish)
       │
       └──► [ Ruta Edge / Local (Failover Automático) ]
              ├─ Transcripción: faster-whisper (CUDA INT8/FP16)
              └─ Traducción/Corrección: Gemma 4 E2B Q4_0 (llama-server local, ~1.7 GB VRAM)
```

- **Ruta de Nube:** Transcripción mediante streaming PCM continuo con Gemini Live y traducción contextual con Gemini 3.5 Flash Lite. Las claves API se almacenan cifradas en Windows DPAPI mediante `safeStorage`.
- **Ruta Local:** Inferencia en GPU NVIDIA local. Si la nube pierde conectividad o agota reintentos, el backend degrada instantáneamente a inferencia local sin perder cláusulas ni reiniciar la sesión.
- **Reconciliador Anti-Parpadeo:** Emite hipótesis intermedias en streaming (*drafts* en gris atenuado) que se consolidan en texto definitivo (*commits* en blanco sólido) en cuanto el VAD detecta una pausa lingüística.

---

## Separación de Dominios y Seguridad

OmniStage separa estrictamente el tráfico público del entorno de operación:

1. **Origen Público (LAN / Vercel / CDN — Puerto `8088` o Dominio HTTPS):**
   - Diseñado para la audiencia, proyectores de escenario y zócalos de streaming.
   - Solo lectura: expone `/app`, `/overlay/:stageId`, `/captions/clean`, `/healthz`, `/api/stages` y los WebSockets de subtítulos.
   - Cualquier intento de acceder a rutas de operador o gestión desde este origen devuelve **404 Not Found**.

2. **Origen de Operación (Privado — Puerto `8080` estrictamente en Loopback):**
   - Enlazado exclusivamente a `127.0.0.1:8080` en la máquina de control.
   - Inaccesible desde la red LAN o internet.
   - Controla inicio de sesiones con referencia documental de permisos, ingreso de credenciales Gemini, base de datos SQLite y exportación de archivos (SRT, VTT, TXT).

3. **Ingesta de Medios (Loopback `127.0.0.1`):**
   - Servidor RTMP (`1935`) y RTSP (`8554`) limitados a loopback local para ingesta de OBS y dispositivos locales de captura.

---

## Matriz de Superficies y Endpoints de Producción

En producción, sustituir `<IP_DE_LA_PC>` por la dirección IP de la máquina de control en la red local o `<DOMINIO_PUBLICO>` / `<DOMINIO_WS>` si se utiliza Vercel o un túnel HTTPS/WSS.

| Superficie / Uso | Formato de Producción (LAN / Vercel) | Ámbito / Acceso |
|---|---|---|
| **PWA de Audiencia** | `https://<DOMINIO_PUBLICO>/app`<br>o `http://<IP_DE_LA_PC>:8088/app` | Público (asistentes desde móviles/navegadores) |
| **Overlay para OBS** | `https://<DOMINIO_PUBLICO>/overlay/:stageId?theme=obs&lang=es&size=md`<br>o `http://<IP_DE_LA_PC>:8088/overlay/:stageId?theme=obs&lang=es&size=md` | Streaming (Browser Source transparente) |
| **Proyector de Auditorio** | `https://<DOMINIO_PUBLICO>/captions/clean?stage=1&lang=es`<br>o `http://<IP_DE_LA_PC>:8088/captions/clean?stage=1&lang=es` | Pantallas de sala (alto contraste, sin distracciones) |
| **WebSocket de Subtítulos** | `wss://<DOMINIO_WS>/ws/stages/:stageId/:lang`<br>o `ws://<IP_DE_LA_PC>:8088/ws/stages/:stageId/:lang` | Público (transmisión en tiempo real por sala e idioma) |
| **API Pública de Salas** | `GET /api/stages` (en origen público) | Público (catálogo y estado básico de salas activas) |
| **Salud Pública** | `GET /healthz` (en origen público) | Público / Balanceador |
| **Consola de Operador (Admin)** | `http://127.0.0.1:8080/` (o interfaz OmniStage Desktop) | **Privado** (solo operador en loopback local) |
| **Archivo y Exportación** | `http://127.0.0.1:8080/operator/archive` (o interfaz Desktop) | **Privado** (descarga de SRT, VTT y TXT de charlas cerradas) |
| **Ingesta RTMP (OBS / Emisor)** | `rtmp://127.0.0.1:1935/live/:stageId` | **Privado** (máquina local de emisión) |
| **Salida HLS para Reuniones** | `http://127.0.0.1:8888/live/:stageId/index.m3u8` | Loopback local (puente a Zoom / Google Meet) |

---

## Instalación y Ejecución

### 1. Aplicación de Escritorio Nativa (Windows)
OmniStage no requiere Docker ni Redis en producción. El instalador empaqueta la API, los workers asíncronos, MediaMTX, FFmpeg, llama.cpp y dependencias CUDA.

- **Instalador NSIS:** `desktop/dist/OmniStage Setup 0.1.4.exe`
- Requisitos: Windows 10/11 (64 bits), GPU NVIDIA (recomendado para ruta local, ej. RTX 4050 con ~1.7 GB VRAM libre), 10 GB de disco.
- Al instalar, crea automáticamente la regla de firewall local para el puerto `8088` en redes Privadas.
- **Modelos:** Se pueden descargar en el primer inicio desde la app (vía Hugging Face con verificación de SHA256) o importar offline mediante un paquete generado con `desktop/prepare_model_pack.py`.
- Más información en [Instalador Windows y recursos requeridos](desktop/README.md).

### 2. Despliegue del Frontend Público en Vercel
La landing y las vistas de audiencia/overlay pueden alojarse de forma distribuida en Vercel:

1. Importar el repositorio en Vercel y definir **Root Directory: `web`**.
2. Variables de entorno en Vercel:
   - `VITE_PUBLIC_API_ORIGIN=https://tu-origen-publico` (apuntando al backend expuesto en puerto 8088 vía túnel HTTPS).
   - `VITE_PUBLIC_WS_ORIGIN=wss://tu-origen-websocket` (apuntando al endpoint WSS).
3. En la máquina anfitriona del backend, configurar:
   - `OMNISTAGE_PUBLIC_CORS_ORIGINS=https://tu-sitio.vercel.app`
4. Desplegar con `npm run build:vercel`.
- Más información en [Landing y frontend público en Vercel](web/README.md).

---

## Ingesta de Audio en Vivo

- **Desde OBS Studio:**
  - Servidor: `rtmp://127.0.0.1:1935/live`
  - Clave de transmisión: `stage-1` (o la sala correspondiente: `stage-2` ... `stage-10`).
- **Desde la Aplicación OmniStage:**
  - Se puede asignar directamente un micrófono físico de la máquina (DirectShow) o un archivo de audio a velocidad real a cualquier sala desde el panel de control.

---

## Pruebas y Validación

```powershell
# Pruebas unitarias y de integración de backend
pytest -q

# Pruebas del reconciliador y vistas frontend
cd web
npm test -- --run
npm run test:vercel

# Pruebas de credenciales, salidas y modelos locales (Node)
cd desktop
npm test
```

Para la ejecución de la prueba formal de carga, cálculo de p95 de latencia y generación de reportes de calidad, consultar la [Guía de ejecución de la demo](docs/demo-final.md).

---

## Documentación de Referencia

- [Instalador Windows y recursos requeridos](desktop/README.md)
- [Landing y frontend público preparados para Vercel](web/README.md)
- [Guía de ejecución y cierre de la demo](docs/demo-final.md)
- [Estado medido y criterios pendientes](docs/demo-status.md)
- [Matriz de validación y manifiesto de grabaciones](docs/piloto.md)
- [Preparación y recetas de ajuste LoRA para Gemma 4](training/README.md)
- [Datasets prioritarios para el ajuste](training/DATASETS.md)
