"""Prompt and ModelRun tests."""

import json
from unittest.mock import patch

import pytest

from message_evidence_workstation.config.settings import NimSettings
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClient
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import (
    RUN_TYPE_KEYWORD_EXPANSION,
    get_active_prompt,
    save_prompt_version,
    seed_default_prompts,
)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "prompts.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    return conn, logger


def test_default_prompt_seeding(db) -> None:
    conn, logger = db
    seed_default_prompts(conn, logger)
    row = get_active_prompt(conn, RUN_TYPE_KEYWORD_EXPANSION)
    assert row is not None
    assert row["version"] == 1


def test_prompt_version_update(db) -> None:
    conn, logger = db
    first_id = save_prompt_version(conn, logger, RUN_TYPE_KEYWORD_EXPANSION, "v1 body")
    second_id = save_prompt_version(conn, logger, RUN_TYPE_KEYWORD_EXPANSION, "v2 body")
    active = get_active_prompt(conn, RUN_TYPE_KEYWORD_EXPANSION)
    assert active is not None
    assert active["prompt_template_id"] == second_id
    assert active["body"] == "v2 body"
    assert int(active["version"]) >= 2
    old = conn.execute(
        "SELECT is_active FROM prompt_template WHERE prompt_template_id = ?",
        (first_id,),
    ).fetchone()
    assert old["is_active"] == 0


def test_model_run_success_record(db) -> None:
    conn, logger = db
    settings = NimSettings(api_key="key", model="test-model")
    client = NimClient(settings)
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
            client,
            run_type=RUN_TYPE_KEYWORD_EXPANSION,
            user_content="allergy",
        )
    row = conn.execute("SELECT error_type, raw_response_json FROM model_run").fetchone()
    assert row["error_type"] is None
    assert "school" in row["raw_response_json"]


def test_model_run_failure_record(db) -> None:
    conn, logger = db
    settings = NimSettings(api_key="", model="test-model")
    client = NimClient(settings)
    with pytest.raises(Exception):
        run_nim_chat(
            conn,
            logger,
            client,
            run_type=RUN_TYPE_KEYWORD_EXPANSION,
            user_content="allergy",
        )
    row = conn.execute("SELECT error_type FROM model_run").fetchone()
    assert row["error_type"] == "missing_api_key"
