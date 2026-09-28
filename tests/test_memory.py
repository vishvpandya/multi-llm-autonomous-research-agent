import sqlite3

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


def test_anonymous_visitors_have_isolated_chats_memory_and_searches(tmp_path) -> None:
    db_path = tmp_path / "history.db"
    first = ResearchMemory(db_path, owner_id="browser-a")
    second = ResearchMemory(db_path, owner_id="browser-b")
    first_conversation = first.create_conversation("First browser")
    first.add_message(first_conversation, "user", "My name is Alice")
    report = ResearchReport(
        query="Private research",
        markdown="# Private report",
        plan=SearchPlan("test", [SearchTask("private query", "coverage")]),
        sources=[Source("Example", "https://example.com")],
        duration_seconds=0.5,
    )
    first_search_id = first.save(report, "test-model")

    assert second.list_conversations() == []
    assert second.get_conversation(first_conversation) is None
    assert second.messages(first_conversation) == []
    assert second.long_term_facts() == []
    assert second.recent() == []
    assert second.get(first_search_id) is None

    second_conversation = second.create_conversation("Second browser")
    second.add_message(second_conversation, "user", "My name is Bob")
    second.delete_conversation(first_conversation)

    assert first.get_conversation(first_conversation) is not None
    assert first.long_term_facts()[0]["value"] == "Alice"
    assert second.long_term_facts()[0]["value"] == "Bob"


def test_legacy_database_migrates_without_exposing_old_records(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE TABLE searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, model TEXT NOT NULL,
                plan_json TEXT NOT NULL, report_markdown TEXT NOT NULL,
                sources_json TEXT NOT NULL, duration_seconds REAL NOT NULL
            );
            CREATE TABLE memory_facts (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, source_conversation_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(source_conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
            );
            INSERT INTO conversations (id, title) VALUES ('old-chat', 'Old shared chat');
            INSERT INTO memory_facts (key, value, source_conversation_id)
            VALUES ('preferred_name', 'Legacy User', 'old-chat');
            """
        )

    visitor = ResearchMemory(db_path, owner_id="new-browser")
    legacy = ResearchMemory(db_path, owner_id="legacy")

    assert visitor.list_conversations() == []
    assert visitor.long_term_facts() == []
    assert legacy.get_conversation("old-chat") is not None
    assert legacy.long_term_facts()[0]["value"] == "Legacy User"
