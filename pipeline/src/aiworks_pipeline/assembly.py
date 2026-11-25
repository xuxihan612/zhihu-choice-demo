"""Assemble externally generated batch JSON through the same strict validator."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import dump_json, sha256_text, utc_now
from .validation import parse_json_output, validate_batch


def assemble_batches(
    batches: list[tuple[list[dict[str, Any]], str | None]],
    scenario: dict[str, Any],
    schema: dict[str, Any],
    run_dir: str | Path,
    *,
    prompt_version: str,
    prompt_sha256: str,
    provider: str = "agent",
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    candidate_map = {x["candidate_id"]: x for candidates, _ in batches for x in candidates}
    metadata = {
        "run_id": run_dir.name,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha256,
        "scenario_version": scenario["schema_version"],
        "provider": provider,
        "model": "not-disclosed",
        "started_at": utc_now(),
        "fixture_run": False,
    }
    accepted: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for index, (candidates, raw_text) in enumerate(batches, 1):
        expected = [x["candidate_id"] for x in candidates]
        if raw_text is None:
            for candidate_id in expected:
                results.append({"candidate_id": candidate_id, "status": "invalid_batch", "errors": [{"code": "missing_raw_batch", "path": "$", "message": "raw batch file is missing"}]})
            attempts.append({"batch": index, "outcome": "missing_raw_batch"})
            continue
        try:
            batch = parse_json_output(raw_text)
            checked = validate_batch(batch, candidate_map, scenario, schema, run_metadata=metadata)
            returned = [x.get("candidate_id") for x in batch.get("items", []) if isinstance(x, dict)] if isinstance(batch, dict) else []
            missing = [x for x in expected if x not in returned]
            extra = [x for x in returned if x not in expected]
            if missing or extra:
                for candidate_id in missing:
                    results.append({"candidate_id": candidate_id, "status": "invalid_batch", "errors": [{"code": "batch_coverage", "path": "$.items", "message": "candidate missing from raw batch"}]})
                results.extend(x for x in checked["item_results"] if x["candidate_id"] in expected)
                attempts.append({"batch": index, "outcome": "invalid_batch", "missing": missing, "unexpected": extra, "raw_sha256": sha256_text(raw_text)})
            else:
                accepted.extend(x for x in checked["accepted"] if x["candidate_id"] in expected)
                results.extend(x for x in checked["item_results"] if x["candidate_id"] in expected)
                attempts.append({"batch": index, "outcome": "validated", "accepted_claims": len(checked["accepted"]), "quarantined": sum(x["status"] == "quarantined" for x in checked["item_results"]), "raw_sha256": sha256_text(raw_text)})
        except (ValueError, json.JSONDecodeError) as error:
            for candidate_id in expected:
                results.append({"candidate_id": candidate_id, "status": "invalid_batch", "errors": [{"code": "invalid_json", "path": "$", "message": str(error)}]})
            attempts.append({"batch": index, "outcome": "invalid_json", "error": str(error), "raw_sha256": sha256_text(raw_text)})
    metadata["finished_at"] = utc_now()
    result = {
        "run": metadata,
        "candidate_count": len(candidate_map),
        "accepted_claim_count": len(accepted),
        "status_counts": {status: sum(x["status"] == status for x in results) for status in sorted({x["status"] for x in results})},
        "accepted": accepted,
        "item_results": results,
        "attempts": attempts,
        "usage": {},
    }
    dump_json(run_dir / "extractions.json", result)
    dump_json(run_dir / "manifest.json", {**metadata, "status_counts": result["status_counts"], "accepted_claim_count": len(accepted)})
    return result
