import re
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path


class DocumentParseError(ValueError):
    """A local source could not be safely parsed into useful text."""


@dataclass(frozen=True, slots=True)
class DocumentSection:
    text: str
    page_number: int | None = None
    section_path: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    sections: tuple[DocumentSection, ...]


@dataclass(frozen=True, slots=True)
class TextChunk:
    text: str
    page_number: int | None
    section_path: str | None


class _VisibleHTMLParser(HTMLParser):
    _ignored_tags = {
        "aside",
        "footer",
        "nav",
        "noscript",
        "script",
        "style",
        "svg",
        "template",
    }
    _block_tags = {
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._ignored_tags:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag in self._block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag in self._block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n\n".join(line for line in lines if line)


def parse_document(content: bytes, media_type: str) -> ParsedDocument:
    """Extract text from one supported, already size-limited local document."""

    if media_type == "application/pdf":
        return _parse_pdf(content)
    if media_type == "text/html":
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParseError("HTML source must be UTF-8 encoded") from exc
        parser = _VisibleHTMLParser()
        try:
            parser.feed(decoded)
            parser.close()
        except Exception as exc:
            raise DocumentParseError("HTML source could not be parsed") from exc
        text = _normalize_text("".join(parser.parts))
        return _non_empty_document((DocumentSection(text=text),))
    if media_type in {"text/plain", "text/markdown"}:
        try:
            text = _normalize_text(content.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise DocumentParseError("text source must be UTF-8 encoded") from exc
        return _non_empty_document((DocumentSection(text=text),))
    raise DocumentParseError("unsupported knowledge source media type")


def _parse_pdf(content: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise DocumentParseError("encrypted PDF sources are not supported")
        sections_list: list[DocumentSection] = []
        for index, page in enumerate(reader.pages, start=1):
            text = _normalize_text(page.extract_text() or "")
            if text:
                sections_list.append(DocumentSection(text=text, page_number=index))
        sections = tuple(sections_list)
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("PDF source could not be parsed") from exc
    return _non_empty_document(sections)


def _non_empty_document(sections: tuple[DocumentSection, ...]) -> ParsedDocument:
    useful = tuple(section for section in sections if section.text.strip())
    if not useful:
        raise DocumentParseError("source contains no extractable text")
    return ParsedDocument(sections=useful)


def chunk_document(
    document: ParsedDocument,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 200,
) -> list[TextChunk]:
    """Create deterministic, bounded chunks while preferring natural boundaries."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")

    chunks: list[TextChunk] = []
    for section in document.sections:
        text = section.text.strip()
        start = 0
        while start < len(text):
            upper = min(start + max_chars, len(text))
            end = upper if upper == len(text) else _preferred_break(text, start, upper, max_chars)
            piece = text[start:end].strip()
            if piece:
                chunks.append(
                    TextChunk(
                        text=piece,
                        page_number=section.page_number,
                        section_path=section.section_path,
                    )
                )
            if end >= len(text):
                break
            next_start = max(start + 1, end - overlap_chars)
            while next_start > start and not text[next_start - 1].isspace():
                next_start -= 1
            if next_start <= start:
                next_start = end
            while next_start < len(text) and text[next_start].isspace():
                next_start += 1
            start = next_start
    if not chunks:
        raise DocumentParseError("source contains no chunkable text")
    return chunks


def _preferred_break(text: str, start: int, upper: int, max_chars: int) -> int:
    lower = start + max_chars // 2
    for marker, offset in (("\n\n", 2), (". ", 1), ("; ", 1), (" ", 0)):
        position = text.rfind(marker, lower, upper)
        if position >= lower:
            return position + offset
    return upper


def resolve_source_path(
    local_path: Path,
    *,
    data_dir: Path,
    project_root: Path,
) -> Path:
    """Resolve a manifest path and prove it remains inside the configured data directory."""

    root = project_root.resolve()
    allowed = (root / data_dir).resolve() if not data_dir.is_absolute() else data_dir.resolve()
    candidate = (root / local_path).resolve()
    if not candidate.is_relative_to(allowed):
        raise DocumentParseError("source path is outside the configured ATO data directory")
    return candidate


def read_source(path: Path, *, max_file_bytes: int) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise DocumentParseError("source file is missing or unreadable") from exc
    if not path.is_file():
        raise DocumentParseError("source path is not a regular file")
    if size > max_file_bytes:
        raise DocumentParseError("source file exceeds the configured size limit")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise DocumentParseError("source file is missing or unreadable") from exc
    if len(content) > max_file_bytes:
        raise DocumentParseError("source file exceeds the configured size limit")
    return content


def validate_extension(path: Path, media_type: str) -> None:
    supported = {
        "application/pdf": {".pdf"},
        "text/html": {".html", ".htm"},
        "text/plain": {".txt"},
        "text/markdown": {".md", ".markdown"},
    }
    if path.suffix.lower() not in supported[media_type]:
        raise DocumentParseError("source extension does not match its declared media type")
