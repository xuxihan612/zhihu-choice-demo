#!/usr/bin/env python3
"""Merge independent gold annotations and validate every final case."""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiworks_pipeline.common import dump_json, load_json, sha256_text, utc_now
from aiworks_pipeline.schema import schema_for_scenario
from aiworks_pipeline.validation import validate_batch

CLAIM_FIELDS = (
    "claim", "option", "polarity", "evidence_quote", "conditions",
    "cost", "source_type", "confidence",
)


def canonical_case(case: dict[str, Any]) -> dict[str, Any]:
    claims = sorted(deepcopy(case["claims"]), key=lambda x: (x["evidence_quote"], x["option"], x["polarity"], x["claim"]))
    return {"candidate_id": case["candidate_id"], "status": case["status"], "claims": claims}


def validate_cases(
    cases: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    scenario: dict[str, Any],
    schema: dict[str, Any],
    label: str,
) -> None:
    candidate_ids = [x["candidate_id"] for x in cases]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError(f"{label}: duplicate candidate cases")
    for case in cases:
        quotes = [x["evidence_quote"] for x in case["claims"]]
        if len(quotes) != len(set(quotes)):
            raise ValueError(f"{label}: duplicate evidence_quote in {case['candidate_id']}")
        for claim in case["claims"]:
            if set(claim) != set(CLAIM_FIELDS):
                raise ValueError(f"{label}: claim fields must be exactly {CLAIM_FIELDS} in {case['candidate_id']}")
    batch = {"items": [{"candidate_id": x["candidate_id"], "status": x["status"], "claims": x["claims"]} for x in cases]}
    checked = validate_batch(batch, {x["candidate_id"]: x for x in candidates}, scenario, schema, run_metadata={"run_id": label, "fixture_run": False})
    if len(checked["item_results"]) != len(cases):
        raise ValueError(f"{label}: validation did not return one outcome per case")
    errors = [x for x in checked["item_results"] if x["status"] == "quarantined"]
    if errors:
        raise ValueError(f"{label}: {len(errors)} cases failed validation: {errors[:2]}")
    for case, outcome in zip(cases, checked["item_results"]):
        if outcome["status"] != case["status"]:
            raise ValueError(f"{label}: status changed for {case['candidate_id']}: {case['status']} -> {outcome['status']}")


def read_annotations(path: Path, candidate_map: dict[str, dict[str, Any]], scenario: dict[str, Any], schema: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    payload = load_json(path)
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise ValueError(f"{label}: cases must be an array")
    validate_cases(cases, list(candidate_map.values()), scenario, schema, label)
    result = {x["candidate_id"]: canonical_case(x) for x in cases}
    missing = set(candidate_map) - set(result)
    extra = set(result) - set(candidate_map)
    if missing or extra:
        raise ValueError(f"{label}: coverage mismatch; missing={sorted(missing)[:5]}, extra={sorted(extra)[:5]}")
    return result


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    candidate_payload = load_json(args.candidates)
    candidates = candidate_payload["candidates"]
    candidate_map = {x["candidate_id"]: x for x in candidates}
    scenario = load_json(args.scenario)
    schema = schema_for_scenario(load_json(ROOT / "schemas" / "extraction-v1.schema.json"), scenario)
    reviewer_a = read_annotations(Path(args.reviewer_a), candidate_map, scenario, schema, "reviewer A")
    reviewer_b = read_annotations(Path(args.reviewer_b), candidate_map, scenario, schema, "reviewer B")
    seed_cases = {x["candidate_id"]: x for x in load_json(args.seed)["cases"]}
    agreed: list[dict[str, Any]] = []
    divergent: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        a, b = reviewer_a[candidate_id], reviewer_b[candidate_id]
        item = {
            "candidate_id": candidate_id,
            "title": candidate["title"],
            "url": candidate["url"],
            "author": candidate["author"],
            "votes": candidate["votes"],
            "full_content_text": candidate["content_text"],
            "reviewer_a": a,
            "reviewer_b": b,
        }
        if candidate_id in seed_cases:
            item["manual_seed_reference"] = canonical_case(seed_cases[candidate_id])
            item["manual_seed_note"] = "Previously manually annotated seed case; provided only to the adjudicator, not to independent annotators."
        if a == b:
            agreed.append(item)
        else:
            divergent.append(item)
    output_dir = Path(args.output)
    payload = {
        "prepared_at": utc_now(),
        "candidate_manifest_sha256": sha256_text(Path(args.candidates).read_text(encoding="utf-8")),
        "reviewer_a_annotations_sha256": sha256_text(Path(args.reviewer_a).read_text(encoding="utf-8")),
        "reviewer_b_annotations_sha256": sha256_text(Path(args.reviewer_b).read_text(encoding="utf-8")),
        "candidate_count": len(candidates),
        "agreed_count": len(agreed),
        "divergent_count": len(divergent),
        "agreement_rate": round(len(agreed) / len(candidates), 4) if candidates else None,
        "agreement_definition": "Exact equality of canonical case status and every claim field after sorting claims by evidence_quote; this is not a semantic-agreement or model-quality metric.",
        "reviewer_types": {"reviewer_a": "AI", "reviewer_b": "AI"},
        "human_double_review_completed": False,
        "agreed": agreed,
        "divergent": divergent,
    }
    dump_json(output_dir / "gold-agreed.json", payload)
    dump_json(output_dir / "gold-adjudication-queue.json", {
        "queue_version": "1.0",
        "prepared_at": utc_now(),
        "review_standard": "Independently resolve each divergent case against its full source text. Use manual_seed_reference only where present. Return one complete case per candidate_id.",
        "total_divergent": len(divergent),
        "records": divergent,
    })
    print(json.dumps({k: payload[k] for k in ["candidate_count", "agreed_count", "divergent_count", "agreement_rate", "human_double_review_completed"]}, ensure_ascii=False))
    return payload


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    candidate_payload = load_json(args.candidates)
    candidates = candidate_payload["candidates"]
    candidate_map = {x["candidate_id"]: x for x in candidates}
    scenario = load_json(args.scenario)
    schema = schema_for_scenario(load_json(ROOT / "schemas" / "extraction-v1.schema.json"), scenario)
    agreed_payload = load_json(args.agreed)
    if agreed_payload.get("candidate_manifest_sha256") != sha256_text(Path(args.candidates).read_text(encoding="utf-8")):
        raise ValueError("candidate manifest changed after annotation preparation; rebuild partitions")
    partition_ids = [x["candidate_id"] for x in agreed_payload["agreed"]] + [x["candidate_id"] for x in agreed_payload["divergent"]]
    if len(partition_ids) != len(set(partition_ids)) or set(partition_ids) != set(candidate_map):
        raise ValueError("agreed/divergent partitions must be unique and exactly cover the candidate manifest")
    adjudicated = read_annotations(Path(args.adjudications), {x["candidate_id"]: candidate_map[x["candidate_id"]] for x in agreed_payload["divergent"]}, scenario, schema, "adjudicator")
    expected = {x["candidate_id"] for x in agreed_payload["divergent"]}
    if set(adjudicated) != expected:
        raise ValueError("adjudicator cases must cover exactly the divergent candidates")
    agreed_map = {x["candidate_id"]: x for x in agreed_payload["agreed"]}
    divergent_map = {x["candidate_id"]: x for x in agreed_payload["divergent"]}
    final_cases: list[dict[str, Any]] = []
    report_items: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        if candidate_id in agreed_map:
            item = agreed_map[candidate_id]
            case = deepcopy(item["reviewer_a"])
            path = "agreement"
        else:
            item = divergent_map[candidate_id]
            case = deepcopy(adjudicated[candidate_id])
            path = "adjudication"
        final_cases.append(case)
        report_items.append({
            "candidate_id": candidate_id,
            "path": path,
            "reviewer_a_status": item["reviewer_a"]["status"],
            "reviewer_b_status": item["reviewer_b"]["status"],
            "reviewer_a_claim_count": len(item["reviewer_a"]["claims"]),
            "reviewer_b_claim_count": len(item["reviewer_b"]["claims"]),
            "final_status": case["status"],
            "final_claim_count": len(case["claims"]),
            "had_manual_seed_reference": "manual_seed_reference" in item,
        })
    validate_cases(final_cases, candidates, scenario, schema, "final gold")
    output_dir = Path(args.output)
    final_cases.sort(key=lambda x: x["candidate_id"])
    gold = {
        "suite_version": "2.0",
        "scenario_id": scenario["id"],
        "dataset_role": "ai-assisted-development-set",
        "annotation_status": "dual-independent-ai-annotation-with-ai-adjudication; seed manual references preserved where available",
        "human_double_review_completed": False,
        "test_set_locked": False,
        "quality_reporting_eligible": False,
        "target_size": 50,
        "actual_size": len(final_cases),
        "candidate_manifest_sha256": sha256_text(Path(args.candidates).read_text(encoding="utf-8")),
        "note": "AI-assisted development set for regression, debugging and product demonstrations. Human double review is not planned for the current delivery, and this set must not be used to claim model quality.",
        "review_summary": {
            "agreed_count": agreed_payload["agreed_count"],
            "divergent_count": agreed_payload["divergent_count"],
            "agreement_rate": agreed_payload["agreement_rate"],
            "agreement_definition": "Exact equality of canonical case status and every claim field after sorting claims by evidence_quote; this is not a semantic-agreement or model-quality metric.",
            "reviewer_a_annotations_sha256": agreed_payload["reviewer_a_annotations_sha256"],
            "reviewer_b_annotations_sha256": agreed_payload["reviewer_b_annotations_sha256"],
            "adjudications_sha256": sha256_text(Path(args.adjudications).read_text(encoding="utf-8")),
            "reviewer_types": {"reviewer_a": "AI", "reviewer_b": "AI", "adjudicator": "AI"},
        },
        "cases": final_cases,
    }
    dump_json(output_dir / "coffee-gold-v1.json", gold)
    dump_json(output_dir / "coffee-ai-development-v1.json", gold)
    report = {
        "finalized_at": utc_now(),
        "dataset_role": "ai-assisted-development-set",
        "candidate_count": len(candidates),
        "claim_count": sum(len(x["claims"]) for x in final_cases),
        "status_counts": {status: sum(x["status"] == status for x in final_cases) for status in ["extracted", "insufficient_evidence", "irrelevant"]},
        "agreement_rate": agreed_payload["agreement_rate"],
        "agreement_definition": "Exact equality of canonical case status and every claim field after sorting claims by evidence_quote; this is not a semantic-agreement or model-quality metric.",
        "divergent_count": agreed_payload["divergent_count"],
        "human_double_review_completed": False,
        "test_set_locked": False,
        "quality_reporting_eligible": False,
        "validation": "All final cases passed schema, exact-evidence, enum and condition lexical-support checks.",
        "usage": "AI-assisted development set for regression, debugging and product demonstrations; not eligible for model-quality claims.",
        "items": report_items,
    }
    dump_json(output_dir / "gold-review-report.json", report)
    dump_json(output_dir / "ai-development-review-report.json", report)
    print(json.dumps({k: report[k] for k in ["candidate_count", "claim_count", "status_counts", "agreement_rate", "divergent_count", "human_double_review_completed", "test_set_locked"]}, ensure_ascii=False))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge and validate two independent AI development-set annotations")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--candidates", required=True)
    prepare_parser.add_argument("--scenario", required=True)
    prepare_parser.add_argument("--seed", required=True)
    prepare_parser.add_argument("--reviewer-a", required=True)
    prepare_parser.add_argument("--reviewer-b", required=True)
    prepare_parser.add_argument("--output", required=True)
    prepare_parser.set_defaults(func=prepare)
    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("--candidates", required=True)
    finalize_parser.add_argument("--scenario", required=True)
    finalize_parser.add_argument("--agreed", required=True)
    finalize_parser.add_argument("--adjudications", required=True)
    finalize_parser.add_argument("--output", required=True)
    finalize_parser.set_defaults(func=finalize)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
