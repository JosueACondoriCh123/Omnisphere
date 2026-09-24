from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.config import Settings
from app.domain import StageContext


class ContextProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get(self, stage_id: str) -> StageContext:
        if self.settings.context_url_template:
            url = self.settings.context_url_template.format(stage_id=stage_id)
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
            return self._normalize(stage_id, data)

        path = Path(self.settings.stage_context_file)
        try:
            content = path.read_text(encoding="utf-8")
            if path.suffix.lower() in {".yaml", ".yml"}:
                data = yaml.safe_load(content)
                data = data or {}
            else:
                data = json.loads(content)
            return self._normalize(stage_id, data.get(stage_id, {}))
        except (OSError, json.JSONDecodeError, yaml.YAMLError, AttributeError, TypeError):
            return self._normalize(stage_id, {})

    @staticmethod
    def _normalize(stage_id: str, data: dict[str, Any]) -> StageContext:
        return StageContext(
            id=stage_id,
            name=str(data.get("name") or f"Stage {stage_id}"),
            session=str(data.get("session") or ""),
            languages=list(data.get("languages") or ["es"]),
            glossary=list(data.get("glossary") or []),
            speakers=list(data.get("speakers") or []),
        )
