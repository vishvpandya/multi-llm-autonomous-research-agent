from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


RESEARCH_INTENTS = {"current_information", "research_request"}


@dataclass(slots=True)
class SearchTask:
    query: str
    rationale: str
    preferred_sources: list[str] = field(default_factory=list)
    preferred_domains: list[str] = field(default_factory=list)
    search_backend: str = "auto"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SearchTask":
        return cls(
            query=str(value.get("query", "")).strip(),
            rationale=str(value.get("rationale", "")).strip(),
            preferred_sources=[str(item) for item in value.get("preferred_sources", [])],
            preferred_domains=[str(item) for item in value.get("preferred_domains", [])],
            search_backend=str(value.get("search_backend", "auto")).strip().lower(),
        )


@dataclass(slots=True)
class SearchPlan:
    topic_type: str
    tasks: list[SearchTask]
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Source:
    title: str
    url: str
    search_query: str = ""
    relevance_score: float = 0.0
    authority_score: float = 0.0
    freshness_score: float = 0.0
    quality_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SearchResult:
    task: SearchTask
    content: str
    sources: list[Source]
    search_backend: str = ""
    candidates_evaluated: int = 0
    candidates_filtered: int = 0


@dataclass(slots=True)
class ResearchReport:
    query: str
    markdown: str
    plan: SearchPlan
    sources: list[Source]
    duration_seconds: float
    memory_id: int | None = None
    candidates_evaluated: int = 0
    candidates_filtered: int = 0


@dataclass(slots=True)
class QueryDecision:
    intent: str
    reasoning: str
    response: str = ""
    memory_updates: list[dict[str, str]] = field(default_factory=list)
    router: str = "LLM intent router"
    confidence: float | None = None

    @property
    def requires_research(self) -> bool:
        return self.intent in RESEARCH_INTENTS


@dataclass(slots=True)
class AgentResponse:
    decision: QueryDecision
    message: str = ""
    report: ResearchReport | None = None
