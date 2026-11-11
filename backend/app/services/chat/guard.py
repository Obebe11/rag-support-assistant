"""Deterministic guards against instruction override.

Two different things are guarded:

- A **visitor message** that tries to change the assistant's role is declined
  before any retrieval or LLM call (`is_instruction_override`).
- **Document text** is data. A passage that addresses the assistant with
  instructions is removed from the material an answer is built from
  (`strip_embedded_instructions`), in local mode and in LLM mode alike.

The patterns catch common, explicit attempts. They are a first line of defense,
not proof against every phrasing: in LLM mode the system prompt carries the
same rules.
"""

import re

_FLAGS = re.IGNORECASE

_OVERRIDE = (
    r"\b(ignore|disregard|forget|override|bypass)\b[^.?!\n]{0,40}"
    r"\b(previous|prior|earlier|above|all|your|system|original|initial)\b[^.?!\n]{0,30}"
    r"\b(instructions?|prompts?|rules|guidelines|directions)\b"
)
"""Telling the reader to drop its instructions. "Ignore the assembly instructions" is not it."""

_VISITOR_OVERRIDE_PATTERNS = tuple(
    re.compile(pattern, _FLAGS)
    for pattern in (
        # Overriding the instructions.
        _OVERRIDE,
        # Extracting the instructions. "Your instructions for returning an item" is a question.
        r"\b(system|hidden)\s+(prompts?|instructions?)\b",
        r"\byour\s+(initial|original|developer|internal|secret)\s+(prompts?|instructions?)\b",
        r"\b(reveal|show|print|repeat|display|output|share|tell)\b[^.?!\n]{0,40}"
        r"\byour\s+(instructions|prompt)\b"
        r"(?=\s*($|[.?!,;:]|(please|word|verbatim|exactly|and|now|in\s+full|to\s+me)\b))",
        r"\b(instructions|rules|prompt)\s+you\s+(were|have been|are)\s+given\b",
        # Changing the role. A device can have a maintenance mode; the assistant cannot.
        r"\byou\s+are\s+now\s+(an?|the|free|allowed|unrestricted|no\s+longer|not\s+bound)\b",
        r"\byou\s+are\s+(now\s+)?in\s+\w+\s+mode\b",
        r"\b(developer|unrestricted|jailbreak|god)\s+mode\b",
        r"\bpretend\s+(to\s+be|you\s+are|that\s+you)\b",
        # Dictating the reply. "Say exactly how long it takes" is a question.
        r"\b(reply|respond|answer|say|write|output|repeat)\b[^.?!\n]{0,30}"
        r"\b(exactly|verbatim|word\s+for\s+word)\s*"
        r"(this|these|the\s+following|as\s+follows|what\s+i|:?\s*[\"'\u201c\u2018])",
        r"\b(repeat|say|write|output)\s+(this|these\s+words|the\s+following)\b[^.?!\n]{0,60}"
        r"\b(exactly|verbatim|word\s+for\s+word)\b",
        r"\brepeat\s+after\s+me\b",
        # Changing the knowledge base through the chat.
        r"\b(delete|remove|erase|replace|rewrite|overwrite|change|update|edit|modify)\b"
        r"[^.?!,\n]{0,60}\b(knowledge\s+base|your\s+(documents?|sources))\b",
    )
)

_ASSISTANT = r"(ai|a\.i\.|automated|virtual|chat|digital)\s+(assistant|agent|bot)s?"
_EMBEDDED_INSTRUCTION_PATTERNS = tuple(
    re.compile(pattern, _FLAGS)
    for pattern in (
        # Text that overrides instructions.
        _OVERRIDE,
        r"\b(instructions|rules|prompt)\s+you\s+(were|have been|are)\s+given\b",
        r"\bdo\s+not\s+(mention|reveal|disclose)\s+this\s+(message|note|instruction)\b",
        r"\bsystem\s+prompt\b",
        # Text addressed to the assistant.
        rf"\b(for|to|attention|dear)\s+(the\s+|all\s+|any\s+)?{_ASSISTANT}\b",
        rf"\b{_ASSISTANT}\s+instructions?\b",
    )
)


def is_instruction_override(message: str) -> bool:
    """True when a visitor message tries to override the assistant's instructions or role."""
    return any(pattern.search(message) for pattern in _VISITOR_OVERRIDE_PATTERNS)


def is_embedded_instruction(block: str) -> bool:
    """True when a block of document text gives instructions to the assistant."""
    return any(pattern.search(block) for pattern in _EMBEDDED_INSTRUCTION_PATTERNS)


def strip_embedded_instructions(text: str) -> str:
    """Drop the blocks of a passage that give instructions to the assistant.

    Blocks are separated by blank lines. An instruction that a blank line cuts
    in two is found in the two blocks read together, and both are dropped. The
    result is empty when nothing is left.
    """
    blocks = [block for block in text.split("\n\n") if block.strip()]
    dropped = {index for index, block in enumerate(blocks) if is_embedded_instruction(block)}
    for index in range(len(blocks) - 1):
        pair = {index, index + 1}
        if not pair & dropped and is_embedded_instruction(f"{blocks[index]} {blocks[index + 1]}"):
            dropped |= pair
    return "\n\n".join(block for index, block in enumerate(blocks) if index not in dropped)
