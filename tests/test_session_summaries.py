"""Session summary generation tests (T6)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimChatResult
from message_evidence_workstation.search.session_map import list_sessions
from message_evidence_workstation.search.session_summaries import (
    generate_session_summary,
    parse_session_summary_response,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def summary_db(tmp_path):
    conn = connect(tmp_path / "summary.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_parse_session_summary_response() -> None:
    content = json.dumps(
        {
            "topics": ["allergy forms"],
            "people": ["Jane"],
            "events": [],
            "commitments": ["submit form"],
            "conflicts": [],
            "appointments": [],
            "money": [],
            "parenting_school": ["school nurse"],
            "medical": ["epi pen"],
            "travel": [],
            "notable_quotes": [{"message_id": "msg_002", "quote": "voicemail for Nurse Kim"}],
        }
    )
    summary = parse_session_summary_response(content)
    assert "allergy forms" in summary["topics"]
    assert summary["notable_quotes"][0]["message_id"] == "msg_002"


def test_generate_session_summary_uses_fake_nim(summary_db) -> None:
    conn, logger, dataset_id = summary_db
    session = list_sessions(conn, dataset_id)[0]

    def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content, dataset_id=None, **kwargs):
        return NimChatResult(
            content=json.dumps(
                {
                    "topics": ["pickup"],
                    "people": ["Art"],
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

    client = MagicMock()
    with patch(
        "message_evidence_workstation.search.session_summaries.run_nim_chat",
        side_effect=fake_run_nim_chat,
    ):
        summary = generate_session_summary(
            conn,
            logger,
            client,
            dataset_id=dataset_id,
            session=session,
        )
    assert summary["topics"] == ["pickup"]
    reloaded = list_sessions(conn, dataset_id)[0]
    assert reloaded.summary_status == "ready"
    assert reloaded.summary_json["topics"] == ["pickup"]
