"""Label a sample of eval results by hand, to check how well the LLM judge agrees with a human.

    uv run python -m support_bot_evals.label            # labels 30 cases from results/v2.json
    uv run python -m support_bot_evals.label --n 40

Labels are saved to results/human_labels.json and picked up by the report.
"""

from __future__ import annotations

import argparse
import json
import random
import textwrap

from .kb import ROOT

LABELS = ROOT / "results" / "human_labels.json"


def stratified_sample(cases: list[dict], n: int, seed: int = 7) -> list[dict]:
    """Sample across categories, oversampling judge failures so disagreements have a chance to show up."""
    rng = random.Random(seed)
    fails = [c for c in cases if c["judge"] and not c["judge"]["passed"]]
    passes = [c for c in cases if c["judge"] and c["judge"]["passed"]]
    picked = rng.sample(fails, min(len(fails), n // 3))
    by_cat: dict[str, list[dict]] = {}
    for c in passes:
        by_cat.setdefault(c["category"], []).append(c)
    pools = [rng.sample(v, len(v)) for v in by_cat.values()]
    while len(picked) < n and any(pools):
        for pool in pools:
            if pool and len(picked) < n:
                picked.append(pool.pop())
    return picked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="v2")
    parser.add_argument("--n", type=int, default=30)
    args = parser.parse_args()

    run = json.loads((ROOT / "results" / f"{args.prompt}.json").read_text())
    labels = json.loads(LABELS.read_text()) if LABELS.exists() else {}
    key = f"{args.prompt}:{run['prompt_sha']}"
    done = labels.setdefault(key, {})

    todo = [c for c in stratified_sample(run["cases"], args.n) if c["id"] not in done]
    print(f"{len(done)} already labeled, {len(todo)} to go. Answer y (good reply), n (bad reply), s (skip), q (quit).\n")
    print("Judge the reply as a support lead would: correct, grounded in the articles, right action, no promises it can't keep.\n")

    for i, case in enumerate(todo, 1):
        print("=" * 80)
        print(f"[{i}/{len(todo)}] {case['id']} ({case['category']})\n")
        for t in case["turns"]:
            print(textwrap.fill(f"{t['role'].upper()}: {t['content']}", 80, subsequent_indent="  "))
        r = case["result"]
        print(f"\nBOT ({r['action']}, cites {r['citations']}):")
        print(textwrap.indent(textwrap.fill(r["reply"], 76), "  "))
        print(f"\nREFERENCE: {case['reference']}")
        while (answer := input("\nGood reply? [y/n/s/q] ").strip().lower()) not in {"y", "n", "s", "q"}:
            pass
        if answer == "q":
            break
        if answer in {"y", "n"}:
            done[case["id"]] = answer == "y"
            LABELS.write_text(json.dumps(labels, indent=2))

    print(f"\nSaved {len(done)} labels to {LABELS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
