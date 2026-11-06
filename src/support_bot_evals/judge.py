"""LLM-as-judge grading for correctness, grounding and policy violations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .bot import BotResult
from .dataset import Case
from .kb import ROOT, Retriever
from .llm import JUDGE_MODEL, Usage, cached_parse

JUDGE_PROMPT = (ROOT / "prompts" / "judge.md").read_text()


class Verdict(BaseModel):
    correctness: Literal[1, 2, 3, 4, 5]
    unsupported_claims: list[str]
    policy_violation: bool
    reason: str

    @property
    def grounded(self) -> bool:
        return not self.unsupported_claims

    @property
    def passed(self) -> bool:
        return self.correctness >= 4 and self.grounded and not self.policy_violation


def judge(case: Case, result: BotResult, retriever: Retriever, usage: Usage, model: str = JUDGE_MODEL) -> Verdict | None:
    conversation = "\n".join(f"{t.role.upper()}: {t.content}" for t in case.turns)
    articles = "\n\n".join(retriever.by_id[i].as_context() for i in result.retrieved_ids) or "(none)"
    content = (
        f"<conversation>\n{conversation}\n</conversation>\n\n"
        f"<articles_given_to_assistant>\n{articles}\n</articles_given_to_assistant>\n\n"
        f"<assistant_reply action=\"{result.action}\" citations=\"{', '.join(result.citations)}\">\n"
        f"{result.reply}\n</assistant_reply>\n\n"
        f"<reference>\nAcceptable actions: {', '.join(case.expected_action)}\n{case.reference}\n</reference>"
    )
    call = cached_parse(
        model=model,
        instructions=JUDGE_PROMPT,
        input=[{"role": "user", "content": content}],
        text_format=Verdict,
        effort="medium",
        usage=usage,
        cache_key_prefix="judge",
    )
    return call.parsed
