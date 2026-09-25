# Transcriber

The service behind `TRANSCRIBER_URL`. It closes the loop between the plumbing in
`app/` and the captions the audience reads: a VAD segment goes in as raw audio,
captions come out in every language the stage publishes.

## Contract

Implements the transcriber half of [`../docs/contracts.md`](../docs/contracts.md).

```http
POST /v1/audio/segments
Content-Type: audio/L16;rate=16000;channels=1
X-Stage-Id: 1
X-Is-Clause-End: true
X-Stage-Context: <json-base64url>

<raw s16le PCM, 16 kHz mono>
```

```json
{
  "events": [
    {"lang": "es", "type": "commit", "text": "Desplegamos el pod.", "seq": 12,
     "is_clause_end": true,
     "payload": {"source_language": "en", "preserved_terms": ["pod"],
                 "audio_ms": 2400, "engine_ms": 812.4}}
  ]
}
```

One event per language in the stage context, all sharing the segment's text.
`GET /health` is liveness and reports model/bus telemetry. `GET /readyz` returns
200 only after the key, model preflight and Redis bus are ready.

### Status codes

| Code | Meaning |
|---|---|
| 200 | Captions produced. An empty `events` array means no intelligible speech. |
| 400 | Malformed stage id or empty body. |
| 413 | Segment longer than `MAX_SEGMENT_SECONDS`. |
| 503 | Every attempt at the model failed. The room worker degrades and the `transcriber_socket_down` alarm fires. |

A malformed or missing `X-Stage-Context` never fails the request: the segment is
transcribed without terminology hints. During a live talk a caption without a
glossary is worth far more than an error.

## Design notes

**One structured call per segment.** Because the room worker hands over discrete
VAD segments rather than a continuous stream, transcription and translation fit
in a single `generate_content` call with a JSON schema. A streaming design would
need the Live API, which does not support structured output — the discrete
contract is what lets us keep the schema, and it halves the call count.

**Terminology comes from the agenda, not from guessing.** `X-Stage-Context`
carries `glossary` and `speakers`; both go into the prompt as terms that must be
spelled exactly and never translated. This is what keeps "Spring Boot" from
becoming "Bota de Primavera" and what keeps speaker names intact.

**Open clauses ship overlapping drafts.** Every 1.5 seconds the worker sends the
same utterance from a stable start timestamp with a growing end timestamp. The
latest queued draft replaces older pending drafts; a commit is never dropped.
This bounds Gemini backlog while preserving the visible draft→commit transition.

**Thinking is minimal.** Gemini 3.5 Flash uses `thinking_level=minimal` and an
explicit system instruction for the lowest practical caption latency. Sampling
parameters such as temperature are intentionally omitted.

## Running it

### Redis Bus Mode (Default in Docker Compose)

In production and Docker Compose, the transcriber connects directly to Redis:

`stage:{id}:audio` → transcription → `stage:{id}:captions`

Configuration:
- `TRANSCRIBER_BUS_ENABLED=true` (enables Redis listener on `stage:*:audio`)
- `REDIS_URL=redis://redis:6379/0`
- `STAGE_CONTEXT_FILE=config/stages.json`
- `BUS_QUEUE_SIZE=32`
- `MAX_PARALLEL_STAGES=4`

In this mode, `GET /health` includes real-time telemetry of the bus:
```json
{
  "service": "nerdearla-transcriber",
  "model": "gemini-3.5-flash",
  "api_key_configured": true,
  "stages_seen": [],
  "bus": {
    "enabled": true,
    "status": "connected",
    "redis_connected": true,
    "queued": 0,
    "processed": 142,
    "published": 139,
    "silent": 3,
    "failures": 0,
    "queue_overflows": 0,
    "drafts_coalesced": 18,
    "last_error": null
  }
}
```

```bash
docker compose up -d redis transcriber
```

### HTTP Mode (Fallback / Dev)

```bash
uvicorn transcriber.main:app --port 8090
```

Point the plumbing at it:

```bash
TRANSCRIBER_URL=http://transcriber:8090/v1/audio/segments
GEMINI_API_KEY=...
```

## Latency note

`PARTIAL_SEGMENT_SECONDS=1.5` controls audio snapshot cadence, not the external
Gemini response time. `/admin` raises the existing latency alarm when the
observed network plus inference latency exceeds 1.5 seconds.
