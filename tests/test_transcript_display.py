"""Transcript display formatting tests."""

from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.ui.transcript_display import (
    build_sender_participant_map,
    format_timestamp_label,
    normalize_speaker_tints,
)


def _message(sender_id: str, sender_display: str, message_id: str) -> Message:
    return Message(
        message_id=message_id,
        dataset_id=1,
        source_thread_id="thread_001",
        source_platform="messenger",
        source_message_id=message_id,
        timestamp="2024-01-02T14:30:00-06:00",
        sender_id=sender_id,
        sender_display=sender_display,
        body="hello",
        body_normalized="hello",
        has_attachment=False,
        attachment_summary="",
        sort_index=0,
        source_metadata_json={},
    )


def test_format_timestamp_label_is_compact_with_timezone() -> None:
    label = format_timestamp_label("2024-01-02T14:30:00-06:00")
    assert "January 2, 2024" in label
    assert "2:30PM" in label
    assert " : " in label


def test_build_sender_participant_map_uses_ascending_sender_id() -> None:
    messages = [
        _message("jane", "Jane", "msg_002"),
        _message("art", "Art", "msg_001"),
        _message("jane", "Jane", "msg_003"),
    ]
    mapping = build_sender_participant_map(messages)
    assert mapping["art"] == 0
    assert mapping["jane"] == 1


def test_normalize_speaker_tints_pads_to_eight() -> None:
    tints = normalize_speaker_tints(["#112233"])
    assert len(tints) == 8
    assert tints[0] == "#112233"
