import os

import pytest

from sortax.llm_gateway import OpenAILLMProvider
from sortax.prompting import LLMRequest

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_explicit_openai_stream_smoke() -> None:
    if os.getenv("SORTAX_RUN_OPENAI_SMOKE") != "1":
        pytest.skip("set SORTAX_RUN_OPENAI_SMOKE=1 to opt in to the billable live smoke test")
    api_key = os.getenv("SORTAX_LLM_API_KEY")
    model = os.getenv("SORTAX_LLM_MODEL")
    if not api_key or not model or model.startswith("fake-"):
        pytest.skip("an explicit API key and real model are required")

    provider = OpenAILLMProvider(
        api_key=api_key,
        model_name=model,
        request_timeout_seconds=30,
        max_output_tokens=16,
    )
    request = LLMRequest(
        system_instruction="Reply with exactly: sortax-ok",
        user_content="Run the connectivity check.",
        history=(),
        evidence=(),
        completion_kind="general_chat",
    )

    chunks = [chunk async for chunk in provider.stream(request)]

    assert "".join(chunk.delta for chunk in chunks).strip()
    assert any(chunk.provider_request_id for chunk in chunks)
