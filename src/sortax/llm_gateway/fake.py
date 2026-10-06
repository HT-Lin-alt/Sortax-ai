from collections.abc import AsyncIterator

from sortax.prompting import LLMRequest


class FakeLLMProvider:
    """Deterministic streaming provider for Phase 5A and automated tests."""

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-chat-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        if request.completion_kind == "clarification":
            labels = {
                "claim_type": "费用类别",
                "tax_year": "税务年度",
            }
            missing = "、".join(labels.get(field, field) for field in request.missing_fields)
            response = f"请补充{missing}，然后我才能检索对应的 ATO 资料。"
        else:
            if not request.evidence:
                raise ValueError("grounded fake generation requires evidence")
            response = (
                "这是阶段 5A 的编排测试回答；当前使用 FakeRetriever，不代表真实 ATO 税务结论。"
            )
        chunk_size = 12
        for start in range(0, len(response), chunk_size):
            yield response[start : start + chunk_size]
