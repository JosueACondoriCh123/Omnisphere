# Componentes de terceros de la demo privada

Las versiones, URL de origen, licencia declarada, tamaño y SHA256 exactos de
cada binario distribuido están en `runtime/manifest.json` dentro de la
instalación. El paquete de modelos lleva su propio `manifest.json` y se
importa por separado después de verificar cada SHA256.

| Componente | Versión fijada | Licencia declarada | Origen |
| --- | --- | --- | --- |
| FFmpeg compartido | n9.0 LGPL, build BtbN | LGPL-2.1-or-later | https://github.com/BtbN/FFmpeg-Builds |
| MediaMTX | v1.21.1 | MIT | https://github.com/bluenviron/mediamtx |
| llama.cpp / llama-server | b11149, CUDA 12.4 | MIT | https://github.com/ggml-org/llama.cpp |
| CUDA DLL para llama.cpp | artefacto CUDA 12.4 de llama.cpp | licencia de redistribución NVIDIA aplicable | https://docs.nvidia.com/cuda/eula/ |
| cuDNN DLL para CTranslate2 | CTranslate2 4.8.2 / cuDNN 9.10.2.21 | términos de redistribución NVIDIA cuDNN aplicables | https://pypi.org/project/ctranslate2/4.8.2/ |
| faster-whisper-small | revisión `536b0662742c02347bc0e980a01041f333bce120` | MIT | https://huggingface.co/Systran/faster-whisper-small |
| Gemma 4 E2B QAT Q4_0 GGUF | revisión `675cff42a74c774d6cb76f76d8eacb49b48c9b93` | Apache-2.0 | https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf |

Este registro identifica los componentes y sus términos para la demo. Antes
de redistribuir el instalador o el paquete fuera del equipo del piloto se
deben completar los avisos y obligaciones de cada licencia, incluidos los
componentes transitivos del ejecutable Python y Electron. Los permisos sobre
las charlas y grabaciones se verifican por separado; las licencias de los
modelos no autorizan por sí solas el entrenamiento ni la publicación de audio.
