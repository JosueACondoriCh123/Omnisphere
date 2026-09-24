from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from pydantic import BaseModel, Field

# Deliberately a local model rather than an import from `app.domain`: this
# service is coupled to the wire contract in docs/contracts.md, not to the
# plumbing package's internals. The two can evolve independently.


class StageContext(BaseModel):
    """What the orchestrator knows about the talk currently on that stage.

    Arrives as `X-Stage-Context`, a json-base64url header set by the room
    worker. Every field is optional: a stage with no agenda entry still gets
    transcribed, just without the terminology advantage.
    """

    id: str = ""
    name: str = ""
    session: str = ""
    languages: list[str] = Field(default_factory=lambda: ["es"])
    glossary: list[str] = Field(default_factory=list)
    speakers: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def speaker_names(self) -> list[str]:
        names: list[str] = []
        for speaker in self.speakers:
            name = str(speaker.get("name") or "").strip()
            if name:
                names.append(name)
        return names

    def protected_terms(self) -> list[str]:
        """Terms the translation must never touch.

        Without this, "Spring Boot" becomes "Bota de Primavera" and the caption
        stops being useful. Speaker names belong here for the same reason.
        """
        seen: dict[str, None] = {}
        for term in (*self.glossary, *self.speaker_names):
            term = str(term).strip()
            if term:
                seen.setdefault(term, None)
        return list(seen)

    def target_languages(self) -> list[str]:
        """Languages this stage publishes, deduplicated and order-preserving."""
        seen: dict[str, None] = {}
        for lang in self.languages:
            lang = str(lang).strip().lower()
            if lang:
                seen.setdefault(lang, None)
        return list(seen) or ["es"]


def decode_stage_context(header: str, stage_id: str = "") -> StageContext:
    """Decode `X-Stage-Context`. A malformed header degrades, never raises.

    A caption without terminology hints is worth far more than a 400.
    """
    if not header:
        return StageContext(id=stage_id)
    try:
        padded = header + "=" * (-len(header) % 4)
        raw = base64.urlsafe_b64decode(padded).decode("utf-8")
        data = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return StageContext(id=stage_id)
    if not isinstance(data, dict):
        return StageContext(id=stage_id)
    data.setdefault("id", stage_id)
    try:
        return StageContext.model_validate(data)
    except Exception:
        return StageContext(id=stage_id)
