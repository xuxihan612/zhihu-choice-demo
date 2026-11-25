#!/usr/bin/env python3
"""Build a 50-case gold candidate manifest and balanced blind-annotation partitions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiworks_pipeline.common import dump_json, load_json, utc_now


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def main(args: argparse.Namespace) -> dict[str, Any]:
    existing = load_json(args.existing)["kept"]
    expansion = load_json(args.expansion)["kept"]
    existing_ids = {x["candidate_id"] for x in existing}
    seen_urls = {canonical_url(x["url"]) for x in existing}
    seen_content_ids = {str(x.get("content_id")) for x in existing if x.get("content_id")}
    eligible = []
    duplicates = []
    for candidate in expansion:
        url = canonical_url(candidate["url"])
        content_id = str(candidate.get("content_id", ""))
        if candidate["candidate_id"] in existing_ids or url in seen_urls or (content_id and content_id in seen_content_ids):
            duplicates.append(candidate["candidate_id"])
            continue
        eligible.append(candidate)
        seen_urls.add(url)
        if content_id:
            seen_content_ids.add(content_id)
    if args.expansion_ids:
        wanted = set(args.expansion_ids.split(","))
        unknown = wanted - {x["candidate_id"] for x in eligible}
        if unknown:
            raise ValueError("unknown or duplicate expansion ids: " + ", ".join(sorted(unknown)))
        chosen_expansion = [x for x in eligible if x["candidate_id"] in wanted]
    else:
        chosen_expansion = sorted(eligible, key=lambda x: (-len(x["content_text"]), x["candidate_id"]))[:args.expansion_count]
    if len(chosen_expansion) != args.expansion_count:
        raise ValueError(f"need {args.expansion_count} unique expansion candidates, got {len(chosen_expansion)}")
    candidates = existing + chosen_expansion
    if len(candidates) != 50:
        raise ValueError(f"expected 50 total candidates, got {len(candidates)}")
    output_dir = Path(args.output)
    manifest = {
        "generated_at": utc_now(),
        "scenario_id": "coffee",
        "selection": "All 32 previously prepared candidates plus manually selected unique expansion candidates; no model extraction outputs used.",
        "existing_count": len(existing),
        "expansion_pool_count": len(eligible),
        "selected_expansion_count": len(chosen_expansion),
        "candidate_count": len(candidates),
        "duplicate_expansion_ids_excluded": duplicates,
        "candidates": candidates,
    }
    dump_json(output_dir / "gold-candidates.json", manifest)
    bins: list[list[dict[str, Any]]] = [[], [], []]
    loads = [0, 0, 0]
    for candidate in sorted(candidates, key=lambda x: (-len(x["content_text"]), x["candidate_id"])):
        index = min(range(3), key=lambda i: loads[i])
        bins[index].append(candidate)
        loads[index] += len(candidate["content_text"])
    partition_manifest = {
        "generated_at": utc_now(),
        "partition_method": "Greedy balance by ContentText character count; candidate_id order within each partition.",
        "partitions": [],
    }
    for index, bin_items in enumerate(bins, 1):
        bin_items.sort(key=lambda x: x["candidate_id"])
        dump_json(output_dir / f"gold-part-{index}.json", {"part": index, "candidates": bin_items})
        partition_manifest["partitions"].append({"part": index, "candidate_count": len(bin_items), "content_chars": loads[index - 1], "candidate_ids": [x["candidate_id"] for x in bin_items]})
    dump_json(output_dir / "gold-partitions.json", partition_manifest)
    print(json.dumps({"candidate_count": len(candidates), "selected_expansion_count": len(chosen_expansion), "duplicates_excluded": len(duplicates), "partitions": [len(x) for x in bins], "content_chars": loads}, ensure_ascii=False))
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build balanced gold candidate partitions")
    parser.add_argument("--existing", required=True)
    parser.add_argument("--expansion", required=True)
    parser.add_argument("--expansion-ids", default="")
    parser.add_argument("--expansion-count", type=int, default=18)
    parser.add_argument("--output", required=True)
    return parser


if __name__ == "__main__":
    main(build_parser().parse_args())
