# Validación B — salidas externas

Fecha: 25/09/2026. Entorno: desarrollo, sin OBS Studio ni cuentas de plataformas.

| Escenario | Estado | Evidencia |
| --- | --- | --- |
| Tres salas RTMP con puertos OBS distintos; detener una no afecta las otras | Aprobado con clientes simulados | `desktop/agent-b-outputs/manager.test.cjs` |
| Autenticación y solicitudes OBS WebSocket v5 | Aprobado con servidor simulado | `desktop/agent-b-outputs/obs-client.test.cjs` |
| Zoom: solo cláusulas confirmadas, envío único y recuperación tras reconexión | Aprobado con HTTP y WebSocket simulados | `desktop/agent-b-outputs/manager.test.cjs` |
| Fallo después de iniciar OBS: detener transmisión, ocultar secretos y permitir reinicio | Aprobado con cliente simulado | `tests/output_manager_resilience.test.cjs` |
| OBS, YouTube, Zoom y Meet reales; audio, video y tres reuniones simultáneas | Bloqueado | Faltan OBS, cuentas y PC definitiva |

Comando ejecutado desde la raíz del proyecto:

```powershell
node --test desktop\agent-a-gemini\*.test.cjs desktop\agent-b-outputs\*.test.cjs tests\output_manager_resilience.test.cjs
```

Resultado conjunto: 9 pruebas Node aprobadas. El gestor ahora intenta `StopStream` si OBS comenzó a transmitir pero la comprobación posterior falla, cierra el cliente y devuelve un error sin datos secretos. La salida puede detenerse y volver a iniciarse.

Comprobaciones pendientes en la PC final: instalar OBS Studio, abrir una instancia y un puerto WebSocket autenticado por sala RTMP, verificar imagen y audio en cada destino real, confirmar subtítulos propios o visibles según plataforma y compartir cada pestaña de Zoom/Meet con audio. Registrar capturas o resultados por sala sin claves, contraseñas ni URL firmadas.
