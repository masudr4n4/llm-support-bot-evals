"""Knowledge base loading and BM25 retrieval over help-center articles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "kb"

_STOPWORDS = set(
    "a an and are as at be but by can do does for from how i if in is it its me my "
    "of on or so that the this to was what when where which who why will with you your".split()
)


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    updated: str
    body: str

    def as_context(self) -> str:
        return f'<article id="{self.id}" title="{self.title}" updated="{self.updated}">\n{self.body}\n</article>'


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9$.]+", text.lower()) if t not in _STOPWORDS]


def load_articles(kb_dir: Path = KB_DIR) -> list[Article]:
    articles = []
    for path in sorted(kb_dir.glob("*.md")):
        _, front, body = path.read_text().split("---", 2)
        meta = yaml.safe_load(front)
        articles.append(Article(meta["id"], meta["title"], str(meta["updated"]), body.strip()))
    return articles


class Retriever:
    def __init__(self, articles: list[Article]):
        self.articles = articles
        self.by_id = {a.id: a for a in articles}
        self._bm25 = BM25Okapi([tokenize(f"{a.title} {a.title} {a.body}") for a in articles])

    def search(self, query: str, k: int = 3) -> list[Article]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(scores, self.articles), key=lambda p: p[0], reverse=True)
        return [a for score, a in ranked[:k] if score > 0]
