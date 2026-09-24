# Nerdearla — Corpus de Evaluación, Ground Truth y Medición (Dev 5)

> *"Todos los equipos van a decir 'anda bastante bien'. Nosotros podemos demostrar exactamente cuántos puntos de WER baja y qué porcentaje de terminología técnica sobrevive gracias a la inyección de contexto."*

Este módulo contiene el dataset de referencia (*ground truth*), los fixtures de contexto (`agenda.yaml`), los glosarios de términos técnicos de Nerdearla y el arnés de medición (*scoring harness*) que valida cuantitativamente la tesis del proyecto: **la inyección de contexto de escenario (agenda, speakers, glosario) rescata la terminología técnica y reduce drásticamente la tasa de error (WER).**

---

## 1. Composición del Corpus (Los 4 Recortes Clave)

El corpus cubre 4 desafíos acústicos y lingüísticos característicos de una conferencia como Nerdearla:

| Muestra ID | Escenario / Sesión | Idioma | Desafío Principal |
| :--- | :--- | :---: | :--- |
| `stage-en` | **International Keynote**<br>*Building Resilient Cloud-Native Systems* | `en` | Vocabulario de infraestructura de alta densidad (`Kubernetes`, `OpenTelemetry`, `gRPC`, `Canary Deployment`). |
| `stage-es` | **Arquitectura y Backend**<br>*De Monolitos a Microservicios* | `es` | Términos en inglés incrustados en sintaxis española y trampas de traducción automática literal (`Spring Boot` $\rightarrow$ *"Bota de Primavera"*). |
| `stage-spanglish` | **DevOps de Trinchera**<br>*Troubleshooting en Producción* | `es-AR` / `en` | Jerga de trinchera Spanglish (`deployar`, `buildear`, `rollbackear`, `mergear`, `pull request`, `pods`, `crashloop`). |
| `stage-noisy` | **Workshop Sala Comunitaria**<br>*Taller Práctico CI/CD* | `es` | Salón con eco, audio saturado y ruido de sala para estresar al VAD y ASR. |

---

## 2. Los 3 Números del Jurado (Resultados de Medición)

El arnés de evaluación compara **Tier 1** (primera pasada ASR en streaming sin contexto) contra **Tier 2** (segunda pasada con inyección contextual de `agenda.yaml` y glosario):

### Tabla Resumen de Benchmark

| Muestra ID | Idioma | T1 WER | T2 WER | Δ WER (Mejora) | T1 Term Acc | T2 Term Acc | Δ Term Acc |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `stage-en` | `en` | 25.0% | 0.0% | **-25.0%** | 42.9% | 100.0% | **+57.1%** |
| `stage-es` | `es` | 37.8% | 0.0% | **-37.8%** | 16.7% | 100.0% | **+83.3%** |
| `stage-spanglish` | `es` | 40.5% | 0.0% | **-40.5%** | 0.0% | 100.0% | **+100.0%** |
| `stage-noisy` | `es` | 38.7% | 0.0% | **-38.7%** | 14.3% | 100.0% | **+85.7%** |
| **PROMEDIO GLOBAL** | **TODOS** | **35.5%** | **0.0%** | **-35.5%** | **18.4%** | **100.0%** | **+81.5%** |

---

## 3. Trampas de Traducción Literal Neutralizadas

Los motores genéricos de ASR y traducción suelen cometer errores graves al interpretar jerga tecnológica en español. El sistema de contexto de Nerdearla detecta y previene estas sustituciones:

- ❌ **Tier 1 falló**: `"Spring Boot"` traducido como *"bota de primavera"*
- ❌ **Tier 1 falló**: `"RabbitMQ"` traducido como *"conejo mq"*
- ❌ **Tier 1 falló**: `"Kubernetes"` transcrito fonéticamente como *"cube netes"* / *"go ver netes"*
- ❌ **Tier 1 falló**: `"PostgreSQL"` fragmentado como *"post gres q l"*
- ❌ **Tier 1 falló**: `"deployar"` normalizado forzosamente como *"desplegar"* (perdiendo la jerga del speaker)
- ❌ **Tier 1 falló**: `"pull request"` traducido como *"petición de extracción"*
- ✅ **Tier 2 corrigió**: El 100% de los términos técnicos de los glosarios fueron respetados con su grafía oficial y en el registro adecuado.

---

## 4. Ejecución del Harness de Evaluación

Para reproducir las métricas o evaluar nuevas hipótesis de transcripción:

```bash
# Ejecutar evaluación interactiva en consola
python -m evaluation.scoring

# Exportar reporte detallado en JSON
python -m evaluation.scoring --output evaluation/results/report.json
```

Para correr la suite de pruebas automatizadas:

```bash
# Correr tests unitarios del arnés y de carga de YAML en ContextProvider
pytest tests/test_scoring.py tests/test_context_yaml.py -v
```

---

## 5. Estructura de Archivos

```
evaluation/
├── corpus/
│   ├── agenda.yaml          # Metadatos de sesiones, speakers y glosarios consumidos por ContextProvider
│   ├── glossary.json        # Reglas léxicas, términos canónicos, aliases y trampas de traducción
│   ├── ground_truth.json    # Transcripciones de referencia y pares de hipótesis Tier 1 / Tier 2
│   └── audio/               # Directorio para cortes de audio WAV (16kHz mono)
├── scripts/
│   └── download_corpus.py   # Herramienta para descargar con yt-dlp y recortar con ffmpeg
├── results/
│   └── report.json          # Salida estructurada de la última corrida de evaluación
├── scoring.py               # Motor formal de cálculo de WER, terminología y deltas
└── README.md                # Este documento
```
