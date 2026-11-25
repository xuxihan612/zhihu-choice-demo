#!/usr/bin/env python3
"""Build the reviewed coffee Demo data consumed by the static frontend."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiworks_pipeline.common import dump_json, load_json, sha256_text  # noqa: E402

KIND_LABEL = {"experience": "真实使用经验", "guide": "导购测评", "cleaning": "清洁保养教程"}


def claim_validation(record: dict[str, Any], candidate: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    evidence = record["evidence_quote"]
    cost = record.get("cost")
    searchable = evidence + ("\n" + cost["evidence_quote"] if cost else "")
    support = []
    for key in scenario["conditions"]:
        value = record["conditions"][key]
        if value is None:
            continue
        terms = scenario["conditions"][key]["evidence_terms"][value]
        matched = [term for term in terms if term in searchable]
        support.append({"key": key, "value": value, "matched_terms": matched, "supported": bool(matched)})
    schema_valid = (
        all(key in record for key in ("claim_id", "claim", "option", "polarity", "evidence_quote", "conditions", "cost", "source_type", "confidence"))
        and record["option"] in {option["id"] for option in scenario["options"]}
        and record["polarity"] in {"pro", "con"}
        and isinstance(record["confidence"], (int, float))
        and all(item["supported"] for item in support)
    )
    start = max(0, int(record.get("evidence_start", candidate["content_text"].find(evidence))) - 100)
    evidence_end = int(record.get("evidence_end", start + len(evidence)))
    end = min(len(candidate["content_text"]), evidence_end + 100)
    return {
        "schema_valid": schema_valid,
        "main_evidence_exact": evidence in candidate["content_text"],
        "cost_evidence_exact": cost["evidence_quote"] in candidate["content_text"] if cost else None,
        "condition_support": support,
        "review_approved": record.get("review", {}).get("reviewed") is True and record.get("review", {}).get("status") == "approved",
    }


def build(approved_path: Path, prepared_path: Path, scenario_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    approved_payload = load_json(approved_path)
    prepared_payload = load_json(prepared_path)
    scenario = load_json(scenario_path)
    records = approved_payload["records"]
    prepared = {item["candidate_id"]: item for item in prepared_payload["kept"]}
    condition_keys = list(scenario["conditions"])
    if not records:
        raise ValueError("approved export is empty")
    if len({record["claim_id"] for record in records}) != len(records):
        raise ValueError("approved claim IDs must be unique")
    if len({record["candidate_id"] for record in records}) != 29:
        raise ValueError("this Demo release expects 29 reviewed sources")

    for record in records:
        review = record.get("review", {})
        if review.get("reviewed") is not True or review.get("status") != "approved":
            raise ValueError(f"unapproved record in Demo export: {record['claim_id']}")
        candidate = prepared.get(record["candidate_id"])
        if candidate is None:
            raise ValueError(f"missing prepared candidate: {record['candidate_id']}")
        source = record["source"]
        parsed = urlsplit(source["url"])
        if parsed.scheme != "https" or parsed.hostname not in {"www.zhihu.com", "zhuanlan.zhihu.com"}:
            raise ValueError(f"invalid Zhihu backlink: {source['url']}")
        if not source.get("title") or not source.get("author"):
            raise ValueError(f"incomplete source metadata: {record['claim_id']}")
        if record["evidence_quote"] not in candidate["content_text"]:
            raise ValueError(f"main evidence is not exact: {record['claim_id']}")
        cost = record.get("cost")
        if cost and cost["evidence_quote"] not in candidate["content_text"]:
            raise ValueError(f"cost evidence is not exact: {record['claim_id']}")
        if set(record["conditions"]) != set(condition_keys):
            raise ValueError(f"condition keys do not match scenario: {record['claim_id']}")
        validation = claim_validation(record, candidate, scenario)
        if not validation["schema_valid"] or not validation["review_approved"]:
            raise ValueError(f"claim validation failed: {record['claim_id']}")

    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(record["candidate_id"], []).append(record)

    sources: list[dict[str, Any]] = []
    for index, (candidate_id, items) in enumerate(sorted(groups.items()), 1):
        representative = max(items, key=lambda x: (x["confidence"], len(x["evidence_quote"]), x["source"]["votes"]))
        known: dict[str, str | None] = {}
        for key in condition_keys:
            values = {item["conditions"][key] for item in items if item["conditions"][key] is not None}
            known[key] = next(iter(values)) if len(values) == 1 else None
        lean_scores = {"capsule": 0, "semi": 0}
        for item in items:
            if item["polarity"] == "pro":
                lean_scores[item["option"]] += 1
            else:
                other = next(option["id"] for option in scenario["options"] if option["id"] != item["option"])
                lean_scores[other] += 1
        leans = max(lean_scores, key=lean_scores.get) if lean_scores["capsule"] != lean_scores["semi"] else None
        current_candidate = prepared[candidate_id]
        claims = [
            {
                "claim_id": item["claim_id"],
                "claim": item["claim"],
                "option": item["option"],
                "polarity": item["polarity"],
                "evidence_quote": item["evidence_quote"],
                "raw_excerpt": current_candidate["content_text"][
                    max(0, int(item.get("evidence_start", current_candidate["content_text"].find(item["evidence_quote"]))) - 100):
                    min(len(current_candidate["content_text"]), int(item.get("evidence_end", 0)) + 100)
                ],
                "conditions": item["conditions"],
                "cost": item["cost"],
                "source_type": item["source_type"],
                "confidence": item["confidence"],
                "validation": claim_validation(item, current_candidate, scenario),
                "reviewed": True,
            }
            for item in items
        ]
        source = representative["source"]
        representative_candidate = prepared[candidate_id]
        sources.append(
            {
                "id": f"{scenario['id']}-s{index}",
                "candidate_id": candidate_id,
                "kind": Counter(item["source_type"] for item in items).most_common(1)[0][0],
                "leans": leans,
                "author": source["author"],
                "badge": source["badge"],
                "votes": source["votes"],
                "title": source["title"],
                "url": source["url"],
                "source_api": representative_candidate["source_api"],
                "content_sha256": representative_candidate["content_sha256"],
                "extraction_run": representative["run"],
                "quote": representative["evidence_quote"],
                "known": known,
                "claims": claims,
            }
        )

    reviewed_dates = [item["review"].get("reviewed_at", "") for item in records]
    reviewed_dates = [value for value in reviewed_dates if value]
    generated_at = max(reviewed_dates) if reviewed_dates else "2026-11-24"
    meta = {
        "question": "想买一台家用咖啡机，有什么建议？",
        "questionUrl": "https://www.zhihu.com/question/49701633",
        "fetchedAt": generated_at[:10],
        "source": "知乎数据开放平台 zhihu_search / global_search",
        "datasetRole": "AI-assisted-development-set",
        "humanDoubleReviewCompleted": False,
        "qualityReportingEligible": False,
        "reviewer": "AI dual independent review + AI adjudication (not human review)",
        "pipelineMode": "offline-reviewed-export",
        "modelCalledInBrowser": False,
        "approvedClaimsSha256": sha256_text(approved_path.read_text(encoding="utf-8")),
    }
    stats = {
        "source_count": len(sources),
        "claim_count": len(records),
        "source_type_counts": dict(Counter(item["source_type"] for item in records)),
        "option_counts": dict(Counter(item["option"] for item in records)),
        "polarity_counts": dict(Counter(item["polarity"] for item in records)),
        "condition_coverage": {key: sum(item["conditions"][key] is not None for item in records) for key in condition_keys},
        "complete_zhihu_backlinks": len(sources),
        "exact_main_evidence_quotes": len(records),
        "exact_cost_evidence_quotes": sum(item.get("cost") is not None for item in records),
        "generated_at": generated_at,
    }
    return meta, sources, stats


def render(meta: dict[str, Any], sources: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    def js(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

    return (
        "/* Generated from approved-extractions.json. Reviewed claims only; not human double review. */\n"
        + "window.META = " + js(meta) + ";\n"
        + "window.KIND_LABEL = " + js(KIND_LABEL) + ";\n"
        + "window.SOURCES = " + js(sources) + ";\n"
        + "window.DEMO_STATS = " + js(stats) + ";\n"
    )


def main() -> int:
    project_root = ROOT.parent
    parser = argparse.ArgumentParser(description="Build reviewed data for all static Demo candidates")
    parser.add_argument("--approved", default=str(ROOT / "runs" / "approved-v1" / "approved-extractions.json"))
    parser.add_argument("--prepared", default=str(ROOT / "runs" / "prepared-v1.json"))
    parser.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    parser.add_argument("--outputs", nargs="+", default=[str(project_root / name / "data.js") for name in ("prototype", "deploy", "deploy-probe")])
    args = parser.parse_args()
    meta, sources, stats = build(Path(args.approved), Path(args.prepared), Path(args.scenario))
    text = render(meta, sources, stats)
    hashes = {}
    for output in args.outputs:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        hashes[str(target)] = sha256_text(text)
    report = {
        "generated_at": stats["generated_at"],
        "source_count": stats["source_count"],
        "claim_count": stats["claim_count"],
        "dataset_role": meta["datasetRole"],
        "human_double_review_completed": False,
        "quality_reporting_eligible": False,
        "output_sha256": hashes,
        "stats": stats,
    }
    dump_json(ROOT / "runs" / "approved-v1" / "demo-data-manifest.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
