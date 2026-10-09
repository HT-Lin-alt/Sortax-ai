from dataclasses import dataclass
from typing import Literal

IntentKind = Literal[
    "general_chat",
    "tax_assistance",
    "ato_document_requirements",
    "unsupported_tax_topic",
]
ClassifierSource = Literal["llm", "rules_fallback"]
WorkflowPhase = Literal[
    "inactive",
    "awaiting_claim_type",
    "awaiting_tax_year",
    "awaiting_summary_confirmation",
    "completed",
]


@dataclass(frozen=True, slots=True)
class IntentHistoryMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class IntentWorkflowState:
    """Minimal persisted workflow snapshot safe to expose to the classifier."""

    phase: WorkflowPhase = "inactive"
    claim_type: str | None = None
    tax_year: str | None = None


@dataclass(frozen=True, slots=True)
class IntentDecision:
    intent: IntentKind
    classifier_version: str
    classifier_source: ClassifierSource = "rules_fallback"
    prompt_version: str | None = None
    schema_version: str | None = None
    fallback_version: str | None = None
    fallback_reason: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
