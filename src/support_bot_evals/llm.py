"""Shared OpenAI client, response cache, cost accounting and spend cap.

Every API response is saved to results/cache/ the moment it arrives, keyed by a hash of the full request
(model, instructions, input, output schema, reasoning effort). Re-running the same case with the same prompt
reads the saved response instead of paying for a new one, so an interrupted run resumes for free and the
report can be rebuilt any number of times. Changing a prompt or model changes the key, so only the
affected calls are made again.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from .kb import ROOT

load_dotenv()

BOT_MODEL = os.getenv("BOT_MODEL", "gpt-6.1-terra")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-6.1-sol")
# Hard stop: no new API calls once this run has spent this much (cached responses cost nothing).
MAX_RUN_COST_USD = float(os.getenv("MAX_RUN_COST_USD", "5"))

CACHE_DIR = ROOT / "results" / "cache"

# USD per 1M tokens: input, cached input, output (standard tier, prompts up to 272K tokens).
PRICES = {
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-6.1-terra": (1.00, 0.05, 5.00),
}

_lock = threading.Lock()
_run_spend_usd = 0.0


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    """Token usage and cost of the responses behind a run, whether fetched now or read from the cache."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    cache_hits: int = 0
    spent_this_run_usd: float = field(default=0.0)

    def add(self, model: str, tokens: dict, from_cache: bool) -> float:
        cost = call_cost(model, tokens)
        with _lock:
            self.input_tokens += tokens["input_tokens"]
            self.cached_input_tokens += tokens["cached_input_tokens"]
            self.output_tokens += tokens["output_tokens"]
            self.reasoning_tokens += tokens["reasoning_tokens"]
            self.cost_usd += cost
            self.calls += 1
            if from_cache:
                self.cache_hits += 1
            else:
                self.spent_this_run_usd += cost
        return cost


def call_cost(model: str, tokens: dict) -> float:
    inp, cached, out = PRICES.get(model, (0, 0, 0))
    # input_tokens includes the cached ones; cached tokens are billed at the lower rate.
    uncached = tokens["input_tokens"] - tokens["cached_input_tokens"]
    return (uncached * inp + tokens["cached_input_tokens"] * cached + tokens["output_tokens"] * out) / 1_000_000


def run_spend() -> float:
    return _run_spend_usd


_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    with _lock:
        if _client is None:
            _client = OpenAI(max_retries=5)
    return _client


@dataclass
class ParsedCall:
    parsed: BaseModel | None
    refusal: str | None
    status: str
    latency_s: float
    from_cache: bool


def _cache_key(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:24]


def cached_parse(
    *,
    model: str,
    instructions: str,
    input: list[dict],
    text_format: type[BaseModel],
    effort: str,
    usage: Usage,
    cache_key_prefix: str | None = None,
) -> ParsedCall:
    """responses.parse with a write-through disk cache and a per-run spend cap."""
    global _run_spend_usd
    request = {
        "model": model,
        "instructions": instructions,
        "input": input,
        "schema": text_format.model_json_schema(),
        "effort": effort,
    }
    path = CACHE_DIR / f"{_cache_key(request)}.json"

    if path.exists():
        saved = json.loads(path.read_text())
        usage.add(model, saved["tokens"], from_cache=True)
        parsed = text_format.model_validate(saved["parsed"]) if saved["parsed"] is not None else None
        return ParsedCall(parsed, saved["refusal"], saved["status"], saved["latency_s"], from_cache=True)

    with _lock:
        if _run_spend_usd >= MAX_RUN_COST_USD:
            raise BudgetExceeded(f"spend cap of ${MAX_RUN_COST_USD:.2f} reached; raise MAX_RUN_COST_USD to continue")

    start = time.perf_counter()
    response = client().responses.parse(
        model=model,
        instructions=instructions,
        input=input,
        text_format=text_format,
        reasoning={"effort": effort},
        max_output_tokens=8000,
        store=False,
        # Requests that share a long prefix (same prompt version) are routed together for prompt caching.
        prompt_cache_key=cache_key_prefix,
    )
    latency = time.perf_counter() - start

    u = response.usage
    tokens = {
        "input_tokens": u.input_tokens,
        "cached_input_tokens": u.input_tokens_details.cached_tokens if u.input_tokens_details else 0,
        "output_tokens": u.output_tokens,
        "reasoning_tokens": u.output_tokens_details.reasoning_tokens if u.output_tokens_details else 0,
    }
    cost = usage.add(model, tokens, from_cache=False)
    with _lock:
        _run_spend_usd += cost

    refusal = _refusal_text(response)
    parsed = response.output_parsed
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "request": request,
                "parsed": parsed.model_dump() if parsed is not None else None,
                "refusal": refusal,
                "status": response.status,
                "latency_s": latency,
                "tokens": tokens,
                "cost_usd": cost,
                "response_id": response.id,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            indent=2,
        )
    )
    return ParsedCall(parsed, refusal, response.status, latency, from_cache=False)


def _refusal_text(response) -> str | None:
    for item in response.output:
        for part in getattr(item, "content", None) or []:
            if part.type == "refusal":
                return part.refusal
    return None
