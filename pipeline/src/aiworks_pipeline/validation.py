"""Strict batch validation. Invalid items are quarantined, never silently repaired."""
from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator

from .common import sha256_text


def parse_json_output(text: str) -> Any:
    value = text.strip()
    if value.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
        if not match:
            raise ValueError("invalid fenced JSON")
        value = match.group(1)
    return json.loads(value)


def _schema_errors(value: Any, schema: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.absolute_path)):
        path = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in error.absolute_path)
        errors.append({"code": "schema", "path": path, "message": error.message})
    return errors


def validate_batch(
    batch: Any,
    candidate_map: dict[str, dict[str, Any]],
    scenario: dict[str, Any],
    schema: dict[str, Any],
    *,
    run_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Return accepted records plus item-level errors.

    A claim is atomic: if any field in an item fails, all claims from that item
    are quarantined. This prevents a plausible claim beside a fabricated quote
    from leaking into the reviewed dataset by accident.
    """
    accepted: list[dict[str, Any]] = []
    item_results: list[dict[str, Any]] = []
    if not isinstance(batch, dict) or set(batch) != {"items"} or not isinstance(batch.get("items"), list):
        return {
            "accepted": [],
            "item_results": [{"candidate_id": None, "status": "invalid", "errors": [{"code": "root_schema", "path": "$", "message": "root must contain only an items array"}]}],
        }

    seen: set[str] = set()
    for index, item in enumerate(batch["items"]):
        candidate_id = item.get("candidate_id") if isinstance(item, dict) else None
        errors = _schema_errors(item, schema["properties"]["items"]["items"])
        if not isinstance(candidate_id, str) or candidate_id not in candidate_map:
            errors.append({"code": "unknown_candidate", "path": f"$.items[{index}].candidate_id", "message": "candidate_id is unknown"})
        if candidate_id in seen:
            errors.append({"code": "duplicate_candidate", "path": f"$.items[{index}].candidate_id", "message": "candidate_id appears more than once in this batch"})
        if isinstance(candidate_id, str):
            seen.add(candidate_id)

        if not errors and candidate_map[candidate_id]["scenario_id"] != scenario["id"]:
            errors.append({"code": "scenario_mismatch", "path": "$.candidate_id", "message": "candidate belongs to another scenario"})

        claims = item.get("claims", []) if isinstance(item, dict) else []
        signatures: set[str] = set()
        candidate = candidate_map.get(candidate_id) if isinstance(candidate_id, str) else None
        if candidate and not errors:
            source_text = candidate["content_text"]
            for claim_index, claim in enumerate(claims):
                path = f"$.items[{index}].claims[{claim_index}]"
                quote = claim["evidence_quote"]
                start = source_text.find(quote)
                if start < 0:
                    errors.append({"code": "evidence_not_exact", "path": path + ".evidence_quote", "message": "evidence is not a verbatim substring of ContentText"})
                    start = None
                if claim["confidence"] < scenario["limits"]["min_confidence"]:
                    errors.append({"code": "low_confidence", "path": path + ".confidence", "message": "confidence is below the configured minimum"})
                cost = claim["cost"]
                cost_start = None
                if cost is not None:
                    cost_start = source_text.find(cost["evidence_quote"])
                    if cost_start < 0:
                        errors.append({"code": "cost_evidence_not_exact", "path": path + ".cost.evidence_quote", "message": "cost evidence is not a verbatim substring of ContentText"})
                evidence_window = quote + (" " + cost["evidence_quote"] if cost else "")
                for key, value in claim["conditions"].items():
                    if value is None:
                        continue
                    terms = scenario["conditions"][key].get("evidence_terms", {}).get(value, [])
                    if terms and not any(term.lower() in evidence_window.lower() for term in terms):
                        errors.append({"code": "condition_without_lexical_support", "path": path + f".conditions.{key}", "message": f"attached evidence does not contain configured support terms for {key}={value}"})
                signature = sha256_text("|".join([claim["option"], claim["polarity"], quote, json.dumps(claim["conditions"], sort_keys=True, ensure_ascii=False)]))
                if signature in signatures:
                    errors.append({"code": "duplicate_claim", "path": path, "message": "duplicate claim within candidate"})
                signatures.add(signature)

        if errors:
            item_results.append({"candidate_id": candidate_id, "status": "quarantined", "errors": errors})
            continue

        if item["status"] != "extracted":
            item_results.append({"candidate_id": candidate_id, "status": item["status"], "errors": []})
            continue

        for claim_index, claim in enumerate(claims):
            claim_id = f'{candidate_id}-c{claim_index + 1}'
            start = candidate["content_text"].find(claim["evidence_quote"])
            cost = claim["cost"]
            accepted.append({
                "claim_id": claim_id,
                "candidate_id": candidate_id,
                "scenario_id": scenario["id"],
                **claim,
                "evidence_start": start,
                "evidence_end": start + len(claim["evidence_quote"]),
                "source": {key: candidate[key] for key in ["title", "url", "author", "badge", "votes", "content_type", "source_api"]},
                "run": run_metadata,
                "review": {"status": "pending", "reviewed": False, "reviewer": None, "reviewed_at": None, "note": ""},
            })
        item_results.append({"candidate_id": candidate_id, "status": "extracted", "errors": [], "accepted_claims": len(claims)})
    return {"accepted": accepted, "item_results": item_results}
