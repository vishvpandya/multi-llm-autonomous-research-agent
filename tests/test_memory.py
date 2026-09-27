from research_agent.memory import ResearchMemory
from research_agent.models import ResearchReport, SearchPlan, SearchTask, Source


def test_save_and_read_history(tmp_path) -> None:
    memory = ResearchMemory(tmp_path / "history.db")
    report = ResearchReport(
        query="Test question",
        markdown="# Answer",
        plan=SearchPlan("test", [SearchTask("test query", "coverage")]),
        sources=[Source("Example", "https://example.com")],
        duration_seconds=1.25,
    )
    saved_id = memory.save(report, "test-model")
    saved = memory.get(saved_id)

    assert saved is not None
    assert saved["query"] == "Test question"
    assert saved["sources"][0]["url"] == "https://example.com"
    assert memory.recent(1)[0]["id"] == saved_id


def test_conversation_messages_persist_across_memory_instances(tmp_path) -> None:
    db_path = tmp_path / "history.db"
    memory = ResearchMemory(db_path)
    conversation_id = memory.create_conversation("Introductions", "DeepSeek", "model")
    memory.add_message(conversation_id, "user", "My name is Vishv")
    memory.add_message(
        conversation_id,
        "assistant",
        "Nice to meet you, Vishv!",
        {"intent": "casual_chat"},
    )

    reopened = ResearchMemory(db_path)
    messages = reopened.messages(conversation_id)

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "My name is Vishv"
    assert messages[1]["metadata"]["intent"] == "casual_chat"
    assert reopened.list_conversations()[0]["message_count"] == 2


def test_delete_conversation_cascades_messages(tmp_path) -> None:
    memory = ResearchMemory(tmp_path / "history.db")
    conversation_id = memory.create_conversation()
    memory.add_message(conversation_id, "user", "Temporary message")

    memory.delete_conversation(conversation_id)

    assert memory.get_conversation(conversation_id) is None
    assert memory.messages(conversation_id) == []


def test_explicit_name_is_saved_as_long_term_memory(tmp_path) -> None:
    memory = ResearchMemory(tmp_path / "history.db")
    conversation_id = memory.create_conversation()

    memory.add_message(conversation_id, "user", "My name is vishv")

    assert memory.long_term_facts()[0]["key"] == "preferred_name"
    assert memory.long_term_facts()[0]["value"] == "Vishv"


def test_cleared_long_term_memory_stays_cleared_after_restart(tmp_path) -> None:
    db_path = tmp_path / "history.db"
    memory = ResearchMemory(db_path)
    conversation_id = memory.create_conversation()
    memory.add_message(conversation_id, "user", "Call me Vishv")
    assert memory.long_term_facts()

    memory.clear_long_term_memory()
    reopened = ResearchMemory(db_path)

    assert reopened.long_term_facts() == []
