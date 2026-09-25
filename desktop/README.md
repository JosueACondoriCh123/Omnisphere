# Instalación Windows para la demo LAN

El instalador Electron incluye API, worker, MediaMTX, FFmpeg y llama.cpp. En la
PC de operación no se necesita Python, Node ni Docker. Cloudflare Tunnel no
forma parte de esta entrega; el público usa `http://IP_DE_LA_PC:8088` en la
misma red local. La API de operación (`8080`), RTMP (`1935`) y RTSP (`8554`)
escuchan solo en loopback.

## Preparar recursos en la máquina de compilación

```powershell
.\.venv\Scripts\python.exe desktop\prepare_vendor.py
.\.venv\Scripts\python.exe desktop\prepare_model_pack.py
.\desktop\build.ps1
.\desktop\package-app-only.ps1
.\desktop\package-offline.ps1
```

`package-app-only.ps1` crea `desktop/release/OmniStage-0.1.4-sin-modelos.7z`:
contiene el instalador, instrucciones y SHA256, pero no los pesos de Gemma ni
faster-whisper. Tras instalar, abrir **Modelos locales** para descargarlos o
importarlos desde otra carpeta, iniciar Gemma y ejecutar una prueba breve.
La ventana de inicio muestra el estado del arranque y permite reintentar si el
backend no responde.

`package-offline.ps1` reúne el instalador y el paquete de modelos ya verificado
en `desktop/release/OmniStage-0.1.3-offline/`. Copiar esa carpeta completa a la
PC final; el instalador y `model-pack` son archivos separados para evitar un
ejecutable NSIS de más de 4 GB. La app importa los modelos desde esa carpeta
con **Importar desde una carpeta** en Primeros pasos. La carpeta de entrega
incluye SHA256 por archivo en `CHECKSUMS.sha256` y un verificador
`VERIFICAR.ps1` para revisar la copia después del traslado.

`prepare_vendor.py` obtiene versiones fijadas de MediaMTX, FFmpeg LGPL shared,
llama.cpp CUDA y sus DLL. También toma la DLL cuDNN verificada de CTranslate2
4.8.2 instalado en `.venv`, y crea `desktop/vendor/manifest.json` con procedencia,
licencia y SHA256 por archivo. `build.ps1` comprueba **todos** esos hashes antes
de producir el instalador NSIS en `desktop/dist/`. Si falta un archivo o aparece
uno no registrado, detiene el empaquetado.

El instalador de esta demo carece de firma de código. Verificar su SHA256 con
`VERIFICAR.ps1` y `CHECKSUMS.sha256` de la carpeta de entrega antes de
ejecutarlo en la PC definitiva.

`prepare_model_pack.py` obtiene revisiones fijadas de
`Systran/faster-whisper-small` y la GGUF QAT Q4_0 oficial de Gemma 4 E2B. El
resultado queda en `desktop/model-pack/` con un manifiesto de tamaños y SHA256.
Es la vía sin internet: el operador copia esa carpeta a un medio local y usa
**Importar desde una carpeta** en Primeros pasos (o **Importar paquete de
modelos** en Integraciones). Con internet, **Descargar modelos** obtiene los
mismos archivos y hashes directamente. La app verifica cada archivo antes de instalarlo en
`%APPDATA%/OmniStage/models/`. La importación no sobrescribe modelos existentes.
Ambas carpetas están excluidas de Git.

La clave Gemini se ingresa en **Integraciones**, se comprueba el acceso a
`gemini-3.5-transcribe-live` y `gemini-3.5-flash-lite` mediante la API y
solo entonces se guarda con `safeStorage` del perfil de Windows. Sin clave
validada, la ruta local sigue disponible. Una clave guardada con versiones
anteriores debe volver a ingresarse para validarla. No se pone en el
repositorio, el manifiesto ni la línea de comandos. Esta comprobación no
confirma facturación ni cuota de Live; verificarlas en el ensayo real.

## Instalar en la PC de operación

Requisitos: Windows 10 u 11 de 64 bits, unos 10 GB libres (≈2,5 GB de la app y
3,6 GB de modelos) y, para el motor local, una GPU NVIDIA con driver actual.
Sin GPU se puede operar con la ruta de nube de Gemini.

1. Ejecutar `OmniStage Setup 0.1.4.exe`. Windows pide permiso de administrador
   una sola vez: el instalador crea la regla de firewall **OmniStage publico
   LAN** (TCP 8088, solo redes Privadas) y la borra al desinstalar. Como el
   instalador no está firmado, SmartScreen muestra "Windows protegió su PC":
   **Más información → Ejecutar de todas formas**, después de verificar el
   SHA256 de `CHECKSUMS.sha256` con `VERIFICAR.ps1`.
2. Al terminar, OmniStage se abre solo (también queda en el Escritorio y en el
   menú Inicio). Crear la cuenta inicial de operador con una contraseña de al
   menos 12 caracteres.
3. La app muestra **Primeros pasos** en Resumen (y siempre en la barra lateral):
   - **Modelos locales → Descargar modelos.** Baja 3,6 GB de Hugging Face en
     revisiones fijadas y verifica el SHA256 de cada archivo antes de
     instalarlo. Se puede pausar; si se corta, retoma desde donde quedó. Sin
     internet, usar **Importar desde una carpeta** con `model-pack/` de la
     carpeta de entrega.
   - **Servicios**: MediaMTX, Gemma, backend y vista pública en *Activo*.
   - **Acceso del público**: muestra la URL LAN (`http://IP_DE_LA_PC:8088`),
     comprueba la regla de firewall y avisa si Windows marcó la red como
     *Pública*, con un botón a la configuración de red para cambiarla a
     *Privada*.
   - **Gemini** (opcional) y **conectar el audio** enlazan a Integraciones y
     Salas.

Descargar los modelos antes del evento: a 1 MB/s tarda cerca de una hora.
`setup-firewall.ps1` queda como alternativa manual si la regla se borró.

Para OBS, usar `rtmp://127.0.0.1:1935/live` y la clave `stage-1`, `stage-2` o
`stage-3`. La app permite seleccionar archivo a velocidad real o micrófono
DirectShow para una sala. Preparar las sesiones con la referencia documental
de permisos antes de activar fuentes.

Para recompilar solo la app de escritorio y la web sin volver a congelar el
backend Python: `.\desktopuild.ps1 -SkipBackend`.

## Salidas externas y pantallas de operación

El panel de operador ahora separa **Resumen**, **Salas**, **Transmisiones**,
**Archivo**, **Integraciones** y **Sistema y operadores**. Las salas y los
WebSocket públicos siguen en `8088`; las pestañas de salida para reuniones
requieren acceso de operador en `127.0.0.1:8080`. MediaMTX sirve HLS de audio
y video únicamente en `127.0.0.1:8888`, para que Chrome pueda compartir la
pestaña con su audio. HLS agrega retraso externo: medirlo por separado del p95
de subtítulos LAN.

OBS Studio 28 o posterior se instala por separado. Para cada sala enviada a
YouTube u otro RTMP/RTMPS, abrir una instancia OBS con su WebSocket autenticado
en un puerto distinto (por ejemplo, 4455, 4456 y 4457). En **Transmisiones**,
guardar servidor, clave, puerto y contraseña; la app crea una escena con la
fuente RTSP de la sala y el overlay, y controla Inicio/Detención. Una sala
puede tener solo un destino externo activo. Si OBS también captura una sala,
esa fuente de entrada ocupa otra instancia o equipo.

Para Zoom, el anfitrión habilita subtítulos manuales y entrega la URL firmada
de subtítulos cuando quiera una pista propia. Para Zoom o Meet con video, el
operador pulsa **Iniciar**, ingresa en Chrome como operador si hace falta,
activa el audio del reproductor y comparte la pestaña de esa sala con audio
desde cada reunión. OmniStage puede preparar una pestaña por cada una de las diez salas; la
confirmación de que están compartidas se hace en cada plataforma. La URL de
Zoom y las claves RTMP se guardan cifradas y no se muestran en el estado.

El instalador compilado y el modelo cargado todavía requieren la matriz de
`docs/piloto.md` en la PC definitiva. La presencia de archivos no certifica
la meta p95 ≤5 s.

El catálogo nativo admite hasta diez salas. El servidor Gemma arranca con tres
ranuras en paralelo; `OMNISTAGE_GEMMA_PARALLEL` permite elegir entre 1 y 10
antes de abrir OmniStage. Aumentarlo también aumenta el contexto total y el
consumo de memoria. Medir latencia y estabilidad en la PC final antes de usar
un valor mayor en producción.
