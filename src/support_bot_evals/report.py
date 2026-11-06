"""Build the static HTML report (docs/index.html) from results/v1.json and results/v2.json.

    uv run python -m support_bot_evals.report
"""

from __future__ import annotations

import json
from html import escape

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .kb import ROOT
from .label import LABELS
from .metrics import ACTIONS

RESULTS = ROOT / "results"
OUT = ROOT / "docs" / "index.html"
TEMPLATES = ROOT / "src" / "support_bot_evals" / "templates"

CATEGORY_LABELS = {
    "factual": "Factual questions",
    "multi_turn": "Multi-turn follow-ups",
    "unanswerable": "Not in knowledge base",
    "handoff": "Needs a human",
    "off_topic": "Off-topic",
    "clarify": "Too vague to answer",
    "outdated": "Legacy / outdated info",
    "adversarial": "Adversarial",
}

# Sequential blue ramp (light -> dark) for the confusion matrix.
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def category_chart(baseline: dict, current: dict) -> str:
    """Grouped horizontal bars: pass rate per category, baseline vs current prompt."""
    cats = [c for c in CATEGORY_LABELS if c in current["summary"]["by_category"]]
    label_w, plot_w, right = 190, 420, 56
    row_h, bar_h, gap = 46, 14, 2
    width, height = label_w + plot_w + right, 28 + row_h * len(cats)
    x = lambda v: label_w + v * plot_w  # noqa: E731

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="cat-title" class="chart">']
    for tick in (0, 0.5, 1):
        parts.append(f'<line x1="{x(tick)}" x2="{x(tick)}" y1="18" y2="{height}" class="grid"/>')
        parts.append(f'<text x="{x(tick)}" y="12" class="tick" text-anchor="middle">{tick:.0%}</text>')

    for i, cat in enumerate(cats):
        y0 = 28 + i * row_h
        b, c = baseline["summary"]["by_category"][cat], current["summary"]["by_category"][cat]
        parts.append(
            f'<text x="{label_w - 12}" y="{y0 + bar_h + 1}" class="cat" text-anchor="end">{CATEGORY_LABELS[cat]}</text>'
        )
        parts.append(f'<text x="{label_w - 12}" y="{y0 + bar_h + 15}" class="tick" text-anchor="end">n = {c["total"]}</text>')
        for j, (name, s, cls) in enumerate(
            [(current["prompt_version"], c, "s1"), (baseline["prompt_version"], b, "s2")]
        ):
            y = y0 + j * (bar_h + gap)
            w = max(s["pass_rate"] * plot_w, 2)
            tip = f'{CATEGORY_LABELS[cat]} · prompt {name}: {s["passed"]}/{s["total"]} passed ({s["pass_rate"]:.0%})'
            parts.append(
                f'<g class="bar"><title>{escape(tip)}</title>'
                f'<path d="{_bar_path(label_w, y, w, bar_h)}" class="{cls}"/>'
                f'<rect x="{label_w}" y="{y - 2}" width="{plot_w}" height="{bar_h + 4}" class="hit"/></g>'
            )
            parts.append(f'<text x="{x(s["pass_rate"]) + 6}" y="{y + bar_h - 3}" class="val">{s["pass_rate"]:.0%}</text>')
    parts.append(f'<line x1="{label_w}" x2="{label_w}" y1="18" y2="{height}" class="axis"/>')
    parts.append("</svg>")
    return "".join(parts)


def _bar_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """Bar anchored square at the baseline, rounded at the data end."""
    r = min(r, w / 2, h / 2)
    return (
        f"M{x},{y} H{x + w - r} Q{x + w},{y} {x + w},{y + r} V{y + h - r} "
        f"Q{x + w},{y + h} {x + w - r},{y + h} H{x} Z"
    )


def confusion_table(run: dict) -> dict:
    counts = run["summary"]["confusion"]
    observed = ACTIONS + sorted({k.split("->")[1] for k in counts} - set(ACTIONS))
    peak = max(counts.values())
    rows = []
    for e in ACTIONS:
        cells = []
        for g in observed:
            n = counts.get(f"{e}->{g}", 0)
            step = 0 if not n else min(len(SEQ) - 1, 1 + round((n / peak) * (len(SEQ) - 2)))
            cells.append({"n": n, "bg": SEQ[step] if n else "", "dark_text": step < 4, "diag": e == g})
        rows.append({"expected": e, "cells": cells, "total": sum(c["n"] for c in cells)})
    return {"cols": observed, "rows": [r for r in rows if r["total"]]}


def calibration(run: dict) -> dict | None:
    if not LABELS.exists():
        return None
    labels = json.loads(LABELS.read_text()).get(f"{run['prompt_version']}:{run['prompt_sha']}", {})
    labeled = [c for c in run["cases"] if c["id"] in labels and c["judge"]]
    pairs = [(labels[c["id"]], c["judge"]["passed"]) for c in labeled]
    if len(pairs) < 10:
        return None
    disagreements = [
        {"id": c["id"], "human": labels[c["id"]], "judge": c["judge"]["passed"], "reason": c["judge"]["reason"]}
        for c in labeled
        if labels[c["id"]] != c["judge"]["passed"]
    ]
    n = len(pairs)
    agree = sum(h == j for h, j in pairs) / n
    p_h, p_j = sum(h for h, _ in pairs) / n, sum(j for _, j in pairs) / n
    expected = p_h * p_j + (1 - p_h) * (1 - p_j)
    kappa = (agree - expected) / (1 - expected) if expected < 1 else 1.0
    return {
        "n": n,
        "agreement": agree,
        "kappa": kappa,
        "judge_stricter": sum(h and not j for h, j in pairs),
        "judge_looser": sum(j and not h for h, j in pairs),
        "human_pass_rate": p_h,
        "disagreements": disagreements,
    }


def failed_checks(case: dict) -> list[str]:
    out = [f"{name}: {c['detail']}" for name, c in case["checks"].items() if not c["passed"]]
    j = case["judge"]
    if j is None:
        out.append(f"no judge verdict ({case['result']['action']})")
    else:
        if j["correctness"] < 4:
            out.append(f"judge correctness {j['correctness']}/5")
        if j["unsupported_claims"]:
            out.append("unsupported claims: " + "; ".join(j["unsupported_claims"]))
        if j["policy_violation"]:
            out.append("policy violation")
    return out


def main() -> None:
    baseline = json.loads((RESULTS / "v1.json").read_text())
    current = json.loads((RESULTS / "v2.json").read_text())
    base_by_id = {c["id"]: c for c in baseline["cases"]}

    fixed, regressed = [], []
    for c in current["cases"]:
        b = base_by_id.get(c["id"])
        if b and b["passed"] != c["passed"]:
            (fixed if c["passed"] else regressed).append({"current": c, "baseline": b})

    for run in (baseline, current):
        for c in run["cases"]:
            c["failed_checks"] = failed_checks(c)

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("report.html.j2").render(
        baseline=baseline,
        current=current,
        b=baseline["summary"],
        s=current["summary"],
        category_chart=category_chart(baseline, current),
        category_labels=CATEGORY_LABELS,
        confusion=confusion_table(current),
        calibration=calibration(current),
        fixed=fixed,
        regressed=regressed,
        current_failures=[c for c in current["cases"] if not c["passed"]],
        baseline_failures=[c for c in baseline["cases"] if not c["passed"]],
        total_cost=sum(r[k]["cost_usd"] for r in (baseline, current) for k in ("bot_usage", "judge_usage")),
    )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
