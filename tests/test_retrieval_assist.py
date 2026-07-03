"""Retrieval assist tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search.retrieval_assist import (
    collect_retrieval_assists,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def assist_db(tmp_path):
    conn = connect(tmp_path / "assist.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_collect_retrieval_assists_returns_message_thread_hints(assist_db) -> None:
    conn, logger, dataset_id = assist_db
    assists = collect_retrieval_assists(
        conn,
        logger,
        dataset_id=dataset_id,
        user_query="allergy",
    )
    assert assists
    assert assists[0]["message_id"]
    assert assists[0]["source_thread_id"]
