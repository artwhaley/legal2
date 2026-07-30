import asyncio
import json
import uuid
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import GlobalConfig
from server.provider import AsyncProvider, ProviderError
from server.resilience import ResilienceController
from tests.sfv1_support import configured_service, fake_embedding_service, server_config


def keyword_app(tmp_path, *, content='{"terms":["school"]}', status=200, include_usage=True, config=None, calls=None):
    selected = config or server_config()
    service, _ = configured_service(tmp_path, selected)
    calls = calls if calls is not None else []

    def handler(request):
        calls.append(request)
        if status != 200:
            return httpx.Response(status, text="provider response body must stay private")
        body = {"choices": [{"message": {"content": content}}]}
        if include_usage:
            body["usage"] = {"prompt_tokens": 7, "completion_tokens": 3}
        return httpx.Response(200, json=body)

    provider = AsyncProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    app = create_app(config_service=service, provider=provider, embedding_service=fake_embedding_service(selected))
    return app, service, calls


@pytest.mark.parametrize(("status", "expected_status", "code"), [
    (400, 502, "PROVIDER_REJECTED"),
    (401, 502, "PROVIDER_REJECTED"),
    (403, 502, "PROVIDER_REJECTED"),
    (404, 502, "PROVIDER_REJECTED"),
    (422, 502, "PROVIDER_REJECTED"),
    (429, 429, "PROVIDER_RATE_LIMITED"),
    (500, 503, "PROVIDER_UNAVAILABLE"),
    (502, 503, "PROVIDER_UNAVAILABLE"),
    (503, 503, "PROVIDER_UNAVAILABLE"),
    (504, 503, "PROVIDER_UNAVAILABLE"),
])
def test_provider_status_matrix_is_safe_and_exact(tmp_path, status, expected_status, code):
    app, _, _ = keyword_app(tmp_path / str(status), status=status)
    with TestClient(app) as client:
        response = client.post("/v1/keyword-expansion", json={"request_id": str(uuid.uuid4()), "query": "school"})
    assert response.status_code == expected_status
    assert response.json()["code"] == code
    assert "provider response body" not in response.text


@pytest.mark.parametrize("content", [
    "{}",
    '{"terms":[]}',
    '{"terms":[1]}',
    '{"terms":["school"],"extra":true}',
    "```json\n{\"terms\":[\"school\"]}\n```",
    'prose {"terms":["school"]}',
])
def test_model_output_matrix_rejects_missing_wrong_extra_fence_and_prose(tmp_path, content):
    app, service, calls = keyword_app(tmp_path / str(abs(hash(content))), content=content)
    with TestClient(app) as client:
        response = client.post("/v1/keyword-expansion", json={"request_id": str(uuid.uuid4()), "query": "school"})
        rows = service.store.conn.execute("SELECT outcome,error_code FROM usage_event").fetchall()
    assert response.status_code == 502
    assert response.json()["code"] == "MODEL_OUTPUT_INVALID"
    assert len(calls) == 1
    assert [(row["outcome"], row["error_code"]) for row in rows] == [("failure", "MODEL_OUTPUT_INVALID")]


def test_missing_provider_usage_is_estimated_from_exact_payload_and_output(tmp_path):
    app, _, _ = keyword_app(tmp_path, include_usage=False)
    with TestClient(app) as client:
        result = client.post("/v1/keyword-expansion", json={"request_id": str(uuid.uuid4()), "query": "school"}).json()
    assert result["usage"]["source"] == "estimated"
    assert result["usage"]["input_tokens"] > 0
    assert result["usage"]["output_tokens"] > 0


def test_accounting_failure_prevents_success_and_retry(tmp_path):
    calls = []
    app, service, _ = keyword_app(tmp_path, calls=calls)
    original = service.store.record_usage

    def fail_accounting(**fields):
        raise OSError("synthetic durable accounting failure")

    service.store.record_usage = fail_accounting
    try:
        with TestClient(app) as client:
            response = client.post("/v1/keyword-expansion", json={"request_id": str(uuid.uuid4()), "query": "school"})
        assert response.status_code == 500
        assert response.json()["code"] == "ACCOUNTING_PERSISTENCE_FAILED"
        assert len(calls) == 1
    finally:
        service.store.record_usage = original


def test_operation_deadline_prevents_another_attempt():
    operation = server_config().operations["keyword_expansion"]
    operation = replace(operation, operation_deadline_seconds=0.02, max_attempts=3, backoff_base_seconds=0.02, retryable_statuses=(503,))
    controller = ResilienceController({"keyword_expansion": operation}, GlobalConfig())
    attempts = []

    async def run():
        async def call(attempt):
            attempts.append(attempt)
            raise ProviderError("PROVIDER_UNAVAILABLE", "temporary", status_code=503, retryable=True)
        with pytest.raises(ProviderError) as caught:
            await controller.run("keyword_expansion", call)
        assert caught.value.code == "PROVIDER_TIMEOUT"

    asyncio.run(run())
    assert attempts == [1]


def test_request_body_ceiling_is_enforced_before_json_decode(tmp_path):
    config = server_config(global_config=GlobalConfig(maximum_product_request_bytes=80))
    app, _, _ = keyword_app(tmp_path, config=config)
    with TestClient(app) as client:
        response = client.post("/v1/keyword-expansion", content=b"{" + b"x" * 200, headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["code"] == "WORKLOAD_TOO_LARGE"
