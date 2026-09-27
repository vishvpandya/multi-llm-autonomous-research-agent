import json

import pytest

from research_agent.agent import ResearchAgent
from research_agent.memory import ResearchMemory
from research_agent.models import SearchPlan, SearchResult, SearchTask, Source
from research_agent.reporting import ReportValidationError, StructuredReportContent
from research_agent.search import SearchHit


def valid_payload() -> dict:
    return {
        "title": "Evidence review",
        "executive_summary": "The evidence supports the conclusion [S1].",
        "key_points": ["A supported key point [S1]."],
        "important_findings": ["A supported important finding [S1]."],
        "actionable_insights": ["Verify local conditions before deciding."],
        "limitations": ["Only one source was available."],
        "used_source_ids": ["S1"],
    }


class NoopSearch:
    name = "Noop"

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        return []


class RepairingLLM:
    provider_name = "Repairing LLM"
    model = "repair-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            invalid = valid_payload()
            invalid["actionable_insights"] = []
            return json.dumps(invalid)
        return json.dumps(valid_payload())


def test_structured_report_requires_actionable_insights() -> None:
    payload = valid_payload()
    payload["actionable_insights"] = []

    with pytest.raises(ReportValidationError, match="actionable_insights"):
        StructuredReportContent.from_dict(payload, source_count=1)


def test_structured_report_renderer_guarantees_required_sections() -> None:
    report = StructuredReportContent.from_dict(valid_payload(), source_count=1)

    markdown = report.to_markdown([Source("Official evidence", "https://example.com")])

    for heading in (
        "## Key Points",
        "## Important Findings",
        "## Actionable Insights",
        "## References",
    ):
        assert heading in markdown
    assert "Verify local conditions" in markdown


def test_synthesis_repairs_invalid_structured_output(tmp_path) -> None:
    llm = RepairingLLM()
    agent = ResearchAgent(
        llm=llm,
        search_client=NoopSearch(),
        memory=ResearchMemory(tmp_path / "memory.db"),
    )
    task = SearchTask("evidence review", "Find evidence")
    source = Source("Official evidence", "https://example.com", "evidence review")
    result = SearchResult(task, "Evidence content", [source])

    markdown = agent._synthesize(
        "Review the evidence",
        SearchPlan("review", [task], "Use official evidence"),
        [result],
        [source],
    )

    assert llm.calls == 2
    assert "## Actionable Insights" in markdown
    assert "[S1](https://example.com)" in markdown
