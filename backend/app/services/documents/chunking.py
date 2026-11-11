"""Split parsed sections into retrievable chunks.

A chunk never crosses a section, so it always has one heading path and, for a
PDF, one page number. A long section is split between blocks; a block that is
still too long is split between lines, with the header of a table repeated, and
a long line between sentences.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from app.core.text import split_sentences
from app.services.documents.parsing import ParsedDocument, Section

MAX_CHUNK_CHARS = 1200
HEADING_SEPARATOR = " > "

_DIVIDER_CELL = re.compile(r":?-{3,}:?")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    content: str
    heading: str | None
    """Heading path joined with " > ", without the document title."""
    page_number: int | None


def embedding_text(title: str, chunk: ChunkDraft) -> str:
    """What is embedded for a chunk: its text under the document and section titles.

    A short passage such as "1 year" means little without the headings above it.
    """
    header = "\n".join(part for part in (title, chunk.heading) if part)
    return f"{header}\n\n{chunk.content}" if header else chunk.content


def build_chunks(document: ParsedDocument, *, max_chars: int = MAX_CHUNK_CHARS) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for section in document.sections:
        heading = HEADING_SEPARATOR.join(section.heading_path) or None
        for content in _pack_section(section, max_chars):
            chunks.append(
                ChunkDraft(content=content, heading=heading, page_number=section.page_number)
            )
    return chunks


def _pack_section(section: Section, max_chars: int) -> Iterator[str]:
    pieces: list[str] = []
    for block in section.blocks:
        pieces.extend(_split_block(block, max_chars))
    yield from _pack(pieces, "\n\n", max_chars)


def _pack(pieces: Iterable[str], separator: str, max_chars: int, prefix: str = "") -> Iterator[str]:
    """Join pieces greedily into strings of at most `max_chars`.

    `prefix` (a table header) opens every string.
    """
    current = prefix
    filled = False
    for piece in pieces:
        candidate = f"{current}{separator}{piece}" if current else piece
        if filled and len(candidate) > max_chars:
            yield current
            current = f"{prefix}{separator}{piece}" if prefix else piece
        else:
            current = candidate
        filled = True
    if filled:
        yield current


def _split_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    lines = block.splitlines()
    if len(lines) > 1:
        prefix = "\n".join(_table_header(lines))
        if len(prefix) > max_chars // 2:
            # Too long to repeat: the header is split like any other line.
            prefix = ""
        body = lines[len(prefix.splitlines()) :]
        # Every string starts with the header, so a row gets what is left.
        room = max_chars - len(prefix) - 1 if prefix else max_chars
        pieces: list[str] = []
        for line in body:
            pieces.extend(_split_line(line, room))
        return list(_pack(pieces, "\n", max_chars, prefix=prefix))
    return _split_line(block, max_chars)


def _table_header(lines: list[str]) -> list[str]:
    """The rows to repeat when a table is split: its header and divider."""
    if len(lines) > 2 and _is_table_divider(lines[1]):
        return lines[:2]
    if " | " in lines[0] and all(" | " in line for line in lines[1:]):
        return lines[:1]
    return []


def _is_table_divider(line: str) -> bool:
    """True for the second row of a Markdown table, such as `| --- | :---: |`."""
    cells = line.strip().strip("|").split("|")
    return all(_DIVIDER_CELL.fullmatch(cell.strip()) for cell in cells)


def _split_line(line: str, max_chars: int) -> list[str]:
    if len(line) <= max_chars:
        return [line]
    pieces: list[str] = []
    for sentence in split_sentences(line):
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            pieces.append(sentence[:cut].rstrip())
            sentence = sentence[cut:].lstrip()
        if sentence:
            pieces.append(sentence)
    return list(_pack(pieces, " ", max_chars))
