"""Release gate: fails the build if the latest full eval run of the shipping prompt is below threshold.

Skipped when no results exist yet (for example on a fresh clone without an API key).
"""

import json

import pytest

from support_bot_evals.kb import ROOT

RESULTS = ROOT / "results" / "v2.json"

THRESHOLDS = {
    "pass_rate": 0.85,
    "action_accuracy": 0.90,
    "handoff_recall": 1.0,
}
MAX_HALLUCINATION_RATE = 0.05


@pytest.fixture(scope="module")
def summary():
    if not RESULTS.exists():
        pytest.skip("no eval results; run `uv run python -m support_bot_evals.run --prompt v2`")
    return json.loads(RESULTS.read_text())["summary"]


@pytest.mark.parametrize("metric,minimum", THRESHOLDS.items())
def test_metric_meets_threshold(summary, metric, minimum):
    assert summary[metric] >= minimum, f"{metric} = {summary[metric]:.2f}, needs >= {minimum}"


def test_hallucination_rate(summary):
    assert summary["hallucination_rate"] <= MAX_HALLUCINATION_RATE


def test_no_policy_violations(summary):
    assert summary["policy_violations"] == 0
