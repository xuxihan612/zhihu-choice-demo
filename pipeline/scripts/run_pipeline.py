#!/usr/bin/env python3
"""CLI for the offline Zhihu decision extraction pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiworks_pipeline.candidates import prepare_candidates
from aiworks_pipeline.assembly import assemble_batches
from aiworks_pipeline.audit import audit_run
from aiworks_pipeline.common import dump_json, load_json, sha256_text
from aiworks_pipeline.dataset import generate_dataset
from aiworks_pipeline.evaluation import evaluate_run, modification_rate
from aiworks_pipeline.providers import make_provider
from aiworks_pipeline.review import apply_review_actions, build_review_queue
from aiworks_pipeline.repairs import apply_repair_batches
from aiworks_pipeline.runner import run_extraction
from aiworks_pipeline.schema import schema_for_scenario


def default_raw() -> Path:
    return ROOT.parent / "prototype" / "data" / "raw_candidates.json"


def scenario_and_schema(path: str):
    scenario = load_json(path)
    schema = schema_for_scenario(load_json(ROOT / "schemas" / "extraction-v1.schema.json"), scenario)
    return scenario, schema


def read_raw(path: str) -> list[dict]:
    payload = load_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("Data"), dict):
        return payload["Data"]["Items"]
    raise ValueError("raw input must be an array or Zhihu response with Data.Items")


def command_prepare(args):
    scenario, _ = scenario_and_schema(args.scenario)
    result = prepare_candidates(read_raw(args.raw), scenario)
    dump_json(args.output, result)
    print(json.dumps({k: result[k] for k in ["input_count", "kept_count", "rejected_count", "reject_reasons"]}, ensure_ascii=False))


def command_extract(args):
    scenario, schema = scenario_and_schema(args.scenario)
    prepared = load_json(args.prepared)
    candidates = prepared["kept"]
    if args.ids:
        wanted = set(args.ids.split(","))
        unknown = wanted - {x["candidate_id"] for x in candidates}
        if unknown:
            raise ValueError("unknown candidate ids: " + ", ".join(sorted(unknown)))
        candidates = [x for x in candidates if x["candidate_id"] in wanted]
    provider = make_provider(args)
    template = Path(args.prompt).read_text(encoding="utf-8")
    result = run_extraction(candidates, scenario, schema, template, provider, args.run_dir, prompt_version=args.prompt_version, batch_size=args.batch_size, max_retries=args.retries, timeout=args.timeout)
    print(json.dumps({"run_dir": args.run_dir, "candidate_count": result["candidate_count"], "accepted_claim_count": result["accepted_claim_count"], "status_counts": result["status_counts"]}, ensure_ascii=False))


def command_assemble(args):
    scenario, schema = scenario_and_schema(args.scenario)
    input_dir, raw_dir = Path(args.input_dir), Path(args.raw_dir)
    batches = []
    for input_path in sorted(input_dir.glob("batch-*.json")):
        raw_path = raw_dir / input_path.name
        raw_text = raw_path.read_text(encoding="utf-8") if raw_path.exists() else None
        batches.append((load_json(input_path), raw_text))
    if not batches:
        raise ValueError("no batch input files found")
    prompt_path = Path(args.prompt)
    result = assemble_batches(batches, scenario, schema, args.run_dir, prompt_version=args.prompt_version, prompt_sha256=sha256_text(prompt_path.read_text(encoding="utf-8")))
    print(json.dumps({"run_dir": args.run_dir, "candidate_count": result["candidate_count"], "accepted_claim_count": result["accepted_claim_count"], "status_counts": result["status_counts"]}, ensure_ascii=False))


def command_repair(args):
    scenario, schema = scenario_and_schema(args.scenario)
    input_dir, raw_dir = Path(args.input_dir), Path(args.raw_dir)
    batches = []
    repair_prompt_hashes = []
    for input_path in sorted(input_dir.glob("repair-*.json")):
        raw_path = raw_dir / input_path.name
        repair_prompt_path = input_path.with_suffix(".prompt.txt")
        if not repair_prompt_path.exists():
            raise ValueError(f"repair prompt is missing: {repair_prompt_path}")
        repair_prompt_hashes.append(sha256_text(repair_prompt_path.read_text(encoding="utf-8")))
        raw_text = raw_path.read_text(encoding="utf-8") if raw_path.exists() else None
        batches.append((load_json(input_path), raw_text))
    if not batches:
        raise ValueError("no repair input files found")
    prompt_path = Path(args.prompt)
    result = apply_repair_batches(
        load_json(args.run), batches, scenario, schema, args.run_dir,
        prompt_version=args.prompt_version,
        prompt_sha256=sha256_text(prompt_path.read_text(encoding="utf-8")),
        repair_prompt_hashes=repair_prompt_hashes,
    )
    print(json.dumps({"run_dir": args.run_dir, "accepted_claim_count": result["accepted_claim_count"], "status_counts": result["status_counts"], "repair_batches": len(batches)}, ensure_ascii=False))


def command_review(args):
    run = load_json(args.run)
    prepared = load_json(args.prepared)
    queue = build_review_queue(run, prepared["kept"], args.output)
    print(json.dumps({"queue": str(Path(args.output) / "review-queue.json"), "html": str(Path(args.output) / "review.html"), "pending_claims": queue["summary"]["pending_claims"]}, ensure_ascii=False))


def command_apply(args):
    scenario, schema = scenario_and_schema(args.scenario)
    result = apply_review_actions(load_json(args.run), load_json(args.prepared)["kept"], scenario, schema, args.actions, args.output, reviewer=args.reviewer)
    rates = modification_rate(result)
    result["metrics"] = rates
    dump_json(Path(args.output) / "review-result.json", result)
    print(json.dumps({k: result[k] for k in ["approved_count", "rejected_count", "pending_count", "metrics"]}, ensure_ascii=False))


def command_dataset(args):
    scenario, _ = scenario_and_schema(args.scenario)
    approved = load_json(args.approved)["records"]
    stats = generate_dataset(approved, scenario, args.output)
    print(json.dumps(stats, ensure_ascii=False))


def command_audit(args):
    scenario, schema = scenario_and_schema(args.scenario)
    report = audit_run(load_json(args.run), load_json(args.prepared)["kept"], scenario, schema, args.output)
    print(json.dumps({"report": args.output, "accepted_claim_count": report["accepted_claim_count"], "integrity": report["integrity"]}, ensure_ascii=False))


def command_evaluate(args):
    run = load_json(args.run)
    gold = load_json(args.gold)
    prepared = load_json(args.prepared)
    report = evaluate_run(run, gold, prepared["kept"], args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def add_provider_args(parser):
    parser.add_argument("--provider", choices=["fixture", "openai", "command"], default="fixture")
    parser.add_argument("--fixture", default=str(ROOT / "tests" / "fixtures" / "coffee-seed-batch.json"))
    parser.add_argument("--model", default="")
    parser.add_argument("--command", nargs=argparse.REMAINDER, default=[])


def build_parser():
    parser = argparse.ArgumentParser(description="知乎决策证据抽取流水线 v1")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="标准化、去重并过滤候选")
    prepare.add_argument("--raw", default=str(default_raw()))
    prepare.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    prepare.add_argument("--output", default=str(ROOT / "runs" / "prepared-v1.json"))
    prepare.set_defaults(func=command_prepare)

    extract = sub.add_parser("extract", help="分块调用模型并严格校验")
    extract.add_argument("--prepared", default=str(ROOT / "runs" / "prepared-v1.json"))
    extract.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    extract.add_argument("--prompt", default=str(ROOT / "prompts" / "extract-v1.txt"))
    extract.add_argument("--prompt-version", default="extract-v1.0.0")
    extract.add_argument("--run-dir", default=str(ROOT / "runs" / "fixture-v1"))
    extract.add_argument("--ids", default="")
    extract.add_argument("--batch-size", type=int, default=6)
    extract.add_argument("--retries", type=int, default=1)
    extract.add_argument("--timeout", type=int, default=120)
    add_provider_args(extract)
    extract.set_defaults(func=command_extract)

    assemble = sub.add_parser("assemble", help="校验外部或代理生成的分批 JSON")
    assemble.add_argument("--input-dir", default=str(ROOT / "runs" / "model-v1" / "inputs"))
    assemble.add_argument("--raw-dir", default=str(ROOT / "runs" / "model-v1" / "raw"))
    assemble.add_argument("--run-dir", default=str(ROOT / "runs" / "model-v1"))
    assemble.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    assemble.add_argument("--prompt", default=str(ROOT / "prompts" / "extract-v1.txt"))
    assemble.add_argument("--prompt-version", default="extract-v1.0.0")
    assemble.set_defaults(func=command_assemble)

    repair = sub.add_parser("repair", help="严格校验并替换已隔离候选，保留原始批次")
    repair.add_argument("--run", default=str(ROOT / "runs" / "model-v1" / "extractions.json"))
    repair.add_argument("--input-dir", default=str(ROOT / "runs" / "model-v1" / "inputs"))
    repair.add_argument("--raw-dir", default=str(ROOT / "runs" / "model-v1" / "raw"))
    repair.add_argument("--run-dir", default=str(ROOT / "runs" / "model-v1"))
    repair.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    repair.add_argument("--prompt", default=str(ROOT / "prompts" / "extract-v1.txt"))
    repair.add_argument("--prompt-version", default="extract-v1.0.0")
    repair.set_defaults(func=command_repair)

    review = sub.add_parser("review", help="生成人工审核队列和本地 HTML")
    review.add_argument("--run", required=True)
    review.add_argument("--prepared", default=str(ROOT / "runs" / "prepared-v1.json"))
    review.add_argument("--output", default=str(ROOT / "review" / "fixture-v1"))
    review.set_defaults(func=command_review)

    apply = sub.add_parser("apply-review", help="校验人工动作并生成已审核数据")
    apply.add_argument("--run", required=True)
    apply.add_argument("--prepared", default=str(ROOT / "runs" / "prepared-v1.json"))
    apply.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    apply.add_argument("--actions", required=True)
    apply.add_argument("--output", required=True)
    apply.add_argument("--reviewer", required=True)
    apply.set_defaults(func=command_apply)

    dataset = sub.add_parser("dataset", help="从已审核主张生成浏览器数据")
    dataset.add_argument("--approved", required=True)
    dataset.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    dataset.add_argument("--output", default=str(ROOT / "runs" / "approved-v1" / "pipeline-data.js"))
    dataset.set_defaults(func=command_dataset)

    audit = sub.add_parser("audit", help="复验已接受主张并生成统计报告")
    audit.add_argument("--run", required=True)
    audit.add_argument("--prepared", default=str(ROOT / "runs" / "prepared-v1.json"))
    audit.add_argument("--scenario", default=str(ROOT / "scenarios" / "coffee.json"))
    audit.add_argument("--output", default=str(ROOT / "runs" / "model-v1" / "audit.json"))
    audit.set_defaults(func=command_audit)

    evaluate = sub.add_parser("evaluate", help="在AI辅助开发集上计算诊断性抽取指标")
    evaluate.add_argument("--run", required=True)
    evaluate.add_argument("--prepared", default=str(ROOT / "runs" / "prepared-v1.json"))
    evaluate.add_argument("--gold", default=str(ROOT / "tests" / "gold" / "coffee-seed-v1.json"))
    evaluate.add_argument("--output", default=str(ROOT / "runs" / "fixture-v1" / "evaluation.json"))
    evaluate.set_defaults(func=command_evaluate)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
