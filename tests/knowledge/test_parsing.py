import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sortax.knowledge.parsing import (
    DocumentParseError,
    chunk_document,
    parse_document,
    resolve_source_path,
)


def test_html_parser_removes_non_visible_content_and_chunks_deterministically() -> None:
    content = b"""
        <html><head><style>.hidden {display:none}</style><script>ignore()</script></head>
        <body><h1>Working from home</h1><p>Claim only eligible expenses.</p></body></html>
    """

    document = parse_document(content, "text/html")
    first = chunk_document(document, max_chars=30, overlap_chars=5)
    second = chunk_document(document, max_chars=30, overlap_chars=5)

    assert first == second
    assert all(len(chunk.text) <= 30 for chunk in first)
    assert "ignore" not in " ".join(chunk.text for chunk in first)
    assert "eligible expenses" in " ".join(chunk.text for chunk in first)


def test_pdf_parser_preserves_page_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        SimpleNamespace(extract_text=lambda: "First page"),
        SimpleNamespace(extract_text=lambda: "Second page"),
    ]
    reader = SimpleNamespace(is_encrypted=False, pages=pages)
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _stream: reader))

    document = parse_document(b"fake PDF", "application/pdf")

    assert [(section.text, section.page_number) for section in document.sections] == [
        ("First page", 1),
        ("Second page", 2),
    ]


def test_source_path_must_remain_in_data_directory(tmp_path: Path) -> None:
    with pytest.raises(DocumentParseError, match="outside"):
        resolve_source_path(
            Path("other/source.html"),
            data_dir=Path("data/ato"),
            project_root=tmp_path,
        )
