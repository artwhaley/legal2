import json
import uuid

import httpx
from fastapi.testclient import TestClient

from server.app import create_app
from server.provider import AsyncProvider
from tests.sfv1_support import configured_service, fake_embedding_service


def configured_app(tmp_path, content='{"terms":["alpha","beta"]}', status=200):
    service, config = configured_service(tmp_path)
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(status, text=content, headers={"x-request-id": "provider-safe"}) if status != 200 else httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}})
    provider = AsyncProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return create_app(config_service=service, provider=provider, embedding_service=fake_embedding_service(config)), provider


def test_keyword_expansion_accepts_only_exact_terms_and_persists_usage(tmp_path):
    app, provider = configured_app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/v1/keyword-expansion", json={"request_id": str(uuid.uuid4()), "query": "school"})
        assert response.status_code == 200
        assert response.json()["terms"] == ["alpha", "beta"]
    provider.client = None


def test_keyword_expansion_rejects_whitespace_and_duplicates(tmp_path):
    app, provider = configured_app(tmp_path, content='{"terms":[" alpha ","alpha","alpha"]}')
    with TestClient(app) as client:
        response = client.post("/v1/keyword-expansion", json={"request_id": str(uuid.uuid4()), "query": "school"})
        assert response.status_code == 502
        assert response.json()["code"] == "MODEL_OUTPUT_INVALID"
    provider.client = None


def test_keyword_provider_failure_is_not_fallback(tmp_path):
    app, provider = configured_app(tmp_path, status=503, content="provider body secret")
    with TestClient(app) as client:
        response = client.post("/v1/keyword-expansion", json={"request_id": str(uuid.uuid4()), "query": "school"})
        assert response.status_code == 503
        assert response.json()["code"] == "PROVIDER_UNAVAILABLE"
        assert "provider body secret" not in response.text
    provider.client = None
