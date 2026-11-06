"""Run the golden dataset against one prompt version and save results.

    uv run python -m support_bot_evals.run --prompt v2
    uv run python -m support_bot_evals.run --prompt v1 --limit 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone

from .bot import SupportBot
from .checks import run_checks
from .dataset import Case, load_cases
from .judge import judge
from .kb import ROOT
from . import llm
from .llm import JUDGE_MODEL, BudgetExceeded, Usage
from .metrics import summarize

RESULTS_DIR = ROOT / "results"


def evaluate_case(case: Case, bot: SupportBot, bot_usage: Usage, judge_usage: Usage) -> dict:
    result = bot.respond(case.turns, bot_usage)
    checks = run_checks(case, result, set(bot.retriever.by_id))
    verdict = judge(case, result, bot.retriever, judge_usage) if not result.action.startswith("error:") else None

    passed = all(c["passed"] for c in checks.values()) and verdict is not None and verdict.passed
    return {
        "id": case.id,
        "category": case.category,
        "turns": [asdict(t) for t in case.turns],
        "expected_action": case.expected_action,
        "expected_citations": case.expected_citations,
        "reference": case.reference,
        "result": asdict(result),
        "checks": checks,
        "judge": None
        if verdict is None
        else {**verdict.model_dump(), "grounded": verdict.grounded, "passed": verdict.passed},
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="v2", help="prompt version in prompts/<version>.md")
    parser.add_argument("--limit", type=int, help="only run the first N cases")
    parser.add_argument("--cases", help="comma-separated case ids to run")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-cost", type=float, help="spend cap in USD for new API calls (default MAX_RUN_COST_USD or 5)")
    args = parser.parse_args()
    if args.max_cost is not None:
        llm.MAX_RUN_COST_USD = args.max_cost

    cases = load_cases()
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c.id in wanted]
    if args.limit:
        cases = cases[: args.limit]

    bot = SupportBot(args.prompt)
    bot_usage, judge_usage = Usage(), Usage()
    print(f"Running {len(cases)} cases with prompt {args.prompt} on {bot.model} (judge: {JUDGE_MODEL})")

    print(f"Spend cap for new API calls this run: ${llm.MAX_RUN_COST_USD:.2f} (saved responses are free)")

    def run_one(case: Case) -> dict | None:
        try:
            record = evaluate_case(case, bot, bot_usage, judge_usage)
        except BudgetExceeded:
            print(f"  SKIP  {case.id:<10} spend cap reached")
            return None
        print(f"  {'PASS' if record['passed'] else 'FAIL'}  {case.id:<10} {record['result']['action']}")
        return record

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = [r for r in pool.map(run_one, cases) if r is not None]

    spent = bot_usage.spent_this_run_usd + judge_usage.spent_this_run_usd
    hits = bot_usage.cache_hits + judge_usage.cache_hits
    calls = bot_usage.calls + judge_usage.calls
    print(f"\nAPI calls: {calls - hits} new, {hits} reused from results/cache | spent this run: ${spent:.4f}")
    if len(records) < len(cases):
        print(
            f"Stopped early: {len(cases) - len(records)} cases skipped by the spend cap. Every response so far is "
            "saved; raise MAX_RUN_COST_USD and run the same command again to continue without paying twice."
        )
        return

    output = {
        "prompt_version": args.prompt,
        "prompt_sha": hashlib.sha256(bot.system.encode()).hexdigest()[:12],
        "bot_model": bot.model,
        "judge_model": JUDGE_MODEL,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bot_usage": asdict(bot_usage),
        "judge_usage": asdict(judge_usage),
        "summary": summarize(records, bot_usage),
        "cases": records,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    suffix = "" if not (args.limit or args.cases) else "-partial"
    path = RESULTS_DIR / f"{args.prompt}{suffix}.json"
    path.write_text(json.dumps(output, indent=2))

    s = output["summary"]
    print(
        f"\nPass rate {s['pass_rate']:.0%} ({s['passed']}/{s['total']}) | "
        f"hallucination rate {s['hallucination_rate']:.0%} | action accuracy {s['action_accuracy']:.0%} | "
        f"p50 latency {s['latency_p50_s']:.1f}s | bot cost ${bot_usage.cost_usd:.2f} | judge cost ${judge_usage.cost_usd:.2f}"
    )
    print(f"Saved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
