from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import ResearchReport


class ResearchMemory:
    """Small, local SQLite memory for completed research runs."""

    def __init__(self, db_path: str | Path = "data/research_history.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    model TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    report_markdown TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    duration_seconds REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_searches_created_at "
                "ON searches(created_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
                "ON messages(conversation_id, id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_updated "
                "ON conversations(updated_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    source_conversation_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(source_conversation_id) REFERENCES conversations(id)
                        ON DELETE SET NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            backfilled = connection.execute(
                "SELECT 1 FROM app_metadata WHERE key = 'memory_backfill_v1'"
            ).fetchone()
            if not backfilled:
                self._backfill_explicit_facts(connection)
                connection.execute(
                    "INSERT INTO app_metadata (key, value) VALUES ('memory_backfill_v1', 'done')"
                )

    def create_conversation(
        self,
        title: str = "New chat",
        provider: str = "",
        model: str = "",
    ) -> str:
        conversation_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (id, title, provider, model)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, title.strip() or "New chat", provider, model),
            )
        return conversation_id

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.title, c.provider, c.model, c.created_at, c.updated_at,
                       COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id
                ORDER BY c.updated_at DESC, c.rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return dict(row) if row else None

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"Unsupported message role: {role}")
        if not content.strip():
            raise ValueError("Message content cannot be empty.")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages (conversation_id, role, content, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content.strip(),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (conversation_id,),
            )
            if role == "user":
                for key, value in self._extract_explicit_facts(content).items():
                    self._upsert_fact(connection, key, value, conversation_id)
            return int(cursor.lastrowid)

    def messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, metadata_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
            messages.append(value)
        return messages

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        updates: list[str] = []
        values: list[str] = []
        for column, value in (("title", title), ("provider", provider), ("model", model)):
            if value is not None:
                updates.append(f"{column} = ?")
                values.append(value)
        if not updates:
            return
        updates.append("updated_at = CURRENT_TIMESTAMP")
        values.append(conversation_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE conversations SET {', '.join(updates)} WHERE id = ?",
                values,
            )

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )

    def remember_facts(
        self,
        facts: list[dict[str, str]],
        source_conversation_id: str | None = None,
    ) -> None:
        with self._connect() as connection:
            for fact in facts:
                key = self._normalize_fact_key(str(fact.get("key", "")))
                value = " ".join(str(fact.get("value", "")).split())[:500]
                if key and value and not self._looks_sensitive(key, value):
                    self._upsert_fact(connection, key, value, source_conversation_id)

    def long_term_facts(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT key, value, source_conversation_id, created_at, updated_at
                FROM memory_facts
                ORDER BY updated_at DESC, key ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def forget_fact(self, key: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM memory_facts WHERE key = ?",
                (self._normalize_fact_key(key),),
            )

    def clear_long_term_memory(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM memory_facts")

    @staticmethod
    def _normalize_fact_key(key: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")[:80]
        if normalized in {"name", "user_name", "username", "preferred_name"}:
            return "preferred_name"
        return normalized

    @staticmethod
    def _looks_sensitive(key: str, value: str) -> bool:
        combined = f"{key} {value}".lower()
        blocked_terms = {
            "api_key",
            "password",
            "passcode",
            "secret",
            "credit_card",
            "cvv",
            "private_key",
            "access_token",
        }
        return any(term in combined for term in blocked_terms)

    @staticmethod
    def _extract_explicit_facts(content: str) -> dict[str, str]:
        patterns = (
            r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{0,50}?)(?=[,.!?;]|\s+and\b|$)",
            r"\bcall me\s+([A-Za-z][A-Za-z .'-]{0,50}?)(?=[,.!?;]|\s+and\b|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                name = " ".join(match.group(1).split()).strip(" .'-")
                if name:
                    return {"preferred_name": name.title()}
        return {}

    @classmethod
    def _upsert_fact(
        cls,
        connection: sqlite3.Connection,
        key: str,
        value: str,
        source_conversation_id: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO memory_facts (key, value, source_conversation_id)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                source_conversation_id = excluded.source_conversation_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (cls._normalize_fact_key(key), value, source_conversation_id),
        )

    @classmethod
    def _backfill_explicit_facts(cls, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT conversation_id, content
            FROM messages
            WHERE role = 'user'
            ORDER BY id ASC
            """
        ).fetchall()
        for row in rows:
            for key, value in cls._extract_explicit_facts(row["content"]).items():
                cls._upsert_fact(connection, key, value, row["conversation_id"])

    def save(self, report: ResearchReport, model: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO searches (
                    query, model, plan_json, report_markdown,
                    sources_json, duration_seconds
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    report.query,
                    model,
                    json.dumps(report.plan.to_dict(), ensure_ascii=False),
                    report.markdown,
                    json.dumps([asdict(source) for source in report.sources], ensure_ascii=False),
                    report.duration_seconds,
                ),
            )
            return int(cursor.lastrowid)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, query, created_at, model, duration_seconds,
                       report_markdown, sources_json, plan_json
                FROM searches
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._deserialize(row) for row in rows]

    def get(self, search_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM searches WHERE id = ?", (search_id,)
            ).fetchone()
        return self._deserialize(row) if row else None

    @staticmethod
    def _deserialize(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["sources"] = json.loads(value.pop("sources_json"))
        value["plan"] = json.loads(value.pop("plan_json"))
        return value
