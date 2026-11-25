"""Versioned, chunked extraction orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import dump_json, load_json, sha256_text, utc_now
from .validation import parse_json_output, validate_batch


def render_prompt(template: str, scenario: dict[str, Any], schema: dict[str, Any], documents: list[dict[str, Any]]) -> str:
    # json.dumps with ensure_ascii=False preserves exact Chinese source text.
    payload = [{"candidate_id": x["candidate_id"], "title": x["title"], "ContentText": x["content_text"]} for x in documents]
    return (template
            .replace("{{scenario_json}}", json.dumps(scenario, ensure_ascii=False, separators=(",", ":")))
            .replace("{{documents_json}}", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            .replace("{{schema_json}}", json.dumps(schema, ensure_ascii=False, separators=(",", ":"))))


def run_extraction(
    candidates: list[dict[str, Any]],
    scenario: dict[str, Any],
    schema: dict[str, Any],
    prompt_template: str,
    provider: Any,
    run_dir: str | Path,
    *,
    prompt_version: str,
    batch_size: int = 6,
    max_retries: int = 1,
    timeout: int = 120,
) -> dict[str, Any]:
    if batch_size < 1 or batch_size > schema["properties"]["items"]["maxItems"]:
        raise ValueError("batch_size exceeds schema item limit")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    candidate_map = {x["candidate_id"]: x for x in candidates}
    run_metadata = {
        "run_id": run_dir.name,
        "prompt_version": prompt_version,
        "prompt_sha256": sha256_text(prompt_template),
        "scenario_version": scenario["schema_version"],
        "provider": "pending",
        "model": "pending",
        "started_at": utc_now(),
        "fixture_run": provider.__class__.__name__ == "FixtureProvider",
    }
    all_accepted: list[dict[str, Any]] = []
    all_results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    total_usage: dict[str, int] = {}

    for offset in range(0, len(candidates), batch_size):
        chunk = candidates[offset:offset + batch_size]
        expected_ids = [x["candidate_id"] for x in chunk]
        base_prompt = render_prompt(prompt_template, scenario, schema, chunk)
        prompt = base_prompt
        response = None
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = provider.complete(prompt, timeout=timeout)
                batch = parse_json_output(response.text)
                preliminary = validate_batch(batch, candidate_map, scenario, schema, run_metadata=run_metadata)
                returned = [x.get("candidate_id") for x in batch.get("items", []) if isinstance(x, dict)] if isinstance(batch, dict) else []
                missing = [x for x in expected_ids if x not in returned]
                extra = [x for x in returned if x not in expected_ids]
                coverage_errors = []
                if missing:
                    coverage_errors.append({"code": "missing_candidates", "path": "$.items", "message": "missing: " + ", ".join(missing)})
                if extra:
                    coverage_errors.append({"code": "unexpected_candidates", "path": "$.items", "message": "unexpected: " + ", ".join(extra)})
                if coverage_errors:
                    raise ValueError("batch coverage mismatch")
                if any(x["status"] == "quarantined" for x in preliminary["item_results"]) and attempt < max_retries:
                    last_error = preliminary["item_results"]
                    correction = json.dumps([x for x in preliminary["item_results"] if x["status"] == "quarantined"], ensure_ascii=False)
                    prompt = base_prompt + "\n\n上一次输出未通过程序校验。请仅修正以下问题后重新输出完整批次，不得遗漏候选：\n" + correction
                    attempts.append({"batch": offset // batch_size + 1, "attempt": attempt + 1, "outcome": "validation_retry", "errors": last_error})
                    continue
                run_metadata.update({"provider": response.provider, "model": response.model})
                all_accepted.extend(preliminary["accepted"])
                all_results.extend(preliminary["item_results"])
                attempts.append({"batch": offset // batch_size + 1, "attempt": attempt + 1, "outcome": "validated", "latency_ms": response.latency_ms})
                (run_dir / f"raw-batch-{offset // batch_size + 1:03d}.json").write_text(response.text, encoding="utf-8")
                if response.usage:
                    for key, value in response.usage.items():
                        if isinstance(value, (int, float)):
                            total_usage[key] = total_usage.get(key, 0) + value
                last_error = None
                break
            except (ValueError, json.JSONDecodeError, RuntimeError) as error:
                last_error = str(error)
                attempts.append({"batch": offset // batch_size + 1, "attempt": attempt + 1, "outcome": "request_retry" if attempt < max_retries else "batch_failed", "error": last_error})
        if last_error is not None:
            # A failed request is isolated to this batch; no output is invented.
            for candidate in chunk:
                all_results.append({"candidate_id": candidate["candidate_id"], "status": "provider_failed", "errors": [{"code": "provider_failure", "path": "$", "message": last_error}]})

    run_metadata["finished_at"] = utc_now()
    result = {
        "run": run_metadata,
        "candidate_count": len(candidates),
        "accepted_claim_count": len(all_accepted),
        "status_counts": {status: sum(x["status"] == status for x in all_results) for status in sorted({x["status"] for x in all_results})},
        "accepted": all_accepted,
        "item_results": all_results,
        "attempts": attempts,
        "usage": total_usage,
    }
    dump_json(run_dir / "extractions.json", result)
    dump_json(run_dir / "manifest.json", {**run_metadata, "status_counts": result["status_counts"], "accepted_claim_count": len(all_accepted), "usage": total_usage})
    return result
