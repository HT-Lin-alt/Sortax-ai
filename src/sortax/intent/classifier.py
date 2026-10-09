import re
from collections.abc import Sequence
from typing import Protocol

from sortax.intent.models import (
    IntentDecision,
    IntentHistoryMessage,
    IntentKind,
    IntentWorkflowState,
)


class IntentClassificationError(RuntimeError):
    """The request could not be classified without risking an unsafe route."""

    code = "intent_classification_uncertain"
    retryable = True


class IntentClassifier(Protocol):
    async def classify(
        self,
        content: str,
        history: Sequence[IntentHistoryMessage] = (),
        workflow_state: IntentWorkflowState | None = None,
    ) -> IntentDecision: ...


class FakeIntentClassifier:
    """Deterministic bilingual first-layer classifier for development and tests."""

    _classifier_version = "phase-5c-rules-v1"
    _claim_terms = (
        "home",
        "wfh",
        "salary",
        "wages",
        "payg",
        "income statement",
        "education",
        "course",
        "training",
        "car",
        "vehicle",
        "mileage",
        "rental property",
        "rental properties",
        "rental income",
        "investment property",
        "landlord",
        "holiday homes",
        "bank interest",
        "interest income",
        "income bond",
        "在家",
        "居家",
        "办公",
        "工资",
        "薪资",
        "学习",
        "课程",
        "培训",
        "汽车",
        "车辆",
        "里程",
        "出租房",
        "出租物业",
        "租金收入",
        "投资房",
        "银行利息",
        "存款利息",
        "利息收入",
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
    _unsupported_terms = (
        "capital gains",
        "cgt",
        "crypto",
        "cryptocurrency",
        "gst",
        "company tax",
        "corporate tax",
        "trust tax",
        "fbt",
        "fringe benefits",
        "养老金",
        "资本利得",
        "加密货币",
        "公司税",
        "企业税",
        "商品及服务税",
    )
    _ambiguous_short_replies = {
        "yes",
        "no",
        "ok",
        "okay",
        "sure",
        "it",
        "that",
        "this",
        "help",
        "是",
        "否",
        "好",
        "可以",
        "这个",
        "那个",
        "帮我",
    }
    _field_supplement_pattern = re.compile(r"^\s*20\d{2}[-–/](?:\d{2}|20\d{2})\s*[?.。]?$", re.I)

    async def classify(
        self,
        content: str,
        history: Sequence[IntentHistoryMessage] = (),
        workflow_state: IntentWorkflowState | None = None,
    ) -> IntentDecision:
        normalized = " ".join(content.lower().split())
        if not normalized:
            raise IntentClassificationError("empty input cannot be classified safely")
        intent: IntentKind
        if workflow_state is not None and workflow_state.phase in {
            "awaiting_claim_type",
            "awaiting_tax_year",
            "awaiting_summary_confirmation",
        }:
            intent = "tax_assistance"
        elif self._is_ato_document_request(content):
            intent = "ato_document_requirements"
        elif self._field_supplement_pattern.fullmatch(content) and self._has_recent_ato_request(
            history
        ):
            intent = "ato_document_requirements"
        elif any(term in normalized for term in self._unsupported_terms):
            intent = "unsupported_tax_topic"
        elif any(term in normalized for term in self._ato_terms) or any(
            term in normalized for term in self._claim_terms
        ):
            intent = "tax_assistance"
        elif normalized in self._ambiguous_short_replies and not history:
            raise IntentClassificationError("short input lacks safe routing context")
        else:
            intent = "general_chat"
        return IntentDecision(
            intent=intent,
            classifier_version=self._classifier_version,
            classifier_source="rules_fallback",
            fallback_version=self._classifier_version,
        )

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
