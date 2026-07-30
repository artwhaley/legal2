import uuid
from dataclasses import replace

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import GlobalConfig
from tests.sfv1_support import configured_service, fake_embedding_service, fake_provider, server_config


def _app(tmp_path, config=None, *, provider=None, calls=None):
    service, selected = configured_service(tmp_path, config=config)
    return create_app(
        config_service=service,
        provider=provider or fake_provider(calls=calls),
        embedding_service=fake_embedding_service(selected),
        embedding_factory=lambda value: fake_embedding_service(selected),
    )


def _body(question="What happened in the messages?"):
    return {"request_id": str(uuid.uuid4()), "question": question}


def test_plan_calls_analysis_planning_once_and_returns_frozen_plan(tmp_path):
    calls = []
    app = _app(tmp_path, calls=calls)
    with TestClient(app) as client:
        response = client.post("/v1/conversational-plan", json=_body())
    assert response.status_code == 200
    value = response.json()
    assert [query["query_id"] for query in value["retrieval_queries"]] == ["q0001", "q0002"]
    assert "retrieval_queries" not in value["analysis_plan"]
    assert value["search_policy"]["mode"] == "none"
    assert value["embedding"] is None
    assert [call["user"]["task"] for call in calls] == ["analysis_planning"]


def test_none_planning_does_not_prepare_embedding_runtime(tmp_path):
    base = server_config(global_config=GlobalConfig(retrieval_assistance_mode="none"))
    app = _app(tmp_path, config=base)
    with TestClient(app) as client:
        value = client.post("/v1/conversational-plan", json=_body()).json()
    assert value["search_policy"]["mode"] == "none"
    assert value["embedding"] is None


def test_semantic_plan_reports_actual_embedding_geometry(tmp_path):
    base = server_config(global_config=GlobalConfig(retrieval_assistance_mode="semantic_ranges"))
    app = _app(tmp_path, config=base)
    with TestClient(app) as client:
        response = client.post("/v1/conversational-plan", json=_body())
    assert response.status_code == 200
    value = response.json()
    assert value["search_policy"]["mode"] == "semantic_ranges"
    assert value["embedding"]["dimensions"] == 3
    assert value["embedding"]["normalization"] == "unit_l2"


def test_old_plan_route_is_removed_and_malformed_planning_is_loud(tmp_path):
    app = _app(tmp_path, provider=fake_provider(mutate=lambda user, output: {**output, "retrieval_queries": [" "]}))
    with TestClient(app) as client:
        old = client.post("/v1/conversational-retrieval-plan", json=_body())
        malformed = client.post("/v1/conversational-plan", json=_body())
    assert old.status_code == 404
    assert malformed.status_code == 502
    assert malformed.json()["code"] == "MODEL_OUTPUT_INVALID"


def test_plan_fingerprint_changes_for_plan_policy_and_planner_operation(tmp_path):
    first_app = _app(tmp_path / "one")
    with TestClient(first_app) as client:
        first = client.post("/v1/conversational-plan", json=_body()).json()
    changed = server_config(global_config=GlobalConfig(retrieval_assistance_mode="none", retrieval_rrf_constant=61))
    second_app = _app(tmp_path / "two", config=changed)
    with TestClient(second_app) as client:
        second = client.post("/v1/conversational-plan", json=_body()).json()
    assert first["compatibility_fingerprint"] != second["compatibility_fingerprint"]
