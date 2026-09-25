# Agente externo A: Gemini y credenciales

La implementación inicial está en `desktop/agent-a-gemini/`. Trabajá en esa carpeta y, si hace falta, en los módulos de proveedor del backend acordados con el integrador. No edites las vistas React ni el controlador principal de Electron. Entregá cambios en tu propia carpeta de trabajo antes de integrarlos.

## Contrato de entrega

- `status()` devuelve `missing`, `validating`, `ready`, `invalid` u `offline`, sin incluir nunca la clave.
- `validateAndSave(key)` comprueba la clave con Gemini antes de activar la nube. Una clave rechazada no reemplaza una clave válida anterior.
- `remove()` elimina la clave y devuelve el sistema al modo local.
- La clave se cifra con `safeStorage` y solo se entrega al proceso backend si fue validada.
- Al perder Internet, la transcripción local sigue disponible y la nube puede reintentarse al regresar.

Entregá pruebas de clave ausente, inválida, sustitución, reinicio, borrado, corte de red y ausencia de secretos en respuestas o registros. Informá los archivos modificados y el comando de prueba.

Estado inicial: validación REST, almacén cifrado y contrato IPC conectados; quedan por verificar la sesión Gemini Live y la cuenta real.
