from dataclasses import replace

from fastapi.testclient import TestClient

from server.config import GlobalConfig
from tests.test_qpa1_analysis_plan import _app, _body
from tests.sfv1_support import fake_provider, server_config


def test_analysis_plan_returns_ordered_queries_policy_and_actual_geometry(tmp_path):
    config = server_config(global_config=GlobalConfig(retrieval_assistance_mode="semantic_ranges"))
    app = _app(tmp_path, config=config, provider=fake_provider())
    with TestClient(app) as client:
        response = client.post("/v1/conversational-plan", json=_body())
    value = response.json()
    assert response.status_code == 200
    assert [query["query_id"] for query in value["retrieval_queries"]] == ["q0001", "q0002"]
    assert value["search_policy"]["mode"] == "semantic_ranges"
    assert value["embedding"]["dimensions"] == 3


def test_none_plan_has_no_embedding_metadata(tmp_path):
    app = _app(tmp_path, config=server_config(global_config=GlobalConfig(retrieval_assistance_mode="none")))
    with TestClient(app) as client:
        value = client.post("/v1/conversational-plan", json=_body()).json()
    assert value["search_policy"]["mode"] == "none"
    assert value["embedding"] is None


def test_malformed_planning_output_is_not_default_filled(tmp_path):
    app = _app(tmp_path, provider=fake_provider(mutate=lambda user, output: {**output, "retrieval_queries": [" "]}))
    with TestClient(app) as client:
        response = client.post("/v1/conversational-plan", json=_body())
    assert response.status_code == 502
    assert response.json()["code"] == "MODEL_OUTPUT_INVALID"


def test_plan_fingerprint_includes_policy_and_planner_operation(tmp_path):
    first = _app(tmp_path / "one", config=server_config(global_config=GlobalConfig(retrieval_assistance_mode="none")))
    with TestClient(first) as client:
        first_value = client.post("/v1/conversational-plan", json=_body()).json()
    changed = server_config(global_config=GlobalConfig(retrieval_assistance_mode="none", retrieval_rrf_constant=61))
    second = _app(tmp_path / "two", config=changed)
    with TestClient(second) as client:
        second_value = client.post("/v1/conversational-plan", json=_body()).json()
    assert first_value["compatibility_fingerprint"] != second_value["compatibility_fingerprint"]
