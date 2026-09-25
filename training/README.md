# Ruta de ajuste Gemma 4

1. Confirmar por cada grabación y ponente permisos de captura, transcripción,
   traducción, envío a Google, publicación, retención y **entrenamiento**. El
   campo `permission_reference` debe apuntar a la evidencia; no se copia el
   documento de consentimiento al repositorio.
2. Crear un manifiesto con `recordings[]`: `id`, `talk_id`, `speaker_id`,
   `audio_path`, `source_lang`, `reference_origin: "human_verified"`,
   `reference_es`, `reference_en`, `clauses` con hipótesis ASR y referencias
   humanas por cláusula (`hypothesis_es/en`, `reference_es/en`),
   `glossary`, `permissions`, `split`.
   Etiquetar manualmente cada referencia sin usar la hipótesis que se evalúa.
3. Ejecutar `python training/prepare_lora.py manifest.json private/`. El
   preparador rechaza permisos ausentes y solapamiento de charla o ponente entre
   entrenamiento y conjunto reservado. El contenido privado queda fuera de Git.
4. En una GPU externa adecuada, instalar `training/requirements.txt` y ejecutar
   `python training/train_lora.py private/train.jsonl private/adapter`. El script
   sigue [la guía oficial de QLoRA de Gemma 4](https://ai.google.dev/gemma/docs/core/huggingface_text_finetune_qlora):
   Gemma 4 E2B, cuantización de 4 bits y adaptador LoRA. No abre el conjunto
   reservado ni publica datos o pesos en Hugging Face.
5. Comparar base, base con glosario y adaptador con los mismos ejemplos
   reservados mediante `scripts/pilot_report.py`. Adoptar el adaptador solo si
   mejora WER, términos y traducción, y después de probar otra vez tres salas,
   una hora y p95 de subtítulo visible ≤5 s en el equipo de producción.

El repositorio no contiene un adaptador entrenado ni afirma mejora de calidad.
La licencia Apache 2.0 de Gemma 4 no confiere derechos sobre las charlas.
