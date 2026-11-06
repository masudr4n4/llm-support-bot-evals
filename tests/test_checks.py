from support_bot_evals.bot import BotResult, Turn
from support_bot_evals.checks import matches, run_checks
from support_bot_evals.dataset import Case

CASE = Case(
    id="t",
    category="factual",
    turns=[Turn("user", "How much is Growth?")],
    expected_action=["answer"],
    reference="$59",
    must_include=["$59", "re:2,?000"],
    must_not_include=["re:free"],
    expected_citations=["plans-and-pricing"],
)
KNOWN = {"plans-and-pricing", "free-trial"}


def result(reply="Growth is $59/month with 2,000 shipments.", action="answer", citations=("plans-and-pricing",)):
    return BotResult(reply, action, list(citations), ["plans-and-pricing"], 1.0, "end_turn")


def test_matches_substring_and_regex():
    assert matches("$59", "it costs $59")
    assert matches("re:2,?000", "2000 shipments")
    assert not matches("re:^free", "not free")


def test_correct_reply_passes_all_checks():
    checks = run_checks(CASE, result(), KNOWN)
    assert all(c["passed"] for c in checks.values()), checks


def test_wrong_action_fails():
    assert not run_checks(CASE, result(action="dont_know"), KNOWN)["action"]["passed"]


def test_missing_fact_and_forbidden_text_fail():
    checks = run_checks(CASE, result(reply="Growth is free for 2000 shipments."), KNOWN)
    assert not checks["must_include"]["passed"]
    assert not checks["must_not_include"]["passed"]


def test_invented_citation_fails():
    checks = run_checks(CASE, result(citations=["plans-and-pricing", "made-up-article"]), KNOWN)
    assert not checks["citations_exist"]["passed"]


def test_expected_citation_only_checked_for_answers():
    assert "cites_expected" not in run_checks(CASE, result(action="handoff", citations=[]), KNOWN)
    assert not run_checks(CASE, result(citations=["free-trial"]), KNOWN)["cites_expected"]["passed"]
