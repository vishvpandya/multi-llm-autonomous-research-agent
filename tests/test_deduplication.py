from research_agent.deduplication import canonicalize_url, deduplicate_sources
from research_agent.models import Source


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    url = "https://Example.com/report/?utm_source=newsletter&id=4#findings"
    assert canonicalize_url(url) == "https://example.com/report?id=4"


def test_deduplicate_sources_by_canonical_url() -> None:
    sources = [
        Source("Annual Report", "https://example.com/report?utm_campaign=test"),
        Source("Annual Report copy", "https://example.com/report"),
    ]
    assert len(deduplicate_sources(sources)) == 1


def test_deduplicate_sources_by_similar_title() -> None:
    sources = [
        Source("Global Energy Outlook 2026", "https://one.example/outlook"),
        Source("Global Energy Outlook 2026", "https://two.example/syndicated"),
    ]
    assert len(deduplicate_sources(sources)) == 1

