# Ejecución y cierre de la demo LAN

## Entrega privada previa

Crear `private/manifest.json` con tres grabaciones autorizadas, referencias
independientes en español e inglés y una referencia documental por ponente.
Usar los campos descritos en [piloto.md](piloto.md); dejar `observations: []`.
El audio y los consentimientos no se copian a Git. La clave Gemini se introduce
en la app Windows, nunca en el manifiesto ni en este documento.

Para el micrófono físico, la app pide un destino WAV antes de capturar. Ese WAV
es un original elegido por el operador para preparar una referencia humana;
las copias temporales del procesamiento siguen sin conservarse. Registrar
permiso de captura y retención antes de iniciar. Crear un identificador y una
referencia humana distintos para la hora cloud y la hora local.

## Preparación en Windows

1. Ejecutar `desktop/prepare_vendor.py`, `desktop/prepare_model_pack.py` y
   `desktop/build.ps1` en la máquina de compilación. Guardar los manifiestos y
   SHA256 de instalador y paquete junto al material privado de la demo.
2. Instalar el EXE en la PC anfitriona, importar la carpeta del paquete de
   modelos, crear operadores individuales e ingresar la clave facturable.
3. Abrir solo TCP 8088 en el perfil de red **Privada** con
   `desktop/setup-firewall.ps1`. Verificar desde un segundo dispositivo LAN
   `/app`, `/overlay/1`, `/captions/clean` y sus WebSocket. Los controles de
   operador y RTMP deben seguir inaccesibles desde ese dispositivo.
4. Preparar las sesiones en salas 1, 2 y 3 con permisos documentados. Usar OBS
   en sala 1, archivo a velocidad real en sala 2 y micrófono físico en sala 3.

## Medición de las dos rutas

El colector abre **seis vistas reales** (tres salas, dos idiomas), sincroniza
su reloj con `/api/time`, espera a que las tres salas tengan audio y el
proveedor elegido esté listo, y recién entonces inicia la hora. Registra el
momento posterior al pintado del subtítulo y conserva un checkpoint cada 30 s.
La incertidumbre de reloj máxima admitida es 100 ms; el informe suma esa
incertidumbre a cada latencia para no mejorar artificialmente el p95.
El inicio de latencia es el fin estimado de la cláusula en el PCM que entrega
FFmpeg al worker; se descuenta el atraso de procesamiento VAD. No incluye
una medición directa del retardo acústico, OBS ni de la red anterior a FFmpeg.
El informe también compara cada cláusula final de VAD con una confirmación
persistida y con ambas vistas pintadas; una discrepancia impide aprobar.

En `web/`, iniciar el colector antes de activar las fuentes. Sustituir `IP`,
identificadores y rutas. El archivo de salida pertenece a `private/`.

```powershell
node scripts/collect-pilot.mjs --base-url http://IP:8088 --route cloud `
  --recordings 1:obs-cloud,2:file-cloud,3:mic-cloud `
  --sources 1:obs,2:file,3:microphone `
  --out ../private/cloud-capture.json
```

Usar modo **Nube preferida**. Al finalizar, cerrar las sesiones, preparar
otras nuevas, elegir **Gemma local** y repetir con `--route local`, nuevos
identificadores y `--out ../private/local-capture.json`. El ponente del
micrófono participa en ambas horas. Guardar los WAV originales y producir
referencias humanas sin usar la hipótesis del sistema evaluado.

Comparar después las mismas tres grabaciones iniciales por ambas rutas en
ensayos separados, a velocidad real, para que WER y calidad de traducción
sean comparables. Registrar revisión bilingüe de errores de sentido y términos.

Con las referencias completas, generar el informe:

```powershell
.\.venv\Scripts\python.exe scripts\pilot_report.py private\manifest.json `
  --capture private\cloud-capture.json --capture private\local-capture.json `
  --output private\report.json --require-pilot
```

Registrar el costo real de Google en `cloud_cost_usd_actual` de cada observación
cuando esté disponible; el costo calculado por tokens y minutos es solo una
estimación. El comando falla si alguna ruta no tiene tres salas y una hora,
ambos idiomas por cláusula, cero duplicados y pérdidas, señales/proveedor
estables y p95 visible ≤5 s **por sala e idioma**.

## Fallas y ensayo de la presentación

En una corrida separada del benchmark, cortar Internet, comprobar que el panel
muestre el proveedor local y que las vistas LAN sigan recibiendo subtítulos;
restaurar Internet y comprobar el reintento de Gemini. Reiniciar el backend,
reconectar las seis vistas y confirmar que el archivo, SRT/VTT/TXT y los IDs
de cláusula no se duplican. Probar cuentas individuales, denegación de
controles por LAN y purga a los 30 días.

El guion de presentación: abrir inicio y elegir sala; mostrar español e inglés
en dos espectadores; mostrar overlay OBS y proyector; enseñar el proveedor y
la señal reales; hacer el corte controlado; abrir archivo y exportar SRT.
Si alguna ruta o el hardware no supera el informe, mostrar el resultado medido
con el criterio pendiente y no anunciar el piloto como aprobado.
