"""Output formatting repository tests (T19)."""

from pathlib import Path

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import (
    create_category,
    create_workstation_conversation_from_search,
    load_output_conversation_context,
)
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


def test_load_output_conversation_context(tmp_path) -> None:
    conn = connect(tmp_path / "output.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    category = create_category(conn, logger, dataset_id, "school")
    conversation = create_workstation_conversation_from_search(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category.category_id,
        source_thread_id="thread_001",
        primary_hit_message_id="msg_001",
        title="Allergy paperwork",
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
    context = load_output_conversation_context(conn, conversation.workstation_conversation_id)
    assert context is not None
    assert context.category_name == "school"
    assert context.thread_display_title == "Art and Jane"
    assert "msg_001" in context.hit_message_ids
    assert len(context.messages) == 100
    assert context.conversation.title == "Allergy paperwork"
