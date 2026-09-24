"""Harness de Scoring y Medición para Nerdearla (Dev 5).

Calcula y reporta:
1. WER (Word Error Rate) formal por muestra y global.
2. Precisión terminológica (% de términos técnicos preservados y detección de trampas de traducción).
3. Delta cuantitativo entre Tier 1 (salida cruda ASR) y Tier 2 (salida refinada con contexto inyectado).
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PUNCTUATION_REGEX = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE_REGEX = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normaliza texto para evaluación ASR estándar: minúsculas, sin signos de puntuación y sin espacios duplicados."""
    if not text:
        return ""
    # Normalizar caracteres unicode (NFC)
    text = unicodedata.normalize("NFC", text.lower())
    # Remover signos de puntuación
    text = PUNCTUATION_REGEX.sub(" ", text)
    # Colapsar espacios múltiples
    text = WHITESPACE_REGEX.sub(" ", text).strip()
    return text


def compute_wer_details(reference: str, hypothesis: str) -> dict[str, float | int]:
    """Calcula la distancia de Levenshtein a nivel de palabras (WER).

    Retorna S (sustituciones), D (deleciones), I (inserciones), N (longitud de referencia) y el WER.
    """
    ref_words = normalize_text(reference).split()
    hyp_words = normalize_text(hypothesis).split()

    n = len(ref_words)
    m = len(hyp_words)

    if n == 0:
        return {
            "wer": 0.0 if m == 0 else 1.0,
            "substitutions": 0,
            "deletions": 0,
            "insertions": m,
            "ref_length": 0,
            "hyp_length": m,
        }

    # Matriz de programación dinámica (Wagner-Fischer)
    dp = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                sub = dp[i - 1][j - 1] + 1
                deletion = dp[i - 1][j] + 1
                insertion = dp[i][j - 1] + 1
                dp[i][j] = min(sub, deletion, insertion)

    # Backtracking para contar S, D, I con precisión
    i, j = n, m
    substitutions, deletions, insertions = 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref_words[i - 1] == hyp_words[j - 1]:
            i -= 1
            j -= 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            substitutions += 1
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1

    total_errors = substitutions + deletions + insertions
    wer = round(total_errors / n, 4)

    return {
        "wer": wer,
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "ref_length": n,
        "hyp_length": m,
    }


def evaluate_terminology(
    target_terms: list[str],
    hypothesis: str,
    glossary_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evalúa la precisión y retención de vocabulario técnico objetivo en la hipótesis."""
    hyp_norm = normalize_text(hypothesis)
    hits: list[str] = []
    misses: list[str] = []
    traps_triggered: list[dict[str, str]] = []

    # Mapa rápido de reglas de términos prohibidos / traducciones erróneas
    rules_by_term: dict[str, dict[str, Any]] = {}
    if glossary_rules:
        for rule in glossary_rules:
            canon = rule.get("canonical", "").lower()
            rules_by_term[canon] = rule

    for term in target_terms:
        term_norm = normalize_text(term)
        rule = rules_by_term.get(term_norm, {})
        aliases = [normalize_text(a) for a in rule.get("aliases", [])]

        # Verificar presencia del término canónico o sus alias
        term_pattern = r"\b" + re.escape(term_norm) + r"\b"
        found = bool(re.search(term_pattern, hyp_norm))
        if not found:
            for alias in aliases:
                if re.search(r"\b" + re.escape(alias) + r"\b", hyp_norm):
                    found = True
                    break

        if found:
            hits.append(term)
        else:
            misses.append(term)

        # Verificar si cayó en una trampa de traducción o sustitución prohibida
        for forbidden in rule.get("forbidden_substitutions", []):
            forb_norm = normalize_text(forbidden)
            if re.search(r"\b" + re.escape(forb_norm) + r"\b", hyp_norm):
                traps_triggered.append(
                    {"term": term, "forbidden_text_found": forbidden}
                )

    total = len(target_terms)
    accuracy = round(len(hits) / total, 4) if total > 0 else 1.0

    return {
        "total_terms": total,
        "hits": hits,
        "misses": misses,
        "accuracy": accuracy,
        "traps_triggered": traps_triggered,
    }


@dataclass
class SampleEvaluation:
    sample_id: str
    title: str
    language: str
    t1_wer: float
    t2_wer: float
    delta_wer: float
    t1_term_accuracy: float
    t2_term_accuracy: float
    delta_term_accuracy: float
    t1_traps: list[dict[str, str]] = field(default_factory=list)
    t2_traps: list[dict[str, str]] = field(default_factory=list)
    t1_misses: list[str] = field(default_factory=list)
    t2_misses: list[str] = field(default_factory=list)


@dataclass
class GlobalEvaluationReport:
    version: str = "1.0.0"
    num_samples: int = 0
    t1_mean_wer: float = 0.0
    t2_mean_wer: float = 0.0
    delta_mean_wer: float = 0.0
    t1_mean_term_acc: float = 0.0
    t2_mean_term_acc: float = 0.0
    delta_mean_term_acc: float = 0.0
    samples: list[SampleEvaluation] = field(default_factory=list)


class ScoringHarness:
    def __init__(
        self,
        ground_truth_path: Path | str,
        glossary_path: Path | str | None = None,
    ) -> None:
        self.ground_truth_path = Path(ground_truth_path)
        self.glossary_path = Path(glossary_path) if glossary_path else None
        self.samples_data: list[dict[str, Any]] = []
        self.glossary_rules: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.ground_truth_path.exists():
            content = json.loads(self.ground_truth_path.read_text(encoding="utf-8"))
            self.samples_data = content.get("samples", [])

        if self.glossary_path and self.glossary_path.exists():
            glossary_content = json.loads(self.glossary_path.read_text(encoding="utf-8"))
            self.glossary_rules = glossary_content.get("terms", [])

    def run(self) -> GlobalEvaluationReport:
        results: list[SampleEvaluation] = []

        for item in self.samples_data:
            sample_id = item["id"]
            title = item.get("title", sample_id)
            lang = item.get("language", "es")
            ref = item["reference"]
            t1_hyp = item.get("tier1_hypothesis", "")
            t2_hyp = item.get("tier2_hypothesis", "")
            target_terms = item.get("key_terms", [])

            # 1. Medir WER
            t1_wer_res = compute_wer_details(ref, t1_hyp)
            t2_wer_res = compute_wer_details(ref, t2_hyp)
            t1_wer = float(t1_wer_res["wer"])
            t2_wer = float(t2_wer_res["wer"])
            delta_wer = round(t1_wer - t2_wer, 4)

            # 2. Medir Terminología
            t1_term = evaluate_terminology(target_terms, t1_hyp, self.glossary_rules)
            t2_term = evaluate_terminology(target_terms, t2_hyp, self.glossary_rules)
            t1_acc = float(t1_term["accuracy"])
            t2_acc = float(t2_term["accuracy"])
            delta_term = round(t2_acc - t1_acc, 4)

            results.append(
                SampleEvaluation(
                    sample_id=sample_id,
                    title=title,
                    language=lang,
                    t1_wer=t1_wer,
                    t2_wer=t2_wer,
                    delta_wer=delta_wer,
                    t1_term_accuracy=t1_acc,
                    t2_term_accuracy=t2_acc,
                    delta_term_accuracy=delta_term,
                    t1_traps=t1_term["traps_triggered"],
                    t2_traps=t2_term["traps_triggered"],
                    t1_misses=t1_term["misses"],
                    t2_misses=t2_term["misses"],
                )
            )

        n = len(results)
        if n == 0:
            return GlobalEvaluationReport()

        mean_t1_wer = round(sum(r.t1_wer for r in results) / n, 4)
        mean_t2_wer = round(sum(r.t2_wer for r in results) / n, 4)
        delta_mean_wer = round(mean_t1_wer - mean_t2_wer, 4)

        mean_t1_acc = round(sum(r.t1_term_accuracy for r in results) / n, 4)
        mean_t2_acc = round(sum(r.t2_term_accuracy for r in results) / n, 4)
        delta_mean_acc = round(mean_t2_acc - mean_t1_acc, 4)

        return GlobalEvaluationReport(
            num_samples=n,
            t1_mean_wer=mean_t1_wer,
            t2_mean_wer=mean_t2_wer,
            delta_mean_wer=delta_mean_wer,
            t1_mean_term_acc=mean_t1_acc,
            t2_mean_term_acc=mean_t2_acc,
            delta_mean_term_acc=delta_mean_acc,
            samples=results,
        )


def print_report_table(report: GlobalEvaluationReport) -> None:
    """Imprime el reporte en formato tabla legible por humanos y lista para el jurado."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    header = (
        f"{'Sample ID':<16} | {'Language':<8} | "
        f"{'T1 WER':<8} | {'T2 WER':<8} | {'Diff WER':<8} | "
        f"{'T1 Term':<8} | {'T2 Term':<8} | {'Diff Term':<9}"
    )
    separator = "-" * len(header)

    print("\n" + "=" * len(header))
    print("NERDEARLA - BENCHMARK EVALUATION (DEV 5)")
    print("=" * len(header))
    print(header)
    print(separator)

    for s in report.samples:
        row = (
            f"{s.sample_id:<16} | {s.language:<8} | "
            f"{s.t1_wer * 100:>6.1f}% | {s.t2_wer * 100:>6.1f}% | {s.delta_wer * 100:>+7.1f}% | "
            f"{s.t1_term_accuracy * 100:>6.1f}% | {s.t2_term_accuracy * 100:>6.1f}% | {s.delta_term_accuracy * 100:>+8.1f}%"
        )
        print(row)

    print(separator)
    summary_row = (
        f"{'PROMEDIO GLOBAL':<16} | {'ALL':<8} | "
        f"{report.t1_mean_wer * 100:>6.1f}% | {report.t2_mean_wer * 100:>6.1f}% | {report.delta_mean_wer * 100:>+7.1f}% | "
        f"{report.t1_mean_term_acc * 100:>6.1f}% | {report.t2_mean_term_acc * 100:>6.1f}% | {report.delta_mean_term_acc * 100:>+8.1f}%"
    )
    print(summary_row)
    print("=" * len(header) + "\n")

    # Detalle de trampas detectadas
    traps_found = False
    print("DETECCION DE TRAMPAS DE TRADUCCION (Tier 1 vs Tier 2):")
    for s in report.samples:
        if s.t1_traps:
            traps_found = True
            for t in s.t1_traps:
                print(
                    f"  [TRAP] [{s.sample_id}] Tier 1 cayo en '{t['term']}': detecto traduccion literal/error '{t['forbidden_text_found']}'"
                )
        if not s.t2_traps and s.t1_traps:
            print(f"  [OK]   [{s.sample_id}] Tier 2 neutralizo los falsos cognados e inyecto los terminos tecnicos canonicos.")
    if not traps_found:
        print("  Ninguna trampa de traduccion detectada en el dataset.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Harness de Scoring para Nerdearla")
    parser.add_argument(
        "--ground-truth",
        type=str,
        default="evaluation/corpus/ground_truth.json",
        help="Ruta al archivo JSON de ground truth",
    )
    parser.add_argument(
        "--glossary",
        type=str,
        default="evaluation/corpus/glossary.json",
        help="Ruta al archivo JSON de glosario y reglas",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Ruta para exportar el reporte en JSON",
    )
    args = parser.parse_args()

    harness = ScoringHarness(args.ground_truth, args.glossary)
    report = harness.run()
    print_report_table(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report_dict = asdict(report)
        out_path.write_text(json.dumps(report_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Reporte exportado exitosamente a: {out_path}")


if __name__ == "__main__":
    main()
