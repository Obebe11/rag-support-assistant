"""One valid request for every endpoint that is declared but not implemented yet.

When you implement an endpoint, remove its case from this list and add real tests.
"""

from dataclasses import dataclass, field
from typing import Any

ANY_ID = "00000000-0000-4000-8000-000000000001"
MARKDOWN_FILE = {"file": ("returns.md", b"# Returns\n\nThirty days.\n", "text/markdown")}


@dataclass(frozen=True, slots=True)
class ApiCase:
    method: str
    path: str
    json: Any = None
    files: dict[str, tuple[str, bytes, str]] | None = None
    data: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.method} {self.path}"


# Every declared endpoint is implemented. The lists stay for the contract tests,
# which run once per case.
VISITOR_STUBS: list[ApiCase] = []

ADMIN_STUBS: list[ApiCase] = []
