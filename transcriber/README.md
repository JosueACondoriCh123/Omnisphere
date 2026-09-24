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
`GET /health` reports the configured model and whether a key is present.

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

**Forced cuts ship as drafts.** When `X-Is-Clause-End` is `false` the segment was
cut at the safety limit mid-sentence, so the events are typed `draft` rather than
`commit` and the UI can style them as provisional.

**Temperature is 0.** `evaluation/` scores this output against fixed ground
truth; reproducibility matters more than fluency.

## Running it

```bash
docker compose up -d transcriber
```

Then point the plumbing at it:

```bash
TRANSCRIBER_URL=http://transcriber:8090/v1/audio/segments
GEMINI_API_KEY=...
```

Locally, without Docker:

```bash
uvicorn transcriber.main:app --port 8090
```

## Known limitation

Captions cannot appear before the VAD closes the clause, because the room worker
only ships audio at segment boundaries. For a six-second sentence the first word
reaches the screen after the sentence ends, not while it is being spoken.
Sub-second drafts would need a second, continuous audio path from the worker —
an additive change to the contract, not a change to this service.
