"""Gold-set metrics. Fixture runs are explicitly not model-quality estimates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import dump_json, load_json


def evaluate_run(run: dict[str, Any], gold: dict[str, Any], candidates: list[dict[str, Any]], output_path: str | Path) -> dict[str, Any]:
    candidate_map = {x["candidate_id"]: x for x in candidates}
    outcomes = {x["candidate_id"]: x for x in run["item_results"]}
    predictions = run["accepted"]
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for claim in predictions:
        by_candidate.setdefault(claim["candidate_id"], []).append(claim)

    status_correct = 0
    gold_quotes = set()
    predicted_quotes = set()
    matched_quotes = set()
    condition_correct = 0
    condition_total = 0
    source_type_correct = 0
    source_type_total = 0
    option_correct = 0
    polarity_correct = 0
    missing_candidates = []
    for case in gold["cases"]:
        candidate_id = case["candidate_id"]
        expected = {x["evidence_quote"]: x for x in case["claims"]}
        gold_quotes.update((candidate_id, q) for q in expected)
        if candidate_id not in outcomes:
            missing_candidates.append(candidate_id)
            continue
        if outcomes[candidate_id]["status"] == case["status"]:
            status_correct += 1
        actual = {x["evidence_quote"]: x for x in by_candidate.get(candidate_id, [])}
        predicted_quotes.update((candidate_id, q) for q in actual)
        for quote in set(expected) & set(actual):
            matched_quotes.add((candidate_id, quote))
            e, a = expected[quote], actual[quote]
            source_type_total += 1
            source_type_correct += e["source_type"] == a["source_type"]
            option_correct += e["option"] == a["option"]
            polarity_correct += e["polarity"] == a["polarity"]
            for key in e["conditions"]:
                condition_total += 1
                condition_correct += e["conditions"][key] == a["conditions"][key]

    denominator = len(gold["cases"])
    metrics = {
        "evaluated_candidates": denominator - len(missing_candidates),
        "gold_candidates": denominator,
        "gold_claims": len(gold_quotes),
        "candidate_status_accuracy": round(status_correct / denominator, 4) if denominator else None,
        "evidence_recall": round(len(matched_quotes) / len(gold_quotes), 4) if gold_quotes else None,
        "evidence_precision_on_gold_candidates": round(len(matched_quotes) / len(predicted_quotes), 4) if predicted_quotes else None,
        "matched_claim_count": len(matched_quotes),
        "source_type_accuracy_on_exact_evidence": round(source_type_correct / source_type_total, 4) if source_type_total else None,
        "option_accuracy_on_exact_evidence": round(option_correct / source_type_total, 4) if source_type_total else None,
        "polarity_accuracy_on_exact_evidence": round(polarity_correct / source_type_total, 4) if source_type_total else None,
        "condition_accuracy_on_exact_evidence": round(condition_correct / condition_total, 4) if condition_total else None,
        "condition_fields_checked": condition_total,
        "missing_candidates": missing_candidates,
    }
    if run["run"]["fixture_run"]:
        interpretation = "fixture regression only; not a model quality estimate"
    elif gold.get("quality_reporting_eligible") is False:
        interpretation = "AI-assisted development set explicitly marked ineligible for quality reporting; metrics are diagnostic only"
    elif gold.get("human_double_review_completed") is True and gold.get("test_set_locked") is True:
        interpretation = "locked gold-set metrics; scope is limited to the evaluated run and candidate distribution"
    elif gold.get("human_double_review_completed") is False or gold.get("test_set_locked") is False:
        interpretation = "AI-assisted or unlocked development set; not eligible for model-quality claims"
    else:
        interpretation = "seed-set regression reference only; expand and freeze a 50-case set before reporting model quality"
    report = {
        "run_id": run["run"]["run_id"],
        "prompt_version": run["run"]["prompt_version"],
        "provider": run["run"]["provider"],
        "model": run["run"]["model"],
        "fixture_run": run["run"]["fixture_run"],
        "gold_suite_version": gold.get("suite_version"),
        "gold_dataset_role": gold.get("dataset_role"),
        "gold_annotation_status": gold.get("annotation_status"),
        "quality_reporting_eligible": bool(run["run"]["fixture_run"] is False and gold.get("quality_reporting_eligible") is True and gold.get("human_double_review_completed") is True and gold.get("test_set_locked") is True),
        "interpretation": interpretation,
        "metrics": metrics,
        "usage": run.get("usage", {}),
    }
    dump_json(output_path, report)
    return report


def modification_rate(review_result: dict[str, Any]) -> dict[str, Any]:
    reviewed = review_result["approved_count"] + review_result["rejected_count"]
    modified = sum(x.get("review", {}).get("decision") == "modify" for x in review_result.get("approved", []))
    return {"reviewed_count": reviewed, "modified_count": modified, "modification_rate": round(modified / reviewed, 4) if reviewed else None}
