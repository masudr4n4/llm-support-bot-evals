"""Aggregate metrics over per-case eval records."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

ACTIONS = ["answer", "clarify", "dont_know", "handoff", "refuse"]


def _rate(n: int, d: int) -> float:
    return n / d if d else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def summarize(records: list[dict], bot_usage=None) -> dict:
    total = len(records)
    passed = sum(r["passed"] for r in records)

    judged = [r for r in records if r["judge"]]
    answered = [r for r in judged if r["result"]["action"] == "answer"]
    hallucinated = [r for r in answered if not r["judge"]["grounded"]]

    by_category: dict[str, dict] = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in records:
        by_category[r["category"]]["total"] += 1
        by_category[r["category"]]["passed"] += r["passed"]
    for c in by_category.values():
        c["pass_rate"] = _rate(c["passed"], c["total"])

    # Expected action is the first listed acceptable action; it is the "ideal" one for the confusion matrix.
    confusion = Counter((r["expected_action"][0], r["result"]["action"]) for r in records)

    handoff_expected = [r for r in records if r["expected_action"] == ["handoff"]]
    handoff_given = [r for r in records if r["result"]["action"] == "handoff"]
    handoff_correct = [r for r in handoff_given if "handoff" in r["expected_action"]]

    with_expected_article = [r for r in records if r["expected_citations"]]
    retrieval_hits = [
        r for r in with_expected_article if set(r["expected_citations"]) & set(r["result"]["retrieved_ids"])
    ]

    latencies = [r["result"]["latency_s"] for r in records]
    return {
        "total": total,
        "passed": passed,
        "pass_rate": _rate(passed, total),
        "action_accuracy": _rate(sum(r["checks"]["action"]["passed"] for r in records), total),
        "hallucination_rate": _rate(len(hallucinated), len(answered)),
        "answered": len(answered),
        "hallucinated": len(hallucinated),
        "policy_violations": sum(1 for r in judged if r["judge"]["policy_violation"]),
        "mean_correctness": _rate(sum(r["judge"]["correctness"] for r in judged), len(judged)),
        "handoff_recall": _rate(sum("handoff" == r["result"]["action"] for r in handoff_expected), len(handoff_expected)),
        "handoff_precision": _rate(len(handoff_correct), len(handoff_given)),
        "retrieval_hit_rate": _rate(len(retrieval_hits), len(with_expected_article)),
        "latency_p50_s": median(latencies) if latencies else 0.0,
        "latency_p95_s": _p95(latencies),
        "cost_per_conversation_usd": _rate(bot_usage.cost_usd, total) if bot_usage else None,
        "by_category": dict(by_category),
        "confusion": {f"{e}->{g}": n for (e, g), n in confusion.items()},
    }
