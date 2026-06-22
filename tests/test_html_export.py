"""HTML export tests (T21)."""

from pathlib import Path

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import (
    create_category,
    create_workstation_conversation_from_search,
    load_output_conversation_context,
    set_highlight_override,
    upsert_conversation_range,
)
from message_evidence_workstation.domain.constants import HIGHLIGHT_CONTEXT
from message_evidence_workstation.export.html_preview import render_conversation_html, write_conversation_html
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


def test_html_contains_messages_and_styles(tmp_path) -> None:
    conn = connect(tmp_path / "html.db")
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
    upsert_conversation_range(
        conn,
        logger,
        workstation_conversation_id=conversation.workstation_conversation_id,
        lead_in_start_message_id="msg_001",
        relevant_start_message_id="msg_001",
        relevant_end_message_id="msg_002",
        lead_out_end_message_id="msg_003",
    )
    set_highlight_override(
        conn,
        logger,
        workstation_conversation_id=conversation.workstation_conversation_id,
        message_id="msg_003",
        highlight_state=HIGHLIGHT_CONTEXT,
    )
    context = load_output_conversation_context(conn, conversation.workstation_conversation_id)
    assert context is not None
    html_text = render_conversation_html(context, include_audit=False)
    assert "Allergy paperwork" in html_text
    assert "Jane Doe" in html_text
    assert "msg_001" in html_text
    assert "class='message hit'" in html_text or 'class="message hit"' in html_text
    out = tmp_path / "preview.html"
    size = write_conversation_html(context, out, logger)
    assert size > 0
    assert out.exists()
