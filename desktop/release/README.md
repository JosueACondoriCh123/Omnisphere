# Entregas de OmniStage Desktop

Esta carpeta muestra en GitHub la estructura y los archivos pequeños necesarios
para verificar la instalación. Los instaladores, archivos `.7z` y pesos de
modelos se generan localmente y se excluyen de Git por su tamaño.

## Versión 0.1.4: sin modelos

La carpeta [`OmniStage-0.1.4-sin-modelos`](OmniStage-0.1.4-sin-modelos/)
contiene instrucciones, SHA256 y el verificador. En la máquina de compilación
también contiene `OmniStage Setup 0.1.4.exe`; el archivo comprimido para
distribución es `OmniStage-0.1.4-sin-modelos.7z` (856 MiB).

Para que otras personas puedan descargarlo desde GitHub, adjuntá el `.7z` como
**asset de una Release** de la versión `v0.1.4`. El archivo no debe agregarse
con `git add`: el código y la documentación permanecen livianos. Una vez
publicado, agregá el enlace de descarga real al README principal.

El SHA256 del `.7z` preparado localmente es
`93ca85bb0c5acb548486734d154421536c91c585c41f9127470e01a88659f26d`.
Los modelos se descargan desde la app o se importan por separado.
