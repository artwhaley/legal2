import json
import uuid
from dataclasses import replace

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import EmbeddingConfig
from server.config_service import ConfigurationService
from server.embeddings import EmbeddingService
from tests.test_sfv1_control_store import make_config


class FakeModel:
    def __init__(self, *, fail_after=None):
        self.calls = 0
        self.fail_after = fail_after

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts, normalize_embeddings):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("synthetic embedding failure")
        return [[1.0, 0.0, 0.0] for _ in texts]


def embedding_app(tmp_path, model):
    service = ConfigurationService(tmp_path)
    service.startup()
    draft = service.store.draft()[0]
    config = replace(make_config(), embedding=EmbeddingConfig(model_name="fake", required_dimensions=3, internal_batch_size=32, maximum_items=10000))
    service.store.save_draft(draft, config)
    for provider_id in config.provider_accounts:
        service.store.set_secret(draft, provider_id, "synthetic-secret-1234")
    service.activate(draft)
    return create_app(config_service=service, embedding_service=EmbeddingService(config.embedding, model=model))


def test_embedding_request_is_complete_workload_and_streams_internal_batches(tmp_path):
    app = embedding_app(tmp_path, FakeModel())
    body = {"request_id": str(uuid.uuid4()), "items": [{"message_id": f"m{i}", "text": f"text {i}"} for i in range(65)]}
    with TestClient(app) as client:
        response = client.post("/v1/embeddings", json=body)
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["data"]["total_items"] == 65
        assert [event["data"]["batch_index"] for event in events if event["event"] == "embedding_batch_started"] == [0, 1, 2]
        assert events[-1]["event"] == "completed"


def test_embedding_failure_reports_exact_batch_and_terminal_failure(tmp_path):
    app = embedding_app(tmp_path, FakeModel(fail_after=1))
    body = {"request_id": str(uuid.uuid4()), "items": [{"message_id": f"m{i}", "text": f"text {i}"} for i in range(65)]}
    with TestClient(app) as client:
        response = client.post("/v1/embeddings", json=body)
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[-1]["event"] == "failed"
        assert events[-1]["error"]["details"]["batch_index"] == 1
        assert events[-1]["error"]["details"]["first_item_index"] == 32
        assert events[-1]["error"]["details"]["last_item_index"] == 63
