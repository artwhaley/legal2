from server.conversation_unified import _window_extraction_user
from server.token_accounting import canonical_json
from fastapi.testclient import TestClient
from tests.test_qpa1_analysis_plan import _app, _body
from tests.test_qpa1_orchestration import _analysis_body
from tests.sfv1_support import fake_provider


def _messages():
    return [
        {
            "message_id": "m1",
            "thread_id": "thread-1",
            "timestamp": "2026-01-01T00:00:00Z",
            "sender": "Person",
            "text": "Quotes: \"school\" and slash \\ — stable corpus.",
        },
        {
            "message_id": "m2",
            "thread_id": "thread-1",
            "timestamp": "2026-01-01T00:01:00Z",
            "sender": "Person",
            "text": "Second message.",
        },
    ]


def _plan(label="first"):
    return {
        "analysis_question": label,
        "answer_objective": "answer",
        "concepts": [],
        "inclusion_criteria": [],
        "exclusion_criteria": [],
        "answer_requirements": [],
        "interpretive_assumptions": [],
    }


def test_extraction_user_has_exact_corpus_first_key_order_and_values():
    value = _window_extraction_user(
        window_id="w000001",
        messages=_messages(),
        question="When?",
        analysis_plan=_plan(),
        retrieval_queries=[{"query_id": "q0001", "text": "school"}],
        suggestion_ranges=[],
    )
    assert list(value) == [
        "task",
        "window_id",
        "messages",
        "question",
        "analysis_plan",
        "retrieval_queries",
        "suggestion_ranges",
    ]
    assert value["task"] == "window_evidence_extraction"
    assert value["messages"] == _messages()


def test_extraction_user_prefix_is_stable_when_query_fields_change():
    first = _window_extraction_user(
        window_id="w000001",
        messages=_messages(),
        question="When did we fight about school?",
        analysis_plan=_plan("school"),
        retrieval_queries=[{"query_id": "q0001", "text": "school"}],
        suggestion_ranges=[],
    )
    second = _window_extraction_user(
        window_id="w000001",
        messages=_messages(),
        question="When did we talk about grandma?",
        analysis_plan=_plan("grandma"),
        retrieval_queries=[{"query_id": "q0001", "text": "grandma"}],
        suggestion_ranges=[{"thread_id": "thread-1", "hit_message_ids": ["m1"]}],
    )
    stable_fields = {
        "task": "window_evidence_extraction",
        "window_id": "w000001",
        "messages": _messages(),
    }
    stable_prefix = canonical_json(stable_fields)[:-1] + ","
    first_json = canonical_json(first)
    second_json = canonical_json(second)
    assert first_json.startswith(stable_prefix)
    assert second_json.startswith(stable_prefix)
    assert first_json != second_json
    changed_window = _window_extraction_user(
        window_id="w000002",
        messages=_messages(),
        question="When did we talk about grandma?",
        analysis_plan=_plan("grandma"),
        retrieval_queries=[],
        suggestion_ranges=[],
    )
    assert not canonical_json(changed_window).startswith(stable_prefix)


def test_live_extraction_call_uses_corpus_first_order(tmp_path):
    calls = []
    app = _app(tmp_path, provider=fake_provider(calls=calls))
    with TestClient(app) as client:
        plan = client.post("/v1/conversational-plan", json=_body())
        assert plan.status_code == 200
        response = client.post(
            "/v1/conversational-analysis",
            json=_analysis_body(plan.json(), _messages()),
        )
    assert response.status_code == 200
    extraction = next(
        call["user"]
        for call in calls
        if call["user"]["task"] == "window_evidence_extraction"
    )
    assert list(extraction) == [
        "task",
        "window_id",
        "messages",
        "question",
        "analysis_plan",
        "retrieval_queries",
        "suggestion_ranges",
    ]
