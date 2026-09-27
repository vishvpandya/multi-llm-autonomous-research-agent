import research_agent.search as search_module
from research_agent.search import (
    DuckDuckGoSearchProvider,
    SerpApiSearchProvider,
    TavilySearchProvider,
    create_search_provider,
    _domain_constrained_query,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_serpapi_parses_organic_results(monkeypatch) -> None:
    captured: dict = {}

    def fake_get(url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(
            {
                "organic_results": [
                    {
                        "title": "Official report",
                        "link": "https://example.com/report",
                        "snippet": "Evidence from the report.",
                    },
                    {
                        "title": "Second source",
                        "link": "https://example.org/data",
                        "snippet": "Additional evidence.",
                    },
                ]
            }
        )

    monkeypatch.setattr(search_module.httpx, "get", fake_get)
    monkeypatch.setattr(
        search_module, "_extract_page_text", lambda url: f"Extracted from {url}"
    )

    hits = SerpApiSearchProvider("secret").search("research topic", max_results=2)

    assert captured["url"] == "https://serpapi.com/search.json"
    assert captured["params"] == {
        "engine": "google",
        "q": "research topic",
        "api_key": "secret",
        "num": 2,
    }
    assert [hit.title for hit in hits] == ["Official report", "Second source"]
    assert hits[0].content == "Extracted from https://example.com/report"


def test_auto_search_backend_priority(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setenv("SERPAPI_API_KEY", "serp-key")
    assert isinstance(create_search_provider("auto"), TavilySearchProvider)

    monkeypatch.delenv("TAVILY_API_KEY")
    assert isinstance(create_search_provider("auto"), SerpApiSearchProvider)

    monkeypatch.delenv("SERPAPI_API_KEY")
    assert isinstance(create_search_provider("auto"), DuckDuckGoSearchProvider)


def test_explicit_serpapi_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    try:
        create_search_provider("serpapi")
    except ValueError as exc:
        assert "SERPAPI_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected SerpAPI to require an API key")


def test_domain_preferences_are_applied_to_search_queries() -> None:
    query = _domain_constrained_query(
        "health guidance", ["https://www.who.int/news", "cdc.gov"]
    )

    assert query == "health guidance (site:who.int OR site:cdc.gov)"
