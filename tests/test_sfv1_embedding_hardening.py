import asyncio
import json
import threading
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import EmbeddingConfig, GlobalConfig
from server.embeddings import EmbeddingService
from tests.sfv1_support import FakeEmbeddingModel, configured_service, fake_provider, server_config


def embedding_app(tmp_path, *, config=None, model=None):
    selected = config or server_config()
    service, _ = configured_service(tmp_path, selected)
    embedding = EmbeddingService(selected.embedding, model=model or FakeEmbeddingModel(dimensions=selected.embedding.required_dimensions or 3))
    return create_app(config_service=service, provider=fake_provider(), embedding_service=embedding), service


def test_embedding_progress_is_measured_and_every_control_changes_batching(tmp_path):
    embedding = EmbeddingConfig(model_name="fake", required_dimensions=3, internal_batch_size=7, worker_count=1, max_queued_workloads=2, progress_min_interval_ms=0)
    config = server_config(embedding=embedding)
    app, _ = embedding_app(tmp_path, config=config)
    items = [{"message_id": f"m{i}", "text": f"text {i}"} for i in range(20)]
    with TestClient(app) as client:
        response = client.post("/v1/embeddings", json={"request_id": str(uuid.uuid4()), "items": items})
        events = [json.loads(line) for line in response.text.splitlines()]
    starts = [event for event in events if event["event"] == "embedding_batch_started"]
    assert [event["data"]["item_count"] for event in starts] == [7, 7, 6]
    progress = [event["data"] for event in events if event["event"] == "embedding_progress"]
    assert progress[-1]["completed_items"] == 20
    assert all(item["server_items_per_second"] > 0 for item in progress)


def test_embedding_profile_fingerprint_changes_with_actual_weights():
    config = EmbeddingConfig(model_name="same-name", required_dimensions=3)

    async def profiles():
        first = EmbeddingService(config, model=FakeEmbeddingModel(weight=1.0))
        second = EmbeddingService(config, model=FakeEmbeddingModel(weight=2.0))
        try:
            return (await first.prepare()).profile_id, (await second.prepare()).profile_id
        finally:
            await first.close_async()
            await second.close_async()

    first, second = asyncio.run(profiles())
    assert first != second


def test_embedding_body_and_item_ceilings_fail_before_stream(tmp_path):
    embedding = EmbeddingConfig(model_name="fake", required_dimensions=3, maximum_items=2, maximum_request_bytes=400)
    config = server_config(global_config=GlobalConfig(maximum_embedding_items=2, maximum_embedding_request_bytes=400), embedding=embedding)
    app, _ = embedding_app(tmp_path, config=config)
    with TestClient(app) as client:
        response = client.post("/v1/embeddings", json={"request_id": str(uuid.uuid4()), "items": [{"message_id": f"m{i}", "text": "x"} for i in range(3)]})
        assert response.status_code == 413
        assert response.json()["code"] == "WORKLOAD_TOO_LARGE"


def test_embedding_drain_includes_already_accepted_queued_workloads():
    async def run():
        config = EmbeddingConfig(
            model_name="fake",
            required_dimensions=3,
            worker_count=1,
            max_queued_workloads=1,
        )
        service = EmbeddingService(config, model=FakeEmbeddingModel())
        await service.prepare()
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        second_entered = asyncio.Event()

        async def first():
            async with service.workload(1):
                first_entered.set()
                await release_first.wait()

        async def second():
            async with service.workload(1):
                second_entered.set()

        first_task = asyncio.create_task(first())
        await first_entered.wait()
        second_task = asyncio.create_task(second())
        while service._workloads.queued != 1:
            await asyncio.sleep(0)

        draining = asyncio.create_task(service.stop_accepting_and_drain())
        await asyncio.sleep(0)
        assert not draining.done()
        release_first.set()
        await asyncio.gather(first_task, second_task, draining)
        assert second_entered.is_set()
        assert service.status()["accepting"] is False
        await service.close_async()

    asyncio.run(run())


def test_timed_out_embedding_job_keeps_model_lease_until_thread_finishes():
    class BlockingModel(FakeEmbeddingModel):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()

        def encode(self, texts, normalize_embeddings):
            self.entered.set()
            if not self.release.wait(5):
                raise RuntimeError("test did not release blocking model")
            return super().encode(texts, normalize_embeddings)

    async def run():
        model = BlockingModel()
        config = EmbeddingConfig(
            model_name="fake",
            required_dimensions=3,
            executor_timeout_seconds=0.01,
        )
        service = EmbeddingService(config, model=model)
        await service.prepare()
        with pytest.raises(asyncio.TimeoutError):
            await service.encode(["one"])
        assert model.entered.is_set()
        assert service.status()["backend_jobs_in_flight"] == 1
        draining = asyncio.create_task(service.stop_accepting_and_drain())
        await asyncio.sleep(0)
        assert not draining.done()
        model.release.set()
        await draining
        assert service.status()["backend_jobs_in_flight"] == 0
        await service.close_async()

    asyncio.run(run())


@pytest.mark.scale
def test_single_public_workload_streams_ten_thousand_items_without_collection(tmp_path):
    embedding = EmbeddingConfig(model_name="fake", required_dimensions=3, internal_batch_size=256, maximum_items=10_000, progress_min_interval_ms=0)
    config = server_config(global_config=GlobalConfig(maximum_embedding_items=10_000), embedding=embedding)
    app, _ = embedding_app(tmp_path, config=config)
    items = [{"message_id": f"m{i:05d}", "text": f"text {i}"} for i in range(10_000)]
    with TestClient(app) as client:
        response = client.post("/v1/embeddings", json={"request_id": str(uuid.uuid4()), "items": items})
        events = [json.loads(line) for line in response.text.splitlines()]
    vector_ids = [item["message_id"] for event in events if event["event"] == "vector_batch" for item in event["data"]["items"]]
    assert vector_ids == [item["message_id"] for item in items]
    assert events[-1]["event"] == "completed"
    assert events[-1]["result"]["total_items"] == 10_000
