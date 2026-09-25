# Validación A — Gemini y ruta local

Fecha: 25/09/2026. Entorno: desarrollo, sin clave Gemini disponible para este proceso.

| Escenario | Estado | Evidencia |
| --- | --- | --- |
| Clave ausente, validación de ambos modelos, sustitución rechazada, corte de red, reinicio y borrado | Aprobado con respuestas simuladas | `node --test desktop/agent-a-gemini/*.test.cjs` |
| Confirmación en español e inglés, archivo y entrega a ambas particiones del hub | Aprobado con Gemini y sockets simulados | `tests/test_cloud_delivery_integration.py` |
| Fallo de conexión y continuación local sin duplicar cláusulas | Aprobado con fallo simulado | `tests/test_hybrid_failover.py` y `tests/test_cloud_delivery_integration.py` |
| Clave ausente en estados y logs ante un error del proveedor | Aprobado con error simulado que contenía la clave | `tests/test_cloud_delivery_integration.py` |
| Sesión Gemini Live real con frase propia y WebSocket del navegador | Bloqueado en este entorno | No se proporcionó la clave al proceso de prueba; no se afirma validación real |
| Ensayo en la PC definitiva y medición de tres salas durante una hora | Bloqueado | Requiere clave, hardware y grabaciones autorizadas |

Comandos ejecutados desde la raíz del proyecto:

```powershell
node --test desktop\agent-a-gemini\*.test.cjs desktop\agent-b-outputs\*.test.cjs tests\output_manager_resilience.test.cjs
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app\hybrid.py tests\test_cloud_delivery_integration.py
```

Resultado conjunto: 9 pruebas Node, 96 pruebas Python y Ruff aprobados; 2 avisos de deprecación de dependencias.

Cambios de integración: el proveedor ahora limpia la clave de errores de Gemini antes de escribir logs o estado. La prueba de entrega cloud/local valida persistencia, partición por idioma y ausencia de duplicados con componentes simulados. No se guardó ninguna clave real en el proyecto.

Siguiente comprobación en la máquina que tenga la clave: ingresar la clave en **Integraciones**, preparar una sesión con permisos y una frase propia, emitirla a velocidad real y confirmar `provider=gemini-live`, un subtítulo `committed` por idioma, archivo y recepción en los WebSocket del navegador. Registrar únicamente estados y tiempos sin clave ni datos privados.
