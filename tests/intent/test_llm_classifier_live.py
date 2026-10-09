import os

import pytest

from sortax.config import Settings
from sortax.intent import LLMIntentClassifier
from sortax.llm_gateway import QwenLLMProvider
from sortax.prompting import LLMRequest


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Hello, how are you?", "general_chat"),
        ("请帮我开始个人报税流程", "tax_assistance"),
        ("What receipts should I keep for working from home?", "ato_document_requirements"),
        ("How should my company lodge GST?", "unsupported_tax_topic"),
    ],
)
async def test_qwen_intent_classifier_live(content: str, expected: str) -> None:
    if os.getenv("SORTAX_RUN_LIVE_INTENT_TESTS") != "1":
        pytest.skip("set SORTAX_RUN_LIVE_INTENT_TESTS=1 to run billable classifier smoke tests")
    settings = Settings()  # type: ignore[call-arg]
    api_key = settings.qwen_api_key
    if (
        settings.intent_classifier_provider != "qwen"
        or api_key is None
        or settings.classifier_model.startswith("fake-")
    ):
        pytest.skip("Qwen classifier API key, base URL, and real model are required")

    classifier = LLMIntentClassifier(
        api_key=api_key.get_secret_value(),
        model_name=settings.classifier_model,
        base_url=settings.qwen_base_url,
        request_timeout_seconds=30,
        max_output_tokens=96,
    )

    decision = await classifier.classify(content)

    assert decision.intent == expected
    assert decision.classifier_source == "llm"


@pytest.mark.live
@pytest.mark.asyncio
async def test_qwen_classifier_live_failure_uses_rules_fallback() -> None:
    if os.getenv("SORTAX_RUN_LIVE_INTENT_TESTS") != "1":
        pytest.skip("set SORTAX_RUN_LIVE_INTENT_TESTS=1 to run billable classifier smoke tests")
    settings = Settings()  # type: ignore[call-arg]
    if settings.classifier_model.startswith("fake-"):
        pytest.skip("a real classifier model is required")

    classifier = LLMIntentClassifier(
        api_key="deliberately-invalid",
        model_name=settings.classifier_model,
        base_url="https://127.0.0.1:1/v1",
        request_timeout_seconds=0.05,
        max_output_tokens=32,
    )

    decision = await classifier.classify("What car records should I keep?")

    assert decision.intent == "ato_document_requirements"
    assert decision.classifier_source == "rules_fallback"
    assert decision.fallback_reason is not None


@pytest.mark.live
@pytest.mark.asyncio
async def test_same_qwen_credential_reaches_both_configured_models() -> None:
    if os.getenv("SORTAX_RUN_LIVE_INTENT_TESTS") != "1":
        pytest.skip("set SORTAX_RUN_LIVE_INTENT_TESTS=1 to run billable classifier smoke tests")
    settings = Settings()  # type: ignore[call-arg]
    api_key = settings.qwen_api_key
    if (
        settings.llm_provider != "qwen"
        or settings.intent_classifier_provider != "qwen"
        or api_key is None
        or settings.llm_model.startswith("fake-")
        or settings.classifier_model.startswith("fake-")
    ):
        pytest.skip("both Qwen models and their shared credential are required")
    assert settings.llm_model != settings.classifier_model
    key = api_key.get_secret_value()
    answer_provider = QwenLLMProvider(
        api_key=key,
        model_name=settings.llm_model,
        base_url=settings.qwen_base_url,
        request_timeout_seconds=30,
        max_output_tokens=32,
    )
    classifier = LLMIntentClassifier(
        api_key=key,
        model_name=settings.classifier_model,
        base_url=settings.qwen_base_url,
        request_timeout_seconds=30,
        max_output_tokens=96,
    )

    answer_chunks = [
        chunk
        async for chunk in answer_provider.stream(
            LLMRequest(
                system_instruction="Reply with only the word ok.",
                user_content="Connectivity check",
                history=(),
                evidence=(),
                completion_kind="general_chat",
            )
        )
    ]
    decision = await classifier.classify("Hello")

    assert any(chunk.delta for chunk in answer_chunks)
    assert decision.intent == "general_chat"
    assert decision.classifier_source == "llm"
