"""Search drop repository tests."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import (
    create_category,
    create_workstation_conversation_from_search,
    list_conversation_hits,
    list_workstation_conversations,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def repo_db(tmp_path):
    conn = connect(tmp_path / "drop.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_search_drop_creates_conversation_and_hits(repo_db) -> None:
    conn, logger, dataset_id = repo_db
    category = create_category(conn, logger, dataset_id, "school")
    conversation = create_workstation_conversation_from_search(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        primary_hit_message_id="msg_001",
        title="Allergy form",
        hits=[
            {
                "message_id": "msg_001",
                "retrieval_method": "fts_exact",
                "query_text": "allergy",
                "matched_term": "allergy",
                "match_type": "exact",
            }
        ],
    )
    stored = list_workstation_conversations(conn, dataset_id, category.category_id)
    assert len(stored) == 1
    hits = list_conversation_hits(conn, conversation.workstation_conversation_id)
    assert hits[0].retrieval_method == "fts_exact"
    assert hits[0].query_text == "allergy"
