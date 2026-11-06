"""Golden dataset loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .bot import Turn
from .kb import ROOT

DATASET = ROOT / "datasets" / "golden.yaml"


@dataclass
class Case:
    id: str
    category: str
    turns: list[Turn]
    expected_action: list[str]
    reference: str
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)
    expected_citations: list[str] = field(default_factory=list)


def load_cases(path: Path = DATASET) -> list[Case]:
    cases = []
    for raw in yaml.safe_load(path.read_text()):
        turns = [Turn(role, text) for t in raw.pop("turns") for role, text in t.items()]
        cases.append(Case(turns=turns, **raw))
    return cases
