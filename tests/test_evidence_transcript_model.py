"""EvidenceTranscriptModel tests."""

from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.ui.transcript_surface import EvidenceTranscriptModel


def _sample_messages() -> list[Message]:
    return [
        Message(
            message_id="msg_001",
            dataset_id=1,
            source_thread_id="thread_001",
            source_platform="facebook",
            source_message_id="s1",
            timestamp="2024-01-01T10:00:00+00:00",
            sender_id="a",
            sender_display="Alice",
            body="first",
            body_normalized="first",
            has_attachment=False,
            attachment_summary="",
            sort_index=0,
            source_metadata_json={},
        ),
        Message(
            message_id="msg_002",
            dataset_id=1,
            source_thread_id="thread_001",
            source_platform="facebook",
            source_message_id="s2",
            timestamp="2024-01-01T10:01:00+00:00",
            sender_id="b",
            sender_display="Bob",
            body="second",
            body_normalized="second",
            has_attachment=False,
            attachment_summary="",
            sort_index=1,
            source_metadata_json={},
        ),
        Message(
            message_id="msg_003",
            dataset_id=1,
            source_thread_id="thread_001",
            source_platform="facebook",
            source_message_id="s3",
            timestamp="2024-01-01T10:02:00+00:00",
            sender_id="a",
            sender_display="Alice",
            body="third",
            body_normalized="third",
            has_attachment=False,
            attachment_summary="",
            sort_index=2,
            source_metadata_json={},
        ),
    ]


def test_draft_boundaries_respect_slot_invariant() -> None:
    model = EvidenceTranscriptModel()
    model.load_messages(_sample_messages())
    model.move_boundary("context_start", 0)
    model.move_boundary("relevant_start", 1)
    model.move_boundary("context_end", 3)
    model.move_boundary("relevant_end", 2)
    assert model.active_slots() == (0, 1, 2, 3)


def test_invalid_boundary_move_is_ignored() -> None:
    model = EvidenceTranscriptModel()
    model.load_messages(_sample_messages())
    model.move_boundary("relevant_start", 3)
    assert model.active_slots()[1] == 0


def test_relevant_start_drag_pushes_context_start_outward() -> None:
    model = EvidenceTranscriptModel()
    model.load_messages(_sample_messages())
    model.move_boundary("context_end", 3)
    model.move_boundary("relevant_end", 2)
    model.move_boundary("relevant_start", 1)
    model.move_boundary("context_start", 1)
    assert model.active_slots() == (1, 1, 2, 3)

    model.move_boundary("relevant_start", 0)
    assert model.active_slots() == (0, 0, 2, 3)


def test_relevant_end_drag_pushes_context_end_outward() -> None:
    model = EvidenceTranscriptModel()
    model.load_messages(_sample_messages())
    model.move_boundary("context_end", 2)
    model.move_boundary("relevant_end", 2)
    model.move_boundary("relevant_start", 1)
    assert model.active_slots() == (0, 1, 2, 2)

    model.move_boundary("relevant_end", 3)
    assert model.active_slots() == (0, 1, 3, 3)


def test_toggle_highlight_tracks_draft_state_without_blocks() -> None:
    model = EvidenceTranscriptModel()
    model.load_messages(_sample_messages())
    model.toggle_highlight_row(1)
    assert "msg_001" in model.highlighted_message_ids()


def test_per_block_anchor_and_highlight_track_each_overlay() -> None:
    model = EvidenceTranscriptModel()
    from message_evidence_workstation.domain.models import EvidenceBlock

    messages = _sample_messages()
    model.load_thread_blocks(
        messages,
        [
            EvidenceBlock(
                evidence_block_id=1,
                dataset_id=1,
                category_id=1,
                source_thread_id="thread_001",
                title="Block A",
                summary="",
                core_hit_message_id="msg_002",
                context_start_slot=0,
                relevant_start_slot=1,
                relevant_end_slot=2,
                context_end_slot=3,
                highlighted_message_ids=frozenset(),
                created_by="manual",
                created_at="",
                updated_at="",
            )
        ],
    )
    assert model.overlays_for_relevant_message(0) == []
    assert len(model.overlays_for_relevant_message(1)) == 1
    model.set_anchor_message(1, "msg_001")
    assert model.overlay_by_id(1).core_hit_message_id == "msg_001"
    model.toggle_highlight_for_block(1, "msg_002")
    assert "msg_002" in model.overlay_by_id(1).highlighted_message_ids


def test_virtualized_separator_updates_stay_bounded() -> None:
    from message_evidence_workstation.domain.models import EvidenceBlock
    from message_evidence_workstation.ui.transcript_data_source import InMemoryTranscriptDataSource

    messages = _sample_messages()
    messages.extend(
        Message(
            message_id=f"msg_{index:03d}",
            dataset_id=1,
            source_thread_id="thread_001",
            source_platform="facebook",
            source_message_id=f"s{index}",
            timestamp=f"2024-01-01T10:{index % 60:02d}:00+00:00",
            sender_id="a",
            sender_display="Alice",
            body=f"body {index}",
            body_normalized=f"body {index}",
            has_attachment=False,
            attachment_summary="",
            sort_index=index,
            source_metadata_json={},
        )
        for index in range(4, 5_000)
    )
    data_source = InMemoryTranscriptDataSource({"thread_001": messages})
    model = EvidenceTranscriptModel()
    model.load_thread_virtualized(data_source, "thread_001", [])

    emit_count = 0
    original_emit = model._emit_separator_change

    def counting_emit(slot_index: int) -> None:
        nonlocal emit_count
        emit_count += 1
        original_emit(slot_index)

    model._emit_separator_change = counting_emit  # type: ignore[method-assign]
    model.append_evidence_block(
        EvidenceBlock(
            evidence_block_id=99,
            dataset_id=1,
            category_id=1,
            source_thread_id="thread_001",
            title="Far block",
            summary="",
            core_hit_message_id="msg_4000",
            context_start_slot=3990,
            relevant_start_slot=3995,
            relevant_end_slot=4000,
            context_end_slot=4005,
            highlighted_message_ids=frozenset(),
            created_by="manual",
            created_at="",
            updated_at="",
        )
    )
    assert emit_count < 500
    assert emit_count > 0
