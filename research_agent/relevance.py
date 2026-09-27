from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .models import SearchTask, Source
from .search import SearchHit


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "which",
    "with",
}


@dataclass(frozen=True, slots=True)
class EvaluatedHit:
    hit: SearchHit
    source: Source


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 1 and token not in STOP_WORDS
    }


def _overlap(reference: set[str], candidate: set[str]) -> float:
    if not reference:
        return 0.0
    return len(reference & candidate) / len(reference)


def _authority_score(url: str, preferred_domains: list[str]) -> float:
    hostname = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    preferred = [domain.lower().removeprefix("www.") for domain in preferred_domains]
    if any(hostname == domain or hostname.endswith(f".{domain}") for domain in preferred):
        return 1.0
    if hostname.endswith(".gov") or ".gov." in hostname:
        return 0.95
    if hostname.endswith(".edu") or ".edu." in hostname or ".ac." in hostname:
        return 0.90
    if hostname.startswith(("docs.", "developer.")):
        return 0.85
    if hostname.endswith(".org"):
        return 0.75
    return 0.55


def _freshness_score(hit: SearchHit) -> float:
    current_year = datetime.now(timezone.utc).year
    candidates = " ".join((hit.published_date, hit.title, hit.snippet, hit.url))
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", candidates)]
    if not years:
        return 0.50
    newest = max(years)
    age = max(0, current_year - newest)
    if age == 0:
        return 1.0
    if age == 1:
        return 0.90
    if age <= 3:
        return 0.75
    if age <= 5:
        return 0.60
    return 0.35


def evaluate_hit(hit: SearchHit, task: SearchTask) -> EvaluatedHit:
    reference = _tokens(f"{task.query} {task.rationale}")
    title_overlap = _overlap(reference, _tokens(hit.title))
    body_overlap = _overlap(reference, _tokens(f"{hit.snippet} {hit.content[:2000]}"))
    relevance = min(1.0, (0.65 * title_overlap) + (0.35 * body_overlap))
    authority = _authority_score(hit.url, task.preferred_domains)
    freshness = _freshness_score(hit)
    quality = (0.60 * relevance) + (0.25 * authority) + (0.15 * freshness)
    return EvaluatedHit(
        hit=hit,
        source=Source(
            title=hit.title,
            url=hit.url,
            search_query=task.query,
            relevance_score=round(relevance, 3),
            authority_score=round(authority, 3),
            freshness_score=round(freshness, 3),
            quality_score=round(quality, 3),
        ),
    )


def filter_relevant_hits(
    hits: list[SearchHit],
    task: SearchTask,
    minimum_relevance: float = 0.08,
) -> tuple[list[EvaluatedHit], int]:
    """Score every candidate and remove weakly related evidence before synthesis."""
    evaluated = [evaluate_hit(hit, task) for hit in hits]
    kept = [item for item in evaluated if item.source.relevance_score >= minimum_relevance]
    kept.sort(key=lambda item: item.source.quality_score, reverse=True)
    return kept, len(evaluated) - len(kept)
