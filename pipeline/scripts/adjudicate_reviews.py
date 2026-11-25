#!/usr/bin/env python3
"""Merge two independent extraction reviews and route disagreements to an adjudicator."""
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

CLAIM_FIELDS = (
    "claim", "option", "polarity", "evidence_quote", "conditions",
    "cost", "source_type", "confidence",
)


def editable(record: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(record[key]) for key in CLAIM_FIELDS}


def read_actions(path: Path, records: dict[str, dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    payload = load_json(path)
    actions = payload.get("actions") if isinstance(payload, dict) else None
    if not isinstance(actions, list):
        raise ValueError(f"{label}: actions must be an array")
    result: dict[str, dict[str, Any]] = {}
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError(f"{label}: each action must be an object")
        claim_id = action.get("claim_id")
        if not isinstance(claim_id, str) or claim_id not in records:
            raise ValueError(f"{label}: unknown claim_id {claim_id!r}")
        if claim_id in result:
            raise ValueError(f"{label}: duplicate claim_id {claim_id}")
        candidate_id = records[claim_id]["candidate_id"]
        if action.get("candidate_id") != candidate_id:
            raise ValueError(f"{label}: candidate_id mismatch for {claim_id}")
        decision = action.get("decision")
        if decision not in {"accept", "modify", "reject"}:
            raise ValueError(f"{label}: invalid decision for {claim_id}")
        note = action.get("note", "")
        if not isinstance(note, str):
            raise ValueError(f"{label}: note must be a string for {claim_id}")
        if decision == "modify":
            claim = action.get("claim")
            if not isinstance(claim, dict) or set(claim) != set(CLAIM_FIELDS):
                raise ValueError(f"{label}: modified claim fields must be exactly {CLAIM_FIELDS} for {claim_id}")
            effective = deepcopy(claim)
        elif decision == "accept":
            effective = editable(records[claim_id])
        else:
            effective = None
        result[claim_id] = {
            "decision": decision,
            "effective_claim": effective,
            "note": note,
            "raw_action": deepcopy(action),
        }
    missing = set(records) - set(result)
    if missing:
        raise ValueError(f"{label}: missing {len(missing)} actions: {sorted(missing)[:5]}")
    return result


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    run = load_json(args.run)
    originals = {x["claim_id"]: x for x in run["accepted"]}
    queue = load_json(args.queue)
    full_text = {x["claim_id"]: x["full_content_text"] for x in queue["records"]}
    reviewer_a = read_actions(Path(args.reviewer_a), originals, "reviewer A")
    reviewer_b = read_actions(Path(args.reviewer_b), originals, "reviewer B")
    agreed: list[dict[str, Any]] = []
    divergent: list[dict[str, Any]] = []
    for claim_id, original in originals.items():
        a, b = reviewer_a[claim_id], reviewer_b[claim_id]
        same = a["effective_claim"] == b["effective_claim"]
        item = {
            "claim_id": claim_id,
            "candidate_id": original["candidate_id"],
            "original": editable(original),
            "reviewer_a": a,
            "reviewer_b": b,
            "difference_fields": [] if same else [
                key for key in CLAIM_FIELDS
                if (a["effective_claim"] or {}).get(key) != (b["effective_claim"] or {}).get(key)
            ],
            "full_content_text": full_text.get(claim_id),
            "source": original["source"],
        }
        if same:
            agreed.append(item)
        else:
            divergent.append(item)
    output_dir = Path(args.output)
    payload = {
        "prepared_at": utc_now(),
        "source_run": args.run,
        "source_run_sha256": sha256_text(Path(args.run).read_text(encoding="utf-8")),
        "source_queue_sha256": sha256_text(Path(args.queue).read_text(encoding="utf-8")),
        "reviewer_a_actions_sha256": sha256_text(Path(args.reviewer_a).read_text(encoding="utf-8")),
        "reviewer_b_actions_sha256": sha256_text(Path(args.reviewer_b).read_text(encoding="utf-8")),
        "reviewer_types": {"reviewer_a": "AI", "reviewer_b": "AI"},
        "independence_statement": "The two action files were requested in separate passes without access to each other's conclusions or the gold set.",
        "total_claims": len(originals),
        "agreed_count": len(agreed),
        "divergent_count": len(divergent),
        "agreement_rate": round(len(agreed) / len(originals), 4) if originals else None,
        "agreed": agreed,
        "divergent": divergent,
    }
    dump_json(output_dir / "agreed.json", payload)
    dump_json(output_dir / "adjudication-queue.json", {
        "queue_version": "1.0",
        "prepared_at": utc_now(),
        "review_standard": "Resolve against original source text and coffee.json; do not average reviewer opinions. Accept original, modify with a complete claim object, or reject.",
        "total_divergent": len(divergent),
        "records": divergent,
    })
    print(json.dumps({k: payload[k] for k in ["total_claims", "agreed_count", "divergent_count", "agreement_rate"]}, ensure_ascii=False))
    return payload


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    run = load_json(args.run)
    originals = {x["claim_id"]: x for x in run["accepted"]}
    agreed_payload = load_json(args.agreed)
    if agreed_payload.get("source_run_sha256") != sha256_text(Path(args.run).read_text(encoding="utf-8")):
        raise ValueError("source run changed after review preparation; rebuild the review queue")
    partition_ids = [x["claim_id"] for x in agreed_payload["agreed"]] + [x["claim_id"] for x in agreed_payload["divergent"]]
    if len(partition_ids) != len(set(partition_ids)) or set(partition_ids) != set(originals):
        raise ValueError("agreed/divergent partitions must be unique and exactly cover the source run")
    decisions = load_json(args.adjudications)
    if not isinstance(decisions, dict) or not isinstance(decisions.get("actions"), list):
        raise ValueError("adjudications must contain an actions array")
    adjudicated = read_actions(Path(args.adjudications), {x["claim_id"]: originals[x["claim_id"]] for x in agreed_payload["divergent"]}, "adjudicator")
    expected_divergent = {x["claim_id"] for x in agreed_payload["divergent"]}
    if set(adjudicated) != expected_divergent:
        raise ValueError("adjudicator actions must cover exactly the divergent claims")
    adjudication_map = {x["claim_id"]: x for x in decisions["actions"]}
    final_actions: list[dict[str, Any]] = []
    report_items: list[dict[str, Any]] = []
    counts = {"approved_unchanged": 0, "approved_modified": 0, "rejected": 0, "adjudicated": 0}
    for claim_id, original in originals.items():
        a = next(x for x in agreed_payload["agreed"] if x["claim_id"] == claim_id) if claim_id not in expected_divergent else None
        if a is not None:
            effective = a["reviewer_a"]["effective_claim"]
            if effective is None:
                action = {"claim_id": claim_id, "candidate_id": original["candidate_id"], "decision": "reject", "note": "Two independent AI reviewers agreed to reject. A: " + a["reviewer_a"]["note"] + " B: " + a["reviewer_b"]["note"]}
                outcome = "rejected"
            else:
                unchanged = effective == editable(original)
                action = {"claim_id": claim_id, "candidate_id": original["candidate_id"], "decision": "accept" if unchanged else "modify", "note": "Two independent AI reviewers agreed on the effective claim. A: " + a["reviewer_a"]["note"] + " B: " + a["reviewer_b"]["note"]}
                if not unchanged:
                    action["claim"] = effective
                outcome = "approved_unchanged" if unchanged else "approved_modified"
            report_items.append({"claim_id": claim_id, "path": "agreement", "reviewer_a_decision": a["reviewer_a"]["decision"], "reviewer_b_decision": a["reviewer_b"]["decision"], "outcome": outcome})
        else:
            chosen = adjudicated[claim_id]
            action = deepcopy(adjudication_map[claim_id])
            action["note"] = "Independent AI reviewers disagreed; AI adjudicator resolved. " + chosen["note"]
            if chosen["decision"] == "reject":
                outcome = "rejected"
            else:
                effective = chosen["effective_claim"]
                unchanged = effective == editable(original)
                action["decision"] = "accept" if unchanged else "modify"
                if not unchanged:
                    action["claim"] = effective
                outcome = "approved_unchanged" if unchanged else "approved_modified"
            counts["adjudicated"] += 1
            report_items.append({"claim_id": claim_id, "path": "adjudication", "reviewer_a_decision": next(x for x in agreed_payload["divergent"] if x["claim_id"] == claim_id)["reviewer_a"]["decision"], "reviewer_b_decision": next(x for x in agreed_payload["divergent"] if x["claim_id"] == claim_id)["reviewer_b"]["decision"], "adjudicator_decision": chosen["decision"], "outcome": outcome})
        counts[outcome] += 1
        final_actions.append(action)
    if len(final_actions) != len(originals):
        raise ValueError("final actions do not cover all original claims")
    output_dir = Path(args.output)
    dump_json(output_dir / "final-review-actions.json", {
        "reviewer": "AI dual independent review + AI adjudication (not human review)",
        "review_kind": "dual-ai-semantic-review-with-adjudication",
        "source_run": args.run,
        "finalized_at": utc_now(),
        "actions": final_actions,
    })
    report = {
        "finalized_at": utc_now(),
        "source_run": args.run,
        "source_run_sha256": agreed_payload["source_run_sha256"],
        "agreed_artifact_sha256": sha256_text(Path(args.agreed).read_text(encoding="utf-8")),
        "adjudications_sha256": sha256_text(Path(args.adjudications).read_text(encoding="utf-8")),
        "reviewer_types": {"reviewer_a": "AI", "reviewer_b": "AI", "adjudicator": decisions.get("adjudicator", "AI")},
        "human_review_completed": False,
        "limitation": "This is two independent AI semantic passes plus AI adjudication. It must not be represented as two-person human review.",
        "total_claims": len(originals),
        "agreement_rate": agreed_payload["agreement_rate"],
        "agreed_count": agreed_payload["agreed_count"],
        "divergent_count": agreed_payload["divergent_count"],
        "counts": counts,
        "items": report_items,
    }
    dump_json(output_dir / "final-review-report.json", report)
    print(json.dumps({k: report[k] for k in ["total_claims", "agreement_rate", "divergent_count", "counts", "human_review_completed"]}, ensure_ascii=False))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adjudicate two independent semantic review passes")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--run", required=True)
    prepare_parser.add_argument("--queue", required=True)
    prepare_parser.add_argument("--reviewer-a", required=True)
    prepare_parser.add_argument("--reviewer-b", required=True)
    prepare_parser.add_argument("--output", required=True)
    prepare_parser.set_defaults(func=prepare)
    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("--run", required=True)
    finalize_parser.add_argument("--agreed", required=True)
    finalize_parser.add_argument("--adjudications", required=True)
    finalize_parser.add_argument("--output", required=True)
    finalize_parser.set_defaults(func=finalize)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
