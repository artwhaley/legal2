import json
import uuid

from fastapi.testclient import TestClient

from server.config import GlobalConfig
from tests.test_qpa1_analysis_plan import _app, _body
from tests.test_qpa1_orchestration import _analysis_body, _messages
from tests.sfv1_support import server_config


def test_small_corpus_uses_one_extraction_window_and_completes(tmp_path):
    app = _app(tmp_path, config=server_config(global_config=GlobalConfig(retrieval_assistance_mode="none")))
    with TestClient(app) as client:
        plan = client.post("/v1/conversational-plan", json=_body()).json()
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages(2)))
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert response.status_code == 200
    assert events[-1]["event"] == "completed"
    assert events[-1]["result"]["strategy"] == "single_window_ledger"


def test_oversized_corpus_uses_all_windows_and_preserves_message_coverage(tmp_path):
    base = server_config(global_config=GlobalConfig(retrieval_assistance_mode="none"))
    from dataclasses import replace
    from tests.sfv1_support import with_resolved_operations
    operations = dict(base.operations)
    operations["window_evidence_extraction"] = replace(operations["window_evidence_extraction"], context_window_tokens=1600, max_output_tokens=100, safety_margin_tokens=20)
    app = _app(tmp_path, config=with_resolved_operations(base, operations))
    messages = [{"message_id": f"m{i}", "thread_id": "t1", "timestamp": f"2026-01-01T00:{i:02d}:00Z", "sender": "a", "text": "x" * 300} for i in range(1, 9)]
    with TestClient(app) as client:
        plan = client.post("/v1/conversational-plan", json=_body()).json()
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, messages))
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[-1]["event"] == "completed"
    assert events[-1]["result"]["strategy"] == "multi_window_ledger"
    assert events[-1]["result"]["coverage"]["message_count"] == 8
    assert sum(event["event"] == "window_started" for event in events) > 1
