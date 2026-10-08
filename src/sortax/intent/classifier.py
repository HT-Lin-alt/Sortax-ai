import re
from collections.abc import Sequence
from typing import Protocol

from sortax.intent.models import IntentDecision, IntentHistoryMessage, IntentKind


class IntentClassifier(Protocol):
    async def classify(
        self,
        content: str,
        history: Sequence[IntentHistoryMessage] = (),
    ) -> IntentDecision: ...


class FakeIntentClassifier:
    """Deterministic bilingual first-layer classifier for development and tests."""

    _classifier_version = "phase-5b-fake-v1"
    _claim_terms = (
        "home",
        "wfh",
        "education",
        "course",
        "training",
        "car",
        "vehicle",
        "mileage",
        "在家",
        "居家",
        "办公",
        "学习",
        "课程",
        "培训",
        "汽车",
        "车辆",
        "里程",
    )
    _ato_terms = (
        "ato",
        "tax",
        "deduction",
        "claim",
        "退税",
        "报税",
        "扣除",
        "税务",
        "申报",
    )
    _requirement_terms = (
        "record",
        "records",
        "receipt",
        "receipts",
        "document",
        "documents",
        "evidence",
        "proof",
        "keep",
        "retain",
        "材料",
        "文件",
        "记录",
        "凭证",
        "收据",
        "证明",
        "保留",
        "准备",
    )
    _field_supplement_pattern = re.compile(r"^\s*20\d{2}[-–/](?:\d{2}|20\d{2})\s*[?.。]?$", re.I)

    async def classify(
        self,
        content: str,
        history: Sequence[IntentHistoryMessage] = (),
    ) -> IntentDecision:
        intent: IntentKind
        if self._is_ato_document_request(content):
            intent = "ato_document_requirements"
        elif self._field_supplement_pattern.fullmatch(content) and self._has_recent_ato_request(
            history
        ):
            intent = "ato_document_requirements"
        else:
            intent = "general_chat"
        return IntentDecision(intent=intent, classifier_version=self._classifier_version)

    def _has_recent_ato_request(self, history: Sequence[IntentHistoryMessage]) -> bool:
        for message in reversed(history[-20:]):
            if message.role == "user":
                return self._is_ato_document_request(message.content)
        return False

    def _is_ato_document_request(self, content: str) -> bool:
        normalized = " ".join(content.lower().split())
        asks_for_documents = any(term in normalized for term in self._requirement_terms)
        identifies_tax_context = any(term in normalized for term in self._ato_terms)
        identifies_supported_claim = any(term in normalized for term in self._claim_terms)
        return asks_for_documents and (identifies_tax_context or identifies_supported_claim)
