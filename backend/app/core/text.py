"""Plain-text helpers: tokens, light stemming, sentence splitting.

Used by the local embedding provider and by the extractive reply of the local
LLM mode. Everything here is deterministic and works offline.
"""

import re

_TOKEN = re.compile(r"[a-z0-9]+(?:[-'\u2019][a-z0-9]+)*")
_VOWELS = frozenset("aeiouy")

STOPWORDS = frozenset(
    """
    a about above after again all also am an and any are as at be because been before being
    below between both but by can cannot could did do does doing down during each either else
    few for from further get got had has have having he her here hers him his how i if in into
    is it its just know let like may me might more most must my no nor not of off ok okay on
    once one only or other our ours out over own please same say shall she should so some such
    tell than thank thanks that the their theirs them then there these they this those through
    to too under until up us very want was we were what when where whether which while who whom
    whose why will with would yes you your yours hello hi hey
    dont doesnt didnt cant couldnt wont wouldnt shouldnt isnt arent wasnt werent havent hasnt
    hadnt im ive id ill youre youve youll theyre weve thats whats theres
    """.split()  # noqa: SIM905
)

_HOW_MODIFIERS = frozenset({"long", "much", "many", "often", "soon", "far", "fast", "big"})
"""Words that only shape a question after "how" ("how long", "how much")."""


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens.

    A product code keeps its parts together ("AB-120" and "AB120" both give
    "ab120"). Other hyphenated words are split ("third-party" gives "third",
    "party"), so both spellings match.
    """
    tokens: list[str] = []
    for match in _TOKEN.finditer(text.lower()):
        raw = match.group().replace("\u2019", "'")
        if raw.endswith("'s"):
            raw = raw[:-2]
        raw = raw.replace("'", "")
        if "-" not in raw:
            if raw:
                tokens.append(raw)
            continue
        parts = [part for part in raw.split("-") if part]
        if parts and parts[0].isalpha() and any(ch.isdigit() for ch in "".join(parts[1:])):
            tokens.append("".join(parts))
        else:
            tokens.extend(parts)
    return tokens


def stem(token: str) -> str:
    """A small suffix stemmer: plurals, -ing, -ed and a final -e.

    It only has to map the forms of one word to the same string; the result is
    not always a dictionary word.
    """
    if len(token) <= 3 or any(ch.isdigit() for ch in token):
        return token
    word = token
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        base = word[: -len(suffix)]
        if word.endswith(suffix) and len(base) >= 3 and _VOWELS & set(base):
            word = base
            if word[-1] == word[-2] and word[-1] not in "lsz":
                word = word[:-1]
            break
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def content_terms(text: str) -> list[str]:
    """Stemmed tokens without stopwords, in order, with repeats."""
    return [stem(token) for token in tokenize(text) if token not in STOPWORDS]


def question_terms(text: str) -> list[str]:
    """`content_terms` of a question, without the words that only shape it.

    "How long is the warranty?" asks about the warranty; "long" is not something
    a passage has to mention.
    """
    terms: list[str] = []
    previous = ""
    for token in tokenize(text):
        is_filler = token in STOPWORDS or (previous == "how" and token in _HOW_MODIFIERS)
        previous = token
        if not is_filler:
            terms.append(stem(token))
    return terms


_SENTENCE_END = re.compile(r"[.!?][\"')\]]*(\s+)(?=[\"'(\[]*[A-Z0-9$])")
_ABBREVIATION = re.compile(
    r"(?:\b(?:[A-Za-z]\.){2,}|\b(?:Inc|Ltd|Co|No|Mr|Mrs|Ms|Dr|vs|approx|etc)\.)$"
)


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences without breaking after "p.m." or "e.g."."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        candidate = text[start : match.start(1)].strip()
        if _ABBREVIATION.search(candidate):
            continue
        if candidate:
            sentences.append(candidate)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())
