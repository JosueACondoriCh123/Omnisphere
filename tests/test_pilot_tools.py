import pytest

from scripts.pilot_report import chrf, report, wer
from training.prepare_lora import prepare


def recording(tmp_path, ident, talk, speaker, split, train=True):
    audio = tmp_path / f"{ident}.wav"
    audio.write_bytes(b"RIFF")
    return {
        "id": ident, "talk_id": talk, "speaker_id": speaker, "split": split,
        "audio_path": str(audio), "source_lang": "es", "reference_origin": "human_verified",
        "reference_es": "Hola mundo", "reference_en": "Hello world",
        "clauses": [{"hypothesis_es": "Ola mundo", "hypothesis_en": "Helo world",
                     "reference_es": "Hola mundo", "reference_en": "Hello world"}],
        "glossary": ["mundo"], "permission_reference": f"permit-{ident}",
        "permissions": {"capture": True, "transcribe": True, "translate": True,
                        "publish": True, "retain": True, "cloud": True, "train": train},
    }


def test_wer_and_translation_metric_are_not_hypothesis_leakage():
    assert wer("hola mundo", "hola mundo") == 0
    assert wer("hola mundo", "hola") == 0.5
    assert chrf("Hello world", "Hello world") == 1


def test_pilot_report_requires_visible_timestamps_and_three_concurrent_rooms(tmp_path):
    recs = [recording(tmp_path, str(i), f"talk-{i}", f"speaker-{i}", "holdout") for i in range(3)]
    observations = []
    for index, rec in enumerate(recs, 1):
        observations.append({
            "recording_id": rec["id"], "route": "local", "stage_id": str(index),
            "source_type": ("obs", "file", "microphone")[index - 1],
            "started_wall_ms": 0, "ended_wall_ms": 3_600_000,
            "dropped_clauses": 0,
            "final_clause_count": 1, "committed_clause_count": 1,
            "provider_samples": [{"provider": "local", "ready": True, "audio_up": True,
                                  "session_id": rec["id"],
                                  "source_type": ("obs", "file", "microphone")[index - 1]}],
            "captions": [
                {"session_id": rec["id"], "clause_id": "a", "state": "committed", "lang": "es",
                 "text": "Hola mundo", "t0_ms": 0, "audio_end_wall_ms": 1000,
                 "visible_wall_ms": 2000, "clock_uncertainty_ms": 10, "provider": "local-gemma4"},
                {"session_id": rec["id"], "clause_id": "a", "state": "committed", "lang": "en",
                 "text": "Hello world", "t0_ms": 0, "audio_end_wall_ms": 1000,
                 "visible_wall_ms": 2000, "clock_uncertainty_ms": 10, "provider": "local-gemma4"},
            ],
        })
    result = report({"recordings": recs, "observations": observations})["local"]
    assert result["three_rooms_one_hour_simultaneous"]
    assert result["latency_target_met"]
    assert result["wer_mean"] == 0
    observations[0]["captions"][0]["visible_wall_ms"] = 8000
    assert not report({"recordings": recs, "observations": observations})["local"]["latency_target_met"]
    observations[0]["captions"][0]["visible_wall_ms"] = 2000
    observations[0]["captions"][1]["clock_uncertainty_ms"] = 250
    assert not report({"recordings": recs, "observations": observations})["local"]["latency_target_met"]
    observations[0]["captions"][1]["clock_uncertainty_ms"] = 10
    observations[0]["committed_clause_count"] = 0
    assert not report({"recordings": recs, "observations": observations})["local"]["latency_target_met"]


def test_training_split_rejects_shared_talk_or_missing_training_permission(tmp_path):
    a = recording(tmp_path, "a", "same", "alice", "train")
    b = recording(tmp_path, "b", "same", "bob", "holdout")
    with pytest.raises(ValueError, match="share a talk"):
        prepare({"recordings": [a, b]})
    b["talk_id"] = "other"
    b["permissions"]["train"] = False
    with pytest.raises(ValueError, match="training permission"):
        prepare({"recordings": [a, b]})
    b["permissions"]["train"] = True
    assert len(prepare({"recordings": [a, b]})["train"]) == 2
