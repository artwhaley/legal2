"""Router error normalization tests."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from message_evidence_workstation.config.settings import (
    AppSettings,
    ModelRoleConfig,
    ModelRoutingSettings,
    NimSettings,
    PROVIDER_NIM,
)
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.llm.errors import ModelError
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.llm.types import ModelChatResult, ModelProvider, ModelTaskRole
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClientError


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "router-retry.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    return conn, logger


def _app_settings() -> AppSettings:
    nim = NimSettings(api_key="key")
    routing = ModelRoutingSettings(
        expansion=ModelRoleConfig(provider=PROVIDER_NIM, model="expansion-model", api_key="key"),
        research=ModelRoleConfig(provider=PROVIDER_NIM, model="research-model", api_key="key"),
        writing=ModelRoleConfig(provider=PROVIDER_NIM, model="writing-model", api_key="key"),
    )
    return AppSettings(nim=nim, model_routing=routing)


def test_router_surfaces_first_429_without_retry() -> None:
    router = ModelRouter(_app_settings())
    attempts = {"count": 0}

    def flaky_chat(*_args, **_kwargs):
        attempts["count"] += 1
        raise NimClientError(
            "rate limited",
            error_type="http_error",
            details={"status_code": 429},
        )

    with patch(
        "message_evidence_workstation.llm.providers.nim_provider.NimClient.chat_completion",
        side_effect=flaky_chat,
    ):
        with pytest.raises(ModelError) as exc_info:
            router.chat(
                task_role=ModelTaskRole.SEARCH_EXPANSION,
                messages=[{"role": "user", "content": "hi"}],
            )
    assert exc_info.value.error_type == "http_error"
    assert exc_info.value.details.get("status_code") == 429
    assert attempts["count"] == 1


def test_router_does_not_retry_missing_api_key() -> None:
    router = ModelRouter(_app_settings())
    with patch(
        "message_evidence_workstation.llm.providers.nim_provider.NimClient.chat_completion",
        side_effect=NimClientError("missing", error_type="missing_api_key"),
    ):
        with pytest.raises(ModelError) as exc_info:
            router.chat(
                task_role=ModelTaskRole.SEARCH_EXPANSION,
                messages=[{"role": "user", "content": "hi"}],
            )
    assert exc_info.value.error_type == "missing_api_key"


def test_model_run_records_provider_and_task_role(db) -> None:
    from tests.router_helpers import router_with_role_models
    from message_evidence_workstation.nim.model_runs import run_nim_chat
    from message_evidence_workstation.nim.prompts import RUN_TYPE_KEYWORD_EXPANSION, seed_default_prompts

    conn, logger = db
    seed_default_prompts(conn, logger)
    router = router_with_role_models(expansion="test-model")
    payload = {"choices": [{"message": {"content": '{"terms":["school"]}'}}]}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        run_nim_chat(
            conn,
            logger,
            router,
            run_type=RUN_TYPE_KEYWORD_EXPANSION,
            user_content="allergy",
        )
    row = conn.execute(
        "SELECT provider, model, raw_request_json, raw_response_json FROM model_run"
    ).fetchone()
    assert row["provider"] == "nim"
    assert row["model"] == "test-model"
    request = json.loads(row["raw_request_json"])
    assert request["task_role"] == ModelTaskRole.SEARCH_EXPANSION.value
    response = json.loads(row["raw_response_json"])
    assert response["_router_audit"]["provider"] == "nim"
