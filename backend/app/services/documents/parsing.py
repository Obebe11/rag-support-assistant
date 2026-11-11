"""Turn an uploaded file into titled sections of text.

Two formats are supported: Markdown and PDF with a text layer. There is no OCR:
a scanned PDF fails with `DocumentParseError`.

A section keeps what a citation needs: the heading path for Markdown and PDF,
and the 1-based page number for PDF. The document title (the first top-level
heading) is not part of the path, so the last item of a path is always the
exact heading text of the section.
"""

import io
import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from typing import Any

from pypdf import PageObject, PdfReader
from pypdf.errors import PyPdfError

MARKDOWN_MEDIA_TYPE = "text/markdown"
PDF_MEDIA_TYPE = "application/pdf"

_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
_MARKDOWN_CONTENT_TYPES = frozenset({"text/markdown", "text/x-markdown"})
_PDF_MAGIC = b"%PDF-"


class DocumentFormat(StrEnum):
    MARKDOWN = "markdown"
    PDF = "pdf"

    @property
    def media_type(self) -> str:
        return MARKDOWN_MEDIA_TYPE if self is DocumentFormat.MARKDOWN else PDF_MEDIA_TYPE


class DocumentParseError(Exception):
    """The file cannot be read as a supported document. Retrying will not help."""


@dataclass(frozen=True, slots=True)
class Section:
    heading_path: tuple[str, ...]
    """Headings above the text, outermost first, without the document title."""
    page_number: int | None
    """1-based page for PDF sources; None for Markdown."""
    blocks: tuple[str, ...]
    """Paragraphs, lists and tables, in reading order."""


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    title: str | None
    page_count: int | None
    sections: tuple[Section, ...]


def detect_format(filename: str, content_type: str | None, data: bytes) -> DocumentFormat | None:
    """Decide the format from the content first, then from the name and declared type."""
    if data.lstrip()[: len(_PDF_MAGIC)] == _PDF_MAGIC:
        return DocumentFormat.PDF
    suffix = PurePath(filename).suffix.lower()
    declared = (content_type or "").split(";")[0].strip().lower()
    if suffix in _MARKDOWN_EXTENSIONS or (not suffix and declared in _MARKDOWN_CONTENT_TYPES):
        return DocumentFormat.MARKDOWN
    return None


def media_type_format(media_type: str) -> DocumentFormat:
    if media_type == PDF_MEDIA_TYPE:
        return DocumentFormat.PDF
    if media_type == MARKDOWN_MEDIA_TYPE:
        return DocumentFormat.MARKDOWN
    raise DocumentParseError(f"Unsupported media type: {media_type}.")


def parse_document(document_format: DocumentFormat, data: bytes) -> ParsedDocument:
    if document_format is DocumentFormat.PDF:
        return parse_pdf(data)
    return parse_markdown(data)


class _SectionBuilder:
    """Collects blocks under the current heading path."""

    def __init__(self) -> None:
        self.title: str | None = None
        self.sections: list[Section] = []
        self._headings: list[tuple[int, str]] = []
        self._seen_heading = False
        self._blocks: list[str] = []

    def add_block(self, block: str) -> None:
        if block.strip():
            self._blocks.append(block)

    def end_section(self, page_number: int | None) -> None:
        if self._blocks:
            path = tuple(heading for _, heading in self._headings)
            self.sections.append(
                Section(heading_path=path, page_number=page_number, blocks=tuple(self._blocks))
            )
            self._blocks = []

    def start_heading(self, level: int, heading: str) -> None:
        """Open a heading. The first top-level heading is the document title."""
        if level == 1 and not self._seen_heading:
            self.title = heading
        else:
            while self._headings and self._headings[-1][0] >= level:
                self._headings.pop()
            self._headings.append((level, heading))
        self._seen_heading = True


# --- Markdown ---------------------------------------------------------------

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def decode_markdown(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("The Markdown file is not valid UTF-8 text.") from exc


def parse_markdown(data: bytes) -> ParsedDocument:
    # HTML comments are not part of the rendered document, so they are not indexed.
    text = _HTML_COMMENT.sub("", decode_markdown(data))
    builder = _SectionBuilder()
    block_lines: list[str] = []
    fence: str | None = None

    def flush_block() -> None:
        builder.add_block("\n".join(block_lines))
        block_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        fence_match = _FENCE.match(line)
        if fence is not None:
            block_lines.append(line)
            # A fence closes with at least as many of the same character and nothing after.
            if (
                fence_match
                and fence_match.group(1).startswith(fence)
                and not fence_match.group(2).strip()
            ):
                fence = None
            continue
        if fence_match:
            fence = fence_match.group(1)
            block_lines.append(line)
            continue
        heading_match = _ATX_HEADING.match(line)
        if heading_match:
            flush_block()
            builder.end_section(None)
            builder.start_heading(len(heading_match.group(1)), heading_match.group(2).strip())
        elif line.strip():
            block_lines.append(line)
        else:
            flush_block()
    flush_block()
    builder.end_section(None)
    if not builder.sections:
        raise DocumentParseError("The Markdown file has no text to index.")
    return ParsedDocument(title=builder.title, page_count=None, sections=tuple(builder.sections))


# --- PDF --------------------------------------------------------------------

_HEADING_SIZE_RATIO = 1.15
_MAX_HEADING_LENGTH = 150
_LIST_MARKER = re.compile(r"^([-\u2022\u2013*]|\d{1,3}[.)])\s+(.*)$")
_CELL = re.compile(r"\S+(?:\s{1,2}\S+)*")
_DIGITS = re.compile(r"\d+")
_RUNNING_ZONE_LINES = 3
"""How many lines at each end of a page may be a running header or footer."""


@dataclass(frozen=True, slots=True)
class _Fragment:
    """A text run as the page draws it."""

    text: str
    font_size: float
    bold: bool


@dataclass(frozen=True, slots=True)
class _PdfPage:
    lines: list[str]
    fragments: list[_Fragment]


def _collapse(text: str) -> str:
    return " ".join(text.split())


def open_pdf(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentParseError("The PDF is password-protected.")
        len(reader.pages)
    except DocumentParseError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError) as exc:
        raise DocumentParseError("The file is not a readable PDF.") from exc
    return reader


def pdf_metadata_title(reader: PdfReader) -> str | None:
    try:
        title = reader.metadata.title if reader.metadata else None
    except (PyPdfError, ValueError, KeyError):
        return None
    return _collapse(title) or None if isinstance(title, str) else None


def _read_pdf_page(page: PageObject) -> _PdfPage:
    fragments: list[_Fragment] = []

    def visit(text: str, _cm: Any, _tm: Any, font: Any, font_size: float) -> None:
        collapsed = _collapse(text)
        if collapsed:
            font_name = str(font.get("/BaseFont", "")) if isinstance(font, dict) else ""
            fragments.append(
                _Fragment(collapsed, round(float(font_size), 1), "bold" in font_name.lower())
            )

    try:
        # Layout mode keeps the cells of a table row on one line. The plain pass
        # only collects fonts, which tell headings from body text.
        layout = page.extract_text(extraction_mode="layout")
        page.extract_text(visitor_text=visit)
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        raise DocumentParseError("The text of a PDF page cannot be extracted.") from exc
    return _PdfPage(lines=layout.splitlines(), fragments=fragments)


def _running_lines(pages: list[_PdfPage]) -> set[str]:
    """Lines at the top or bottom of every page, such as a header or "Page 1 of 3".

    A sentence that every page repeats in its body is text, not a running line.
    """
    if len(pages) < 2:
        return set()
    seen: Counter[str] = Counter()
    for page in pages:
        lines = [_DIGITS.sub("#", _collapse(line)) for line in page.lines if line.strip()]
        seen.update({*lines[:_RUNNING_ZONE_LINES], *lines[-_RUNNING_ZONE_LINES:]})
    return {line for line, count in seen.items() if count == len(pages)}


def _heading_levels(pages: list[_PdfPage]) -> dict[float, int]:
    """Map heading font sizes to levels: the largest size is level 1.

    A heading is set clearly larger than the body text, or in bold and larger
    than the body text. The body size is the size most of the text uses.
    """
    weight: Counter[float] = Counter()
    bold_sizes: set[float] = set()
    for page in pages:
        for fragment in page.fragments:
            weight[fragment.font_size] += len(fragment.text)
            if fragment.bold:
                bold_sizes.add(fragment.font_size)
    if not weight:
        return {}
    body_size = weight.most_common(1)[0][0]
    sizes = sorted(
        (
            size
            for size in weight
            if size >= body_size * _HEADING_SIZE_RATIO or (size > body_size and size in bold_sizes)
        ),
        reverse=True,
    )
    return {size: level for level, size in enumerate(sizes, start=1)}


class _PdfTable:
    """Rows of a table rebuilt from layout lines.

    The first line gives the column positions. A later line that fills every
    column starts a new row; a line that fills only some columns is the wrapped
    rest of the row above it and is joined to the cells it sits under.
    """

    def __init__(self, cells: list[tuple[int, str]]) -> None:
        self._starts = [start for start, _ in cells]
        self.rows: list[list[str]] = [[text for _, text in cells]]

    def add(self, cells: list[tuple[int, str]]) -> None:
        columns = [
            min(range(len(self._starts)), key=lambda index: abs(self._starts[index] - start))
            for start, _ in cells
        ]
        starts_row = len(set(columns)) == len(self._starts)
        row = [""] * len(self._starts) if starts_row else self.rows[-1]
        for column, (_, text) in zip(columns, cells, strict=True):
            row[column] = f"{row[column]} {text}".strip()
        if starts_row:
            self.rows.append(row)

    def render(self) -> list[str]:
        return [" | ".join(row) for row in self.rows]


def _normalize_pdf_block(lines: list[str]) -> str:
    """Rebuild a block: join wrapped lines, mark list items and table cells."""
    output: list[str | _PdfTable] = []
    for raw in lines:
        line = raw.strip()
        marker = _LIST_MARKER.match(line)
        cells = [(match.start(), match.group()) for match in _CELL.finditer(raw)]
        last = output[-1] if output else None
        if marker:
            bullet = marker.group(1) if marker.group(1)[0].isdigit() else "-"
            output.append(f"{bullet} {_collapse(marker.group(2))}")
        elif isinstance(last, _PdfTable):
            last.add(cells)
        elif len(cells) >= 2:
            output.append(_PdfTable(cells))
        elif isinstance(last, str):
            output[-1] = f"{last} {_collapse(line)}"
        else:
            output.append(_collapse(line))
    rendered: list[str] = []
    for item in output:
        rendered.extend(item.render() if isinstance(item, _PdfTable) else [item])
    return "\n".join(rendered)


def parse_pdf(data: bytes) -> ParsedDocument:
    reader = open_pdf(data)
    pages = [_read_pdf_page(page) for page in reader.pages]
    if not any(page.fragments for page in pages):
        raise DocumentParseError("The PDF has no text layer. Scanned documents are not supported.")

    running = _running_lines(pages)
    levels = _heading_levels(pages)
    builder = _SectionBuilder()
    block_lines: list[str] = []

    def flush_block() -> None:
        if block_lines:
            builder.add_block(_normalize_pdf_block(block_lines))
            block_lines.clear()

    for page_number, page in enumerate(pages, start=1):
        heading_level = {
            fragment.text: levels[fragment.font_size]
            for fragment in page.fragments
            if fragment.font_size in levels
        }
        for line in page.lines:
            collapsed = _collapse(line)
            if not collapsed:
                flush_block()
            elif _DIGITS.sub("#", collapsed) in running:
                continue
            elif collapsed in heading_level and len(collapsed) <= _MAX_HEADING_LENGTH:
                flush_block()
                builder.end_section(page_number)
                builder.start_heading(heading_level[collapsed], collapsed)
            else:
                block_lines.append(line)
        # A section that continues on the next page becomes a new section there,
        # so every piece of text keeps its own page number.
        flush_block()
        builder.end_section(page_number)

    if not builder.sections:
        raise DocumentParseError("The PDF has no text to index.")
    return ParsedDocument(
        title=builder.title or pdf_metadata_title(reader),
        page_count=len(pages),
        sections=tuple(builder.sections),
    )


# --- Title for a new upload ---------------------------------------------------


def find_title(document_format: DocumentFormat, data: bytes) -> str | None:
    """The title stated by the file: the first top-level heading, or PDF metadata.

    Raises `DocumentParseError` when the file cannot be opened at all, so a
    broken upload is rejected before it is stored.
    """
    if document_format is DocumentFormat.MARKDOWN:
        text = _HTML_COMMENT.sub("", decode_markdown(data))
        if not text.strip():
            raise DocumentParseError("The Markdown file is empty.")
        for line in text.splitlines():
            match = _ATX_HEADING.match(line)
            if match:
                return match.group(2).strip() if len(match.group(1)) == 1 else None
        return None
    return pdf_metadata_title(open_pdf(data))
