"""The reply of the local LLM mode: passages quoted from the knowledge base.

No text is generated. The reply quotes the retrieved passages that share the
most informative words with the question and says so. This is a demo mode: it
matches words, not meaning, and must not pass for a working LLM.

Knowledge gap rule. Each content word of the question gets a weight: a word
found in few of the retrieved passages weighs more than a word found in most of
them, and a word found in none weighs the most. The reply is grounded only when
the quoted passages cover at least half of that weight. A question about
something the documents never mention (a country, a service) fails the rule even
if the rest of its words are common. The rule cannot recognize a synonym, so it
errs toward a knowledge gap. A retrieval score alone decides nothing here.
"""

import math
from dataclasses import dataclass

from app.core.text import content_terms, question_terms
from app.models.enums import AnswerType
from app.services.chat.answering import (
    CLARIFICATION_TEXT,
    AnswerDraft,
    Passage,
    is_elliptical,
    knowledge_gap,
    make_citation,
    split_units,
)

MAX_QUOTES = 3
MIN_COVERAGE = 0.5
"""Share of the question's term weight that the quoted passages must cover."""
MIN_EXTRA_GAIN = 0.15
"""A second or third quote must add at least this share of the term weight."""
CONTEXT_WEIGHT = 0.5
"""Weight of terms from earlier visitor messages, relative to the new message."""
MIN_SCORE_PRIOR = 0.5
QUOTE_WINDOW_CHARS = 400
"""A quoted sentence or list item is extended with its neighbors up to this length."""

LOCAL_MODE_INTRO = "Here is what the documents say:"
LOCAL_MODE_NOTICE = (
    "Local demo mode: this reply quotes passages retrieved from the knowledge base. "
    "It was not written by an AI model."
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    passage_index: int
    position: int
    text: str
    is_row: bool
    body_terms: frozenset[str]
    all_terms: frozenset[str]
    """Terms of the unit and of the document title and headings above it."""


def _header_text(passage: Passage) -> str:
    return f"{passage.chunk.document_title} {passage.chunk.heading or ''}"


def _window(start: _Candidate, siblings: list[_Candidate], taken: set[int]) -> list[_Candidate]:
    """`start` with the units after it, then before it, while the quote stays short."""
    window = [start]
    if start.is_row:
        return window
    length = len(start.text)
    following = [unit for unit in siblings if unit.position > start.position]
    preceding = [unit for unit in reversed(siblings) if unit.position < start.position]
    for neighbors in (following, preceding):
        for unit in neighbors:
            if unit.is_row or unit.position in taken:
                break
            if length + 1 + len(unit.text) > QUOTE_WINDOW_CHARS:
                break
            window.append(unit)
            length += 1 + len(unit.text)
    return sorted(window, key=lambda unit: unit.position)


def compose_extractive_answer(
    question: str,
    context: str,
    passages: list[Passage],
    statistics_passages: list[Passage],
) -> AnswerDraft:
    """Build a reply from quotes.

    `question` is the new visitor message and `context` the earlier visitor
    messages a follow-up may depend on. `passages` are the candidates to quote,
    best first. `statistics_passages` is the wider retrieval result used to
    weigh the question's terms.
    """
    asked = set(question_terms(question))
    # A short follow-up ("The color one.") names its subject in earlier messages.
    hints = set(question_terms(context)) - asked if is_elliptical(question) else set()
    if not asked:
        asked, hints = hints, set()
    if not asked:
        return AnswerDraft(AnswerType.CLARIFICATION, CLARIFICATION_TEXT)
    if not passages:
        return knowledge_gap()

    term_sets = [
        frozenset(content_terms(f"{_header_text(passage)} {passage.text}"))
        for passage in statistics_passages
    ]

    def weight(term: str) -> float:
        frequency = sum(term in terms for terms in term_sets)
        return math.log(1.0 + len(term_sets) / (1.0 + frequency))

    weights = {term: weight(term) for term in asked | hints}
    total = sum(weights[term] for term in asked)

    by_passage: list[list[_Candidate]] = []
    for passage_index, passage in enumerate(passages):
        header_terms = frozenset(content_terms(_header_text(passage)))
        candidates: list[_Candidate] = []
        for position, piece in enumerate(split_units(passage.text)):
            body_terms = frozenset(content_terms(piece.text))
            candidates.append(
                _Candidate(
                    passage_index,
                    position,
                    piece.text,
                    piece.is_row,
                    body_terms,
                    body_terms | header_terms,
                )
            )
        by_passage.append(candidates)

    top_score = max(passage.chunk.score for passage in passages)
    covered: set[str] = set()
    quoted: dict[int, set[int]] = {}
    """Positions of the quoted units, by passage, in the order passages were first quoted."""
    for _ in range(MAX_QUOTES):
        best: tuple[tuple[float, float, int, int], _Candidate] | None = None
        for units in by_passage:
            for unit in units:
                if unit.position in quoted.get(unit.passage_index, ()):
                    continue
                asked_gain = sum(weights[term] for term in (unit.all_terms & asked) - covered)
                hint_gain = sum(weights[term] for term in (unit.body_terms & hints) - covered)
                if asked_gain + hint_gain <= 0 or (quoted and asked_gain < MIN_EXTRA_GAIN * total):
                    continue
                score = passages[unit.passage_index].chunk.score
                prior = max(MIN_SCORE_PRIOR, score / top_score) if top_score > 0 else 1.0
                body_gain = sum(weights[term] for term in (unit.body_terms & asked) - covered)
                key = (
                    (asked_gain + CONTEXT_WEIGHT * hint_gain) * prior,
                    body_gain,
                    -unit.passage_index,
                    -unit.position,
                )
                if best is None or key > best[0]:
                    best = (key, unit)
        if best is None:
            break
        start = best[1]
        taken = quoted.setdefault(start.passage_index, set())
        for unit in _window(start, by_passage[start.passage_index], taken):
            taken.add(unit.position)
            covered |= unit.all_terms & (asked | hints)

    coverage = sum(weights[term] for term in covered & asked) / total if total else 0.0
    if not quoted or coverage < MIN_COVERAGE:
        return knowledge_gap()

    lines: list[str] = []
    citations = []
    for number, (passage_index, positions) in enumerate(quoted.items(), start=1):
        quote = " ".join(
            unit.text for unit in by_passage[passage_index] if unit.position in positions
        )
        lines.append(f"- {quote} [{number}]")
        citations.append(make_citation(passages[passage_index], quote))
    text = "\n".join([LOCAL_MODE_INTRO, "", *lines, "", LOCAL_MODE_NOTICE])
    return AnswerDraft(AnswerType.GROUNDED, text, citations=citations)
