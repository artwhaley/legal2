"""Range suggestion and highlight override tests (T20)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.db.repositories import (
    create_category,
    create_workstation_conversation_from_search,
    get_conversation_range,
    list_highlight_overrides,
    load_output_conversation_context,
    set_highlight_override,
    upsert_conversation_range,
)
from message_evidence_workstation.domain.constants import HIGHLIGHT_HIT, HIGHLIGHT_RELEVANT
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimChatResult
from message_evidence_workstation.output.display_states import compute_message_display_states
from message_evidence_workstation.search.range_suggestion import (
    parse_range_suggestion_response,
    run_range_suggestion,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


def _conversation(tmp_path):
    conn = connect(tmp_path / "ranges.db")
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
    return conn, logger, conversation


def test_parse_range_suggestion_response() -> None:
    content = json.dumps(
        {
            "lead_in_start_message_id": "msg_001",
            "relevant_start_message_id": "msg_001",
            "relevant_end_message_id": "msg_002",
            "lead_out_end_message_id": "msg_003",
            "explanation": "Covers allergy discussion.",
        }
    )
    result = parse_range_suggestion_response(content)
    assert result.relevant_end_message_id == "msg_002"


def test_upsert_and_reload_range(tmp_path) -> None:
    conn, logger, conversation = _conversation(tmp_path)
    upsert_conversation_range(
        conn,
        logger,
        workstation_conversation_id=conversation.workstation_conversation_id,
        lead_in_start_message_id="msg_001",
        relevant_start_message_id="msg_001",
        relevant_end_message_id="msg_002",
        lead_out_end_message_id="msg_003",
        user_modified=True,
    )
    stored = get_conversation_range(conn, conversation.workstation_conversation_id)
    assert stored is not None
    assert stored.user_modified
    context = load_output_conversation_context(conn, conversation.workstation_conversation_id)
    assert context is not None
    assert context.display_states["msg_001"] == HIGHLIGHT_HIT
    assert context.display_states["msg_002"] == HIGHLIGHT_RELEVANT


def test_highlight_override_persists(tmp_path) -> None:
    conn, logger, conversation = _conversation(tmp_path)
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
        message_id="msg_002",
        highlight_state=HIGHLIGHT_HIT,
    )
    overrides = list_highlight_overrides(conn, conversation.workstation_conversation_id)
    assert overrides["msg_002"] == HIGHLIGHT_HIT
    context = load_output_conversation_context(conn, conversation.workstation_conversation_id)
    assert context is not None
    assert context.display_states["msg_002"] == HIGHLIGHT_HIT


def test_run_range_suggestion_mock_nim(tmp_path) -> None:
    conn, logger, conversation = _conversation(tmp_path)
    context = load_output_conversation_context(conn, conversation.workstation_conversation_id)
    assert context is not None
    mock_client = MagicMock()
    mock_client.settings.model = "test-model"
    payload = {
        "lead_in_start_message_id": "msg_001",
        "relevant_start_message_id": "msg_001",
        "relevant_end_message_id": "msg_002",
        "lead_out_end_message_id": "msg_003",
        "explanation": "Suggested by NIM.",
    }
    with patch(
        "message_evidence_workstation.search.range_suggestion.run_nim_chat",
        return_value=NimChatResult(content=json.dumps(payload), raw_response={}, latency_ms=3),
    ):
        result = run_range_suggestion(
            conn,
            logger,
            mock_client,
            context=context,
            dataset_id=context.conversation.dataset_id,
        )
    assert result.relevant_end_message_id == "msg_002"


def test_compute_display_states_without_range() -> None:
    from message_evidence_workstation.domain.models import Message

    messages = [
        Message(
            message_id="m1",
            dataset_id=1,
            source_thread_id="t",
            source_platform="fb",
            source_message_id="s1",
            timestamp="t",
            sender_id="a",
            sender_display="A",
            body="hi",
            body_normalized="hi",
            has_attachment=False,
            attachment_summary="",
            sort_index=0,
            source_metadata_json={},
        )
    ]
    states = compute_message_display_states(messages, hit_message_ids={"m1"}, conversation_range=None, highlight_overrides={})
    assert states["m1"] == HIGHLIGHT_HIT
