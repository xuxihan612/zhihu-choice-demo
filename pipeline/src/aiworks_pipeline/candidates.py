"""Candidate normalization and conservative pre-filtering."""
from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from .common import canonical_url, compact_text, sha256_text


def _infer_content_type(item: dict[str, Any], url: str) -> str:
    value = str(item.get("ContentType") or "").strip()
    if value:
        return value
    if "/answer/" in urlsplit(url).path:
        return "Answer"
    if urlsplit(url).hostname == "zhuanlan.zhihu.com":
        return "Article"
    return "Unknown"


def prepare_candidates(raw_items: list[dict[str, Any]], scenario: dict[str, Any]) -> dict[str, Any]:
    config = scenario["filter"]
    allowed_hosts = set(config["allowed_hosts"])
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_urls: dict[str, str] = {}
    seen_ids: dict[str, str] = {}
    seen_text: dict[str, str] = {}

    for index, item in enumerate(raw_items):
        title = str(item.get("Title") or "").strip()
        text = str(item.get("ContentText") or "").strip()
        original_url = str(item.get("Url") or "").strip()
        url = canonical_url(original_url)
        host = (urlsplit(url).hostname or "").lower()
        content_type = _infer_content_type(item, url)
        signed_id = str(item.get("ContentID") or "").strip()
        absolute_id = signed_id.lstrip("-")
        candidate_id = f'{scenario["id"]}-{content_type.lower()}-{absolute_id or sha256_text(url)[:16]}'
        candidate = {
            "candidate_id": candidate_id,
            "scenario_id": scenario["id"],
            "title": title,
            "content_text": text,
            "url": url,
            "author": str(item.get("AuthorName") or "").strip(),
            "badge": str(item.get("AuthorBadgeText") or "").strip(),
            "votes": int(item.get("VoteUpCount") or 0),
            "content_type": content_type,
            "content_id": absolute_id,
            "source_api": str(item.get("_api") or "unknown"),
            "content_sha256": sha256_text(text),
            "input_index": index,
        }
        reason = None
        duplicate_of = None
        if not url or host not in allowed_hosts:
            reason = "untrusted_or_missing_host"
        elif not text:
            reason = "empty_content"
        elif len(text) < config["min_content_chars"]:
            reason = "content_too_short"
        elif len(text) > config["max_content_chars"]:
            reason = "content_too_long"
        else:
            haystack = compact_text(title + "\n" + text).lower()
            if not any(term.lower() in haystack for term in config["coffee_terms_any"]):
                reason = "off_topic"
            elif not any(term.lower() in haystack for term in config["option_terms_any"]):
                reason = "no_target_option"

        if reason is None:
            keys = [("url", url), ("content", f"{content_type}:{absolute_id}"), ("text", candidate["content_sha256"])]
            for kind, key in keys:
                if key in {"url": seen_urls, "content": seen_ids, "text": seen_text}[kind]:
                    reason = "duplicate_" + kind
                    duplicate_of = {"url": seen_urls, "content": seen_ids, "text": seen_text}[kind][key]
                    break
        if reason is None:
            seen_urls[url] = candidate_id
            if absolute_id:
                seen_ids[f"{content_type}:{absolute_id}"] = candidate_id
            seen_text[candidate["content_sha256"]] = candidate_id
            kept.append(candidate)
        else:
            candidate["reject_reason"] = reason
            if duplicate_of:
                candidate["duplicate_of"] = duplicate_of
            rejected.append(candidate)

    return {
        "scenario_id": scenario["id"],
        "input_count": len(raw_items),
        "kept_count": len(kept),
        "rejected_count": len(rejected),
        "reject_reasons": dict(Counter(x["reject_reason"] for x in rejected)),
        "kept": kept,
        "rejected": rejected,
    }
