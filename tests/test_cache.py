"""The response cache must make repeat runs free: a saved request never reaches the API again."""

from types import SimpleNamespace

import pytest

from support_bot_evals import llm
from support_bot_evals.bot import BotReply


class FakeResponses:
    def __init__(self):
        self.calls = 0

    def parse(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            id="resp_test",
            status="completed",
            output=[],
            output_parsed=BotReply(reply="Growth is $59/month.", action="answer", citations=["plans-and-pricing"]),
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=100,
                input_tokens_details=SimpleNamespace(cached_tokens=200),
                output_tokens_details=SimpleNamespace(reasoning_tokens=40),
            ),
        )


@pytest.fixture
def fake_api(tmp_path, monkeypatch):
    fake = FakeResponses()
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm, "_client", SimpleNamespace(responses=fake))
    monkeypatch.setattr(llm, "_run_spend_usd", 0.0)
    return fake


def call(usage, text="How much is Growth?"):
    return llm.cached_parse(
        model="gpt-6.1-terra",
        instructions="system",
        input=[{"role": "user", "content": text}],
        text_format=BotReply,
        effort="low",
        usage=usage,
    )


def test_second_identical_call_is_served_from_disk(fake_api):
    usage = llm.Usage()
    first, second = call(usage), call(usage)
    assert fake_api.calls == 1
    assert not first.from_cache and second.from_cache
    assert second.parsed == first.parsed
    # Report cost reflects both responses; only the first one was actually paid for.
    assert usage.cache_hits == 1
    assert usage.spent_this_run_usd == pytest.approx(usage.cost_usd / 2)


def test_changed_request_is_not_reused(fake_api):
    usage = llm.Usage()
    call(usage, "How much is Growth?")
    call(usage, "How much is Scale?")
    assert fake_api.calls == 2


def test_cost_bills_cached_input_at_lower_rate():
    tokens = {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100, "reasoning_tokens": 40}
    # 800 * $1 + 200 * $0.05 + 100 * $5, per 1M tokens
    assert llm.call_cost("gpt-6.1-terra", tokens) == pytest.approx((800 + 10 + 500) / 1_000_000)


def test_spend_cap_blocks_new_calls_but_not_saved_ones(fake_api, monkeypatch):
    usage = llm.Usage()
    call(usage)
    monkeypatch.setattr(llm, "MAX_RUN_COST_USD", 0.0)
    assert call(usage).from_cache  # saved response still available
    with pytest.raises(llm.BudgetExceeded):
        call(usage, "something new")
    assert fake_api.calls == 1
