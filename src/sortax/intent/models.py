from dataclasses import dataclass
from typing import Literal

IntentKind = Literal["general_chat", "ato_document_requirements"]


@dataclass(frozen=True, slots=True)
class IntentHistoryMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class IntentDecision:
    intent: IntentKind
    classifier_version: str
