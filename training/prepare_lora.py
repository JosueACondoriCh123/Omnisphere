"""Produce private Gemma 4 translation examples only from audited recordings."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def prepare(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    splits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    talks: dict[str, set[str]] = defaultdict(set)
    speakers: dict[str, set[str]] = defaultdict(set)
    for recording in manifest["recordings"]:
        split = recording.get("split")
        if split not in {"train", "holdout"}:
            raise ValueError(f"{recording.get('id')}: split must be train or holdout")
        permissions = recording.get("permissions") or {}
        required = {"capture", "transcribe", "translate", "retain", "train"}
        if not recording.get("permission_reference") or not all(permissions.get(key) for key in required):
            raise ValueError(f"{recording.get('id')}: training permission is not documented")
        if recording.get("reference_origin") != "human_verified":
            raise ValueError(f"{recording.get('id')}: reference is not independently verified")
        source = recording.get("source_lang")
        if source not in {"es", "en"}:
            raise ValueError(f"{recording.get('id')}: source_lang must be es or en")
        target = "en" if source == "es" else "es"
        if not Path(recording["audio_path"]).is_file():
            raise ValueError(f"{recording.get('id')}: original audio not found")
        talks[split].add(recording["talk_id"])
        speakers[split].add(recording["speaker_id"])
        clauses = recording.get("clauses") or []
        if not clauses:
            raise ValueError(f"{recording['id']}: human-aligned clause references are required")
        for clause in clauses:
            if clause.get("hypothesis_provider") == "cloud" and not permissions.get("cloud"):
                raise ValueError(f"{recording['id']}: cloud hypothesis lacks Google permission")
            original = clause.get(f"reference_{source}", "").strip()
            translated = clause.get(f"reference_{target}", "").strip()
            hypothesis = clause.get(f"hypothesis_{source}", "").strip()
            if not original or not translated or not hypothesis:
                raise ValueError(f"{recording['id']}: source hypothesis and human references are required")
            prompt = (
                f"Correct recognition errors in this {source} conference caption, then translate it to {target}. "
                "Preserve meaning, product names, commands, and technical Spanglish. "
                "Do not add content. Return only JSON with keys corrected and translation.\n"
                f"Protected terms: {', '.join(recording.get('glossary', [])[:100])}\n"
                f"Caption: {hypothesis}"
            )
            splits[split].append({"messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": json.dumps(
                    {"corrected": original, "translation": translated}, ensure_ascii=False)},
            ]})
    if not splits["train"] or not splits["holdout"]:
        raise ValueError("both training and reserved holdout data are required")
    if talks["train"] & talks["holdout"] or speakers["train"] & speakers["holdout"]:
        raise ValueError("train and holdout share a talk or speaker")
    return dict(splits)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    splits = prepare(json.loads(args.manifest.read_text(encoding="utf-8")))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        (args.output_dir / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
    print(f"Prepared {len(splits['train'])} training and {len(splits['holdout'])} holdout examples")


if __name__ == "__main__":
    main()
