#!/usr/bin/env python3
"""Verify reviewed export isolation, engineering metrics, and AI development-set integrity."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from adjudicate_gold import validate_cases
from adjudicate_reviews import CLAIM_FIELDS, read_actions
from aiworks_pipeline.common import dump_json, load_json, utc_now
from aiworks_pipeline.schema import schema_for_scenario
from aiworks_pipeline.validation import validate_batch


def js_value(text: str, name: str) -> Any:
    match = re.search(rf"window\.{re.escape(name)}\s*=\s*(.*?);\s*(?=window\.|$)", text, re.S)
    if not match:
        raise ValueError(f"missing JavaScript value: {name}")
    return json.loads(match.group(1))


def is_zhihu_url(value: Any) -> bool:
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname in {"www.zhihu.com", "zhuanlan.zhihu.com"}


def evidence_metrics(
    approved: list[dict[str, Any]],
    candidate_map: dict[str, dict[str, Any]],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    claims = approved
    main_exact = sum(claim["evidence_quote"] in candidate_map[claim["candidate_id"]]["content_text"] for claim in claims)
    cost_claims = [claim for claim in claims if claim.get("cost") is not None]
    cost_exact = sum(claim["cost"]["evidence_quote"] in candidate_map[claim["candidate_id"]]["content_text"] for claim in cost_claims)
    condition_checked = 0
    condition_supported = 0
    for claim in claims:
        source_text = candidate_map[claim["candidate_id"]]["content_text"]
        evidence_window = claim["evidence_quote"] + (" " + claim["cost"]["evidence_quote"] if claim.get("cost") else "")
        for key, value in claim["conditions"].items():
            if value is None:
                continue
            condition_checked += 1
            terms = scenario["conditions"][key].get("evidence_terms", {}).get(value, [])
            if not terms or any(term.lower() in evidence_window.lower() for term in terms):
                condition_supported += 1
    return {
        "approved_claims_checked": len(claims),
        "main_evidence_quotes_checked": len(claims),
        "main_evidence_quotes_exact": main_exact,
        "main_evidence_exact_rate": round(main_exact / len(claims), 4) if claims else None,
        "cost_evidence_quotes_checked": len(cost_claims),
        "cost_evidence_quotes_exact": cost_exact,
        "cost_evidence_exact_rate": round(cost_exact / len(cost_claims), 4) if cost_claims else None,
        "condition_fields_checked": condition_checked,
        "condition_fields_supported": condition_supported,
        "condition_support_rate": round(condition_supported / condition_checked, 4) if condition_checked else None,
    }


def main(args: argparse.Namespace) -> dict[str, Any]:
    run = load_json(args.run)
    actions_payload = load_json(args.actions)
    approved_payload = load_json(args.approved)
    approved = approved_payload["records"]
    prepared = load_json(args.prepared)
    scenario = load_json(args.scenario)
    schema = schema_for_scenario(load_json(ROOT / "schemas" / "extraction-v1.schema.json"), scenario)
    original_ids = {x["claim_id"] for x in run["accepted"]}
    action_ids = [x["claim_id"] for x in actions_payload["actions"]]
    approved_ids = [x["claim_id"] for x in approved]
    checks: dict[str, bool] = {}
    checks["actions_cover_all_original_claims"] = len(action_ids) == len(set(action_ids)) and set(action_ids) == original_ids
    checks["approved_ids_unique_and_from_run"] = len(approved_ids) == len(set(approved_ids)) and set(approved_ids) <= original_ids
    checks["all_approved_records_explicitly_reviewed"] = all(
        isinstance(x.get("review"), dict) and x["review"].get("reviewed") is True and x["review"].get("status") == "approved"
        for x in approved
    )
    checks["reviewer_is_not_misrepresented_as_human"] = "not human" in str(actions_payload.get("reviewer", "")).lower()
    final_review = read_actions(Path(args.actions), {x["claim_id"]: x for x in run["accepted"]}, "final delivery actions")
    expected_approved = {claim_id: action["effective_claim"] for claim_id, action in final_review.items() if action["effective_claim"] is not None}
    approved_map = {x["claim_id"]: x for x in approved}
    checks["approved_records_match_final_actions"] = set(approved_map) == set(expected_approved) and all(
        all(approved_map[claim_id].get(key) == value for key, value in expected.items())
        for claim_id, expected in expected_approved.items()
    )
    checks["rejected_actions_are_absent_from_approved"] = all(
        action["effective_claim"] is not None or claim_id not in approved_map
        for claim_id, action in final_review.items()
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in approved:
        grouped.setdefault(record["candidate_id"], []).append({key: record[key] for key in ["claim", "option", "polarity", "evidence_quote", "conditions", "cost", "source_type", "confidence"]})
    prepared_map = {x["candidate_id"]: x for x in prepared["kept"]}
    batch = {"items": [{"candidate_id": candidate_id, "status": "extracted", "claims": claims} for candidate_id, claims in grouped.items()]}
    revalidated = validate_batch(batch, prepared_map, scenario, schema, run_metadata=run["run"])
    checks["approved_claims_revalidate"] = len(revalidated["accepted"]) == len(approved) and not any(x["status"] == "quarantined" for x in revalidated["item_results"])
    evidence = evidence_metrics(approved, prepared_map, scenario)

    js = Path(args.dataset).read_text(encoding="utf-8")
    # Current demo exports use META/SOURCES/DEMO_STATS with claims nested under
    # their source. Older reviewed exports used flat PIPELINE_* values. Normalize
    # both formats here without changing the exported records or review verdicts.
    try:
        meta = js_value(js, "PIPELINE_META")
        sources = js_value(js, "PIPELINE_SOURCES")
        claims = js_value(js, "PIPELINE_CLAIMS")
        stats = js_value(js, "PIPELINE_STATS")
    except ValueError:
        meta = js_value(js, "META")
        sources = js_value(js, "SOURCES")
        stats = js_value(js, "DEMO_STATS")
        claims = [
            {**claim, "candidate_id": source["candidate_id"], "source": approved_map[claim["claim_id"]]["source"]}
            for source in sources
            for claim in source["claims"]
        ]
        meta = {**meta, "reviewed_only": bool(claims) and all(claim.get("reviewed") is True for claim in claims)}
    dataset_ids = [x["claim_id"] for x in claims]
    checks["dataset_contains_exactly_approved_claim_ids"] = len(dataset_ids) == len(set(dataset_ids)) and set(dataset_ids) == set(approved_ids)
    dataset_map = {x["claim_id"]: x for x in claims}
    checks["dataset_fields_match_approved_records"] = all(
        all(dataset_map[claim_id].get(key) == approved_map[claim_id].get(key) for key in (*CLAIM_FIELDS, "candidate_id", "source"))
        for claim_id in approved_ids
    )
    checks["dataset_meta_reviewed_only"] = meta.get("reviewed_only") is True
    checks["dataset_counts_match"] = stats.get("source_count") == len(sources) and stats.get("claim_count") == len(claims)
    checks["dataset_contains_no_pending_review_flag"] = all(x.get("reviewed") is True for x in claims)
    checks["approved_sources_have_complete_backlinks"] = all(
        isinstance(record.get("source"), dict)
        and bool(record["source"].get("title"))
        and bool(record["source"].get("author"))
        and is_zhihu_url(record["source"].get("url"))
        for record in approved
    )

    development = load_json(args.gold)
    development_candidates = load_json(args.gold_candidates)["candidates"]
    development_ids = [x["candidate_id"] for x in development["cases"]]
    checks["development_set_has_50_unique_cases"] = len(development_ids) == len(set(development_ids)) == 50
    checks["development_candidate_coverage_exact"] = set(development_ids) == {x["candidate_id"] for x in development_candidates}
    try:
        validate_cases(development["cases"], development_candidates, scenario, schema, "AI development set")
        checks["development_cases_revalidate"] = True
    except ValueError:
        checks["development_cases_revalidate"] = False
    checks["development_set_role_is_explicit"] = development.get("dataset_role") == "ai-assisted-development-set"
    checks["development_set_not_eligible_for_quality_reporting"] = (
        development.get("human_double_review_completed") is False
        and development.get("test_set_locked") is False
        and development.get("quality_reporting_eligible") is False
    )
    seed = load_json(Path(args.seed))
    seed_ids = [x["candidate_id"] for x in seed["cases"]]
    checks["seed_cases_remain_covered_as_regression_reference"] = len(seed_ids) == 5 and set(seed_ids) <= set(development_ids)

    evaluation_summary = None
    if args.evaluation:
        evaluation = load_json(Path(args.evaluation))
        missing = evaluation.get("metrics", {}).get("missing_candidates", [])
        evaluated = evaluation.get("metrics", {}).get("evaluated_candidates")
        checks["model_evaluation_is_diagnostic_only"] = (
            evaluation.get("quality_reporting_eligible") is False
            and "diagnostic" in str(evaluation.get("interpretation", "")).lower()
        )
        checks["model_evaluation_candidate_coverage_disclosed"] = (
            isinstance(evaluated, int)
            and 0 <= evaluated <= 50
            and isinstance(missing, list)
            and len(missing) == 50 - evaluated
        )
        evaluation_summary = {
            "evaluated_candidates": evaluated,
            "development_candidates": 50,
            "missing_candidates": len(missing),
            "quality_reporting_eligible": evaluation.get("quality_reporting_eligible"),
            "interpretation": evaluation.get("interpretation"),
        }

    approved_candidate_ids = {x["candidate_id"] for x in approved}
    prepared_candidate_ids = set(prepared_map)
    complete_backlinks = sum(
        isinstance(record.get("source"), dict)
        and bool(record["source"].get("title"))
        and bool(record["source"].get("author"))
        and is_zhihu_url(record["source"].get("url"))
        for record in approved
    )
    report = {
        "verified_at": utc_now(),
        "dataset_role": "ai-assisted-development-set",
        "checks": checks,
        "all_passed": all(checks.values()),
        "counts": {
            "original_claims": len(original_ids),
            "reviewed_actions": len(action_ids),
            "approved_claims": len(approved),
            "rejected_claims": sum(x["decision"] == "reject" for x in actions_payload["actions"]),
            "dataset_sources": len(sources),
            "dataset_claims": len(claims),
            "prepared_candidates": len(prepared_candidate_ids),
            "approved_candidates": len(approved_candidate_ids),
            "development_cases": len(development_ids),
            "development_claims": sum(len(x["claims"]) for x in development["cases"]),
            "seed_reference_cases": len(seed_ids),
        },
        "engineering_metrics": {
            "schema_valid_approved_claims": len(revalidated["accepted"]),
            "schema_pass_rate": round(len(revalidated["accepted"]) / len(approved), 4) if approved else None,
            **evidence,
            "complete_zhihu_backlinks": complete_backlinks,
            "backlink_complete_rate": round(complete_backlinks / len(approved), 4) if approved else None,
            "approved_candidate_coverage": round(len(approved_candidate_ids) / len(prepared_candidate_ids), 4) if prepared_candidate_ids else None,
            "development_candidate_coverage": round(len(set(development_ids)) / len(development_candidates), 4) if development_candidates else None,
        },
        "option_counts": dict(Counter(x["option"] for x in approved)),
        "polarity_counts": dict(Counter(x["polarity"] for x in approved)),
        "source_type_counts": dict(Counter(x["source_type"] for x in approved)),
        "model_evaluation": evaluation_summary,
        "quality_reporting_eligible": False,
        "limitations": [
            "Semantic review was performed by two independent AI passes plus AI adjudication, not by two humans.",
            "The 50-case set is an AI-assisted development set for regression and demonstrations; human double review is not planned for the current delivery.",
            "Model-evaluation metrics are diagnostic only and must not be presented as model-quality claims.",
        ],
    }
    dump_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify reviewed dataset and AI-assisted development set")
    parser.add_argument("--run", required=True)
    parser.add_argument("--actions", required=True)
    parser.add_argument("--approved", required=True)
    parser.add_argument("--prepared", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--gold", required=True, help="AI-assisted development-set JSON")
    parser.add_argument("--gold-candidates", required=True, help="AI-assisted development candidate manifest")
    parser.add_argument("--seed", default=str(ROOT / "tests" / "gold" / "coffee-seed-v1.json"))
    parser.add_argument("--evaluation", help="Optional diagnostic model-evaluation JSON")
    parser.add_argument("--output", required=True)
    return parser


if __name__ == "__main__":
    main(build_parser().parse_args())
