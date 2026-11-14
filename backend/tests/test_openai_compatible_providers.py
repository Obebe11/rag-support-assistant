"""OpenAI-compatible providers against a mock transport. No request leaves the process."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.providers.embeddings.openai_compatible import BATCH_SIZE, OpenAICompatibleEmbeddingProvider
from app.providers.errors import ProviderError
from app.providers.llm.base import ChatMessage, TokenUsage
from app.providers.llm.local import LocalLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

Handler = Callable[[httpx.Request], httpx.Response]


def _embeddings(
    handler: Handler, api_key: str | None = "embedding-key"
) -> OpenAICompatibleEmbeddingProvider:
    return OpenAICompatibleEmbeddingProvider(
        base_url="https://embeddings.example.com/v1/",
        api_key=SecretStr(api_key) if api_key else None,
        model="example-embedding-model",
        transport=httpx.MockTransport(handler),
    )


def _llm(
    handler: Handler, api_key: str | None = "llm-key", reasoning_effort: str | None = None
) -> OpenAICompatibleLLMProvider:
    return OpenAICompatibleLLMProvider(
        base_url="https://llm.example.com/v1",
        api_key=SecretStr(api_key) if api_key else None,
        model="example-chat-model",
        reasoning_effort=reasoning_effort,
        transport=httpx.MockTransport(handler),
    )


def _embedding_body(request: httpx.Request) -> dict[str, Any]:
    inputs = json.loads(request.content)["input"]
    # Reversed on purpose: the provider must order vectors by `index`.
    data = [{"index": index, "embedding": [float(index), 1.0]} for index in range(len(inputs))]
    return {"data": data[::-1], "model": "example-embedding-model"}


async def test_embeddings_request_uses_the_configured_url_key_and_model() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_embedding_body(request))

    provider = _embeddings(handler)
    vectors = await provider.embed_documents(["first", "second", "third"])
    query = await provider.embed_query("question")
    await provider.aclose()

    assert vectors == [[0.0, 1.0], [1.0, 1.0], [2.0, 1.0]]
    assert query == [0.0, 1.0]
    assert str(requests[0].url) == "https://embeddings.example.com/v1/embeddings"
    assert requests[0].headers["authorization"] == "Bearer embedding-key"
    assert json.loads(requests[0].content) == {
        "model": "example-embedding-model",
        "input": ["first", "second", "third"],
    }
    assert json.loads(requests[1].content)["input"] == ["question"]


async def test_embeddings_are_requested_in_batches() -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        batch_sizes.append(len(json.loads(request.content)["input"]))
        return httpx.Response(200, json=_embedding_body(request))

    vectors = await _embeddings(handler).embed_documents(["text"] * (BATCH_SIZE + 3))

    assert batch_sizes == [BATCH_SIZE, 3]
    assert len(vectors) == BATCH_SIZE + 3


async def test_embeddings_without_a_key_send_no_authorization_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json=_embedding_body(request))

    assert await _embeddings(handler, api_key=None).embed_query("question") == [0.0, 1.0]


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(429, True), (500, True), (503, True), (400, False), (401, False), (404, False)],
)
async def test_embedding_errors_say_whether_a_retry_can_help(
    status_code: int, retryable: bool
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "nope"}})

    with pytest.raises(ProviderError) as error:
        await _embeddings(handler).embed_query("question")

    assert error.value.retryable is retryable
    assert str(status_code) in str(error.value)
    assert "embedding-key" not in str(error.value)


async def test_embedding_timeout_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError) as error:
        await _embeddings(handler).embed_query("question")

    assert error.value.retryable is True


@pytest.mark.parametrize(
    "body",
    [
        {"data": []},
        {"data": [{"index": 0, "embedding": []}]},
        {"data": [{"index": 0, "embedding": ["a"]}]},
        {"data": [{"index": 5, "embedding": [1.0]}]},
        {"unexpected": True},
    ],
)
async def test_embedding_response_of_the_wrong_shape_is_rejected(body: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(ProviderError) as error:
        await _embeddings(handler).embed_query("question")

    assert error.value.retryable is False


async def test_llm_request_and_response_follow_chat_completions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "example-chat-model-2026",
                "choices": [{"message": {"role": "assistant", "content": '{"answer": "ok"}'}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 15, "total_tokens": 135},
            },
        )

    provider = _llm(handler)
    response = await provider.complete(
        [ChatMessage("system", "Rules."), ChatMessage("user", "Question?")],
        temperature=0.0,
        max_output_tokens=300,
        json_output=True,
    )
    await provider.aclose()

    assert response.text == '{"answer": "ok"}'
    assert response.model == "example-chat-model-2026"
    assert response.usage == TokenUsage(input_tokens=120, output_tokens=15)
    assert str(requests[0].url) == "https://llm.example.com/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer llm-key"
    assert json.loads(requests[0].content) == {
        "model": "example-chat-model",
        "messages": [
            {"role": "system", "content": "Rules."},
            {"role": "user", "content": "Question?"},
        ],
        "temperature": 0.0,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }


async def test_llm_request_omits_optional_parameters_and_usage_may_be_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert set(json.loads(request.content)) == {"model", "messages"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hello."}}]})

    response = await _llm(handler, api_key=None).complete([ChatMessage("user", "Hi")])

    assert (response.text, response.model, response.usage) == (
        "Hello.",
        "example-chat-model",
        None,
    )


async def test_llm_request_sends_the_configured_reasoning_effort() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["reasoning_effort"] == "low"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hello."}}]})

    response = await _llm(handler, reasoning_effort="low").complete([ChatMessage("user", "Hi")])

    assert response.text == "Hello."


async def test_a_reply_cut_off_by_the_token_limit_names_the_fix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
        )

    with pytest.raises(ProviderError) as error:
        await _llm(handler).complete([ChatMessage("user", "Hi")], max_output_tokens=10)

    assert "LLM_REASONING_EFFORT" in str(error.value)
    assert error.value.retryable is False


@pytest.mark.parametrize(
    ("status_code", "retryable"), [(429, True), (502, True), (400, False), (403, False)]
)
async def test_llm_errors_say_whether_a_retry_can_help(status_code: int, retryable: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="upstream said no")

    with pytest.raises(ProviderError) as error:
        await _llm(handler).complete([ChatMessage("user", "Hi")])

    assert error.value.retryable is retryable
    assert "llm-key" not in str(error.value)


@pytest.mark.parametrize(
    "body", [{"choices": []}, {"choices": [{"message": {"content": "  "}}]}, {"choices": "none"}]
)
async def test_llm_response_without_text_is_rejected(body: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(ProviderError):
        await _llm(handler).complete([ChatMessage("user", "Hi")])


async def test_llm_connection_failure_and_non_json_body() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    with pytest.raises(ProviderError) as connection_error:
        await _llm(refuse).complete([ChatMessage("user", "Hi")])
    with pytest.raises(ProviderError) as body_error:
        await _llm(html).complete([ChatMessage("user", "Hi")])

    assert connection_error.value.retryable is True
    assert body_error.value.retryable is False


async def test_local_llm_never_generates_text() -> None:
    provider = LocalLLMProvider()

    with pytest.raises(ProviderError) as error:
        await provider.complete([ChatMessage("user", "Hi")])

    assert provider.live is False
    assert provider.model_name is None
    assert error.value.retryable is False
