"""Repository tests for categories and workstation conversations."""

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import (
    create_category,
    create_workstation_conversation_manual,
    list_categories,
    list_conversation_hits,
    list_workstation_conversations,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def repo_db(tmp_path):
    conn = connect(tmp_path / "test.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_category_crud(repo_db) -> None:
    conn, logger, dataset_id = repo_db
    school = create_category(conn, logger, dataset_id, "school")
    work = create_category(conn, logger, dataset_id, "work")
    categories = list_categories(conn, dataset_id)
    assert {category.name for category in categories} == {"school", "work"}
    assert school.category_id != work.category_id


def test_workstation_conversation_manual_creation(repo_db) -> None:
    conn, logger, dataset_id = repo_db
    category = create_category(conn, logger, dataset_id, "allergies")
    conversation = create_workstation_conversation_manual(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        primary_hit_message_id="msg_001",
        hit_message_ids=["msg_001", "msg_002"],
        title="Allergy form discussion",
    )
    conversations = list_workstation_conversations(conn, dataset_id, category.category_id)
    assert len(conversations) == 1
    assert conversations[0].workstation_conversation_id == conversation.workstation_conversation_id
    hits = list_conversation_hits(conn, conversation.workstation_conversation_id)
    assert [hit.message_id for hit in hits] == ["msg_001", "msg_002"]
