import uuid
import re
from dataclasses import fields, replace

from fastapi.testclient import TestClient

from server.app import create_app
from server.config_service import ConfigurationService
from tests.test_sfv1_control_store import make_config
from server.embeddings import EmbeddingService
from tests.sfv1_support import FakeEmbeddingModel, fake_provider
from server.config import (
    EmbeddingConfig,
    GlobalConfig,
    ModelProfile,
    OperationAssignment,
    ProviderAccount,
)


def test_admin_bootstrap_and_public_surface(tmp_path):
    app = create_app(config_service=ConfigurationService(tmp_path))
    with TestClient(app) as client:
        page = client.get("/admin/")
        assert page.status_code == 200
        assert "Validate draft" in page.text
        assert client.get("/internal/live").json() == {"status": "alive", "api_version": 1}
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        req = {"request_id": str(uuid.uuid4()), "query": "q"}
        assert client.post("/v1/keyword-expansion", json=req).status_code == 503
        assert client.post("/v1/keyword-expansion", json=req).json()["code"] == "CONFIGURATION_REQUIRED"


def test_admin_events_has_one_route_and_one_complete_live_projection(tmp_path):
    config = make_config()
    service = ConfigurationService(tmp_path)
    service.startup()
    draft = service.store.draft()[0]
    service.store.save_draft(draft, config)
    for provider_id in config.provider_accounts:
        service.store.set_secret(draft, provider_id, "synthetic-secret-1234")
    service.activate(draft)
    app = create_app(
        config_service=service,
        provider=fake_provider(),
        embedding_service=EmbeddingService(
            config.embedding, model=FakeEmbeddingModel()
        ),
        embedding_factory=lambda embedding: EmbeddingService(
            embedding,
            model=FakeEmbeddingModel(
                dimensions=embedding.required_dimensions or 3
            ),
        ),
    )

    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/admin/events"
        and "GET" in getattr(route, "methods", set())
    ]
    assert len(routes) == 1
    with TestClient(app) as client:
        value = client.get("/admin/events").json()

    assert {
        "events",
        "metrics",
        "usage",
        "embedding",
        "operations",
        "debug_capture",
        "debug_status",
        "active_config_version",
        "retrieval_assistance_mode",
        "configuration_fingerprint",
        "mode_independent_configuration_fingerprint",
    } == set(value)
    assert value["debug_capture"] == value["debug_status"]


def test_admin_save_masks_secret_and_audits_real_draft(tmp_path):
    service = ConfigurationService(tmp_path)
    service.startup()
    draft = service.store.draft()[0]
    config = make_config()
    service.store.save_draft(draft, config)
    provider_id = next(iter(config.provider_accounts))
    service.store.set_secret(draft, provider_id, "old-sentinel-secret")
    service.activate(draft)
    app = create_app(config_service=service, provider=fake_provider(), embedding_service=EmbeddingService(config.embedding, model=FakeEmbeddingModel()))
    with TestClient(app) as client:
        page = client.get("/admin/operations")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        draft_id = int(re.search(r'name="version_id" value="(\d+)"', page.text).group(1))
        response = client.post("/admin/action", data={"csrf_token": token, "action": "save_operations", "return_page": "operations", "version_id": str(draft_id), "operation_assignments.keyword_expansion.system_prompt": "edited prompt"})
        provider_page = client.get("/admin/providers")
        token = re.search(r'name="csrf_token" value="([^"]+)"', provider_page.text).group(1)
        response = client.post("/admin/action", data={"csrf_token": token, "action": "save_provider", "return_page": "providers", "version_id": str(draft_id), "provider_account_id": provider_id, "provider_accounts.name": config.provider_accounts[provider_id].name, "provider_accounts.base_url": config.provider_accounts[provider_id].base_url, "secret": "new-sentinel-secret"})
        assert response.status_code == 200
        assert "new-sentinel-secret" not in response.text
        assert service.store.get_version(draft_id).operations["keyword_expansion"].system_prompt == "edited prompt"
        assert service.store.get_version(draft_id).provider_accounts[provider_id].api_key == "new-sentinel-secret"


def test_admin_exposes_every_runtime_control_schema_payload_and_strict_test(tmp_path):
    service = ConfigurationService(tmp_path)
    service.startup()
    draft = service.store.draft()[0]
    config = make_config()
    service.store.save_draft(draft, config)
    for provider_id in config.provider_accounts:
        service.store.set_secret(draft, provider_id, "synthetic-secret-1234")
    service.activate(draft)
    app = create_app(config_service=service, provider=fake_provider(), embedding_service=EmbeddingService(config.embedding, model=FakeEmbeddingModel()), embedding_factory=lambda embedding: EmbeddingService(embedding, model=FakeEmbeddingModel(dimensions=embedding.required_dimensions or 3)))
    with TestClient(app) as client:
        page = client.get("/admin/operations")
        for field in fields(OperationAssignment):
            assert f"operation_assignments.keyword_expansion.{field.name}" in page.text
        model_page = client.get("/admin/models")
        for field in fields(ModelProfile):
            if field.name not in {"model_profile_id", "provider_account_id"}:
                assert f"model_profiles.{field.name}" in model_page.text
        provider_page = client.get("/admin/providers")
        for field in fields(ProviderAccount):
            if field.name not in {"provider_account_id", "api_key"}:
                assert f"provider_accounts.{field.name}" in provider_page.text
        page = client.get("/admin/server")
        for field in fields(GlobalConfig):
            assert f"global_config.{field.name}" in page.text
        for field in fields(EmbeddingConfig):
            assert f"embedding.{field.name}" in page.text
        assert "Conversational window size" in page.text
        assert "Draft window target" in page.text
        assert "No restart required" in page.text
        assert (
            page.text.count(
                'name="global_config.window_input_utilization_percent"'
            )
            == 1
        )
        page = client.get("/admin/operations")
        assert "Exact model output schema" in page.text
        assert "Generated synthetic provider payload" in page.text
        assert "Complete system prompt" in page.text
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        draft_id = int(re.search(r'name="version_id" value="(\d+)"', page.text).group(1))
        tested = client.post("/admin/action", data={"csrf_token": token, "action": "test", "version_id": draft_id, "operation": "keyword_expansion"})
        assert tested.status_code == 200
        assert "Strict test passed" in tested.text
        assert '"schema_valid": true' in tested.text


def test_failed_admin_model_test_shows_raw_only_in_response_and_accounts_failure(tmp_path):
    service = ConfigurationService(tmp_path)
    service.startup()
    draft = service.store.draft()[0]
    config = make_config()
    service.store.save_draft(draft, config)
    for provider_id in config.provider_accounts:
        service.store.set_secret(draft, provider_id, "synthetic-secret-1234")
    service.activate(draft)

    def malformed_keyword(user, output):
        if user["task"] == "keyword_expansion":
            output["unexpected"] = "response-only-sentinel"
        return output

    from tests.sfv1_support import fake_provider as configured_fake_provider

    app = create_app(
        config_service=service,
        provider=configured_fake_provider(mutate=malformed_keyword),
        embedding_service=EmbeddingService(config.embedding, model=FakeEmbeddingModel()),
    )
    with TestClient(app) as client:
        page = client.get("/admin/")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        draft_id = int(re.search(r'name="version_id" value="(\d+)"', page.text).group(1))
        tested = client.post(
            "/admin/action",
            data={
                "csrf_token": token,
                "action": "test",
                "version_id": draft_id,
                "operation": "keyword_expansion",
            },
        )
        rows = service.store.conn.execute(
            "SELECT outcome,error_code FROM usage_event WHERE product_endpoint='/admin/test'"
        ).fetchall()
        durable = " ".join(
            str(value)
            for row in service.store.conn.execute(
                "SELECT details_json FROM admin_audit UNION ALL SELECT payload_json FROM config_version"
            ).fetchall()
            for value in row
        )

    assert tested.status_code == 200
    assert '"schema_valid": false' in tested.text
    assert "response-only-sentinel" in tested.text
    assert [(row["outcome"], row["error_code"]) for row in rows] == [
        ("failure", "MODEL_OUTPUT_INVALID")
    ]
    assert "response-only-sentinel" not in durable


def test_failed_admin_provider_test_accounts_safe_failure_without_raw_body(tmp_path):
    service = ConfigurationService(tmp_path)
    service.startup()
    draft = service.store.draft()[0]
    config = make_config()
    service.store.save_draft(draft, config)
    for provider_id in config.provider_accounts:
        service.store.set_secret(draft, provider_id, "synthetic-secret-1234")
    service.activate(draft)
    app = create_app(
        config_service=service,
        provider=fake_provider(status_by_task={"keyword_expansion": 503}),
        embedding_service=EmbeddingService(config.embedding, model=FakeEmbeddingModel()),
    )
    with TestClient(app) as client:
        page = client.get("/admin/")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        draft_id = int(re.search(r'name="version_id" value="(\d+)"', page.text).group(1))
        tested = client.post(
            "/admin/action",
            data={
                "csrf_token": token,
                "action": "test",
                "version_id": draft_id,
                "operation": "keyword_expansion",
            },
        )
        row = service.store.conn.execute(
            "SELECT outcome,error_code,input_tokens,output_tokens FROM usage_event "
            "WHERE product_endpoint='/admin/test'"
        ).fetchone()

    assert tested.status_code == 200
    assert "provider returned HTTP 503" in tested.text
    assert "safe synthetic provider failure" not in tested.text
    assert '"raw_output": null' in tested.text
    assert (row["outcome"], row["error_code"], row["output_tokens"]) == (
        "failure",
        "PROVIDER_UNAVAILABLE",
        0,
    )
    assert row["input_tokens"] > 0


def test_admin_debug_capture_records_exact_traffic_separately_without_secrets(
    tmp_path,
):
    service = ConfigurationService(tmp_path)
    service.startup()
    draft = service.store.draft()[0]
    config = make_config()
    service.store.save_draft(draft, config)
    for provider_id in config.provider_accounts:
        service.store.set_secret(draft, provider_id, "never-capture-this-secret")
    service.activate(draft)
    app = create_app(
        config_service=service,
        provider=fake_provider(),
        embedding_service=EmbeddingService(
            config.embedding, model=FakeEmbeddingModel()
        ),
    )

    with TestClient(app) as client:
        page = client.get("/admin/debug")
        assert page.status_code == 200
        assert "Temporary exact debug capture" in page.text
        assert "Capture stopped" in page.text
        token = re.search(
            r'name="csrf_token" value="([^"]+)"', page.text
        ).group(1)
        draft_id = int(
            re.search(r'name="version_id" value="(\d+)"', page.text).group(1)
        )
        started = client.post(
            "/admin/action",
            data={
                "csrf_token": token,
                "action": "start_debug_capture",
                "return_page": "debug",
                "version_id": draft_id,
            },
        )
        assert "started" in started.text

        request_id = str(uuid.uuid4())
        response = client.post(
            "/v1/keyword-expansion",
            json={
                "request_id": request_id,
                "query": "exact-debug-query-sentinel",
            },
        )
        assert response.status_code == 200

        token = re.search(
            r'name="csrf_token" value="([^"]+)"', started.text
        ).group(1)
        stopped = client.post(
            "/admin/action",
            data={
                "csrf_token": token,
                "action": "stop_debug_capture",
                "return_page": "debug",
                "version_id": draft_id,
            },
        )
        assert "stopped" in stopped.text
        capture_files = list((tmp_path / "debug-captures").glob("*.jsonl"))
        assert len(capture_files) == 1
        captured = capture_files[0].read_text(encoding="utf-8")

        assert "exact-debug-query-sentinel" in captured
        assert '"kind":"public_request"' in captured
        assert '"kind":"provider_request"' in captured
        assert '"kind":"provider_response"' in captured
        assert '"kind":"public_response_body"' in captured
        assert config.operations["keyword_expansion"].system_prompt in captured
        assert "never-capture-this-secret" not in captured
        assert "authorization" not in captured.lower()

        client.post(
            "/v1/keyword-expansion",
            json={
                "request_id": str(uuid.uuid4()),
                "query": "must-not-be-captured-after-stop",
            },
        )
        assert (
            "must-not-be-captured-after-stop"
            not in capture_files[0].read_text(encoding="utf-8")
        )


def test_embedding_config_activation_validates_then_atomically_swaps(tmp_path):
    service = ConfigurationService(tmp_path)
    service.startup()
    first_id = service.store.draft()[0]
    config = make_config()
    service.store.save_draft(first_id, config)
    for provider_id in config.provider_accounts:
        service.store.set_secret(first_id, provider_id, "synthetic-secret-1234")
    service.activate(first_id)

    def factory(embedding):
        if embedding.model_name == "invalid-dimensions":
            return EmbeddingService(embedding, model=FakeEmbeddingModel(dimensions=99))
        weight = 2.0 if embedding.model_name == "fake-v2" else 1.0
        return EmbeddingService(embedding, model=FakeEmbeddingModel(dimensions=embedding.required_dimensions or 3, weight=weight))

    app = create_app(config_service=service, provider=fake_provider(), embedding_service=factory(config.embedding), embedding_factory=factory)
    with TestClient(app) as client:
        old_profile = app.state.embedding.status()["profile_id"]
        original_publish = service.publish_activated
        published_versions = []

        def assert_runtime_precedes_publish(candidate):
            assert candidate.config_version in app.state.runtimes
            assert app.state.current_runtime.config.config_version == candidate.config_version
            published_versions.append(candidate.config_version)
            original_publish(candidate)

        service.publish_activated = assert_runtime_precedes_publish
        draft_id = service.store.copy_as_draft(first_id)
        draft = service.store.get_version(draft_id)
        service.store.save_draft(draft_id, replace(draft, embedding=replace(draft.embedding, model_name="fake-v2")))
        page = client.get("/admin/")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        activated = client.post("/admin/action", data={"csrf_token": token, "action": "activate", "version_id": draft_id})
        assert "activated" in activated.text
        assert service.snapshot().config_version == draft_id
        assert published_versions == [draft_id]
        assert app.state.embedding.status()["profile_id"] != old_profile

        failed_id = service.store.copy_as_draft(draft_id)
        failed = service.store.get_version(failed_id)
        service.store.save_draft(
            failed_id,
            replace(failed, embedding=replace(failed.embedding, model_name="invalid-dimensions")),
        )
        page = client.get("/admin/")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        rejected = client.post(
            "/admin/action",
            data={"csrf_token": token, "action": "activate", "version_id": failed_id},
        )
        assert "configured embedding dimensions do not match loaded artifact" in rejected.text
        assert service.snapshot().config_version == draft_id
        assert app.state.embedding.status()["accepting"] is True

        response = client.post(
            "/v1/embeddings",
            json={
                "request_id": str(uuid.uuid4()),
                "items": [{"message_id": "m1", "text": "still available"}],
            },
        )
        events = [line for line in response.text.splitlines() if line]
        assert response.status_code == 200
        assert '"event":"completed"' in events[-1]
