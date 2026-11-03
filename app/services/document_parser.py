import io
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

MAX_SOURCE_BYTES = 20 * 1024 * 1024
URL_TIMEOUT_SECONDS = 30
_CONTENT_TYPES = {
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "text/html": ".html",
    "application/json": ".json",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


class DocumentParseError(Exception):
    pass


class _HTMLText(HTMLParser):
    _skip = {"script", "style", "noscript", "head", "svg"}
    _breaks = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "section"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._skip:
            self._skip_depth += 1
        elif tag in self._breaks:
            self.parts.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag):
        if tag in self._skip and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def _text(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


def _html(data: bytes) -> str:
    parser = _HTMLText()
    parser.feed(_text(data))
    return "".join(parser.parts)


def _pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _docx(data: bytes) -> str:
    lines = []
    for block in Document(io.BytesIO(data)).iter_inner_content():
        if hasattr(block, "rows"):
            lines.extend(" | ".join(cell.text.strip() for cell in row.cells) for row in block.rows)
        elif block.text.strip():
            style = block.style.name if block.style is not None else ""
            lines.append(f"- {block.text}" if style.startswith("List") else block.text)
    return "\n".join(lines)


def _xlsx(data: bytes) -> str:
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for sheet in workbook.worksheets:
        lines.append(f"## {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            if any(value is not None for value in row):
                lines.append(" | ".join("" if value is None else str(value) for value in row))
    workbook.close()
    return "\n".join(lines)


def _pptx(data: bytes) -> str:
    lines = []
    for number, slide in enumerate(Presentation(io.BytesIO(data)).slides, start=1):
        lines.append(f"## Slide {number}")
        lines.extend(shape.text_frame.text for shape in slide.shapes if shape.has_text_frame)
    return "\n".join(lines)


_PARSERS = {
    ".txt": _text, ".md": _text, ".log": _text, ".csv": _text, ".json": _text,
    ".yaml": _text, ".yml": _text, ".html": _html, ".htm": _html,
    ".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx,
}
SUPPORTED_EXTENSIONS = frozenset(_PARSERS)


def is_url(source: str) -> bool:
    return urlparse(source).scheme in {"http", "https"}


def source_extension(source: str) -> str:
    path = urlparse(source).path if is_url(source) else source
    return os.path.splitext(path)[1].lower()


def _fetch(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "runbook-ingest/1.0"})
    with urlopen(request, timeout=URL_TIMEOUT_SECONDS) as response:
        data = response.read(MAX_SOURCE_BYTES + 1)
        content_type = response.headers.get_content_type()
    extension = source_extension(url)
    if extension not in _PARSERS:
        extension = _CONTENT_TYPES.get(content_type, "")
    return data, extension


def _read_file(path: str) -> tuple[bytes, str]:
    if os.path.getsize(path) > MAX_SOURCE_BYTES:
        raise DocumentParseError(f"{path} exceeds {MAX_SOURCE_BYTES} bytes")
    with open(path, "rb") as file_handle:
        return file_handle.read(), source_extension(path)


def parse_source(source: str) -> str:
    """Return plain text from a local file or http(s) URL."""
    data, extension = _fetch(source) if is_url(source) else _read_file(source)
    if len(data) > MAX_SOURCE_BYTES:
        raise DocumentParseError(f"{source} exceeds {MAX_SOURCE_BYTES} bytes")
    parser = _PARSERS.get(extension)
    if parser is None:
        raise DocumentParseError(
            f"Unsupported format for {source}; supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    try:
        text = parser(data)
    except Exception as exc:
        raise DocumentParseError(f"Could not parse {source}: {exc}") from exc
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise DocumentParseError(f"No extractable text in {source} (scanned PDFs/images need OCR first)")
    return text
