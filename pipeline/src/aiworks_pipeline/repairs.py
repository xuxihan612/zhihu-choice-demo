"""Apply validated, isolated re-extractions without overwriting original raw batches."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .common import dump_json, sha256_text, utc_now
from .validation import parse_json_output, validate_batch


def apply_repair_batches(
    run: dict[str, Any],
    batches: list[tuple[list[dict[str, Any]], str | None]],
    scenario: dict[str, Any],
    schema: dict[str, Any],
    run_dir: str | Path,
    *,
    prompt_version: str,
    prompt_sha256: str,
    provider: str = "agent",
    repair_prompt_hashes: list[str] | None = None,
) -> dict[str, Any]:
    if run["run"]["prompt_version"] != prompt_version or run["run"]["prompt_sha256"] != prompt_sha256:
        raise ValueError("repair prompt does not match the original run")
    if repair_prompt_hashes is None:
        repair_prompt_hashes = [prompt_sha256] * len(batches)
    if len(repair_prompt_hashes) != len(batches):
        raise ValueError("repair prompt hash count does not match repair batch count")
    # Repair inputs carry the same candidate fields as prepared inputs. Build the map
    # from all repair batches and verify every target against the original outcomes.
    candidate_map = {x["candidate_id"]: x for candidates, _ in batches for x in candidates}
    required_source_fields = {"title", "url", "author", "badge", "votes", "content_type", "source_api"}
    incomplete = [candidate_id for candidate_id, candidate in candidate_map.items() if not required_source_fields.issubset(candidate)]
    if incomplete:
        raise ValueError("repair inputs are missing source metadata: " + ", ".join(sorted(incomplete)))
    original_outcomes = {x.get("candidate_id"): x for x in run["item_results"]}
    repairable = {"quarantined", "provider_failed", "invalid_batch"}
    targets = [x["candidate_id"] for candidates, _ in batches for x in candidates]
    if len(targets) != len(set(targets)):
        raise ValueError("a candidate may appear in only one repair batch")
    for candidate_id in targets:
        if candidate_id not in original_outcomes:
            raise ValueError(f"unknown repair candidate: {candidate_id}")
        if original_outcomes[candidate_id]["status"] not in repairable:
            raise ValueError(f"refusing to overwrite non-repairable candidate: {candidate_id}")

    result = deepcopy(run)
    metadata = result["run"]
    metadata.update({"provider": provider, "model": "not-disclosed", "finished_at": utc_now(), "repair_applied_at": utc_now()})
    repair_attempts: list[dict[str, Any]] = []
    for index, (candidates, raw_text) in enumerate(batches, 1):
        expected = [x["candidate_id"] for x in candidates]
        target_set = set(expected)
        accepted: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        attempt: dict[str, Any] = {"kind": "repair", "repair_batch": index, "target_candidates": expected, "repair_prompt_sha256": repair_prompt_hashes[index - 1]}
        if raw_text is None:
            outcomes = [{"candidate_id": candidate_id, "status": "invalid_batch", "errors": [{"code": "missing_raw_batch", "path": "$", "message": "repair raw batch file is missing"}]} for candidate_id in expected]
            attempt.update({"outcome": "missing_raw_batch"})
        else:
            attempt["raw_sha256"] = sha256_text(raw_text)
            try:
                batch = parse_json_output(raw_text)
                returned = [x.get("candidate_id") for x in batch.get("items", []) if isinstance(x, dict)] if isinstance(batch, dict) else []
                if len(returned) != len(expected) or set(returned) != target_set:
                    raise ValueError("repair batch candidate coverage mismatch")
                checked = validate_batch(batch, candidate_map, scenario, schema, run_metadata=metadata)
                if any(x["candidate_id"] is None or x["status"] == "invalid" for x in checked["item_results"]):
                    raise ValueError("repair batch root validation failed")
                accepted = checked["accepted"]
                outcomes = checked["item_results"]
                attempt.update({
                    "outcome": "validated",
                    "accepted_claims": len(accepted),
                    "quarantined": sum(x["status"] == "quarantined" for x in outcomes),
                })
            except (ValueError, json.JSONDecodeError) as error:
                outcomes = [{"candidate_id": candidate_id, "status": "invalid_batch", "errors": [{"code": "invalid_repair_batch", "path": "$", "message": str(error)}]} for candidate_id in expected]
                attempt.update({"outcome": "invalid_batch", "error": str(error)})
        # Replacement is atomic per candidate and happens only after the entire
        # repair batch has passed coverage and validation.
        result["accepted"] = [x for x in result["accepted"] if x["candidate_id"] not in target_set]
        result["accepted"].extend(accepted)
        result["item_results"] = [x for x in result["item_results"] if x.get("candidate_id") not in target_set]
        result["item_results"].extend(outcomes)
        repair_attempts.append(attempt)

    result["accepted_claim_count"] = len(result["accepted"])
    result["status_counts"] = {status: sum(x["status"] == status for x in result["item_results"]) for status in sorted({x["status"] for x in result["item_results"]})}
    result["attempts"] = list(result.get("attempts", [])) + repair_attempts
    result["run"] = metadata
    run_dir = Path(run_dir)
    dump_json(run_dir / "extractions.json", result)
    dump_json(run_dir / "manifest.json", {**metadata, "status_counts": result["status_counts"], "accepted_claim_count": len(result["accepted"]), "usage": result.get("usage", {}), "repair_batches": len(repair_attempts)})
    return result
