from datetime import datetime, timezone

from research_agent.models import SearchTask
from research_agent.relevance import evaluate_hit, filter_relevant_hits
from research_agent.search import SearchHit


def test_relevance_filter_removes_unrelated_source() -> None:
    task = SearchTask(
        query="electric vehicle battery range India",
        rationale="Compare real driving range and battery performance",
        preferred_domains=["example.gov"],
    )
    relevant = SearchHit(
        "Electric vehicle battery range report",
        "https://example.gov/ev-report",
        "Battery range results for electric vehicles in India.",
    )
    irrelevant = SearchHit(
        "Chocolate cake recipe",
        "https://food.example/cake",
        "Flour, sugar and chocolate instructions.",
    )

    kept, filtered_count = filter_relevant_hits([irrelevant, relevant], task)

    assert filtered_count == 1
    assert [item.hit.url for item in kept] == ["https://example.gov/ev-report"]
    assert kept[0].source.relevance_score > 0


def test_source_quality_scores_authority_and_freshness() -> None:
    current_year = datetime.now(timezone.utc).year
    task = SearchTask(
        query="public health guidance",
        rationale="Use current official guidance",
        preferred_domains=["who.int"],
    )
    hit = SearchHit(
        f"Public health guidance {current_year}",
        "https://www.who.int/guidance",
        "Current public health guidance.",
        published_date=str(current_year),
    )

    evaluated = evaluate_hit(hit, task)

    assert evaluated.source.authority_score == 1.0
    assert evaluated.source.freshness_score == 1.0
    assert evaluated.source.quality_score > 0.5
