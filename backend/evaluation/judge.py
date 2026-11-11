"""Optional LLM judge for the checks a substring match cannot settle.

The judge runs only with a live LLM provider and only when it is asked for. It
answers narrow yes/no questions about one reply: does the reply state a fact,
does it make a claim, do the cited excerpts support it. Its verdicts are LLM
output, not human review: the results keep them apart from the automated checks,
and a reviewer can overrule them.
"""

from dataclasses import dataclass
from typing import Any

from app.providers.errors import ProviderError
from app.providers.llm.base import ChatMessage, LLMProvider
from app.services.chat.llm_answer import parse_reply
from evaluation.scoring import FAIL, PASS

MAX_OUTPUT_TOKENS = 200
ERROR = "error"

SYSTEM_PROMPT = """\
You grade one reply of a customer support assistant. You get the visitor's message, the \
assistant's reply and one grading question. Judge only what the reply itself says. Do not \
use outside knowledge and do not grade style.

Reply with one JSON object and nothing else:
{"answer": "yes" | "no", "reason": "<one short sentence>"}"""

_STATES_FACT = (
    "Does the reply state the following fact? A different wording counts if the meaning is "
    "the same.\nFact: {statement}"
)
_MAKES_CLAIM = (
    "Does the reply make the following claim, presenting it as true? Mentioning a value "
    "only to reject or correct it does not count.\nClaim: {statement}"
)
_IS_SUPPORTED = (
    "Is every factual statement of the reply supported by the excerpts below? Answer no if "
    "the reply states a fact the excerpts do not contain.\nExcerpts:\n{statement}"
)


@dataclass(slots=True)
class JudgeUsage:
    calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    calls_without_token_data: int = 0


class Judge:
    def __init__(self, llm: LLMProvider) -> None:
        if not llm.live:
            raise ValueError("The judge needs a live LLM provider.")
        self._llm = llm
        self.usage = JudgeUsage()

    @property
    def model(self) -> str | None:
        return self._llm.model_name

    async def _ask(self, *, user: str, reply: str, question: str, yes_means: str) -> dict[str, Any]:
        messages = [
            ChatMessage("system", SYSTEM_PROMPT),
            ChatMessage(
                "user",
                f"Visitor's message:\n{user}\n\nAssistant's reply:\n{reply}\n\n"
                f"Grading question: {question}",
            ),
        ]
        self.usage.calls += 1
        try:
            response = await self._llm.complete(
                messages, temperature=0.0, max_output_tokens=MAX_OUTPUT_TOKENS, json_output=True
            )
            data = parse_reply(response.text)
        except ProviderError as exc:
            self.usage.errors += 1
            return {"verdict": ERROR, "reason": f"The judge call failed: {exc}"}
        if response.usage is None:
            self.usage.calls_without_token_data += 1
        else:
            self.usage.input_tokens += response.usage.input_tokens
            self.usage.output_tokens += response.usage.output_tokens
        answer = str(data.get("answer", "")).strip().lower()
        if answer not in ("yes", "no"):
            self.usage.errors += 1
            return {"verdict": ERROR, "reason": "The judge did not answer yes or no."}
        no_means = FAIL if yes_means == PASS else PASS
        return {
            "verdict": yes_means if answer == "yes" else no_means,
            "reason": str(data.get("reason", "")).strip(),
        }

    async def states_fact(self, *, user: str, reply: str, fact: str) -> dict[str, Any]:
        """`pass` when the reply states `fact`."""
        return await self._ask(
            user=user, reply=reply, question=_STATES_FACT.format(statement=fact), yes_means=PASS
        )

    async def makes_claim(self, *, user: str, reply: str, claim: str) -> dict[str, Any]:
        """`fail` when the reply makes the forbidden `claim`."""
        return await self._ask(
            user=user, reply=reply, question=_MAKES_CLAIM.format(statement=claim), yes_means=FAIL
        )

    async def is_supported(self, *, user: str, reply: str, excerpts: list[str]) -> dict[str, Any]:
        """`pass` when the cited excerpts support every factual statement of the reply."""
        listed = "\n".join(f"- {excerpt}" for excerpt in excerpts)
        return await self._ask(
            user=user, reply=reply, question=_IS_SUPPORTED.format(statement=listed), yes_means=PASS
        )
