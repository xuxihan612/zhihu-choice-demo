"""Deterministic integrity checks and descriptive statistics for an extraction run."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .common import dump_json, utc_now
from .validation import validate_batch


def audit_run(
    run: dict[str, Any],
    candidates: list[dict[str, Any]],
    scenario: dict[str, Any],
    schema: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    candidate_map = {x["candidate_id"]: x for x in candidates}
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    claim_fields = ["claim", "option", "polarity", "evidence_quote", "conditions", "cost", "source_type", "confidence"]
    for record in run["accepted"]:
        by_candidate.setdefault(record["candidate_id"], []).append({key: record[key] for key in claim_fields})

    rechecked_ids: set[str] = set()
    for candidate_id, claims in by_candidate.items():
        if candidate_id not in candidate_map:
            continue
        checked = validate_batch(
            {"items": [{"candidate_id": candidate_id, "status": "extracted", "claims": claims}]},
            {candidate_id: candidate_map[candidate_id]},
            scenario,
            schema,
            run_metadata=run["run"],
        )
        rechecked_ids.update(x["claim_id"] for x in checked["accepted"])

    accepted_ids = [x["claim_id"] for x in run["accepted"]]
    outcome_ids = [x.get("candidate_id") for x in run["item_results"]]
    expected_ids = set(candidate_map)
    outcome_set = set(outcome_ids)
    errors = Counter(
        error["code"]
        for item in run["item_results"]
        for error in item.get("errors", [])
    )
    accepted = run["accepted"]
    confidences = [x["confidence"] for x in accepted]
    condition_counts = {
        key: dict(Counter(x["conditions"][key] for x in accepted if x["conditions"][key] is not None))
        for key in scenario["conditions"]
    }
    integrity = {
        "candidate_coverage_complete": outcome_set == expected_ids and len(outcome_ids) == len(expected_ids),
        "missing_candidates": sorted(expected_ids - outcome_set),
        "unexpected_candidates": sorted(outcome_set - expected_ids),
        "duplicate_candidate_outcomes": sorted(key for key, count in Counter(outcome_ids).items() if count > 1),
        "claim_ids_unique": len(accepted_ids) == len(set(accepted_ids)),
        "accepted_count_matches": run["accepted_claim_count"] == len(accepted),
        "accepted_claims_revalidate": rechecked_ids == set(accepted_ids),
        "claims_failing_revalidation": sorted(set(accepted_ids) - rechecked_ids),
        "unexpected_revalidated_claims": sorted(rechecked_ids - set(accepted_ids)),
    }
    report = {
        "report_version": "1.0",
        "generated_at": utc_now(),
        "scenario_id": scenario["id"],
        "run_id": run["run"]["run_id"],
        "prompt_version": run["run"]["prompt_version"],
        "prompt_sha256": run["run"]["prompt_sha256"],
        "provider": run["run"]["provider"],
        "model": run["run"]["model"],
        "fixture_run": run["run"].get("fixture_run", False),
        "candidate_count": len(candidates),
        "accepted_claim_count": len(accepted),
        "accepted_candidate_count": len(by_candidate),
        "status_counts": dict(Counter(x["status"] for x in run["item_results"])),
        "error_code_counts": dict(errors),
        "claims_by_option_and_polarity": dict(Counter(f'{x["option"]}:{x["polarity"]}' for x in accepted)),
        "claims_by_source_type": dict(Counter(x["source_type"] for x in accepted)),
        "claims_with_cost": sum(x["cost"] is not None for x in accepted),
        "condition_value_counts": condition_counts,
        "confidence_summary": {
            "min": min(confidences) if confidences else None,
            "max": max(confidences) if confidences else None,
            "mean": round(sum(confidences) / len(confidences), 4) if confidences else None,
        },
        "pending_claim_count": sum(not x["review"]["reviewed"] for x in accepted),
        "integrity": integrity,
        "interpretation": (
            "Programmatic schema, exact-evidence, enum and condition-support checks only. "
            "This report does not establish semantic direction, source-type accuracy or model quality; human review is required."
        ),
    }
    dump_json(output_path, report)
    return report
