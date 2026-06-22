"""Compute per-message highlight states for output formatting."""

from __future__ import annotations

from message_evidence_workstation.domain.constants import (
    HIGHLIGHT_CONTEXT,
    HIGHLIGHT_HIT,
    HIGHLIGHT_NONE,
    HIGHLIGHT_RELEVANT,
)
from message_evidence_workstation.domain.models import ConversationRange, Message


def _message_index(messages: list[Message], message_id: str | None) -> int | None:
    if not message_id:
        return None
    for index, message in enumerate(messages):
        if message.message_id == message_id:
            return index
    return None


def compute_message_display_states(
    messages: list[Message],
    *,
    hit_message_ids: set[str],
    conversation_range: ConversationRange | None,
    highlight_overrides: dict[str, str],
) -> dict[str, str]:
    states: dict[str, str] = {}
    lead_in = _message_index(messages, conversation_range.lead_in_start_message_id if conversation_range else None)
    rel_start = _message_index(
        messages, conversation_range.relevant_start_message_id if conversation_range else None
    )
    rel_end = _message_index(messages, conversation_range.relevant_end_message_id if conversation_range else None)
    lead_out = _message_index(messages, conversation_range.lead_out_end_message_id if conversation_range else None)

    for index, message in enumerate(messages):
        message_id = message.message_id
        if message_id in highlight_overrides:
            states[message_id] = highlight_overrides[message_id]
            continue
        if message_id in hit_message_ids:
            states[message_id] = HIGHLIGHT_HIT
            continue
        if (
            conversation_range is not None
            and lead_in is not None
            and rel_start is not None
            and rel_end is not None
            and lead_out is not None
        ):
            if rel_start <= index <= rel_end:
                states[message_id] = HIGHLIGHT_RELEVANT
            elif lead_in <= index < rel_start or rel_end < index <= lead_out:
                states[message_id] = HIGHLIGHT_CONTEXT
            else:
                states[message_id] = HIGHLIGHT_NONE
        else:
            states[message_id] = HIGHLIGHT_NONE
    return states


def boundary_labels_for_range(
    messages: list[Message],
    conversation_range: ConversationRange | None,
) -> dict[str, str]:
    if conversation_range is None:
        return {}
    labels: dict[str, str] = {}
    mapping = {
        conversation_range.lead_in_start_message_id: "lead-in start",
        conversation_range.relevant_start_message_id: "relevant start",
        conversation_range.relevant_end_message_id: "relevant end",
        conversation_range.lead_out_end_message_id: "lead-out end",
    }
    valid_ids = {message.message_id for message in messages}
    for message_id, label in mapping.items():
        if message_id and message_id in valid_ids:
            labels[message_id] = label
    return labels


def messages_in_export_window(
    messages: list[Message],
    conversation_range: ConversationRange | None,
) -> list[Message]:
    if conversation_range is None:
        return list(messages)
    start = _message_index(messages, conversation_range.lead_in_start_message_id)
    end = _message_index(messages, conversation_range.lead_out_end_message_id)
    if start is None or end is None:
        return list(messages)
    if start > end:
        start, end = end, start
    return messages[start : end + 1]
