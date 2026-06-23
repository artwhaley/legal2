"""Retrieval assist tests (T8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.conversational_answer import SESSION_CLASS_NOT_RELEVANT
from message_evidence_workstation.search.retrieval_assist import (
    collect_retrieval_assists,
    promote_sessions_from_retrieval_assists,
)
from message_evidence_workstation.search.session_map import list_sessions, rebuild_dataset_sessions

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def assist_db(tmp_path):
    conn = connect(tmp_path / "assist.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    rebuild_dataset_sessions(conn, logger, dataset_id, gap_minutes=30)
    return conn, logger, dataset_id


def test_collect_retrieval_assists_maps_hits_to_sessions(assist_db) -> None:
    conn, logger, dataset_id = assist_db
    sessions = list_sessions(conn, dataset_id)
    assists = collect_retrieval_assists(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="allergy",
        sessions=sessions,
    )
    assert assists
    assert assists[0]["session_id"]
    assert assists[0]["message_id"]


def test_promote_sessions_from_retrieval_assists(assist_db) -> None:
    sessions = list_sessions(assist_db[0], assist_db[2])
    target = sessions[-1]
    classifications = {session.session_id: SESSION_CLASS_NOT_RELEVANT for session in sessions}
    assists = [
        {
            "session_id": target.session_id,
            "message_id": target.start_message_id,
            "retrieval_method": "fts_exact",
        }
    ]
    updated, notes = promote_sessions_from_retrieval_assists(
        classifications,
        assists,
        inspected_session_ids=set(),
    )
    assert updated[target.session_id] == "possibly_relevant"
    assert notes
