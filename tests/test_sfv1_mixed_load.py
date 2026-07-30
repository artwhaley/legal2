import asyncio
import json
import time
import uuid
from collections import defaultdict
from dataclasses import replace

import httpx
import pytest

from server.app import create_app
from server.config import EmbeddingConfig, GlobalConfig
from server.embeddings import EmbeddingService
from server.provider import AsyncProvider
from tests.sfv1_support import FakeEmbeddingModel, configured_service, output_for_user, server_config, with_resolved_operations


def _ndjson(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def _context(plan, message_id, *, distance=0.0):
    return {
        "analysis_plan_id": plan["analysis_plan_id"],
        "plan_config_version": plan["config_version"],
        "compatibility_fingerprint": plan["compatibility_fingerprint"],
        "analysis_plan": plan["analysis_plan"],
        "retrieval_queries": plan["retrieval_queries"],
        "embedding": plan["embedding"],
        "search_policy": plan["search_policy"],
        "hits": [
            {"query_id": query["query_id"], "message_id": message_id, "rank": 1, "distance": distance}
            for query in plan["retrieval_queries"]
        ],
    }


@pytest.mark.scale
def test_qpa1_mixed_load_is_bounded_and_admin_stays_responsive(tmp_path):
    active = defaultdict(int)
    maximum = defaultdict(int)
    lock = asyncio.Lock()

    async def handler(request):
        payload = json.loads(request.content)
        user = json.loads(payload["messages"][1]["content"])
        task = user["task"]
        async with lock:
            active[task] += 1
            maximum[task] = max(maximum[task], active[task])
        try:
            await asyncio.sleep(1.0 if task == "window_evidence_extraction" and user["messages"][0]["message_id"] == "c1" else 0.01)
            output = output_for_user(user)
            if task == "window_evidence_extraction" and user["messages"][0]["message_id"] == "p1":
                output["evidence_ranges"].append(
                    {
                        "thread_id": user["messages"][0]["thread_id"],
                        "start_message_id": "unknown-start",
                        "end_message_id": user["messages"][0]["message_id"],
                        "summary": "rejected fixture range",
                        "relevance": "invalid endpoint fixture",
                    }
                )
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(output)}}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 10},
                },
            )
        finally:
            async with lock:
                active[task] -= 1

    global_config = GlobalConfig(
        retrieval_assistance_mode="semantic_ranges",
        retrieval_maximum_prompt_suggestion_messages=1,
        retrieval_top_k_per_query=20,
        product_max_in_flight=4,
        product_max_queued=20,
        global_queue_wait_timeout_seconds=5,
        window_input_utilization_percent=100.0,
        maximum_concurrent_windows=2,
    )
    config = server_config(
        context_window_tokens=6_000,
        max_output_tokens=500,
        global_config=global_config,
        embedding=EmbeddingConfig(model_name="fake", required_dimensions=3, internal_batch_size=25, worker_count=1, max_queued_workloads=8),
        operation_changes={"max_in_flight": 2, "max_queued": 20, "queue_wait_timeout_seconds": 5},
    )
    operations = dict(config.operations)
    operations["window_evidence_extraction"] = replace(operations["window_evidence_extraction"], target_input_tokens=1_600)
    operations["ledger_synthesis"] = replace(operations["ledger_synthesis"], target_input_tokens=1_200)
    config = with_resolved_operations(config, operations)
    service, _ = configured_service(tmp_path, config)
    provider = AsyncProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    app = create_app(
        config_service=service,
        provider=provider,
        embedding_service=EmbeddingService(config.embedding, model=FakeEmbeddingModel(delay=0.005)),
    )

    def messages(prefix, count, width=20):
        return [
            {
                "message_id": f"{prefix}{i}",
                "thread_id": "t1",
                "timestamp": f"2026-01-01T00:{i:02d}:00Z",
                "sender": "A",
                "text": "school meeting " + ("x" * width),
            }
            for i in range(1, count + 1)
        ]

    async def run():
        latencies = []
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                async def timed(coro):
                    started = time.perf_counter()
                    response = await coro
                    latencies.append((time.perf_counter() - started) * 1000)
                    return response

                plan_responses = await asyncio.gather(*[
                    timed(client.post("/v1/conversational-plan", json={"request_id": str(uuid.uuid4()), "question": "What happened?"}))
                    for _ in range(3)
                ])
                assert all(response.status_code == 200 for response in plan_responses)
                plans = [response.json() for response in plan_responses]

                embedding_responses = await asyncio.gather(*[
                    timed(client.post("/v1/embeddings", json={"request_id": str(uuid.uuid4()), "items": [{"message_id": query["query_id"], "text": query["text"]} for query in plan["retrieval_queries"]]}))
                    for plan in plans
                ])
                assert all(response.status_code == 200 for response in embedding_responses)
                assert all(_ndjson(response)[-1]["event"] == "completed" for response in embedding_responses)

                admin_during_prep = await asyncio.gather(*(timed(client.get("/admin/")) for _ in range(2)))
                assert all(response.status_code == 200 for response in admin_during_prep)

                requests = []
                for index, plan in enumerate(plans):
                    prefix = "p" if index == 0 else "s"
                    corpus = messages(prefix, 1 if index == 0 else 12, 600 if index else 20)
                    requests.append(timed(client.post("/v1/conversational-analysis", json={
                        "request_id": str(uuid.uuid4()),
                        "question": "What happened?",
                        "working_corpus": {"scope_id": f"scope-{index}", "messages": corpus},
                        "analysis_context": _context(plan, corpus[0]["message_id"]),
                    })))
                # A second large request forces concurrent multi-window work and compaction.
                corpus = messages("l", 12, 600)
                requests.append(timed(client.post("/v1/conversational-analysis", json={
                    "request_id": str(uuid.uuid4()),
                    "question": "What happened?",
                    "working_corpus": {"scope_id": "scope-large", "messages": corpus},
                    "analysis_context": _context(plans[1], corpus[0]["message_id"]),
                })))
                analyses = await asyncio.gather(*requests)
                admin_started = time.perf_counter()
                admin_response = await client.get("/admin/")
                admin_latency = (time.perf_counter() - admin_started) * 1000
                assert admin_response.status_code == 200
                audit_text = json.dumps(service.store.audit_history(), ensure_ascii=False)

                cancellation_coro = asyncio.create_task(client.post("/v1/conversational-analysis", json={
                    "request_id": str(uuid.uuid4()),
                    "question": "What happened?",
                        "working_corpus": {"scope_id": "scope-cancel", "messages": messages("c", 12, 600)},
                    "analysis_context": _context(plans[2], "c1"),
                }))
                cancellation_coro.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await cancellation_coro
        return plan_responses, embedding_responses, analyses, latencies, admin_latency, audit_text

    plans, embeddings, analyses, latencies, admin_latency, audit_text = asyncio.run(run())
    assert len(plans) == len(embeddings) == 3
    assert len(analyses) == 4
    assert all(response.status_code == 200 for response in plans + embeddings + analyses), [
        (response.status_code, response.text[:500])
        for response in plans + embeddings + analyses
        if response.status_code != 200
    ]
    parsed = [_ndjson(response) for response in analyses]
    assert all(events[-1]["event"] == "completed" for events in parsed)
    assert all([event["sequence"] for event in events] == list(range(1, len(events) + 1)) for events in parsed)
    assert any(events[-1]["result"]["completion_status"] == "partial" for events in parsed)
    assert any(events[-1]["result"]["ledger_processing"]["compaction_applied"] for events in parsed)
    assert any(events[-1]["result"]["strategy"] == "multi_window_ledger" for events in parsed)
    assert all(value <= 2 for value in maximum.values())
    assert admin_latency < 1_000
    assert "school meeting" not in audit_text
