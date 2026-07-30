import asyncio
import json
import uuid
from dataclasses import replace

import httpx
from fastapi.testclient import TestClient

from server.conversation import plan_windows
from server.provider import AsyncProvider
from tests.test_qpa1_analysis_plan import _app, _body
from tests.test_qpa1_orchestration import _analysis_body, _messages
from tests.sfv1_support import fake_provider, server_config, with_resolved_operations


def _plan_for(client):
    response = client.post("/v1/conversational-plan", json=_body())
    assert response.status_code == 200
    return response.json()


def test_frozen_plan_reaches_extraction_and_synthesis_unchanged(tmp_path):
    calls = []
    app = _app(tmp_path, provider=fake_provider(calls=calls))
    with TestClient(app) as client:
        plan = _plan_for(client)
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages()))
    assert response.status_code == 200
    extraction = next(call["user"] for call in calls if call["user"]["task"] == "window_evidence_extraction")
    synthesis = next(call["user"] for call in calls if call["user"]["task"] == "ledger_synthesis")
    assert extraction["analysis_plan"] == plan["analysis_plan"]
    assert synthesis["analysis_plan"] == plan["analysis_plan"]


def test_window_planner_preserves_interleaved_thread_order_and_boundaries():
    config = server_config()
    operation = config.operations["window_evidence_extraction"]
    submitted = [
        {"message_id": f"{thread}-{index}", "thread_id": thread, "timestamp": str(index), "sender": "A", "text": f"{thread} {index}"}
        for index in range(3) for thread in ("thread-1", "thread-2")
    ]
    plan = {"analysis_question": "q", "answer_objective": "a", "concepts": [], "inclusion_criteria": [], "exclusion_criteria": [], "answer_requirements": [], "interpretive_assumptions": []}
    windows = plan_windows(submitted, question="q", analysis_plan=plan, retrieval_queries=[], operation=operation, utilization_percent=100.0)
    flattened = [message for window in windows for message in window.messages]
    assert [message["message_id"] for message in flattened] == [message["message_id"] for message in submitted]
    assert all(len({message["thread_id"] for message in window.messages}) == 1 for window in windows)


def test_compaction_preserves_every_range_id_in_new_contract(tmp_path):
    calls = []
    selected = server_config()
    operations = dict(selected.operations)
    operations["ledger_synthesis"] = replace(operations["ledger_synthesis"], target_input_tokens=1450)
    selected = with_resolved_operations(selected, operations)
    app = _app(tmp_path, config=selected, provider=fake_provider(calls=calls))
    with TestClient(app) as client:
        plan = _plan_for(client)
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages(8)))
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[-1]["event"] == "completed"
    if any(event["event"] == "ledger_compaction_group_completed" for event in events):
        compaction = next(call["user"] for call in calls if call["user"]["task"] == "ledger_compaction")
        assert "records_or_summaries" in compaction


def test_malformed_synthesis_shape_returns_readable_raw_answer_with_warning(tmp_path):
    def mutate(user, output):
        if user["task"] == "ledger_synthesis":
            del output["overview"]
        return output

    app = _app(tmp_path, provider=fake_provider(mutate=mutate))
    with TestClient(app) as client:
        plan = _plan_for(client)
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages()))
    terminal = json.loads(response.text.splitlines()[-1])
    assert terminal["event"] == "completed"
    assert terminal["result"]["answer_source"] == "raw_synthesis_output"
    assert terminal["result"]["synthesis_validation"]["status"] == "warnings"


def test_compaction_failure_returns_original_ledger_only_result(tmp_path):
    def mutate(user, output):
        if user["task"] == "ledger_compaction":
            return {"group_id": user["group_id"], "summary": "", "covered_range_ids": [], "uncertainties": []}
        return output

    selected = server_config()
    operations = dict(selected.operations)
    operations["ledger_synthesis"] = replace(operations["ledger_synthesis"], target_input_tokens=100)
    selected = with_resolved_operations(selected, operations)
    app = _app(tmp_path, config=selected, provider=fake_provider(mutate=mutate))
    with TestClient(app) as client:
        plan = _plan_for(client)
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages(8)))
    events = [json.loads(line) for line in response.text.splitlines() if line]
    terminal = events[-1]
    assert terminal["event"] == "completed"
    assert terminal["result"]["completion_status"] == "partial"
    assert terminal["result"]["answer_source"] == "synthesis_unavailable"
    assert terminal["result"]["evidence_ledger"]
    assert any(event.get("data", {}).get("code") == "COMPACTION_UNAVAILABLE" for event in events if event["event"] == "warning")
    assert any(event.get("data", {}).get("code") == "SYNTHESIS_UNAVAILABLE" for event in events if event["event"] == "warning")


def test_empty_compaction_output_retries_only_the_group(tmp_path):
    calls = []
    attempts = 0

    def mutate(user, output):
        nonlocal attempts
        if user["task"] == "ledger_compaction":
            attempts += 1
            if attempts == 1:
                return {}
        return output

    selected = server_config()
    operations = dict(selected.operations)
    operations["ledger_synthesis"] = replace(operations["ledger_synthesis"], target_input_tokens=100)
    operations["ledger_compaction"] = replace(operations["ledger_compaction"], max_attempts=2, backoff_base_seconds=0, backoff_jitter_seconds=0)
    selected = with_resolved_operations(selected, operations)
    app = _app(tmp_path, config=selected, provider=fake_provider(mutate=mutate, calls=calls))
    with TestClient(app) as client:
        plan = _plan_for(client)
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages(8)))
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[-1]["event"] == "completed"
    assert attempts >= 2
    assert any(event["event"] == "retry_wait" and event["data"]["operation"] == "ledger_compaction" for event in events)


def test_configured_retry_is_visible_and_accounted(tmp_path):
    attempts = 0

    async def handler(request):
        nonlocal attempts
        payload = json.loads(request.content)
        user = json.loads(payload["messages"][1]["content"])
        if user["task"] == "ledger_synthesis":
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, text="provider failure")
        from tests.sfv1_support import output_for_user
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output_for_user(user))}}], "usage": {"prompt_tokens": 101, "completion_tokens": 23}})

    config = server_config(operation_changes={"max_attempts": 2, "backoff_base_seconds": 0, "backoff_jitter_seconds": 0})
    from tests.sfv1_support import configured_service, fake_embedding_service
    service, _ = configured_service(tmp_path, config)
    app = __import__("server.app", fromlist=["create_app"]).create_app(config_service=service, provider=AsyncProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler))), embedding_service=fake_embedding_service(config))
    with TestClient(app) as client:
        plan = _plan_for(client)
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages()))
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert attempts == 2
    assert any(event["event"] == "retry_wait" for event in events)


def test_long_provider_call_emits_heartbeat(tmp_path):
    async def handler(request):
        payload = json.loads(request.content)
        user = json.loads(payload["messages"][1]["content"])
        if user["task"] == "window_evidence_extraction":
            await asyncio.sleep(0.05)
        from tests.sfv1_support import output_for_user
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output_for_user(user))}}], "usage": {"prompt_tokens": 101, "completion_tokens": 23}})

    selected = server_config(global_config=__import__("server.config", fromlist=["GlobalConfig"]).GlobalConfig(stream_heartbeat_seconds=0.01))
    from tests.sfv1_support import configured_service, fake_embedding_service
    service, _ = configured_service(tmp_path, selected)
    app = __import__("server.app", fromlist=["create_app"]).create_app(config_service=service, provider=AsyncProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler))), embedding_service=fake_embedding_service(selected))
    with TestClient(app) as client:
        plan = _plan_for(client)
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages()))
    assert any(json.loads(line)["event"] == "heartbeat" for line in response.text.splitlines() if line)
