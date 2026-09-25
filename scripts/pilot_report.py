"""Score an authorized, human-referenced pilot capture without claiming synthetic WER."""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any


def words(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.findall(r"\w+", value, flags=re.UNICODE)


def wer(reference: str, hypothesis: str) -> float:
    a, b = words(reference), words(hypothesis)
    if not a:
        return 0.0 if not b else 1.0
    previous = list(range(len(b) + 1))
    for i, source in enumerate(a, 1):
        current = [i]
        for j, target in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (source != target)))
        previous = current
    return previous[-1] / len(a)


def chrf(reference: str, hypothesis: str) -> float:
    """Character 2-gram F score, a compact translation similarity indicator."""
    def grams(value: str) -> Counter[str]:
        clean = unicodedata.normalize("NFKC", value).casefold()
        return Counter(clean[i:i + 2] for i in range(max(0, len(clean) - 1)))

    a, b = grams(reference), grams(hypothesis)
    common = sum((a & b).values())
    precision = common / sum(b.values()) if b else 0
    recall = common / sum(a.values()) if a else 0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def p95(values: list[float]) -> float | None:
    return sorted(values)[math.ceil(0.95 * len(values)) - 1] if values else None


def validate_recording(recording: dict[str, Any], route: str) -> None:
    required = {"capture", "transcribe", "translate", "publish", "retain"}
    permissions = recording.get("permissions") or {}
    if not recording.get("permission_reference") or not required.issubset(
        {key for key, value in permissions.items() if value}
    ):
        raise ValueError(f"{recording.get('id')}: insufficient documented permissions")
    if route in {"cloud", "legacy"} and not permissions.get("cloud"):
        raise ValueError(f"{recording['id']}: no Google processing permission")
    if recording.get("reference_origin") != "human_verified":
        raise ValueError(f"{recording['id']}: reference must be independently human verified")
    if not Path(recording["audio_path"]).is_file():
        raise ValueError(f"{recording['id']}: audio file not found")


def report(manifest: dict[str, Any]) -> dict[str, Any]:
    recordings = {item["id"]: item for item in manifest["recordings"]}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in manifest["observations"]:
        recording = recordings[observation["recording_id"]]
        route = observation["route"]
        validate_recording(recording, route)
        grouped[route].append({"recording": recording, **observation})
    result: dict[str, Any] = {}
    for route, observations in grouped.items():
        latency: list[float] = []
        partition_latency: dict[str, list[float]] = defaultdict(list)
        originals: list[float] = []
        translations: list[float] = []
        term_hits = term_total = duplicates = missing_pairs = missing_timestamps = 0
        clock_errors = dropped_clauses = provider_errors = signal_errors = 0
        missing_drop_counters = 0
        clause_accounting_errors = 0
        audio_minutes = input_tokens = output_tokens = 0
        actual_costs: list[float] = []
        stages = set()
        sources = set()
        intervals: list[tuple[int, int, str]] = []
        for item in observations:
            recording = item["recording"]
            stages.add(str(item["stage_id"]))
            sources.add(item.get("source_type"))
            if isinstance(item.get("started_wall_ms"), int) and isinstance(item.get("ended_wall_ms"), int):
                intervals.append((item["started_wall_ms"], item["ended_wall_ms"], str(item["stage_id"])))
            captions = item.get("captions") or []
            final_count = item.get("final_clause_count")
            committed_count = item.get("committed_clause_count")
            counts_valid = (isinstance(final_count, int) and isinstance(committed_count, int)
                            and final_count > 0 and committed_count == final_count)
            rendered_count_matches = counts_valid and all(
                sum(c.get("lang") == lang and c.get("state") == "committed" for c in captions)
                == committed_count for lang in ("es", "en")
            )
            if not rendered_count_matches:
                clause_accounting_errors += 1
            seen: set[tuple[str, str, str]] = set()
            clauses: dict[tuple[str, str], set[str]] = defaultdict(set)
            if item.get("dropped_clauses") is None:
                missing_drop_counters += 1
            else:
                dropped_clauses += int(item["dropped_clauses"])
            expected_status = "cloud" if route == "cloud" else "local" if route == "local" else None
            expected_caption_provider = (
                "gemini-live" if route == "cloud" else "local-gemma4" if route == "local" else None
            )
            samples = item.get("provider_samples") or []
            session_ids = {sample.get("session_id") for sample in samples if sample.get("session_id")}
            if len(session_ids) != 1:
                signal_errors += 1
            if expected_status and not samples:
                signal_errors += 1
            for sample in samples:
                if not sample.get("audio_up") or not sample.get("ready"):
                    signal_errors += 1
                if expected_status and sample.get("provider") != expected_status:
                    provider_errors += 1
                if sample.get("source_type") != item.get("source_type"):
                    signal_errors += 1
            for caption in captions:
                key = (str(caption.get("session_id")), str(caption.get("clause_id")),
                       str(caption.get("lang")))
                if key in seen:
                    duplicates += 1
                seen.add(key)
                clauses[(key[0], key[1])].add(key[2])
                if expected_caption_provider and caption.get("provider") != expected_caption_provider:
                    provider_errors += 1
                end = caption.get("audio_end_wall_ms")
                visible = caption.get("visible_wall_ms")
                if isinstance(end, (int, float)) and isinstance(visible, (int, float)):
                    uncertainty = caption.get("clock_uncertainty_ms")
                    if not isinstance(uncertainty, (int, float)) or uncertainty > 100 or uncertainty < 0:
                        clock_errors += 1
                        continue
                    if visible < end:
                        clock_errors += 1
                        continue
                    measured = visible - end + uncertainty
                    latency.append(measured)
                    partition_latency[f"{item['stage_id']}:{caption.get('lang')}"].append(measured)
                else:
                    missing_timestamps += 1
            missing_pairs += sum(langs != {"es", "en"} for langs in clauses.values())
            source_lang = recording["source_lang"]
            target_lang = "en" if source_lang == "es" else "es"
            ordered = {
                lang: " ".join(c["text"] for c in sorted(
                    (c for c in captions if c.get("lang") == lang and c.get("state") == "committed"),
                    key=lambda c: c.get("t0_ms", 0)
                ))
                for lang in (source_lang, target_lang)
            }
            original = ordered[source_lang]
            translated = ordered[target_lang]
            originals.append(wer(recording[f"reference_{source_lang}"], original))
            translations.append(chrf(recording[f"reference_{target_lang}"], translated))
            for term in recording.get("glossary", []):
                if term.casefold() not in recording["reference_es"].casefold() and term.casefold() not in recording["reference_en"].casefold():
                    continue
                term_total += 1
                term_hits += int(term.casefold() in original.casefold()
                                 or term.casefold() in translated.casefold())
            audio_minutes += float(item.get("cloud_audio_minutes") or 0)
            input_tokens += int(item.get("translation_input_tokens") or 0)
            output_tokens += int(item.get("translation_output_tokens") or 0)
            if item.get("cloud_cost_usd_actual") is not None:
                actual_costs.append(float(item["cloud_cost_usd_actual"]))
        simultaneous_hour = any(
            min(end for start, end, stage in trio) - max(start for start, end, stage in trio) >= 3_600_000
            and len({stage for start, end, stage in trio}) == 3
            for trio in combinations(intervals, 3)
        )
        result[route] = {
            "recordings": len(observations), "stages": sorted(stages),
            "sources": sorted(source for source in sources if source),
            "visible_latency_p95_ms": p95(latency), "visible_samples": len(latency),
            "visible_latency_by_stage_language_ms": {
                key: {"p95": p95(values), "samples": len(values)}
                for key, values in sorted(partition_latency.items())
            },
            "wer_mean": sum(originals) / len(originals),
            "translation_char_bigram_f1_mean": sum(translations) / len(translations),
            "glossary_recall": term_hits / term_total if term_total else None,
            "duplicate_captions": duplicates,
            "missing_language_pairs": missing_pairs,
            "missing_visible_timestamps": missing_timestamps,
            "clock_errors": clock_errors,
            "dropped_clauses": dropped_clauses,
            "missing_drop_counters": missing_drop_counters,
            "clause_accounting_errors": clause_accounting_errors,
            "provider_errors": provider_errors,
            "signal_errors": signal_errors,
            "three_rooms_one_hour_simultaneous": simultaneous_hour,
            "gpu_memory_peak_mib": max((item.get("gpu_memory_peak_mib") or 0 for item in observations), default=0),
            "cloud_audio_minutes": round(audio_minutes, 3),
            "translation_input_tokens": input_tokens,
            "translation_output_tokens": output_tokens,
            "cloud_cost_usd_estimate": round(audio_minutes * 0.009 + input_tokens * 0.30 / 1e6
                                             + output_tokens * 2.50 / 1e6, 4),
            "cloud_cost_usd_actual": round(sum(actual_costs), 4)
            if len(actual_costs) == len(observations) else None,
            "latency_target_met": (
                simultaneous_hour and sources == {"obs", "file", "microphone"}
                and all(f"{stage}:{lang}" in partition_latency
                        and p95(partition_latency[f"{stage}:{lang}"]) <= 5000
                        for stage in ("1", "2", "3") for lang in ("es", "en"))
                and not any((duplicates, missing_pairs, missing_timestamps, clock_errors,
                             dropped_clauses, missing_drop_counters, clause_accounting_errors,
                             provider_errors, signal_errors))
            ),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--capture", type=Path, action="append", default=[],
                        help="JSON producido por collect-pilot.mjs; se combina en memoria")
    parser.add_argument("--require-pilot", action="store_true",
                        help="Salir con error si cloud o local no supera la matriz de aceptación")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest.setdefault("observations", [])
    for capture in args.capture:
        manifest["observations"].extend(json.loads(capture.read_text(encoding="utf-8"))["observations"])
    result = report(manifest)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    if args.require_pilot and not all(
        result.get(route, {}).get("latency_target_met") for route in ("cloud", "local")
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
