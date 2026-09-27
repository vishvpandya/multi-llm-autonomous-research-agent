from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import Source


class ReportValidationError(ValueError):
    pass


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ReportValidationError(f"{key} must be a non-empty string")
    return value


def _required_list(payload: dict[str, Any], key: str) -> list[str]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        raise ReportValidationError(f"{key} must be a list")
    values = [str(item).strip() for item in raw if str(item).strip()]
    if not values:
        raise ReportValidationError(f"{key} must contain at least one item")
    return values


@dataclass(frozen=True, slots=True)
class StructuredReportContent:
    title: str
    executive_summary: str
    key_points: list[str]
    important_findings: list[str]
    actionable_insights: list[str]
    limitations: list[str]
    used_source_ids: list[str]

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], source_count: int
    ) -> "StructuredReportContent":
        source_ids = _required_list(payload, "used_source_ids")
        normalized_ids: list[str] = []
        for value in source_ids:
            match = re.fullmatch(r"\[?S(\d+)\]?", value.strip(), re.IGNORECASE)
            if not match:
                raise ReportValidationError(f"Invalid source ID: {value}")
            index = int(match.group(1))
            if index < 1 or index > source_count:
                raise ReportValidationError(f"Unknown source ID: S{index}")
            source_id = f"S{index}"
            if source_id not in normalized_ids:
                normalized_ids.append(source_id)
        return cls(
            title=_required_text(payload, "title"),
            executive_summary=_required_text(payload, "executive_summary"),
            key_points=_required_list(payload, "key_points"),
            important_findings=_required_list(payload, "important_findings"),
            actionable_insights=_required_list(payload, "actionable_insights"),
            limitations=_required_list(payload, "limitations"),
            used_source_ids=normalized_ids,
        )

    def to_markdown(self, sources: list[Source]) -> str:
        def bullets(values: list[str]) -> str:
            return "\n".join(f"- {value}" for value in values)

        references = []
        for source_id in self.used_source_ids:
            index = int(source_id[1:])
            references.append(f"- [{source_id}] {sources[index - 1].title}")
        reference_text = "\n".join(references)
        return "\n\n".join(
            (
                f"# Research Summary: {self.title}",
                f"## Executive Summary\n\n{self.executive_summary}",
                f"## Key Points\n\n{bullets(self.key_points)}",
                f"## Important Findings\n\n{bullets(self.important_findings)}",
                f"## Actionable Insights\n\n{bullets(self.actionable_insights)}",
                f"## Limitations\n\n{bullets(self.limitations)}",
                f"## References\n\n{reference_text}",
            )
        )
