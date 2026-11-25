"""Provider adapters. Keys are read from environment variables only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    latency_ms: int
    usage: dict[str, Any] | None = None


class FixtureProvider:
    """Test-only provider. Every returned record must be labelled as a fixture."""

    def __init__(self, path: str):
        with open(path, encoding="utf-8") as handle:
            self.data = json.load(handle)

    def complete(self, prompt: str, *, timeout: int = 120) -> ProviderResponse:
        payload = self.data
        if callable(payload):
            payload = payload(prompt)
        return ProviderResponse(json.dumps(payload, ensure_ascii=False), "fixture", "hand-labelled-fixture", 0)


class OpenAICompatibleProvider:
    """Minimal /chat/completions adapter; no SDK or retries are hidden here."""

    def __init__(self, base_url: str, api_key: str, model: str):
        if not base_url.startswith("https://") and not base_url.startswith("http://localhost") and not base_url.startswith("http://127.0.0.1"):
            raise ValueError("AIWORKS_LLM_BASE_URL must use HTTPS (localhost HTTP is allowed)")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str, *, timeout: int = 120) -> ProviderResponse:
        import time
        endpoint = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if os.environ.get("AIWORKS_LLM_JSON_MODE", "1") != "0":
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(endpoint, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        })
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            # Never echo request headers, prompt or provider response body.
            raise RuntimeError(f"model provider HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError("model provider connection failed or timed out") from None
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                raise TypeError
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise RuntimeError("model provider returned an unsupported response structure") from None
        return ProviderResponse(text, "openai-compatible", self.model, round((time.monotonic() - started) * 1000), data.get("usage"))


class CommandProvider:
    """Run an explicitly supplied local extractor command with JSON on stdin.

    Contract: stdout is the extraction JSON. The command must not receive secrets
    from this pipeline; configure it separately. stderr is never persisted.
    """

    def __init__(self, argv: list[str], model: str):
        if not argv:
            raise ValueError("empty command provider")
        self.argv = argv
        self.model = model

    def complete(self, prompt: str, *, timeout: int = 120) -> ProviderResponse:
        import time
        started = time.monotonic()
        try:
            result = subprocess.run(self.argv, input=prompt, text=True, encoding="utf-8", capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("command provider failed or timed out") from None
        if result.returncode != 0:
            raise RuntimeError(f"command provider exited with code {result.returncode}")
        return ProviderResponse(result.stdout.strip(), "command", self.model, round((time.monotonic() - started) * 1000))


def make_provider(args: Any):
    if args.provider == "fixture":
        return FixtureProvider(args.fixture)
    if args.provider == "openai":
        key = os.environ.get("AIWORKS_LLM_API_KEY", "")
        base = os.environ.get("AIWORKS_LLM_BASE_URL", "")
        model = args.model or os.environ.get("AIWORKS_LLM_MODEL", "")
        if not key or not base or not model:
            raise ValueError("openai provider requires AIWORKS_LLM_API_KEY, AIWORKS_LLM_BASE_URL and AIWORKS_LLM_MODEL")
        return OpenAICompatibleProvider(base, key, model)
    if args.provider == "command":
        return CommandProvider(args.command, args.model or "external-command")
    raise ValueError(f"unsupported provider: {args.provider}")
