"""Offline retrieval quality: the right article should be in the top 3 for at least 90% of answerable cases.

Known misses: fact-10 (a tokenizer bug, see README "Known issues") and adv-06 (injected text dilutes the query).
"""

from support_bot_evals.bot import SupportBot
from support_bot_evals.dataset import load_cases


def test_retrieval_finds_expected_article():
    bot = SupportBot("v2")
    misses = []
    for case in load_cases():
        if not case.expected_citations:
            continue
        got = {a.id for a in bot._retrieve(case.turns)}
        if not got & set(case.expected_citations):
            misses.append((case.id, case.expected_citations, sorted(got)))
    hit_rate = 1 - len(misses) / sum(1 for c in load_cases() if c.expected_citations)
    assert hit_rate >= 0.9, f"retrieval hit rate {hit_rate:.0%}; misses: {misses}"
