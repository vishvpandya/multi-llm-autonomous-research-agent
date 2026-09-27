from research_agent.exporters import markdown_bytes, pdf_bytes


def test_markdown_export() -> None:
    assert markdown_bytes("# Report") == b"# Report"


def test_pdf_export() -> None:
    result = pdf_bytes("# Report\n\n## Key Points\n\n- One useful fact")
    assert result.startswith(b"%PDF")
    assert len(result) > 500

