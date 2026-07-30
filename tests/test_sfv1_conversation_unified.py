import json
from dataclasses import replace

from fastapi.testclient import TestClient

from server.config import GlobalConfig
from tests.test_qpa1_analysis_plan import _app, _body
from tests.test_qpa1_orchestration import _analysis_body
from tests.sfv1_support import fake_provider, server_config, with_resolved_operations


def _messages():
    return [{"message_id": "m1", "thread_id": "thread-1", "timestamp": "2026-01-01T00:00:00Z", "sender": "Person", "text": "We discussed the question."}]


def test_semantic_conversation_uses_one_unified_ledger_stream(tmp_path):
    app = _app(tmp_path, config=server_config(global_config=GlobalConfig(retrieval_assistance_mode="semantic_ranges")))
    with TestClient(app) as client:
        plan = client.post("/v1/conversational-plan", json=_body()).json()
        body = _analysis_body(plan, _messages())
        body["analysis_context"]["hits"] = [{"query_id": "q0001", "message_id": "m1", "rank": 1, "distance": 0.1}]
        response = client.post("/v1/conversational-analysis", json=body)
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert response.status_code == 200
    assert events[-1]["event"] == "completed"
    assert events[-1]["result"]["retrieval_diagnostics"]["selected_suggestion_message_count"] == 1
    assert "analysis_plan_accepted" in [event["event"] for event in events]


def test_synthesis_overflow_emits_loud_compaction_progress(tmp_path):
    base = server_config(global_config=GlobalConfig(retrieval_assistance_mode="none"))
    operations = dict(base.operations)
    operations["ledger_synthesis"] = replace(operations["ledger_synthesis"], target_input_tokens=1450)
    config = with_resolved_operations(base, operations)
    app = _app(tmp_path, config=config, provider=fake_provider())
    with TestClient(app) as client:
        plan = client.post("/v1/conversational-plan", json=_body()).json()
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, [{"message_id": f"m{i}", "thread_id": "t1", "timestamp": str(i), "sender": "p", "text": "message" * 20} for i in range(1, 9)]))
    events = [json.loads(line) for line in response.text.splitlines() if line]
    names = [event["event"] for event in events]
    assert response.status_code == 200
    assert events[-1]["event"] == "completed"
    assert "ledger_compaction_required" in names
    assert "ledger_compaction_completed" in names


def test_reversed_valid_range_is_normalized_and_reported_as_partial_or_complete(tmp_path):
    def reverse_range(user, output):
        if user["task"] == "window_evidence_extraction":
            output["evidence_ranges"][0]["start_message_id"] = user["messages"][-1]["message_id"]
            output["evidence_ranges"][0]["end_message_id"] = user["messages"][0]["message_id"]
        return output

    app = _app(tmp_path, provider=fake_provider(mutate=reverse_range))
    messages = [
        {"message_id": "source:20", "thread_id": "thread-1", "timestamp": "1", "sender": "Person", "text": "one"},
        {"message_id": "source:19", "thread_id": "thread-1", "timestamp": "2", "sender": "Person", "text": "two"},
    ]
    with TestClient(app) as client:
        plan = client.post("/v1/conversational-plan", json=_body()).json()
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, messages))
    events = [json.loads(line) for line in response.text.splitlines() if line]
    result = events[-1]
    assert response.status_code == 200
    assert result["event"] == "completed"
    assert result["result"]["evidence_ledger"][0]["normalizations"] == ["endpoint_order_swapped"]
