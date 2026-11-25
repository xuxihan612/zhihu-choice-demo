#!/usr/bin/env python3
"""Prepare, check, adjudicate, and lock independent human gold-review annotations."""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from adjudicate_gold import canonical_case, validate_cases
from aiworks_pipeline.common import dump_json, load_json, sha256_text, utc_now
from aiworks_pipeline.human_review import INDEPENDENCE_STATEMENT, REVIEW_KIND, build_human_gold_templates
from aiworks_pipeline.schema import schema_for_scenario


ADJUDICATION_KIND = "human-gold-adjudication"
AGREEMENT_DEFINITION = (
    "Exact equality of canonical case status and every claim field after sorting claims by evidence_quote; "
    "this is not a semantic-agreement or model-quality metric."
)


def _schema(scenario: dict[str, Any]) -> dict[str, Any]:
    return schema_for_scenario(load_json(ROOT / "schemas" / "extraction-v1.schema.json"), scenario)


def _require_signed_at(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: signed_at must not be empty")
    try:
        signed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label}: signed_at must be an ISO-8601 timestamp") from error
    if signed.tzinfo is None:
        raise ValueError(f"{label}: signed_at must include a timezone")
    return value.strip()


def _read_human_annotations(
    path: Path,
    slot: str,
    candidates: list[dict[str, Any]],
    scenario: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]], dict[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"reviewer {slot}: annotation file must contain an object")
    if payload.get("review_kind") != REVIEW_KIND:
        raise ValueError(f"reviewer {slot}: review_kind must be {REVIEW_KIND}")
    if payload.get("human_review") is not True:
        raise ValueError(f"reviewer {slot}: human_review must be true; AI output cannot be submitted as human review")
    if payload.get("reviewer_slot") != slot:
        raise ValueError(f"reviewer {slot}: reviewer_slot must be {slot}")
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError(f"reviewer {slot}: reviewer name must not be empty")
    if payload.get("scenario_id") != scenario["id"]:
        raise ValueError(f"reviewer {slot}: scenario_id mismatch")
    if payload.get("independence_statement") != INDEPENDENCE_STATEMENT:
        raise ValueError(f"reviewer {slot}: independence statement is missing or changed")
    _require_signed_at(payload.get("exported_at"), f"reviewer {slot}")
    attestation = payload.get("attestation")
    if not isinstance(attestation, dict) or attestation.get("independent_completion") is not True or attestation.get("source_only") is not True:
        raise ValueError(f"reviewer {slot}: signed source-only independence attestation is required")
    _require_signed_at(attestation.get("signed_at"), f"reviewer {slot} attestation")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"reviewer {slot}: cases must be an array")
    validate_cases(cases, candidates, scenario, _schema(scenario), f"human reviewer {slot}")
    annotations = {x["candidate_id"]: canonical_case(x) for x in cases}
    candidate_ids = {x["candidate_id"] for x in candidates}
    if len(cases) != len(candidate_ids) or set(annotations) != candidate_ids:
        raise ValueError(f"reviewer {slot}: cases must exactly cover all {len(candidate_ids)} candidates once")
    return reviewer.strip(), annotations, payload


def _read_human_adjudications(
    path: Path,
    candidates: list[dict[str, Any]],
    scenario: dict[str, Any],
    expected_ids: set[str],
) -> tuple[str, dict[str, dict[str, Any]], dict[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("human adjudication file must contain an object")
    if payload.get("review_kind") != ADJUDICATION_KIND:
        raise ValueError(f"human adjudication review_kind must be {ADJUDICATION_KIND}")
    if payload.get("human_review") is not True:
        raise ValueError("human adjudication must be explicitly marked human_review=true")
    adjudicator = payload.get("adjudicator")
    if not isinstance(adjudicator, str) or not adjudicator.strip():
        raise ValueError("human adjudicator name must not be empty")
    if payload.get("scenario_id") != scenario["id"]:
        raise ValueError("human adjudication scenario_id mismatch")
    _require_signed_at(payload.get("signed_at"), "human adjudicator")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("human adjudication cases must be an array")
    for case in cases:
        note = case.get("adjudication_note") if isinstance(case, dict) else None
        if not isinstance(note, str) or len(note.strip()) < 2 or len(note.strip()) > 500:
            raise ValueError(f"human adjudication requires a 2-500 character adjudication_note for {case.get('candidate_id') if isinstance(case, dict) else 'unknown'}")
    validate_cases(cases, candidates, scenario, _schema(scenario), "human adjudicator")
    annotations = {x["candidate_id"]: canonical_case(x) for x in cases}
    if len(cases) != len(expected_ids) or set(annotations) != expected_ids:
        raise ValueError("human adjudicator cases must cover exactly the divergent candidates once")
    return adjudicator.strip(), annotations, payload


def command_templates(args: argparse.Namespace) -> dict[str, Any]:
    payload = load_json(args.candidates)
    candidates = payload["candidates"]
    scenario = load_json(args.scenario)
    result = build_human_gold_templates(candidates, scenario, args.output)
    result["dataset_role"] = "ai-assisted-development-set"
    result["delivery_status"] = "optional-future-asset-not-a-current-blocker"
    result["manifest_sha256"] = sha256_text(Path(args.candidates).read_text(encoding="utf-8"))
    dump_json(Path(args.output) / "human-template-manifest.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _load_inputs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = load_json(args.candidates)["candidates"]
    scenario = load_json(args.scenario)
    return candidates, scenario


def command_check(args: argparse.Namespace) -> dict[str, Any]:
    candidates, scenario = _load_inputs(args)
    reviewer, annotations, payload = _read_human_annotations(Path(args.annotation), args.slot.upper(), candidates, scenario)
    result = {
        "valid": True,
        "reviewer": reviewer,
        "reviewer_slot": args.slot.upper(),
        "review_kind": REVIEW_KIND,
        "human_review": True,
        "candidate_count": len(annotations),
        "claim_count": sum(len(x["claims"]) for x in annotations.values()),
        "status_counts": {
            status: sum(x["status"] == status for x in annotations.values())
            for status in ["extracted", "insufficient_evidence", "irrelevant"]
        },
        "sha256": sha256_text(Path(args.annotation).read_text(encoding="utf-8")),
        "exported_at": payload.get("exported_at"),
        "attestation": payload.get("attestation"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def command_prepare(args: argparse.Namespace) -> dict[str, Any]:
    candidates, scenario = _load_inputs(args)
    reviewer_a, annotations_a, payload_a = _read_human_annotations(Path(args.reviewer_a), "A", candidates, scenario)
    reviewer_b, annotations_b, payload_b = _read_human_annotations(Path(args.reviewer_b), "B", candidates, scenario)
    if reviewer_a == reviewer_b:
        raise ValueError("reviewer A and reviewer B must be different people")
    agreed: list[dict[str, Any]] = []
    divergent: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        a, b = annotations_a[candidate_id], annotations_b[candidate_id]
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
        (agreed if a == b else divergent).append(item)
    output = Path(args.output)
    manifest_hash = sha256_text(Path(args.candidates).read_text(encoding="utf-8"))
    hash_a = sha256_text(Path(args.reviewer_a).read_text(encoding="utf-8"))
    hash_b = sha256_text(Path(args.reviewer_b).read_text(encoding="utf-8"))
    report = {
        "prepared_at": utc_now(),
        "review_kind": REVIEW_KIND,
        "reviewer_a": reviewer_a,
        "reviewer_b": reviewer_b,
        "reviewer_types": {"reviewer_a": "human", "reviewer_b": "human"},
        "independence_statement": "Both reviewers completed source-only templates independently. The preparer must not replace either reviewer's annotation.",
        "candidate_manifest_sha256": manifest_hash,
        "reviewer_a_annotations_sha256": hash_a,
        "reviewer_b_annotations_sha256": hash_b,
        "candidate_count": len(candidates),
        "agreed_count": len(agreed),
        "divergent_count": len(divergent),
        "agreement_rate": round(len(agreed) / len(candidates), 4) if candidates else None,
        "agreement_definition": AGREEMENT_DEFINITION,
        "human_double_review_completed": False,
        "test_set_locked": False,
        "quality_reporting_eligible": False,
        "note": "Human independent annotation has been collected and checked. Divergent cases still require human adjudication and sign-off before the gold set can be locked.",
    }
    dump_json(output / "human-agreed.json", report | {"agreed": agreed, "divergent": divergent})
    dump_json(output / "human-adjudication-queue.json", {
        "queue_version": "1.0",
        "prepared_at": utc_now(),
        "candidate_manifest_sha256": manifest_hash,
        "reviewer_a_annotations_sha256": hash_a,
        "reviewer_b_annotations_sha256": hash_b,
        "reviewer_types": {"reviewer_a": "human", "reviewer_b": "human"},
        "review_standard": "A human adjudicator must resolve every divergent case against the full source text. Return one complete case per candidate_id, add an adjudication_note, and sign the result. Do not copy an AI gold answer.",
        "total_divergent": len(divergent),
        "records": divergent,
    })
    print(json.dumps({key: report[key] for key in ["candidate_count", "agreed_count", "divergent_count", "agreement_rate", "human_double_review_completed", "test_set_locked"]}, ensure_ascii=False))
    return report


def command_adjudication_template(args: argparse.Namespace) -> dict[str, Any]:
    queue = load_json(args.queue)
    if queue.get("reviewer_types") != {"reviewer_a": "human", "reviewer_b": "human"}:
        raise ValueError("adjudication template requires a human-prepared divergence queue")
    records = queue.get("records")
    if not isinstance(records, list):
        raise ValueError("adjudication queue must contain records")
    scenario = load_json(args.scenario)
    cases = []
    for record in records:
        cases.append({
            "candidate_id": record["candidate_id"],
            "status": None,
            "claims": [],
            "adjudication_note": "",
            "source": {
                "title": record["title"],
                "url": record["url"],
                "author": record["author"],
                "votes": record["votes"],
                "content_type": record.get("content_type", "unknown"),
            },
            "full_content_text": record["full_content_text"],
            "reviewer_a": deepcopy(record["reviewer_a"]),
            "reviewer_b": deepcopy(record["reviewer_b"]),
        })
    result = {
        "template_version": "1.0",
        "generated_at": utc_now(),
        "scenario_id": scenario["id"],
        "review_kind": ADJUDICATION_KIND,
        "human_review": True,
        "adjudicator": "",
        "signed_at": "",
        "decision_note": "Resolve each case against full_content_text. The two human annotations are evidence of disagreement, not an answer key. Add a 2-500 character adjudication_note to every case.",
        "candidate_count": len(cases),
        "cases": cases,
    }
    output = Path(args.output)
    dump_json(output, result)
    print(json.dumps({"adjudication_template": str(output), "candidate_count": len(cases)}, ensure_ascii=False))
    return result


def command_check_adjudication(args: argparse.Namespace) -> dict[str, Any]:
    candidates, scenario = _load_inputs(args)
    queue = load_json(args.queue)
    if queue.get("reviewer_types") != {"reviewer_a": "human", "reviewer_b": "human"}:
        raise ValueError("queue is not marked as a human divergence queue")
    if queue.get("candidate_manifest_sha256") != sha256_text(Path(args.candidates).read_text(encoding="utf-8")):
        raise ValueError("candidate manifest changed after the divergence queue was prepared")
    expected_ids = {x["candidate_id"] for x in queue.get("records", [])}
    adjudicator, annotations, payload = _read_human_adjudications(Path(args.adjudication), candidates, scenario, expected_ids)
    result = {
        "valid": True,
        "adjudicator": adjudicator,
        "review_kind": ADJUDICATION_KIND,
        "human_review": True,
        "candidate_count": len(annotations),
        "claim_count": sum(len(x["claims"]) for x in annotations.values()),
        "status_counts": {
            status: sum(x["status"] == status for x in annotations.values())
            for status in ["extracted", "insufficient_evidence", "irrelevant"]
        },
        "sha256": sha256_text(Path(args.adjudication).read_text(encoding="utf-8")),
        "signed_at": payload.get("signed_at"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def command_finalize(args: argparse.Namespace) -> dict[str, Any]:
    lock_approved_by = args.lock_approved_by.strip()
    lock_note = args.lock_note.strip()
    if not lock_approved_by:
        raise ValueError("lock-approved-by must not be empty")
    if len(lock_note) < 2:
        raise ValueError("lock-note must contain at least 2 characters")
    candidates, scenario = _load_inputs(args)
    if len(candidates) != 50:
        raise ValueError("human gold lock requires exactly 50 candidates")
    candidate_map = {x["candidate_id"]: x for x in candidates}
    reviewer_a, annotations_a, _ = _read_human_annotations(Path(args.reviewer_a), "A", candidates, scenario)
    reviewer_b, annotations_b, _ = _read_human_annotations(Path(args.reviewer_b), "B", candidates, scenario)
    if reviewer_a == reviewer_b:
        raise ValueError("reviewer A and reviewer B must be different people")
    agreed_payload = load_json(args.agreed)
    manifest_hash = sha256_text(Path(args.candidates).read_text(encoding="utf-8"))
    if agreed_payload.get("candidate_manifest_sha256") != manifest_hash:
        raise ValueError("candidate manifest changed after human review preparation")
    if agreed_payload.get("reviewer_types") != {"reviewer_a": "human", "reviewer_b": "human"}:
        raise ValueError("agreed payload is not marked as human review")
    if agreed_payload.get("reviewer_a_annotations_sha256") != sha256_text(Path(args.reviewer_a).read_text(encoding="utf-8")):
        raise ValueError("reviewer A annotation file changed after preparation")
    if agreed_payload.get("reviewer_b_annotations_sha256") != sha256_text(Path(args.reviewer_b).read_text(encoding="utf-8")):
        raise ValueError("reviewer B annotation file changed after preparation")
    agreed_items = agreed_payload.get("agreed")
    divergent_items = agreed_payload.get("divergent")
    if not isinstance(agreed_items, list) or not isinstance(divergent_items, list):
        raise ValueError("human-agreed.json must contain agreed and divergent arrays")
    partition_ids = [x.get("candidate_id") for x in agreed_items + divergent_items]
    if len(partition_ids) != len(set(partition_ids)) or set(partition_ids) != set(candidate_map):
        raise ValueError("agreed/divergent partitions must be unique and exactly cover the candidate manifest")
    for item in agreed_items + divergent_items:
        candidate_id = item["candidate_id"]
        if item.get("reviewer_a") != annotations_a[candidate_id] or item.get("reviewer_b") != annotations_b[candidate_id]:
            raise ValueError(f"prepared reviewer annotations do not match signed files for {candidate_id}")
        if (item in agreed_items) != (annotations_a[candidate_id] == annotations_b[candidate_id]):
            raise ValueError(f"agreed/divergent placement is wrong for {candidate_id}")
    divergent_ids = {x["candidate_id"] for x in divergent_items}
    adjudicator, adjudications, adjudication_payload = _read_human_adjudications(
        Path(args.adjudications),
        [candidate_map[x] for x in divergent_ids],
        scenario,
        divergent_ids,
    )
    agreed_map = {x["candidate_id"]: x for x in agreed_items}
    final_cases: list[dict[str, Any]] = []
    report_items: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        if candidate_id in agreed_map:
            case = deepcopy(annotations_a[candidate_id])
            path = "agreement"
            note = "Two independent human annotations matched exactly."
        else:
            case = deepcopy(adjudications[candidate_id])
            path = "adjudication"
            note = next(x["adjudication_note"] for x in adjudication_payload["cases"] if x["candidate_id"] == candidate_id)
        final_cases.append(case)
        report_items.append({
            "candidate_id": candidate_id,
            "path": path,
            "reviewer_a_status": annotations_a[candidate_id]["status"],
            "reviewer_b_status": annotations_b[candidate_id]["status"],
            "reviewer_a_claim_count": len(annotations_a[candidate_id]["claims"]),
            "reviewer_b_claim_count": len(annotations_b[candidate_id]["claims"]),
            "final_status": case["status"],
            "final_claim_count": len(case["claims"]),
            "adjudication_note": note,
        })
    validate_cases(final_cases, candidates, scenario, _schema(scenario), "final human gold")
    final_cases.sort(key=lambda x: x["candidate_id"])
    output = Path(args.output)
    locked_at = utc_now()
    gold = {
        "suite_version": "2.0",
        "scenario_id": scenario["id"],
        "annotation_status": "dual-independent-human-annotation-with-human-adjudication",
        "human_double_review_completed": True,
        "test_set_locked": True,
        "quality_reporting_eligible": True,
        "target_size": 50,
        "actual_size": len(final_cases),
        "candidate_manifest_sha256": manifest_hash,
        "locked_at": locked_at,
        "lock_signoff": {"approved_by": lock_approved_by, "approved_at": locked_at, "note": lock_note},
        "note": "Locked only after two distinct signed human annotations, human adjudication of every divergent case, and explicit lock sign-off.",
        "review_summary": {
            "reviewer_a": reviewer_a,
            "reviewer_b": reviewer_b,
            "adjudicator": adjudicator,
            "reviewer_types": {"reviewer_a": "human", "reviewer_b": "human", "adjudicator": "human"},
            "agreed_count": len(agreed_items),
            "divergent_count": len(divergent_items),
            "agreement_rate": agreed_payload.get("agreement_rate"),
            "agreement_definition": AGREEMENT_DEFINITION,
            "reviewer_a_annotations_sha256": agreed_payload["reviewer_a_annotations_sha256"],
            "reviewer_b_annotations_sha256": agreed_payload["reviewer_b_annotations_sha256"],
            "adjudications_sha256": sha256_text(Path(args.adjudications).read_text(encoding="utf-8")),
        },
        "cases": final_cases,
    }
    dump_json(output / "coffee-gold-human-v1.json", gold)
    report = {
        "finalized_at": locked_at,
        "candidate_count": len(final_cases),
        "claim_count": sum(len(x["claims"]) for x in final_cases),
        "status_counts": {status: sum(x["status"] == status for x in final_cases) for status in ["extracted", "insufficient_evidence", "irrelevant"]},
        "agreement_rate": agreed_payload.get("agreement_rate"),
        "agreement_definition": AGREEMENT_DEFINITION,
        "divergent_count": len(divergent_items),
        "reviewer_a": reviewer_a,
        "reviewer_b": reviewer_b,
        "adjudicator": adjudicator,
        "lock_signoff": gold["lock_signoff"],
        "human_double_review_completed": True,
        "test_set_locked": True,
        "quality_reporting_eligible": True,
        "validation": "All final cases passed schema, exact-evidence, enum and condition lexical-support checks.",
        "items": report_items,
    }
    dump_json(output / "human-gold-review-report.json", report)
    print(json.dumps({key: report[key] for key in ["candidate_count", "claim_count", "status_counts", "agreement_rate", "divergent_count", "human_double_review_completed", "test_set_locked", "quality_reporting_eligible"]}, ensure_ascii=False))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare, adjudicate, and lock independent human gold-review annotations")
    sub = parser.add_subparsers(dest="command", required=True)

    templates = sub.add_parser("templates", help="Generate source-only A/B JSON templates and offline HTML workbenches")
    templates.add_argument("--candidates", default=str(ROOT / "review" / "gold-v1" / "gold-candidates.json"))
    templates.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    templates.add_argument("--output", default=str(ROOT / "review" / "gold-v1" / "human-review"))
    templates.set_defaults(func=command_templates)

    check = sub.add_parser("check", help="Validate one completed and signed human annotation file")
    check.add_argument("--annotation", required=True)
    check.add_argument("--slot", choices=["a", "b"], required=True)
    check.add_argument("--candidates", default=str(ROOT / "review" / "gold-v1" / "gold-candidates.json"))
    check.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    check.set_defaults(func=command_check)

    prepare = sub.add_parser("prepare", help="Compare two signed human files and build a divergence queue")
    prepare.add_argument("--reviewer-a", required=True)
    prepare.add_argument("--reviewer-b", required=True)
    prepare.add_argument("--candidates", default=str(ROOT / "review" / "gold-v1" / "gold-candidates.json"))
    prepare.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    prepare.add_argument("--output", default=str(ROOT / "review" / "gold-v1" / "human-review" / "prepared"))
    prepare.set_defaults(func=command_prepare)

    adjudication = sub.add_parser("adjudication-template", help="Build a blank signed human-adjudicator file from a prepared divergence queue")
    adjudication.add_argument("--queue", required=True)
    adjudication.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    adjudication.add_argument("--output", default=str(ROOT / "review" / "gold-v1" / "human-review" / "human-adjudicator.template.json"))
    adjudication.set_defaults(func=command_adjudication_template)

    check_adjudication = sub.add_parser("check-adjudication", help="Validate a completed and signed human adjudication file")
    check_adjudication.add_argument("--queue", required=True)
    check_adjudication.add_argument("--adjudication", required=True)
    check_adjudication.add_argument("--candidates", default=str(ROOT / "review" / "gold-v1" / "gold-candidates.json"))
    check_adjudication.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    check_adjudication.set_defaults(func=command_check_adjudication)

    finalize = sub.add_parser("finalize", help="Validate all human evidence and lock the gold set with explicit sign-off")
    finalize.add_argument("--reviewer-a", required=True)
    finalize.add_argument("--reviewer-b", required=True)
    finalize.add_argument("--agreed", required=True)
    finalize.add_argument("--adjudications", required=True)
    finalize.add_argument("--lock-approved-by", required=True)
    finalize.add_argument("--lock-note", required=True)
    finalize.add_argument("--candidates", default=str(ROOT / "review" / "gold-v1" / "gold-candidates.json"))
    finalize.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    finalize.add_argument("--output", default=str(ROOT / "review" / "gold-v1" / "human-review" / "final"))
    finalize.set_defaults(func=command_finalize)
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
