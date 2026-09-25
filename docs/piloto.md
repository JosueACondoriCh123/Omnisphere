# Matriz de validación del piloto

## Preparación

Crear un manifiesto privado JSON con `recordings[]` y `observations[]`.
Cada grabación requiere `id`, `talk_id`, `speaker_id`, `audio_path`, `source_lang`,
`reference_origin: "human_verified"`, transcripciones de referencia
`reference_es` y `reference_en`, `glossary`, `permission_reference` y
`permissions` separados para `capture`, `transcribe`, `translate`, `cloud`,
`publish`, `retain` y `train`. Documentar el alcance por ponente y charla. No
incluir material privado en Git. El reporte rechaza referencias generadas por
la misma hipótesis evaluada; por eso el WER 0 % del corpus antiguo no es una
medición de rendimiento real.

Cada observación lleva `recording_id`, `route` (`legacy`, `cloud`, `local`,
`local-glossary`, `local-lora`), `stage_id`, `source_type`, tiempos de inicio y
fin, memoria GPU máxima, minutos de audio de nube, tokens de traducción y
`captions[]`. Cada subtítulo tiene `session_id`, `clause_id`, `lang`, `state`,
`t0_ms`, `text`, `audio_end_wall_ms` y `visible_wall_ms`. Medir
`visible_wall_ms` tras pintar el texto en navegador o proyector, con relojes
sincronizados; la recepción WebSocket por sí sola no es visibilidad.

```
python scripts/pilot_report.py private/manifest.json --output private/report.json
```

El reporte calcula WER del original, similitud de traducción por bigramas de
caracteres, conservación de glosario, duplicados, p95 visible, memoria y
estimación de nube. Los precios de la estimación son los publicados para
Transcribe Live (USD 0,009/min sumando entrada y salida aproximadas) y Flash-Lite
(USD 0,30/M tokens de entrada y USD 2,50/M de salida) al 23 de septiembre de
2026; contrastar con facturación real antes de decidir. La métrica de
traducción es una señal automática, no reemplaza revisión bilingüe humana.

## Casos obligatorios

1. Tres salas simultáneas durante una hora, con audio autorizado y los dos
   idiomas en cada sala; p95 visible ≤5 segundos para nube y local.
2. OBS, archivo reproducido a velocidad real y micrófono, cada uno asignado a
   una sala. Verificar reinicio y reconexión sin pérdida ni duplicación.
3. Cortar Internet, constatar proveedor local, servicio LAN y archivo;
   restaurar Internet y medir recuperación automática de Gemini. El dominio y
   HTTPS/WSS externos quedan para una fase posterior a esta demo LAN.
4. Mantener Live por más de diez minutos y verificar renovación anticipada.
5. Probar cuentas individuales, CSRF, cierre de sesión, denegación pública de
   controles/RTMP, exportaciones SRT/VTT/TXT y eliminación tras 30 días.
6. Comparar tres rutas sobre **las mismas** grabaciones y referencias humanas:
   segmento anterior, Transcribe Live y local. Repetir base, glosario y LoRA
   sobre el conjunto reservado antes de adoptar un adaptador.

Si la RTX 4050 de 6 GB no sostiene tres salas y p95 ≤5 s, ejecutar la misma
matriz en una máquina propuesta con más VRAM; no cambiar el umbral.
