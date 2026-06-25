"""Prompt and ModelRun tests."""

import json
from unittest.mock import patch

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from tests.router_helpers import router_with_role_models
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import (
    DEFAULT_PROMPT_BODIES,
    RUN_TYPE_CONVERSATIONAL_PLANNER,
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
    RUN_TYPE_SESSION_CLASSIFICATION,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
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


def test_default_prompts_are_legal_evidence_hardened() -> None:
    assert "Treat supplied messages" in DEFAULT_PROMPT_BODIES[RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER]
    assert "answer_ranges" in DEFAULT_PROMPT_BODIES[RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER]
    assert "answer_format" in DEFAULT_PROMPT_BODIES[RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER]
    assert "brief mode" in DEFAULT_PROMPT_BODIES[RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER]
    assert "ONLY that range's date_description" in DEFAULT_PROMPT_BODIES[RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER]
    assert "clickable answer_ranges" in DEFAULT_PROMPT_BODIES[RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER]
    assert "display_text should be short hover text" in DEFAULT_PROMPT_BODIES[RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER]
    assert "candidate_evidence_blocks" not in DEFAULT_PROMPT_BODIES[RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER]
    assert "Do not return tool_calls" in DEFAULT_PROMPT_BODIES[RUN_TYPE_CONVERSATIONAL_PLANNER]
    assert "Err toward possibly_relevant" in DEFAULT_PROMPT_BODIES[RUN_TYPE_SESSION_CLASSIFICATION]
    assert "do not drop minority" in DEFAULT_PROMPT_BODIES[RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE]
    assert "candidate_evidence_blocks" not in DEFAULT_PROMPT_BODIES[RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE]


def test_seed_default_prompts_does_not_overwrite_active_versions(db) -> None:
    conn, logger = db
    save_prompt_version(conn, logger, RUN_TYPE_KEYWORD_EXPANSION, "workspace-specific prompt")

    seed_default_prompts(conn, logger)

    row = get_active_prompt(conn, RUN_TYPE_KEYWORD_EXPANSION)
    assert row is not None
    assert row["body"] == "workspace-specific prompt"


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
    row = conn.execute("SELECT error_type, raw_response_json FROM model_run").fetchone()
    assert row["error_type"] is None
    assert "school" in row["raw_response_json"]


def test_model_run_failure_record(db) -> None:
    conn, logger = db
    router = router_with_role_models(expansion="test-model", api_key="")
    with pytest.raises(Exception):
        run_nim_chat(
            conn,
            logger,
            router,
            run_type=RUN_TYPE_KEYWORD_EXPANSION,
            user_content="allergy",
        )
    row = conn.execute("SELECT error_type FROM model_run").fetchone()
    assert row["error_type"] == "missing_api_key"
