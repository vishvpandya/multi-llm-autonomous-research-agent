import json
import threading
import time

from research_agent.agent import ResearchAgent
from research_agent.memory import ResearchMemory
from research_agent.models import SearchTask, Source
from research_agent.providers import PROVIDERS, create_llm_client
from research_agent.search import SearchHit


class FakeLLM:
    provider_name = "Fake LLM"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return json.dumps(
                {
                    "topic_type": "test",
                    "reasoning": "Use two independent primary-source searches.",
                    "tasks": [
                        {
                            "query": "official evidence one",
                            "rationale": "first angle",
                            "preferred_sources": ["official"],
                        },
                        {
                            "query": "official evidence two",
                            "rationale": "second angle",
                            "preferred_sources": ["official"],
                        },
                    ],
                }
            )
        return "# Research Summary: Test\n\n## References\n\n- [S1] Evidence"


class FakeSearch:
    name = "Fake Search"

    def __init__(self) -> None:
        self.thread_ids: set[int] = set()

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        self.thread_ids.add(threading.get_ident())
        time.sleep(0.02)
        slug = query.rsplit(" ", 1)[-1]
        return [SearchHit(f"Evidence {slug}", f"https://example.com/{slug}", "Fact")]


class RecordingSearch:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, list[str]]] = []

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        self.calls.append((query, preferred_domains or []))
        return [SearchHit("Evidence", "https://who.int/evidence", "Fact")]


class GreetingLLM:
    provider_name = "Fake LLM"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        return json.dumps(
            {
                "intent": "casual_chat",
                "reasoning": "The user offered a greeting.",
                "response": "Hello! What would you like help with?",
            }
        )


class RoutedResearchLLM:
    provider_name = "Fake LLM"
    model = "fake-model"

    def generate(self, prompt: str) -> str:
        if "intent router" in prompt:
            return json.dumps(
                {
                    "intent": "research_request",
                    "reasoning": "The user explicitly requested a comparison.",
                    "response": "",
                }
            )
        if "planning component" in prompt:
            return json.dumps(
                {
                    "topic_type": "comparison",
                    "reasoning": "Compare two evidence streams.",
                    "tasks": [
                        {
                            "query": "comparison evidence one",
                            "rationale": "first angle",
                            "preferred_sources": ["official"],
                        },
                        {
                            "query": "comparison evidence two",
                            "rationale": "second angle",
                            "preferred_sources": ["official"],
                        },
                    ],
                }
            )
        return "# Research Summary: Comparison\n\n## References\n\n- [S1] Evidence"


class ExplodingSearch:
    name = "Must Not Run"

    def search(
        self,
        query: str,
        max_results: int = 4,
        preferred_domains: list[str] | None = None,
    ) -> list[SearchHit]:
        raise AssertionError("Search must not run for a greeting")


class MemoryAwareLLM:
    provider_name = "Memory LLM"
    model = "memory-model"

    def generate(self, prompt: str) -> str:
        raise AssertionError("The chat method should be used for routed conversation turns")

    def chat(
        self, messages: list[dict[str, str]], system_prompt: str | None = None
    ) -> str:
        transcript = " ".join(message["content"].lower() for message in messages)
        context = f"{system_prompt or ''} {transcript}".lower()
        newest = messages[-1]["content"].lower()
        if "what is my name" in newest and (
            "my name is vishv" in context or "preferred_name: vishv" in context
        ):
            response = "Your name is Vishv."
        else:
            response = "Nice to meet you, Vishv!"
        return json.dumps(
            {
                "intent": "simple_question",
                "reasoning": "Answered using conversation memory.",
                "response": response,
            }
        )


def test_end_to_end_agent_with_provider_independent_search(tmp_path) -> None:
    search = FakeSearch()
    agent = ResearchAgent(
        llm=FakeLLM(),
        search_client=search,
        memory=ResearchMemory(tmp_path / "memory.db"),
        max_parallel_searches=2,
    )

    report = agent.research("A useful test question")

    assert len(report.sources) == 2
    assert "[S1](https://example.com/" in report.markdown
    assert len(search.thread_ids) == 2
    assert report.memory_id is not None


def test_greeting_is_answered_without_research_or_memory_write(tmp_path) -> None:
    llm = GreetingLLM()
    memory = ResearchMemory(tmp_path / "memory.db")
    agent = ResearchAgent(
        llm=llm,
        search_client=ExplodingSearch(),
        memory=memory,
    )

    outcome = agent.run("hello")

    assert outcome.report is None
    assert outcome.decision.intent == "casual_chat"
    assert outcome.message.startswith("Hello")
    assert llm.calls == 1
    assert memory.recent() == []


def test_research_intent_runs_full_workflow(tmp_path) -> None:
    agent = ResearchAgent(
        llm=RoutedResearchLLM(),
        search_client=FakeSearch(),
        memory=ResearchMemory(tmp_path / "memory.db"),
        max_parallel_searches=2,
    )

    outcome = agent.run("Compare option one and option two using evidence")

    assert outcome.decision.intent == "research_request"
    assert outcome.report is not None
    assert len(outcome.report.sources) == 2


def test_follow_up_uses_current_thread_history(tmp_path) -> None:
    agent = ResearchAgent(
        llm=MemoryAwareLLM(),
        search_client=ExplodingSearch(),
        memory=ResearchMemory(tmp_path / "memory.db"),
    )
    history = [
        {"role": "user", "content": "My name is Vishv"},
        {"role": "assistant", "content": "Nice to meet you, Vishv!"},
    ]

    outcome = agent.run("What is my name?", history=history)

    assert outcome.message == "Your name is Vishv."
    assert outcome.report is None


def test_new_thread_uses_long_term_memory(tmp_path) -> None:
    memory = ResearchMemory(tmp_path / "memory.db")
    first_thread = memory.create_conversation("Introduction")
    memory.add_message(first_thread, "user", "My name is Vishv")
    second_thread = memory.create_conversation("A separate chat")
    agent = ResearchAgent(
        llm=MemoryAwareLLM(),
        search_client=ExplodingSearch(),
        memory=memory,
    )

    outcome = agent.run(
        "What is my name?",
        history=memory.messages(second_thread),
        conversation_id=second_thread,
    )

    assert outcome.message == "Your name is Vishv."
    assert memory.long_term_facts()[0]["value"] == "Vishv"


def test_link_source_ids_makes_citations_clickable() -> None:
    linked = ResearchAgent._link_source_ids(
        "Claim [S1] and repeated claim [S1].",
        [Source("Evidence", "https://example.com/evidence")],
    )
    assert linked.count("[S1](https://example.com/evidence)") == 2


def test_supported_provider_defaults_are_defined() -> None:
    assert {"openai", "deepseek", "gemini", "groq", "custom"} <= set(PROVIDERS)
    assert PROVIDERS["deepseek"].base_url == "https://api.deepseek.com"
    assert PROVIDERS["gemini"].api_key_env == "GEMINI_API_KEY"


def test_custom_provider_requires_base_url() -> None:
    try:
        create_llm_client("custom", "test-key", "test-model")
    except ValueError as exc:
        assert "base URL" in str(exc)
    else:
        raise AssertionError("Expected a missing base URL error")


def test_auto_mode_executes_llm_selected_backend_and_domains(tmp_path) -> None:
    fallback = RecordingSearch("DuckDuckGo")
    selected = RecordingSearch("SerpAPI")
    agent = ResearchAgent(
        llm=FakeLLM(),
        search_client=fallback,
        memory=ResearchMemory(tmp_path / "memory.db"),
    )
    agent._fixed_search_client = False
    agent.search_backend_mode = "auto"
    agent._search_providers = {"duckduckgo": fallback, "serpapi": selected}
    task = SearchTask(
        query="public health evidence",
        rationale="Use an official public-health source",
        preferred_sources=["official agency"],
        preferred_domains=["who.int"],
        search_backend="serpapi",
    )

    result = agent._search_task(task)

    assert result.search_backend == "SerpAPI"
    assert selected.calls == [("public health evidence", ["who.int"])]
    assert fallback.calls == []
