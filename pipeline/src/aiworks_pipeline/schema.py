"""Runtime JSON Schema derived from a scenario configuration."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import load_json


def schema_for_scenario(base_schema: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    schema = deepcopy(base_schema)
    item = schema["properties"]["items"]["items"]
    claims = item["properties"]["claims"]
    claim = claims["items"]["properties"]
    limits = scenario["limits"]
    claims["maxItems"] = limits["max_claims_per_candidate"]
    claim["evidence_quote"]["minLength"] = limits["min_evidence_chars"]
    claim["evidence_quote"]["maxLength"] = limits["max_evidence_chars"]
    claim["cost"]["oneOf"][1]["properties"]["evidence_quote"]["minLength"] = limits["min_evidence_chars"]
    claim["cost"]["oneOf"][1]["properties"]["evidence_quote"]["maxLength"] = limits["max_evidence_chars"]
    claim["option"]["enum"] = [x["id"] for x in scenario["options"]]
    claim["source_type"]["enum"] = list(scenario["source_types"])
    conditions = claim["conditions"]["properties"]
    conditions["required"] = list(scenario["conditions"])
    for key, definition in scenario["conditions"].items():
        conditions[key]["enum"] = list(definition["values"]) + [None]
    conditions["additionalProperties"] = False
    return schema
