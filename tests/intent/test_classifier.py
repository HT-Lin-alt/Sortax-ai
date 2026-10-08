import pytest

from sortax.intent import FakeIntentClassifier, IntentHistoryMessage


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["Hello", "你好", "What is income tax?", "2025-26"])
async def test_general_chat_does_not_enter_ato_document_flow(content: str) -> None:
    decision = await FakeIntentClassifier().classify(content)

    assert decision.intent == "general_chat"


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
