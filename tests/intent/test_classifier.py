import pytest

from sortax.intent import (
    FakeIntentClassifier,
    IntentClassificationError,
    IntentHistoryMessage,
    IntentWorkflowState,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["Hello", "你好", "2025-26"])
async def test_general_chat_does_not_enter_ato_document_flow(content: str) -> None:
    decision = await FakeIntentClassifier().classify(content)

    assert decision.intent == "general_chat"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["What is income tax?", "Can you help with my tax return?"])
async def test_tax_requests_are_not_misrouted_to_general_chat(content: str) -> None:
    decision = await FakeIntentClassifier().classify(content)

    assert decision.intent == "tax_assistance"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["How is crypto taxed?", "公司税和 GST 怎么申报？"])
async def test_unsupported_tax_topics_fail_closed(content: str) -> None:
    decision = await FakeIntentClassifier().classify(content)

    assert decision.intent == "unsupported_tax_topic"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "What car records do I need?",
        "Which receipts should I keep for a tax deduction?",
        "汽车费用需要准备哪些记录？",
    ],
)
async def test_ato_document_requirements_are_classified_deterministically(
    content: str,
) -> None:
    decision = await FakeIntentClassifier().classify(content)

    assert decision.intent == "ato_document_requirements"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "Which PAYG income statement documents should I keep?",
        "工资收入需要保留哪些文件？",
        "What records do I need for a rental property?",
        "出租物业需要准备哪些记录？",
        "Which bank interest documents should I retain?",
        "银行利息需要哪些证明？",
    ],
)
async def test_phase_4b_claim_types_enter_document_requirements_flow(content: str) -> None:
    decision = await FakeIntentClassifier().classify(content)

    assert decision.intent == "ato_document_requirements"


@pytest.mark.asyncio
async def test_year_only_follow_up_inherits_recent_ato_document_intent() -> None:
    history = (
        IntentHistoryMessage(role="user", content="What car records do I need?"),
        IntentHistoryMessage(role="assistant", content="Which tax year?"),
    )

    decision = await FakeIntentClassifier().classify("2025-26", history)

    assert decision.intent == "ato_document_requirements"


@pytest.mark.asyncio
async def test_year_only_message_does_not_inherit_stale_ato_intent() -> None:
    history = (
        IntentHistoryMessage(role="user", content="What car records do I need?"),
        IntentHistoryMessage(role="assistant", content="Which tax year?"),
        IntentHistoryMessage(role="user", content="Thanks, tell me about bookkeeping instead"),
        IntentHistoryMessage(role="assistant", content="Sure."),
    )

    decision = await FakeIntentClassifier().classify("2025-26", history)

    assert decision.intent == "general_chat"


@pytest.mark.asyncio
async def test_short_reply_uses_persisted_workflow_state() -> None:
    decision = await FakeIntentClassifier().classify(
        "yes",
        workflow_state=IntentWorkflowState(phase="awaiting_summary_confirmation"),
    )

    assert decision.intent == "tax_assistance"


@pytest.mark.asyncio
async def test_ambiguous_short_reply_without_context_is_inconclusive() -> None:
    with pytest.raises(IntentClassificationError):
        await FakeIntentClassifier().classify("help")
