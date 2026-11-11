"""Shared pieces of an assistant reply: passages, drafts, fixed wording, excerpts."""

import re
from dataclasses import dataclass, field
from itertools import zip_longest

from app.core.text import collapse_whitespace, content_terms, question_terms, split_sentences
from app.models.enums import AnswerType
from app.schemas.conversations import Citation
from app.services.documents.retrieval import RetrievedChunk

MAX_EXCERPT_CHARS = 500
SHORT_PASSAGE_CHARS = 350
"""A passage or paragraph up to this length is quoted whole, not sentence by sentence."""

ELLIPTICAL_TERMS = 2
"""A message with fewer content terms than this leans on the earlier messages."""

KNOWLEDGE_GAP_TEXT = (
    "I could not find an answer to that in the company's documents, and I do not want to "
    "guess. I can pass your question to a member of the team. Would you like a person to "
    "follow up with you?"
)
HANDOFF_OFFER_TEXT = (
    "I can pass your question to a member of the team. Would you like a person to follow up?"
)
CLARIFICATION_TEXT = (
    "Could you tell me a bit more about what you need? For example, name the product or "
    "the policy your question is about."
)
REFUSAL_TEXT = (
    "I can't help with that request. I can answer questions about the company's products "
    "and policies from its documents, and help you prepare a purchase inquiry."
)

_HANDOFF_WORDS = re.compile(
    r"\b(human|person|people|team|colleague|agent|representative|someone|staff)\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class Passage:
    """A retrieved chunk and the text an answer may use from it."""

    chunk: RetrievedChunk
    text: str
    """The chunk content without blocks that give instructions to the assistant."""


@dataclass(frozen=True, slots=True)
class AnswerDraft:
    answer_type: AnswerType
    text: str
    citations: list[Citation] = field(default_factory=list)
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    llm_time_ms: int | None = None
    note: str | None = None


def is_elliptical(message: str) -> bool:
    """True for a short follow-up such as "The color one." or "What about returns?".

    Such a message names its subject in the earlier messages, so they weigh
    more in the search and in the choice of quotes.
    """
    return len(set(question_terms(message))) < ELLIPTICAL_TERMS


def knowledge_gap(note: str | None = None) -> AnswerDraft:
    return AnswerDraft(AnswerType.KNOWLEDGE_GAP, KNOWLEDGE_GAP_TEXT, note=note)


def with_handoff_offer(text: str) -> str:
    """Make sure a knowledge-gap reply offers a human handoff."""
    return text if _HANDOFF_WORDS.search(text) else f"{text.rstrip()} {HANDOFF_OFFER_TEXT}"


def make_citation(passage: Passage, excerpt: str) -> Citation:
    chunk = passage.chunk
    return Citation(
        document_id=chunk.document_id,
        document_title=chunk.document_title,
        document_version_id=chunk.document_version_id,
        version_number=chunk.version_number,
        version_label=chunk.version_label,
        chunk_id=chunk.chunk_id,
        page_number=chunk.page_number,
        section=chunk.heading,
        excerpt=truncate(excerpt, MAX_EXCERPT_CHARS),
        score=round(chunk.score, 4),
    )


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text.rfind(" ", 0, max_chars - 1)
    return text[: cut if cut > 0 else max_chars - 1].rstrip(" ,;:") + "…"


# --- Quotable units of a passage ----------------------------------------------

_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+(.*)$")
_TABLE_DIVIDER_CELL = re.compile(r"^:?-{3,}:?$")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MARKDOWN_EMPHASIS = re.compile(r"(\*\*|__|`)")


def plain(text: str) -> str:
    """Markdown inline markup removed, whitespace collapsed."""
    text = _MARKDOWN_LINK.sub(r"\1", text)
    return collapse_whitespace(_MARKDOWN_EMPHASIS.sub("", text))


def _table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") or " | " in stripped):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


@dataclass(frozen=True, slots=True)
class Unit:
    """A quotable piece of a passage."""

    text: str
    is_row: bool = False
    """A table row. It reads on its own; its neighbors are other rows, not context."""


def _paragraph_units(lines: list[str]) -> list[Unit]:
    joined = plain(" ".join(lines))
    if not joined:
        return []
    sentences = [joined] if len(joined) <= SHORT_PASSAGE_CHARS else split_sentences(joined)
    return [Unit(sentence) for sentence in sentences]


def _row_unit(header: list[str], cells: list[str]) -> Unit:
    pairs = zip_longest(header, cells, fillvalue="")
    text = "; ".join(f"{name}: {cell}" if name else cell for name, cell in pairs if cell)
    return Unit(plain(text), is_row=True)


def split_units(text: str) -> list[Unit]:
    """Split passage text into quotable units: list items, table rows, paragraphs.

    A table row is written as "Header: cell; Header: cell", so it can be read
    without the table around it. A long paragraph is split into sentences. A
    short passage of plain paragraphs stays whole.
    """
    units: list[Unit] = []
    structured = False
    for block in text.split("\n\n"):
        header: list[str] | None = None
        paragraph: list[str] = []
        for line in block.splitlines():
            item = None if line.lstrip().startswith("|") else _LIST_ITEM.match(line)
            cells = None if item else _table_cells(line)
            if item is None and cells is None:
                if line.strip():
                    paragraph.append(line.strip())
                continue
            units.extend(_paragraph_units(paragraph))
            paragraph = []
            structured = True
            if item is not None:
                units.append(Unit(plain(item.group(1))))
            elif cells is not None and not all(_TABLE_DIVIDER_CELL.match(cell) for cell in cells):
                if header is None:
                    header = cells
                else:
                    units.append(_row_unit(header, cells))
        units.extend(_paragraph_units(paragraph))
    units = [unit for unit in units if unit.text]
    if not structured and len(units) > 1:
        whole = " ".join(unit.text for unit in units)
        if len(whole) <= SHORT_PASSAGE_CHARS:
            return [Unit(whole)]
    return units


def best_excerpt(passage_text: str, terms: set[str], *, max_units: int = 2) -> str:
    """The units of a passage that share the most terms with `terms`, in document order."""
    units = [unit.text for unit in split_units(passage_text)]
    if not units:
        return ""
    overlap = [len(terms & set(content_terms(unit))) for unit in units]
    ranked = sorted(range(len(units)), key=lambda index: (-overlap[index], index))
    chosen = sorted(ranked[:max_units]) if overlap[ranked[0]] else [0]
    return " ".join(units[index] for index in chosen)
