from __future__ import annotations

import html
import io
import re
from collections.abc import Iterable

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer


def markdown_bytes(markdown: str) -> bytes:
    return markdown.encode("utf-8")


def _inline_markup(text: str) -> str:
    safe = html.escape(text.strip())
    safe = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<link href="\2">\1</link>', safe)
    safe = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", safe)
    safe = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', safe)
    return safe


def _flush_bullets(story: list, bullets: list[str], body_style: ParagraphStyle) -> None:
    if not bullets:
        return
    story.append(
        ListFlowable(
            [ListItem(Paragraph(_inline_markup(item), body_style)) for item in bullets],
            bulletType="bullet",
            leftIndent=16,
        )
    )
    story.append(Spacer(1, 3 * mm))
    bullets.clear()


def pdf_bytes(markdown: str, title: str = "Research Report") -> bytes:
    """Render the report to a readable PDF without using a browser."""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=6,
    )
    story: list = []
    bullets: list[str] = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith(("- ", "* ")):
            bullets.append(line[2:].strip())
            continue
        _flush_bullets(story, bullets, body)
        if not line:
            story.append(Spacer(1, 2 * mm))
        elif line.startswith("### "):
            story.append(Paragraph(_inline_markup(line[4:]), styles["Heading3"]))
        elif line.startswith("## "):
            story.append(Paragraph(_inline_markup(line[3:]), styles["Heading2"]))
        elif line.startswith("# "):
            story.append(Paragraph(_inline_markup(line[2:]), styles["Title"]))
        elif re.match(r"^\d+\.\s+", line):
            story.append(Paragraph(_inline_markup(line), body))
        else:
            story.append(Paragraph(_inline_markup(line), body))
    _flush_bullets(story, bullets, body)
    document.build(story)
    return buffer.getvalue()

