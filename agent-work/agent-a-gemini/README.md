# Módulo A: Gemini y credenciales

La implementación inicial está en `desktop/agent-a-gemini/`. Trabajá en esa carpeta y, si hace falta, en los módulos de proveedor del backend acordados con el integrador. No edites las vistas React ni el controlador principal de Electron. Entregá cambios en tu propia carpeta de trabajo antes de integrarlos.

## Contrato de entrega

- `status()` devuelve `missing`, `validating`, `ready`, `invalid` u `offline`, sin incluir nunca la clave.
- `validateAndSave(key)` comprueba la clave con Gemini antes de activar la nube. Una clave rechazada no reemplaza una clave válida anterior.
- `remove()` elimina la clave y devuelve el sistema al modo local.
- La clave se cifra con `safeStorage` y solo se entrega al proceso backend si fue validada.
- Al perder Internet, la transcripción local sigue disponible y la nube puede reintentarse al regresar.

Entregá pruebas de clave ausente, inválida, sustitución, reinicio, borrado, corte de red y ausencia de secretos en respuestas o registros. Informá los archivos modificados y el comando de prueba.

Estado al 25/09/2026: el integrador asumió esta entrega. La clave se verifica
contra los dos modelos requeridos, se cifra con `safeStorage`, y una sustitución
inválida o un corte de red conserva la clave anterior. El backend usa
`google-genai==2.25.0`, aplica el glosario a Live, renueva la sesión y reintenta
cláusulas finales localmente si falla la nube o el modelo todavía se está
cargando. Pruebas: `node --test desktop/agent-a-gemini/*.test.cjs` y
`python -m pytest tests/test_hybrid_failover.py`. Falta la prueba Live con una
clave facturable y grabaciones autorizadas.
