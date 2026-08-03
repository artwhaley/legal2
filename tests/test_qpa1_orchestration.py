import json
import asyncio
import uuid
from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

from server.config import GlobalConfig
from server.contracts import AnalysisContext, FrozenAnalysisPlan, RetrievalQuery, SearchPolicy
from server.conversation_unified import _analysis_fingerprint, _validate_analysis_context
from tests.test_qpa1_analysis_plan import _app, _body
from tests.sfv1_support import fake_provider, server_config, with_resolved_operations


def _messages(count=2):
    return [
        {
            "message_id": f"m{index}",
            "thread_id": "t1",
            "timestamp": f"2026-01-01T00:0{index}:00Z",
            "sender": "Person",
            "text": f"Message {index} about the planned question.",
        }
        for index in range(1, count + 1)
    ]


def _analysis_body(plan, messages=None):
    return {
        "request_id": str(uuid.uuid4()),
        "question": "What happened in the messages?",
        "working_corpus": {"scope_id": "scope", "messages": messages or _messages()},
        "analysis_context": {
            "analysis_plan_id": plan["analysis_plan_id"],
            "plan_config_version": plan["config_version"],
            "compatibility_fingerprint": plan["compatibility_fingerprint"],
            "analysis_plan": plan["analysis_plan"],
            "retrieval_queries": plan["retrieval_queries"],
            "embedding": plan["embedding"],
            "search_policy": plan["search_policy"],
            "hits": [],
        },
    }


def test_none_mode_runs_one_frozen_plan_through_extraction_and_synthesis(tmp_path):
    app = _app(tmp_path, config=server_config(global_config=GlobalConfig(retrieval_assistance_mode="none")))
    with TestClient(app) as client:
        plan_response = client.post("/v1/conversational-plan", json=_body())
        assert plan_response.status_code == 200
        plan = plan_response.json()
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan))
    assert response.status_code == 200
    events = [line for line in response.text.splitlines() if line]
    names = [__import__("json").loads(line)["event"] for line in events]
    assert names[0:3] == ["accepted", "accounting_completed", "analysis_plan_accepted"]
    assert "evidence_validation_completed" in names
    assert names[-1] == "completed"
    result = __import__("json").loads(events[-1])["result"]
    assert result["completion_status"] == "complete"
    assert result["strategy"] == "single_window_ledger"
    assert result["coverage"]["message_count"] == 2


def test_planning_request_can_override_prompt_suggestion_limit(tmp_path):
    app = _app(
        tmp_path,
        config=server_config(
            global_config=GlobalConfig(retrieval_assistance_mode="none")
        ),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/conversational-plan",
            json={**_body(), "maximum_prompt_suggestion_messages": 17},
        )
    assert response.status_code == 200
    assert response.json()["search_policy"]["maximum_prompt_suggestion_messages"] == 17


def test_analysis_requires_the_frozen_context_and_old_route_is_not_invoked(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        missing = client.post("/v1/conversational-analysis", json={"request_id": str(uuid.uuid4()), "question": "q", "working_corpus": {"scope_id": "s", "messages": _messages()}})
        old = client.post("/v1/conversational-retrieval-plan", json=_body())
    assert missing.status_code == 422
    assert old.status_code == 404


def test_edited_frozen_plan_is_rejected_before_model_work(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        plan_response = client.post("/v1/conversational-plan", json=_body())
        assert plan_response.status_code == 200
        plan = plan_response.json()
        plan["analysis_plan"]["answer_objective"] = "edited"
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan))
    assert response.status_code == 409
    assert response.json()["code"] == "ANALYSIS_PLAN_STALE"


def test_unrelated_active_config_change_does_not_stale_a_frozen_plan():
    base = server_config(
        global_config=GlobalConfig(retrieval_assistance_mode="none")
    )
    changed_operations = dict(base.operations)
    changed_operations["window_evidence_extraction"] = replace(
        changed_operations["window_evidence_extraction"],
        system_prompt=changed_operations["window_evidence_extraction"].system_prompt
        + "\nUnrelated extraction revision.",
    )
    changed = replace(
        with_resolved_operations(base, changed_operations),
        config_version=base.config_version + 1,
    )
    plan = FrozenAnalysisPlan.model_validate(
        {
            "analysis_question": "Identify passages that answer the question.",
            "answer_objective": "Return a supported answer.",
            "concepts": [
                {
                    "label": "responsive passage",
                    "definition": "A passage that answers the question.",
                    "manifestations": ["direct discussion"],
                }
            ],
            "inclusion_criteria": ["Materially answers the question."],
            "exclusion_criteria": [],
            "answer_requirements": ["Cite evidence."],
            "interpretive_assumptions": [],
        }
    )
    context = AnalysisContext(
        analysis_plan_id=str(uuid.uuid4()),
        plan_config_version=base.config_version,
        compatibility_fingerprint="a" * 64,
        analysis_plan=plan,
        retrieval_queries=[RetrievalQuery(query_id="q0001", text="responsive passage")],
        embedding=None,
        search_policy=SearchPolicy(
            mode="none",
            top_k_per_query=base.global_config.retrieval_top_k_per_query,
            fusion_method="reciprocal_rank_fusion",
            rrf_constant=base.global_config.retrieval_rrf_constant,
            maximum_prompt_suggestion_messages=base.global_config.retrieval_maximum_prompt_suggestion_messages,
        ),
        hits=[],
    )
    fingerprint = _analysis_fingerprint(
        base,
        question="What happened?",
        context=context,
    )
    context = context.model_copy(
        update={"compatibility_fingerprint": fingerprint}
    )
    assert fingerprint == _analysis_fingerprint(
        changed,
        question="What happened?",
        context=context,
    )

    mode, accepted = asyncio.run(
        _validate_analysis_context(
            SimpleNamespace(),
            changed,
            SimpleNamespace(
                question="What happened?",
                analysis_context=context,
            ),
            _messages(),
        )
    )

    assert mode == "none"
    assert accepted is context


def test_partial_range_validation_preserves_valid_siblings_and_final_status(tmp_path):
    def mutate(user, output):
        if user["task"] == "window_evidence_extraction":
            messages = user["messages"]
            output["evidence_ranges"] = [
                {"thread_id": messages[0]["thread_id"], "start_message_id": messages[0]["message_id"], "end_message_id": messages[0]["message_id"], "summary": "first", "relevance": "responsive"},
                {"thread_id": messages[0]["thread_id"], "start_message_id": "fabricated", "end_message_id": messages[0]["message_id"], "summary": "bad", "relevance": "bad"},
                {"thread_id": messages[0]["thread_id"], "start_message_id": messages[1]["message_id"], "end_message_id": messages[1]["message_id"], "summary": "second", "relevance": "responsive"},
                {"thread_id": messages[0]["thread_id"], "start_message_id": messages[2]["message_id"], "end_message_id": messages[1]["message_id"], "summary": None, "relevance": "responsive"},
            ]
        return output

    app = _app(tmp_path, provider=fake_provider(mutate=mutate))
    with TestClient(app) as client:
        plan_response = client.post("/v1/conversational-plan", json=_body())
        assert plan_response.status_code == 200
        plan = plan_response.json()
        response = client.post("/v1/conversational-analysis", json=_analysis_body(plan, _messages(3)))
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line]
    window = next(event for event in events if event["event"] == "window_completed")
    validation = next(event for event in events if event["event"] == "evidence_validation_completed")
    result = events[-1]["result"]
    assert window["data"]["accepted_range_count"] == 3
    assert window["data"]["rejected_range_count"] == 1
    assert len(window["data"]["accepted_ranges"]) == 3
    assert all(item["start_message_id"] != "fabricated" for item in window["data"]["accepted_ranges"])
    normalized = window["data"]["accepted_ranges"][-1]
    assert normalized["start_message_id"] == "m2"
    assert normalized["end_message_id"] == "m3"
    assert normalized["summary"] is None
    assert normalized["normalizations"] == ["endpoint_order_swapped"]
    assert window["data"]["window_uncertainties"] == []
    assert validation["data"]["status"] == "partial"
    assert result["completion_status"] == "partial"
    assert result["evidence_validation"]["accepted_range_count"] == 3
    assert result["evidence_validation"]["rejected_range_count"] == 1
    assert [record["range_id"] for record in result["evidence_ledger"]] == ["r000001", "r000002", "r000003"]
