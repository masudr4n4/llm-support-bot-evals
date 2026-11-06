"""The system under test: a retrieval-augmented support assistant for Tidewell (a fictional company)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .kb import ROOT, Article, Retriever, load_articles
from .llm import BOT_MODEL, Usage, cached_parse

PROMPTS_DIR = ROOT / "prompts"

Action = Literal["answer", "clarify", "handoff", "refuse", "dont_know"]


class BotReply(BaseModel):
    reply: str = Field(description="The message shown to the customer.")
    action: Action = Field(
        description="answer: answered from the articles. clarify: asked a clarifying question. "
        "handoff: routing to a human agent. refuse: declined an off-topic or disallowed request. "
        "dont_know: the articles do not contain the answer."
    )
    citations: list[str] = Field(description="Ids of the articles the reply relies on. Empty if none.")


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class BotResult:
    reply: str
    action: str
    citations: list[str]
    retrieved_ids: list[str]
    latency_s: float
    stop_reason: str


class SupportBot:
    def __init__(self, prompt_version: str, model: str = BOT_MODEL, top_k: int = 3):
        self.prompt_version = prompt_version
        self.system = (PROMPTS_DIR / f"{prompt_version}.md").read_text()
        self.model = model
        self.top_k = top_k
        self.retriever = Retriever(load_articles())

    def _retrieve(self, turns: list[Turn]) -> list[Article]:
        # Use the last two customer messages so follow-ups like "and on Scale?" still find the topic.
        user_msgs = [t.content for t in turns if t.role == "user"][-2:]
        return self.retriever.search(" ".join(user_msgs), k=self.top_k)

    def respond(self, turns: list[Turn], usage: Usage) -> BotResult:
        articles = self._retrieve(turns)
        context = "\n\n".join(a.as_context() for a in articles) or "(no matching articles)"
        messages = [{"role": t.role, "content": t.content} for t in turns[:-1]]
        messages.append(
            {
                "role": "user",
                "content": f"<help_center_articles>\n{context}\n</help_center_articles>\n\n"
                f"<customer_message>\n{turns[-1].content}\n</customer_message>",
            }
        )

        call = cached_parse(
            model=self.model,
            instructions=self.system,
            input=messages,
            text_format=BotReply,
            effort="low",
            usage=usage,
            cache_key_prefix=f"bot-{self.prompt_version}",
        )

        retrieved = [a.id for a in articles]
        if call.parsed is None:
            # A model-level refusal or truncated output is a real outcome, so record it instead of raising.
            status = "refusal" if call.refusal else call.status
            return BotResult(call.refusal or "", f"error:{status}", [], retrieved, call.latency_s, status)
        p = call.parsed
        return BotResult(p.reply, p.action, p.citations, retrieved, call.latency_s, call.status)
