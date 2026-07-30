import asyncio
import json

import httpx
import pytest

from server.config import OperationConfig
from server.provider import AsyncProvider, ProviderError
from server.token_accounting import (
    _deepseek_v4_prompt,
    build_provider_payload,
    count_provider_payload,
)


def config(**changes):
    value = OperationConfig(base_url="https://provider.example/v1", model_id="model", system_prompt="quoted data only", context_window_tokens=1000, max_output_tokens=100, safety_margin_tokens=10, api_key="secret")
    return value.__class__(**{**value.to_dict(include_secret=True), **changes})


def test_provider_payload_is_exact_and_accounted():
    cfg = config(structured_output_mode="json_object")
    user = {"task": "keyword_expansion", "query": "a"}
    messages = [{"role": "system", "content": cfg.system_prompt}, {"role": "user", "content": json.dumps(user, ensure_ascii=False, separators=(",", ":"))}]
    payload = build_provider_payload(cfg, operation="keyword_expansion", messages=messages, user_object=user, response_schema=None)
    assert set(payload) == {"model", "messages", "temperature", "max_tokens", "response_format"}
    result = count_provider_payload(payload, cfg)
    assert result.input_tokens > 0
    assert result.fits


def test_huggingface_chat_template_counts_returned_token_ids(monkeypatch):
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            assert len(messages) == 2
            assert kwargs == {
                "tokenize": True,
                "add_generation_prompt": True,
                "return_dict": False,
            }
            return [1, 2, 3, 4]

        def encode(self, text, *, add_special_tokens):
            assert add_special_tokens is False
            return [1, 2, 3]

    monkeypatch.setattr(
        "server.token_accounting._load_local_tokenizer",
        lambda _name, _revision: Tokenizer(),
    )
    cfg = config(
        accounting_mode="huggingface_chat_template",
        tokenizer_name="official/model",
        structured_output_mode="json_object",
        provider_wrapper_tokens=2,
    )
    user = {"task": "keyword_expansion", "query": "a"}
    messages = [
        {"role": "system", "content": cfg.system_prompt},
        {
            "role": "user",
            "content": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
        },
    ]
    payload = build_provider_payload(
        cfg,
        operation="keyword_expansion",
        messages=messages,
        user_object=user,
        response_schema=None,
    )
    assert count_provider_payload(payload, cfg).input_tokens == 9


def test_deepseek_v4_accounting_uses_published_two_message_encoding(monkeypatch):
    captured = {}

    class Tokenizer:
        def encode(self, text, *, add_special_tokens):
            captured["text"] = text
            assert add_special_tokens is False
            return [1, 2, 3, 4, 5]

    monkeypatch.setattr(
        "server.token_accounting._load_local_tokenizer",
        lambda _name, _revision: Tokenizer(),
    )
    cfg = config(
        accounting_mode="deepseek_v4_official",
        tokenizer_name="deepseek-ai/DeepSeek-V4-Flash",
        provider_wrapper_tokens=2,
    )
    user = {"task": "keyword_expansion", "query": "a"}
    messages = [
        {"role": "system", "content": cfg.system_prompt},
        {
            "role": "user",
            "content": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
        },
    ]
    payload = build_provider_payload(
        cfg,
        operation="keyword_expansion",
        messages=messages,
        user_object=user,
        response_schema=None,
    )
    assert count_provider_payload(payload, cfg).input_tokens == 7
    assert captured["text"] == _deepseek_v4_prompt(payload)
    assert captured["text"].startswith(
        "<｜begin▁of▁sentence｜>quoted data only<｜User｜>"
    )
    assert captured["text"].endswith("<｜Assistant｜><think>")


def test_provider_success_and_safe_status_mapping():
    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer secret"
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"terms":["alpha"]}'}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}, headers={"x-request-id": "safe-id"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = await AsyncProvider(client).chat("keyword_expansion", config(), messages=[{"role": "system", "content": "quoted data only"}, {"role": "user", "content": '{"task":"keyword_expansion","query":"a"}'}], user_object={"task": "keyword_expansion", "query": "a"}, response_schema=None)
        assert result.content == '{"terms":["alpha"]}'
        assert result.usage_source == "provider_reported"
        await client.aclose()
    asyncio.run(run())


def test_provider_http_error_does_not_leak_body():
    async def run():
        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(503, text="question-secret-output")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with pytest.raises(ProviderError) as caught:
            await AsyncProvider(client).chat("keyword_expansion", config(), messages=[{"role": "system", "content": "quoted data only"}, {"role": "user", "content": '{"task":"keyword_expansion","query":"a"}'}], user_object={"task": "keyword_expansion", "query": "a"}, response_schema=None)
        assert caught.value.code == "PROVIDER_UNAVAILABLE"
        assert "question-secret-output" not in str(caught.value)
        await client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize(
    ("exception_type", "expected_code"),
    [
        (httpx.ConnectTimeout, "PROVIDER_TIMEOUT"),
        (httpx.ReadTimeout, "PROVIDER_TIMEOUT"),
        (httpx.WriteTimeout, "PROVIDER_TIMEOUT"),
        (httpx.PoolTimeout, "PROVIDER_TIMEOUT"),
        (httpx.ConnectError, "PROVIDER_UNAVAILABLE"),
        (httpx.ReadError, "PROVIDER_UNAVAILABLE"),
        (httpx.WriteError, "PROVIDER_UNAVAILABLE"),
    ],
)
def test_provider_transport_failures_are_retryable_and_safe(exception_type, expected_code):
    async def run():
        async def handler(request: httpx.Request) -> httpx.Response:
            raise exception_type("transport-secret", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ProviderError) as caught:
                await AsyncProvider(client).chat(
                    "keyword_expansion",
                    config(),
                    messages=[
                        {"role": "system", "content": "quoted data only"},
                        {"role": "user", "content": '{"task":"keyword_expansion","query":"a"}'},
                    ],
                    user_object={"task": "keyword_expansion", "query": "a"},
                    response_schema=None,
                )
            assert caught.value.code == expected_code
            assert caught.value.retryable is True
            assert "transport-secret" not in str(caught.value)
        finally:
            await client.aclose()

    asyncio.run(run())


def test_provider_cancellation_propagates_without_reclassification():
    async def run():
        entered = asyncio.Event()

        async def handler(_request: httpx.Request) -> httpx.Response:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            task = asyncio.create_task(
                AsyncProvider(client).chat(
                    "keyword_expansion",
                    config(),
                    messages=[
                        {"role": "system", "content": "quoted data only"},
                        {"role": "user", "content": '{"task":"keyword_expansion","query":"a"}'},
                    ],
                    user_object={"task": "keyword_expansion", "query": "a"},
                    response_schema=None,
                )
            )
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await client.aclose()

    asyncio.run(run())
