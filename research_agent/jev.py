from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


JEV_INTENTS = {
    "casual_chat",
    "simple_question",
    "current_information",
    "research_request",
    "clarification_required",
}


@dataclass(frozen=True, slots=True)
class JevRoute:
    intent: str
    confidence: float


class JevDecisionRouter:
    """Optional TypeSafe Jev adapter for fast, typed intent decisions."""

    def __init__(
        self,
        api_key: str,
        model: str = "jev-latest",
        base_url: str = "https://api.typesafe.ai",
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("A TypeSafe Jev API key is required.")
        self.api_key = api_key
        self.model = model
        self.endpoint = f'{base_url.rstrip("/")}/v1/systemone'
        self.timeout_seconds = timeout_seconds

    def classify(
        self,
        query: str,
        conversation_context: str = "",
        memory_context: str = "",
    ) -> JevRoute:
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "state": {
                    "newest_user_message": query,
                    "recent_conversation": conversation_context[-12000:],
                    "known_user_facts": memory_context[-4000:],
                },
                "questions": {
                    "intent": {
                        "type": "choice",
                        "instructions": (
                            "Classify the newest user message for an autonomous research "
                            "assistant. Use conversation and user facts only as context."
                        ),
                        "criteria": {
                            "casual_chat": "Greetings, thanks, or social conversation.",
                            "simple_question": (
                                "Can be answered without current external information or "
                                "multi-source investigation."
                            ),
                            "current_information": (
                                "Depends on recent, changing, live, or time-sensitive facts."
                            ),
                            "research_request": (
                                "Asks for comparison, investigation, evidence, multiple "
                                "sources, recommendations, or a structured research report."
                            ),
                            "clarification_required": (
                                "Too vague or ambiguous to answer usefully."
                            ),
                        },
                    }
                },
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        answer = payload.get("answers", {}).get("intent", {})
        intent = str(answer.get("choice", "")).strip().lower()
        if intent not in JEV_INTENTS:
            raise ValueError("TypeSafe Jev returned an unsupported intent.")
        confidence = float(answer.get("confidence", 0.0))
        return JevRoute(intent=intent, confidence=max(0.0, min(1.0, confidence)))
