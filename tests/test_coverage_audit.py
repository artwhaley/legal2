"""Coverage audit tests (T9)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.config.settings import NimSettings
from message_evidence_workstation.nim.client import NimChatResult, NimClient
from message_evidence_workstation.search.conversational_answer import (
    SESSION_CLASS_NOT_RELEVANT,
    SESSION_CLASS_RELEVANT,
    run_session_coverage_answer,
)
from message_evidence_workstation.search.coverage_audit import parse_coverage_audit_response
from message_evidence_workstation.search.session_map import list_sessions, rebuild_dataset_sessions

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


def test_parse_coverage_audit_response_filters_unknown_sessions() -> None:
    content = json.dumps(
        {
            "additional_session_ids": ["thread_001__session_002", "missing"],
            "residual_uncertainties": ["May have missed evening messages."],
            "audit_notes": "Added one more session.",
        }
    )
    result = parse_coverage_audit_response(
        content,
        valid_session_ids={"thread_001__session_002"},
    )
    assert result.additional_session_ids == ["thread_001__session_002"]
    assert result.residual_uncertainties


@pytest.fixture
def audit_db(tmp_path):
    conn = connect(tmp_path / "audit.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=30)
    return conn, logger, dataset_id


def test_session_coverage_audit_can_add_session(audit_db) -> None:
    conn, logger, dataset_id = audit_db
    requested_extra_session = {"session_id": ""}

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content, dataset_id=None, **kwargs):
        if run_type.endswith("session_summary"):
            return NimChatResult(
                content=json.dumps(
                    {
                        "topics": [],
                        "people": [],
                        "events": [],
                        "commitments": [],
                        "conflicts": [],
                        "appointments": [],
                        "money": [],
                        "parenting_school": [],
                        "medical": [],
                        "travel": [],
                        "notable_quotes": [],
                    }
                ),
                raw_response={},
                latency_ms=1,
            )
        if run_type.endswith("session_classification"):
            payload = json.loads(user_content)
            return NimChatResult(
                content=json.dumps(
                    {
                        "session_classifications": [
                            {
                                "session_id": item["session_id"],
                                "classification": SESSION_CLASS_RELEVANT
                                if index == 0
                                else SESSION_CLASS_NOT_RELEVANT,
                                "reason": "test",
                            }
                            for index, item in enumerate(payload["session_summaries"])
                        ]
                    }
                ),
                raw_response={},
                latency_ms=1,
            )
        if run_type.endswith("coverage_audit"):
            payload = json.loads(user_content)
            skipped = payload.get("skipped_session_summaries") or []
            requested_extra_session["session_id"] = str(skipped[-1]["session_id"]) if skipped else ""
            return NimChatResult(
                content=json.dumps(
                    {
                        "additional_session_ids": [requested_extra_session["session_id"]],
                        "residual_uncertainties": ["Audit requested another session."],
                        "audit_notes": "Expanded inspection set.",
                    }
                ),
                raw_response={},
                latency_ms=1,
            )
        payload = json.loads(user_content)
        inspected_ids = {item["session_id"] for item in payload["inspected_transcript_windows"]}
        assert requested_extra_session["session_id"] in inspected_ids
        return NimChatResult(
            content=json.dumps(
                {
                    "answer": "Audit-expanded answer.",
                    "cited_message_ids": [],
                    "candidate_evidence_blocks": [],
                    "uncertainties": [],
                    "coverage_summary": {
                        "mode": "session_coverage",
                        "messages_considered": 1,
                        "source_thread_ids": ["thread_001"],
                        "sessions_considered": len(payload["session_summaries"]),
                        "sessions_inspected": len(payload["inspected_transcript_windows"]),
                        "sessions_skipped": 0,
                    },
                }
            ),
            raw_response={},
            latency_ms=1,
        )

    client = NimClient(NimSettings(model="test-model", api_key="key"))
    with (
        patch(
            "message_evidence_workstation.search.conversational_answer.run_nim_chat",
            side_effect=fake_run_nim_chat,
        ),
        patch(
            "message_evidence_workstation.search.coverage_audit.run_nim_chat",
            side_effect=fake_run_nim_chat,
        ),
        patch(
            "message_evidence_workstation.search.session_summaries.run_nim_chat",
            side_effect=fake_run_nim_chat,
        ),
    ):
        result = run_session_coverage_answer(
            conn,
            logger,
            client,
            user_query="allergy",
            dataset_id=dataset_id,
        )
    assert any("Audit" in item for item in result.uncertainties)
