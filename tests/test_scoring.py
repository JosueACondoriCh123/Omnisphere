from __future__ import annotations

from pathlib import Path

from evaluation.scoring import (
    ScoringHarness,
    compute_wer_details,
    evaluate_terminology,
    normalize_text,
)


def test_normalize_text() -> None:
    raw = "¡Hola, Nerdearla! ¿Estamos listos para K8s?"
    normalized = normalize_text(raw)
    assert normalized == "hola nerdearla estamos listos para k8s"


def test_compute_wer_exact_match() -> None:
    ref = "Deployamos Kubernetes en producción"
    hyp = "Deployamos Kubernetes en producción"
    res = compute_wer_details(ref, hyp)
    assert res["wer"] == 0.0
    assert res["substitutions"] == 0
    assert res["deletions"] == 0
    assert res["insertions"] == 0


def test_compute_wer_substitutions() -> None:
    ref = "Spring Boot con Kafka"
    hyp = "Bota Primavera con Kafka"
    res = compute_wer_details(ref, hyp)
    # Ref has 4 words ("spring", "boot", "con", "kafka")
    # Hyp has 4 words ("bota", "primavera", "con", "kafka") -> 2 substitutions
    assert res["substitutions"] == 2
    assert res["wer"] == 0.5


def test_evaluate_terminology_hits_and_traps() -> None:
    rules = [
        {
            "canonical": "Spring Boot",
            "forbidden_substitutions": ["bota de primavera"],
        },
        {
            "canonical": "Kubernetes",
            "aliases": ["k8s"],
            "forbidden_substitutions": ["cube netes"],
        },
    ]

    # Caso Tier 1 con trampa
    hyp_t1 = "migramos a bota de primavera y cube netes"
    res_t1 = evaluate_terminology(["Spring Boot", "Kubernetes"], hyp_t1, rules)
    assert res_t1["accuracy"] == 0.0
    assert len(res_t1["traps_triggered"]) == 2

    # Caso Tier 2 corregido
    hyp_t2 = "migramos a Spring Boot y Kubernetes"
    res_t2 = evaluate_terminology(["Spring Boot", "Kubernetes"], hyp_t2, rules)
    assert res_t2["accuracy"] == 1.0
    assert len(res_t2["traps_triggered"]) == 0


def test_scoring_harness_corpus_delta() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    gt_file = base_dir / "evaluation" / "corpus" / "ground_truth.json"
    glossary_file = base_dir / "evaluation" / "corpus" / "glossary.json"

    assert gt_file.exists()
    assert glossary_file.exists()

    harness = ScoringHarness(gt_file, glossary_file)
    report = harness.run()

    assert report.num_samples == 4
    # En todas las muestras, Tier 2 debe superar a Tier 1 (menor WER y mayor precisión terminológica)
    assert report.t2_mean_wer < report.t1_mean_wer
    assert report.delta_mean_wer > 0
    assert report.t2_mean_term_acc > report.t1_mean_term_acc
    assert report.delta_mean_term_acc > 0

    # Verificar que Tier 2 tiene precisión terminológica de 100%
    assert report.t2_mean_term_acc == 1.0
