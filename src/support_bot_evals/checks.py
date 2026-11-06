"""Deterministic checks. Cheap, exact, and run before the LLM judge."""

from __future__ import annotations

import re

from .bot import BotResult
from .dataset import Case


def matches(pattern: str, text: str) -> bool:
    if pattern.startswith("re:"):
        return re.search(pattern[3:], text, flags=re.IGNORECASE) is not None
    return pattern.lower() in text.lower()


def run_checks(case: Case, result: BotResult, known_ids: set[str]) -> dict[str, dict]:
    """Return {check_name: {"passed": bool, "detail": str}} for every check that applies to the case."""
    checks: dict[str, dict] = {}

    checks["action"] = {
        "passed": result.action in case.expected_action,
        "detail": f"got {result.action}, expected one of {case.expected_action}",
    }

    if case.must_include:
        missing = [p for p in case.must_include if not matches(p, result.reply)]
        checks["must_include"] = {"passed": not missing, "detail": f"missing: {missing}" if missing else "all present"}

    if case.must_not_include:
        found = [p for p in case.must_not_include if matches(p, result.reply)]
        checks["must_not_include"] = {"passed": not found, "detail": f"found: {found}" if found else "none present"}

    unknown = [c for c in result.citations if c not in known_ids]
    checks["citations_exist"] = {
        "passed": not unknown,
        "detail": f"cited ids that don't exist: {unknown}" if unknown else "all cited ids exist",
    }

    if case.expected_citations and result.action == "answer":
        hit = set(case.expected_citations) & set(result.citations)
        checks["cites_expected"] = {
            "passed": bool(hit),
            "detail": f"cited {result.citations}, expected one of {case.expected_citations}",
        }

    return checks
