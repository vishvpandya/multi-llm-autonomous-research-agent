import json

import research_agent.jev as jev_module
from research_agent.agent import ResearchAgent
from research_agent.jev import JevDecisionRouter, JevRoute
from research_agent.memory import ResearchMemory
from research_agent.search import SearchHit


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSearch:
    name = "Fake Search"

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        return [SearchHit("Evidence", "https://example.com/evidence", "Fact")]


class ResearchLLM:
    provider_name = "Research LLM"
    model = "research-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "planning component" in prompt:
            return json.dumps(
                {
                    "topic_type": "comparison",
                    "reasoning": "Use independent evidence.",
                    "tasks": [
                        {
                            "query": "current comparison evidence",
                            "rationale": "Find current facts",
                            "preferred_sources": ["official documentation"],
                        }
                    ],
                }
            )
        if "synthesis component" in prompt:
            return "# Research Summary: Test\n\n## References\n\n- [S1] Evidence"
        raise AssertionError("Jev should replace the LLM intent-classification call")


class GreetingLLM:
    provider_name = "Greeting LLM"
    model = "greeting-model"

    def generate(self, prompt: str) -> str:
        return json.dumps(
            {
                "intent": "casual_chat",
                "reasoning": "Greeting",
                "response": "Hello!",
                "memory_updates": [],
            }
        )


class StaticJevRouter:
    def __init__(self, route: JevRoute) -> None:
        self.route = route

    def classify(self, query: str, **kwargs) -> JevRoute:
        return self.route


class FailingJevRouter:
    def classify(self, query: str, **kwargs) -> JevRoute:
        raise RuntimeError("temporary Jev outage")


def test_jev_adapter_sends_typed_choice_request(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url: str, **kwargs) -> FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(
            {
                "model": "jev-latest",
                "answers": {
                    "intent": {
                        "type": "choice",
                        "choice": "research_request",
                        "confidence": 0.94,
                        "probabilities": {"research_request": 0.94},
                    }
                },
                "usage": {"input_tokens": 20, "output_tokens": 1},
            }
        )

    monkeypatch.setattr(jev_module.httpx, "post", fake_post)
    router = JevDecisionRouter("test-key")

    route = router.classify("Compare the latest electric cars")

    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["questions"]["intent"]["type"] == "choice"
    assert route == JevRoute("research_request", 0.94)


def test_jev_research_route_skips_llm_intent_call(tmp_path) -> None:
    llm = ResearchLLM()
    agent = ResearchAgent(
        llm=llm,
        search_client=FakeSearch(),
        memory=ResearchMemory(tmp_path / "memory.db"),
        jev_router=StaticJevRouter(JevRoute("research_request", 0.91)),
    )

    outcome = agent.run("Compare the latest options using current evidence")

    assert outcome.report is not None
    assert outcome.decision.router == "TypeSafe Jev"
    assert outcome.decision.confidence == 0.91
    assert not any("intent router" in prompt for prompt in llm.prompts)


def test_jev_failure_falls_back_to_existing_llm_router(tmp_path) -> None:
    agent = ResearchAgent(
        llm=GreetingLLM(),
        search_client=FakeSearch(),
        memory=ResearchMemory(tmp_path / "memory.db"),
        jev_router=FailingJevRouter(),
    )

    outcome = agent.run("hello")

    assert outcome.message == "Hello!"
    assert outcome.decision.intent == "casual_chat"
    assert outcome.decision.router == "LLM fallback (Jev unavailable)"


def test_enabled_jev_without_key_uses_llm_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    agent = ResearchAgent(
        llm=GreetingLLM(),
        search_client=FakeSearch(),
        memory=ResearchMemory(tmp_path / "memory.db"),
        jev_enabled=True,
        jev_api_key="",
    )

    outcome = agent.run("hello")

    assert agent.jev_router is None
    assert outcome.message == "Hello!"
    assert outcome.decision.router == "LLM fallback (Jev unavailable)"


def test_low_confidence_jev_decision_uses_llm_fallback(tmp_path) -> None:
    agent = ResearchAgent(
        llm=GreetingLLM(),
        search_client=FakeSearch(),
        memory=ResearchMemory(tmp_path / "memory.db"),
        jev_router=StaticJevRouter(JevRoute("research_request", 0.40)),
        jev_min_confidence=0.60,
    )

    outcome = agent.run("hello")

    assert outcome.report is None
    assert outcome.decision.intent == "casual_chat"
    assert outcome.decision.confidence == 0.40
    assert outcome.decision.router == "LLM fallback (Jev low confidence)"
