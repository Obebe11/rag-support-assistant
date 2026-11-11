"""Rule-based reading of a visitor message: purchase intent and inquiry fields.

Owner: T4. Used when no live LLM is configured, and as the fallback when the
LLM call fails. The rules prefer missing an inquiry over inventing one: a
question about a policy must never open an inquiry, because the visitor can
always state the request again, while a wrong offer breaks a grounded answer.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.schemas.inquiries import InquiryField

_I = re.IGNORECASE

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_WEEKDAY = r"(?:mon|tues?|wed(?:nes)?|thur?s?|fri|sat(?:ur)?|sun)(?:day)?"
_TIME_UNIT = r"(?:minutes?|hours?|(?:business |working )?days?|weeks?|months?|quarters?|years?)"
_NUMBER_WORDS: Mapping[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "a dozen": 12,
    "a hundred": 100,
    "one hundred": 100,
}
_NUMBER = r"\d{1,3}(?:,\d{3})+|\d+|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))

_SUBJECT = r"(?:i|we|my (?:company|team|office|firm)|our (?:company|team|office|firm))"
_WANT = (
    r"(?:(?:would|'d) (?:like|love)|want|wish|need|plan|intend|hope|"
    r"(?:am|'m|are|'re) (?:looking|hoping|planning|ready))"
)
_BUY = (
    r"(?:buy|order|purchase|procure|"
    r"(?:place|make|submit|put in) (?:an?|my|our)(?: \w+)? order)"
)
_QUOTE = r"(?:quote|quotation|price quote|estimate|proforma(?: invoice)?)"

# A sentence that matches one of these states a request to buy.
_INTENT_PATTERNS = [
    re.compile(rf"\b{_SUBJECT}\b[^.?!]{{0,20}}\b{_WANT} to {_BUY}\b", _I),
    re.compile(
        rf"\b{_SUBJECT}(?:\s?(?:am|'m|are|'re))? interested in "
        r"(?:buying|ordering|purchasing)\b",
        _I,
    ),
    re.compile(
        rf"\b{_SUBJECT} (?:need|needs|want|wants|require|requires|(?:would|'d) like|"
        rf"(?:am|'m|are|'re) looking for) (?:about |around |approximately |roughly |"
        rf"at least |up to )?(?:{_NUMBER})\s+(?!{_TIME_UNIT}\b)[a-z]",
        _I,
    ),
    re.compile(rf"\bplease (?:{_BUY}|quote)\b", _I),
]
# A polite question that names a quantity is a request: "Can we order 10 cabinets?"
# Without a quantity it asks how ordering works: "Can I order online?"
_POLITE_REQUEST = re.compile(
    r"\b(?:(?:can|could|may) (?:i|we)|(?:is it|would it be) possible to) (?:please )?"
    rf"(?:buy|order|purchase) (?:{_NUMBER})\b",
    _I,
)
# Asking for a quote is a request even when it is phrased as a question.
_QUOTE_PATTERNS = [
    re.compile(
        r"\b(?:get|have|send|need|want|like|request|requesting|provide|give|prepare|share)\b"
        rf"[^.?!]{{0,40}}\b{_QUOTE}\b",
        _I,
    ),
    re.compile(rf"\b{_QUOTE} for (?:{_NUMBER}|an?|the|some|your)\b", _I),
    re.compile(r"\b(?:quote|price) (?:me|us)\b", _I),
    re.compile(r"\b(?:request for quotation|rfq)\b", _I),
]

# What the visitor already bought: a support topic, not a new purchase.
_PAST_PURCHASE = re.compile(
    r"\b(?:i|we) (?:have |had |already |recently |just )*(?:bought|ordered|purchased|received)\b|"
    r"\b(?:my|our) (?:order|purchase|delivery|shipment)\b|"
    r"\b(?:order|purchase) (?:number|no\.?|#|status|confirmation)\b|"
    r"\ban order (?:i|we) (?:placed|made)\b",
    _I,
)
_HYPOTHETICAL = re.compile(
    r"\b(?:if|when|once|after|before|suppose|supposing|in case|whenever)\b[^.?!]{0,40}"
    r"\b(?:buy|buying|order|ordering|purchase|purchasing)\b",
    _I,
)
_POLICY_TOPIC = re.compile(
    r"\b(?:polic(?:y|ies)|returns?|returning|refunds?|warrant(?:y|ies)|guarantees?|"
    r"exchanges?|cancel(?:lation|ing|s)?|shipping|ship|deliver(?:y|ies)?|"
    r"service|servicing|repairs?|maintenance|terms|conditions)\b",
    _I,
)
_POLICY_CORE = re.compile(
    r"\b(?:polic(?:y|ies)|returns?|returning|refunds?|refunding|warrant(?:y|ies)|guarantees?|"
    r"exchanges?|exchanging|cancel(?:lation|ing|s)?)\b",
    _I,
)
_QUESTION_START = re.compile(
    r"^(?:(?:hi|hello|hey|so|and|but|also|ok|okay|thanks|thank you)[,!. ]+)*"
    r"(?:how|what|whats|what's|when|where|why|who|which|is|are|was|were|does|do|did|will|"
    r"should|has|have)\b",
    _I,
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w@.])\+?\(?\d[\d\s().-]{6,}\d(?![\w@])")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_TIMELINE_PATTERNS = [
    re.compile(
        r"\b(?:asap|a\.s\.a\.p\.?|as soon as possible|immediately|right away|urgently|"
        r"no rush|no hurry)\b",
        _I,
    ),
    re.compile(
        r"\b(?:by|before|until|no later than|not later than)\s+(?:the\s+)?"
        r"(?:(?:end|beginning|start|middle) of\s+(?:the\s+)?|mid[- ]|early\s+|late\s+)?"
        rf"(?:(?:next|this)\s+)?(?:week|month|quarter|year|q[1-4]|{_WEEKDAY}|{_MONTH})\b"
        r"(?:\s+\d{1,2}(?:st|nd|rd|th)?\b)?(?:,?\s+\d{4}\b)?",
        _I,
    ),
    re.compile(
        r"\b(?:by|before|on|until)\s+(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?"
        rf"{_MONTH}\b(?:,?\s+\d{{4}}\b)?",
        _I,
    ),
    re.compile(r"\b(?:by|before|on|until)\s+\d{1,2}[/.]\d{1,2}(?:[/.]\d{2,4})?\b", _I),
    re.compile(r"\b(?:by|before|on|until)\s+\d{4}-\d{2}-\d{2}\b", _I),
    re.compile(
        r"\b(?:within|in|in the next|within the next|over the next)\s+"
        rf"(?:(?:{_NUMBER})|a|a few|a couple of|several)\s+"
        r"(?:business |working )?(?:days?|weeks?|months?|quarters?)\b",
        _I,
    ),
    re.compile(
        r"\b(?:(?:the )?(?:end|beginning|start|middle) of(?: the| this| next)?|next|this|"
        rf"early|late|mid)\s+(?:week|month|quarter|year|q[1-4]|{_MONTH})\b(?:\s+\d{{4}}\b)?",
        _I,
    ),
    re.compile(rf"\b(?:in|during)\s+{_MONTH}\b(?:\s+\d{{4}}\b)?", _I),
    re.compile(r"\bq[1-4](?:\s+\d{4})?\b", _I),
]

_PRODUCT_END = (
    r"(?=\s*(?:[.,;:!?()]|$|\b(?:by|before|until|within|in|for|to|delivered|shipped|asap|"
    r"as soon|next|this|please|and|but|my|our|thanks|thank|no later|not later|urgently|"
    r"immediately|if|with delivery|at|on)\b))"
)
_PRODUCT_BODY = r"(?P<product>[A-Za-z][\w\-/&'\" ]{1,80}?)"
_QUANTITY_PRODUCT = re.compile(
    rf"(?<![\w@.,/-])(?P<quantity>{_NUMBER})\s*(?:(?:x|\u00d7)\s+)?"
    r"(?:(?:units?|pcs|pieces?|sets?|boxes|packs?) of\s+)?"
    rf"(?!{_TIME_UNIT}\b){_PRODUCT_BODY}{_PRODUCT_END}",
    _I,
)
_QUANTITY_UNITS = re.compile(
    rf"(?<![\w@.,/-])(?P<quantity>{_NUMBER})\s*(?:units?|pcs|pieces?|sets?|items?)\b", _I
)
_BARE_QUANTITY = re.compile(
    rf"^(?:[a-z' ]{{0,20}}\s)?(?P<quantity>{_NUMBER})(?:\s[a-z ]{{0,20}})?[.!]?$", _I
)
_PRODUCT_AFTER_VERB = re.compile(
    rf"\b(?:buy|order|purchase|procure|{_QUOTE} (?:for|on)|"
    r"interested in(?: buying| ordering| purchasing)?|looking for)\s+"
    r"(?:(?:a|an|the|some|your|several|a few|more)\s+)?"
    rf"{_PRODUCT_BODY}{_PRODUCT_END}",
    _I,
)
_NOT_A_PRODUCT = re.compile(
    r"^(?:it|them|this|that|these|those|something|some|one|ones|more|items?|products?|"
    r"things?|stuff|equipment|units?|pcs|pieces?|order|orders|quote|quotes|information|info|"
    r"details|you|your|us|me|now|today|online|here)$",
    _I,
)
_LEADING_FILLER = re.compile(r"^(?:(?:a|an|the|some|of|your|more|new)\s+)+", _I)

_NAME_WORD = r"[A-Z][a-zA-Z'-]+"
_NAME = re.compile(
    r"(?i:\b(?:my name is|my name's|i am|i'm|this is|name:|name is)\s+)"
    rf"(?P<name>{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,3}})"
)
_NAME_BEFORE_EMAIL = re.compile(rf"(?P<name>{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,3}})\s*[,;:(<-]\s*$")
_BARE_NAME = re.compile(r"^[A-Za-z][a-zA-Z'-]+(?:\s+[A-Za-z][a-zA-Z'-]+){0,3}$")
_NOT_A_NAME = re.compile(
    r"^(?:interested|looking|ready|sorry|happy|sure|here|from|the|a|an|not|still|just|"
    r"writing|calling|contacting|emailing|wondering|trying|planning|hoping|yes|no|ok|okay|"
    r"thanks|hello|hi|hey|please|asap)\b",
    _I,
)
_COMPANY_WORD = r"[A-Z0-9][\w&.'-]*"
_COMPANY_TAIL = rf"(?P<company>{_COMPANY_WORD}(?:\s+(?:{_COMPANY_WORD}|&|of|and)){{0,4}})"
_COMPANY = re.compile(
    r"(?i:\b(?:company(?: name)?(?: is|:)|organi[sz]ation(?: is|:)|work(?:ing)? (?:for|at)|"
    r"on behalf of|representing|we are from|i am from|i'm from|calling from|"
    r"writing from)\s+)(?i:the\s+)?" + _COMPANY_TAIL
)
_COMPANY_AFTER_NAME = re.compile(
    rf"{_NAME_WORD}(?:\s+{_NAME_WORD}){{0,3}},?\s+(?i:from|at|with|of)\s+(?i:the\s+)?"
    + _COMPANY_TAIL
)
_NOT_A_COMPANY = re.compile(rf"^(?:{_MONTH}|{_WEEKDAY}|q[1-4]|i|we|the|my|our)$", _I)

_CONFIRMATION = re.compile(
    r"^(?:yes|yep|yeah|correct|confirm(?:ed)?|that'?s (?:right|correct|all)|"
    r"(?:it |that |this )?looks (?:good|right|correct|fine)|sounds good|ok(?:ay)?|sure|"
    r"go ahead|send it|submit(?: it)?|please (?:send|submit|proceed|go ahead)|perfect|great)"
    r"\b[\w\s,.!']{0,40}$",
    _I,
)
_NOT_AN_ANSWER = re.compile(
    r"^(?:no|nope|nah|none|nothing|not sure|not yet|i don'?t know|idk|never ?mind|cancel|"
    r"stop|skip|later|hi|hello|hey|thanks|thank you|help|what|why|huh)\b",
    _I,
)
_PURCHASE_HINT = re.compile(
    r"\b(?:buy|buying|orders?|ordering|purchas\w+|procur\w+|quot\w+|rfq|pricing|prices?|"
    r"estimate|invoice|bulk|interested|needs?|wants?|requir\w+|suppl\w+|like to|"
    rf"looking (?:for|to)|{_NUMBER})\b",
    _I,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
_SHORT_ANSWER_WORDS = 8


@dataclass(frozen=True, slots=True)
class MessageReading:
    """What the rules found in one visitor message."""

    intent: bool = False
    """The message states a request to buy or to get a quote."""
    confirmation: bool = False
    """The message only agrees ("yes", "looks good")."""
    fields: Mapping[InquiryField, str | int] = field(default_factory=dict)


def _normalize(text: str) -> str:
    """Use the plain apostrophe, so one spelling of "I'd" and "I'm" is enough."""
    return text.replace("\u2019", "'").strip()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]


def _is_question(sentence: str) -> bool:
    return sentence.rstrip().endswith("?") or _QUESTION_START.search(sentence) is not None


def _states_intent(sentence: str) -> bool:
    """True when one sentence asks to buy. Guards come first: precision over recall."""
    if _PAST_PURCHASE.search(sentence):
        return False
    quote_request = any(pattern.search(sentence) for pattern in _QUOTE_PATTERNS)
    question = _is_question(sentence)
    if question and _POLICY_TOPIC.search(sentence):
        return False
    if _HYPOTHETICAL.search(sentence):
        return bool(quote_request and _QUESTION_START.search(sentence) is None)
    if _POLITE_REQUEST.search(sentence):
        return True
    if quote_request:
        # "Can I get a quote for 20 desks?" is a request; "How long is a quote valid?" is not.
        return _QUESTION_START.search(sentence) is None
    if _QUESTION_START.search(sentence):
        return False
    return any(pattern.search(sentence) for pattern in _INTENT_PATTERNS)


def has_purchase_intent(text: str) -> bool:
    return any(_states_intent(sentence) for sentence in _sentences(_normalize(text)))


def asks_about_policy(text: str) -> bool:
    """True when the message is about a policy, a past order or a what-if, not a request.

    The detector uses it as a veto on an LLM reading: a message that mentions
    returns, refunds, warranty or cancellation, refers to an earlier order, or
    asks "if I order ..., what ...?" opens no draft unless one of its sentences
    plainly asks to buy.
    """
    sentences = _sentences(_normalize(text))
    if any(_states_intent(sentence) for sentence in sentences):
        return False
    return any(
        _POLICY_CORE.search(sentence)
        or _PAST_PURCHASE.search(sentence)
        or (_is_question(sentence) and _HYPOTHETICAL.search(sentence))
        for sentence in sentences
    )


def might_concern_a_purchase(text: str) -> bool:
    """Cheap pre-filter: can this message possibly be a purchase request?

    Used to skip the LLM call for messages that have nothing to do with buying.
    It is deliberately broad (any buying word, any number); the LLM or
    `has_purchase_intent` makes the decision.
    """
    return _PURCHASE_HINT.search(_normalize(text)) is not None


def _number(raw: str) -> int | None:
    raw = raw.lower().strip()
    if raw in _NUMBER_WORDS:
        return _NUMBER_WORDS[raw]
    digits = raw.replace(",", "")
    return int(digits) if digits.isdigit() else None


def _clean_product(raw: str) -> str | None:
    product = _LEADING_FILLER.sub("", raw.strip(" \t\"'.,;:!?-"))
    product = re.sub(r"\s+", " ", product).strip()
    if len(product) < 2 or _NOT_A_PRODUCT.match(product):
        return None
    if re.match(rf"^{_TIME_UNIT}$", product, _I):
        return None
    return product


def _mask(text: str, pattern: re.Pattern[str]) -> str:
    """Blank out matches so later patterns do not read them as something else."""
    return pattern.sub(lambda match: " " * len(match.group(0)), text)


def _extract_timeline(text: str) -> str | None:
    best: re.Match[str] | None = None
    for pattern in _TIMELINE_PATTERNS:
        for match in pattern.finditer(text):
            if best is None or len(match.group(0)) > len(best.group(0)):
                best = match
    return best.group(0).strip() if best else None


def _extract_phone(text: str) -> str | None:
    for match in _PHONE.finditer(text):
        candidate = match.group(0).strip()
        digits = re.sub(r"\D", "", candidate)
        if 8 <= len(digits) <= 15 and not _ISO_DATE.match(candidate):
            return candidate
    return None


def _extract_name(text: str, email: re.Match[str] | None) -> str | None:
    match = _NAME.search(text)
    if match and not _NOT_A_NAME.match(match.group("name")):
        return match.group("name")
    if email is not None:
        before = _NAME_BEFORE_EMAIL.search(text[: email.start()])
        if before and not _NOT_A_NAME.match(before.group("name")):
            return before.group("name")
    return None


def _extract_company(text: str) -> str | None:
    for pattern in (_COMPANY, _COMPANY_AFTER_NAME):
        match = pattern.search(text)
        if match:
            company = match.group("company").rstrip(".,;:")
            if not _NOT_A_COMPANY.match(company):
                return company
    return None


def _extract_from_statement(text: str) -> dict[InquiryField, str | int]:
    """Fields stated in text that is known to belong to the inquiry."""
    fields: dict[InquiryField, str | int] = {}

    email = _EMAIL.search(text)
    if email:
        fields[InquiryField.CONTACT_EMAIL] = email.group(0).rstrip(".")
    name = _extract_name(text, email)
    if name:
        fields[InquiryField.CONTACT_NAME] = name
    company = _extract_company(text)
    if company:
        fields[InquiryField.CONTACT_COMPANY] = company

    remaining = _mask(text, _EMAIL)
    phone = _extract_phone(remaining)
    if phone:
        fields[InquiryField.CONTACT_PHONE] = phone
        remaining = remaining.replace(phone, " " * len(phone))

    timeline = _extract_timeline(remaining)
    if timeline:
        fields[InquiryField.TIMELINE] = timeline
        remaining = remaining.replace(timeline, " " * len(timeline) + ".", 1)

    for match in _QUANTITY_PRODUCT.finditer(remaining):
        quantity = _number(match.group("quantity"))
        product = _clean_product(match.group("product"))
        if quantity and product:
            fields[InquiryField.QUANTITY] = quantity
            fields[InquiryField.PRODUCT] = product
            break
    if InquiryField.QUANTITY not in fields:
        units = _QUANTITY_UNITS.search(remaining)
        quantity = _number(units.group("quantity")) if units else None
        if quantity:
            fields[InquiryField.QUANTITY] = quantity
    if InquiryField.PRODUCT not in fields:
        after_verb = _PRODUCT_AFTER_VERB.search(remaining)
        product = _clean_product(after_verb.group("product")) if after_verb else None
        if product:
            fields[InquiryField.PRODUCT] = product
    return fields


def _short_answer(text: str, expecting: InquiryField) -> dict[InquiryField, str | int]:
    """Read a short reply as the answer to the field the assistant is waiting for."""
    answer = text.strip().strip(".!")
    if not answer or len(answer.split()) > _SHORT_ANSWER_WORDS or _NOT_AN_ANSWER.match(answer):
        return {}
    if expecting is InquiryField.QUANTITY:
        match = _BARE_QUANTITY.match(answer)
        quantity = _number(match.group("quantity")) if match else None
        return {InquiryField.QUANTITY: quantity} if quantity else {}
    if expecting is InquiryField.PRODUCT:
        product = _clean_product(answer)
        return {InquiryField.PRODUCT: product} if product else {}
    if expecting is InquiryField.TIMELINE:
        return {InquiryField.TIMELINE: answer}
    if (
        expecting is InquiryField.CONTACT_NAME
        and _BARE_NAME.match(answer)
        and not _NOT_A_NAME.match(answer)
    ):
        return {InquiryField.CONTACT_NAME: answer}
    return {}


def read_message(
    text: str,
    *,
    draft_open: bool = False,
    expecting: InquiryField | None = None,
) -> MessageReading:
    """Read one visitor message.

    Without an open draft, fields are extracted only when the message states a
    request to buy. With an open draft (`draft_open`), statements may also supply
    details; `expecting` is the field the assistant is most likely waiting for,
    which lets a short reply such as "20" or "Jane Doe" be understood. Questions
    never supply details, so "Do you deliver within 5 days?" changes nothing.
    """
    text = _normalize(text)
    sentences = _sentences(text)
    intent_sentences = [sentence for sentence in sentences if _states_intent(sentence)]
    intent = bool(intent_sentences)

    if not draft_open:
        if not intent:
            return MessageReading()
        statements = [
            sentence
            for sentence in sentences
            if sentence in intent_sentences or not _is_question(sentence)
        ]
        return MessageReading(intent=True, fields=_extract_from_statement(" ".join(statements)))

    if not intent and _CONFIRMATION.match(text):
        return MessageReading(confirmation=True)

    statements = [
        sentence
        for sentence in sentences
        if sentence in intent_sentences or not _is_question(sentence)
    ]
    fields = _extract_from_statement(" ".join(statements))
    if not fields and not intent and expecting is not None and len(sentences) == 1:
        # A short reply the patterns do not recognize answers the pending question.
        fields = _short_answer(text, expecting) if statements else {}
    return MessageReading(intent=intent, fields=fields)
