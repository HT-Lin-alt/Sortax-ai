from collections.abc import AsyncIterator

from sortax.llm_gateway.base import LLMStreamChunk
from sortax.prompting import LLMRequest


class FakeLLMProvider:
    """Deterministic streaming provider for Phase 5A and automated tests."""

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-chat-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        if request.completion_kind == "clarification":
            labels = {
                "claim_type": "费用类别",
                "tax_year": "税务年度",
                "tax_intake": "个人报税所需的费用或收入类别",
                "supported_tax_topic": "当前支持的个人报税资料主题",
            }
            missing = "、".join(labels.get(field, field) for field in request.missing_fields)
            response = f"请补充{missing}，然后我才能检索对应的 ATO 资料。"
        elif request.completion_kind == "answer":
            if not request.evidence:
                raise ValueError("grounded fake generation requires evidence")
            response = (
                "这是阶段 5A 的编排测试回答；当前使用 FakeRetriever，不代表真实 ATO 税务结论。"
            )
        elif request.completion_kind == "tax_summary":
            if not request.evidence:
                raise ValueError("tax summary fake generation requires persisted evidence")
            response = (
                "Here is your preparation summary based only on the saved questionnaire and "
                "ATO-backed checklist. Confirm eligibility and amounts with a registered tax agent."
            )
        else:
            if request.evidence:
                raise ValueError("general fake generation cannot use retrieval evidence")
            response = "你好！我是 Sortax 会计信息助手。请告诉我你想了解什么。"
        chunk_size = 12
        for start in range(0, len(response), chunk_size):
            yield LLMStreamChunk(delta=response[start : start + chunk_size])
        yield LLMStreamChunk(
            provider_request_id="fake-response",
            input_tokens=len(request.user_content.split()),
            output_tokens=len(response.split()),
        )
