# Datos para ajustar Gemma 4 en OmniStage

El modelo local recibe **texto**: una hipótesis de ASR en español o inglés,
el glosario de la charla y la instrucción de corregir y traducir. Por eso, el
dataset principal debe contener hipótesis reales, correcciones humanas y
traducciones humanas alineadas por cláusula. Los corpus de voz públicos ayudan
a producir y evaluar hipótesis ASR, pero no reemplazan esos pares del evento.

| Prioridad | Fuente | Uso propuesto | Condición |
|---|---|---|---|
| 1 | Charlas y ensayos propios autorizados | Ajuste de corrección y traducción en el dominio de la conferencia | Guardar permiso explícito de entrenamiento y referencia humana independiente; reservar charlas y ponentes enteros para evaluación. |
| 2 | [OMC: corpus trilingüe público](https://www.wto.org/english/res_e/corpus_e/corpus_e.htm), inglés y español | Pares de traducción humana para una fase general de traducción | Uso permitido con reconocimiento de la OMC. El alineado automático puede contener errores; filtrar y revisar una muestra. Su dominio es comercio, no charlas técnicas. |
| 3 | [ALIA Parallel Translation](https://huggingface.co/datasets/SINAI/ALIA-parallel-translation), español e inglés | Pares de traducción para vocabulario biomédico y técnico | CC BY-SA 4.0; revisar fuentes y obligaciones de atribución. Seleccionar un subconjunto pertinente; el corpus completo es demasiado grande y heterogéneo para el primer ajuste. |
| 4 | [Mozilla Common Voice](https://commonvoice.mozilla.org/fr/datasets), español e inglés | Robustez de ASR, acentos y errores realistas para generar hipótesis | Las versiones de voz publicadas por Mozilla se ofrecen bajo CC0; revisar la ficha de la versión descargada. No hay traducción paralela garantizada. |
| 5 | [Google FLEURS](https://huggingface.co/datasets/google/fleurs), `es_419` y `en_us` | Evaluación externa de reconocimiento por idioma/acento | CC BY 4.0: conservar atribución y procedencia. No convertirlo en traducciones supuestamente humanas. |
| 6 | [FLORES+](https://huggingface.co/datasets/openlanguagedata/flores_plus), inglés y español | Medir traducción fuera del evento | Mantener `dev` y `devtest` fuera del entrenamiento; documentar CC BY-SA 4.0. |

Los subtítulos de charlas técnicas [IWSLT TED](https://huggingface.co/datasets/IWSLT/ted_talks_iwslt)
son tentadores por el dominio, pero su ficha indica CC BY-NC-ND 4.0. Asimismo,
[CoVoST 2](https://huggingface.co/datasets/facebook/covost2) indica CC BY-NC
4.0. No incluirlos en el ajuste de una aplicación que pueda tener uso comercial
sin autorización específica.

## Primer lote útil

1. Reunir charlas y ensayos propios con permisos verificables para capturar,
   transcribir, traducir, conservar y entrenar. No subir audios o textos privados
   al repositorio.
2. Para cada cláusula, conservar `hypothesis_es` o `hypothesis_en` según
   `source_lang`, además de `reference_es`, `reference_en` y los términos
   protegidos del glosario.
   Generar las hipótesis con la misma ruta de ASR que usará la app. Una persona
   corrige y traduce sin copiar la hipótesis como referencia.
3. Separar `train` y `holdout` por **charla y ponente**, antes de aumentar datos
   o probar hiperparámetros. No usar FLORES+ `dev`/`devtest` como entrenamiento.
4. Crear el manifiesto que describe [README.md](README.md), ejecutar
   `python training/prepare_lora.py private/manifest.json private/lora` y
   verificar los JSONL. Entrenar solo después de confirmar derechos, calidad,
   ID exacto de Gemma en Hugging Face y disponibilidad de una GPU compatible.

Una mezcla inicial prudente es mayoritariamente material propio verificado;
OMC y ALIA pueden ayudar a preparar la traducción, mientras Common Voice y
FLEURS prueban diversidad acústica. El preparador actual exige audio,
hipótesis y referencias humanas por cláusula: **no acepta los corpus paralelos
por sí solos**. Una fase general con esos corpus necesitaría un convertidor y
una evaluación separados. Ajustar la mezcla con el conjunto reservado, no
con una cifra fija ni con traducciones automáticas presentadas como verdad
humana.
