from dataclasses import dataclass
from typing import Literal

from sortax.messages import CompletionKind


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    system_instruction: str
    user_content: str
    history: tuple[HistoryMessage, ...]
    evidence: tuple[str, ...]
    completion_kind: CompletionKind
    missing_fields: tuple[str, ...] = ()
