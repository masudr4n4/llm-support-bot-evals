"""Sanity checks on the golden dataset itself, so a typo can't silently weaken the eval."""

import re

from support_bot_evals.dataset import load_cases
from support_bot_evals.kb import load_articles
from support_bot_evals.metrics import ACTIONS

CASES = load_cases()
ARTICLE_IDS = {a.id for a in load_articles()}


def test_ids_are_unique():
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_every_case_is_well_formed():
    for c in CASES:
        assert c.turns and c.turns[-1].role == "user", c.id
        assert c.reference.strip(), c.id
        assert set(c.expected_action) <= set(ACTIONS), c.id
        assert set(c.expected_citations) <= ARTICLE_IDS, c.id


def test_regex_patterns_compile():
    for c in CASES:
        for p in c.must_include + c.must_not_include:
            if p.startswith("re:"):
                re.compile(p[3:])
