"""Slot-based message boundary helpers for evidence blocks."""

from __future__ import annotations


def validate_slot_bounds(
    message_count: int,
    context_start_slot: int,
    relevant_start_slot: int,
    relevant_end_slot: int,
    context_end_slot: int,
) -> None:
    if message_count < 0:
        raise ValueError("message_count must be non-negative")
    upper = message_count
    if not (
        0 <= context_start_slot <= relevant_start_slot <= relevant_end_slot <= context_end_slot <= upper
    ):
        raise ValueError(
            "Slot invariant violated: "
            f"context_start({context_start_slot}) <= relevant_start({relevant_start_slot}) "
            f"<= relevant_end({relevant_end_slot}) <= context_end({context_end_slot}) <= {upper}"
        )


def message_indices_for_slot_range(start_slot: int, end_slot: int) -> range:
    return range(start_slot, end_slot)


def message_ids_for_slot_range(ordered_message_ids: list[str], start_slot: int, end_slot: int) -> list[str]:
    return [
        ordered_message_ids[index]
        for index in message_indices_for_slot_range(start_slot, end_slot)
        if 0 <= index < len(ordered_message_ids)
    ]


def default_slots_for_hit_index(message_count: int, hit_index: int) -> tuple[int, int, int, int]:
    if message_count <= 0:
        return (0, 0, 0, 0)
    hit_index = max(0, min(hit_index, message_count - 1))
    relevant_start = hit_index
    relevant_end = hit_index + 1
    context_start = max(0, hit_index - 1)
    context_end = min(message_count, hit_index + 2)
    return context_start, relevant_start, relevant_end, context_end


def hit_index_for_message(ordered_message_ids: list[str], message_id: str) -> int:
    try:
        return ordered_message_ids.index(message_id)
    except ValueError:
        return 0


def slots_from_message_boundary_ids(
    ordered_message_ids: list[str],
    *,
    leading_context_start_message_id: str,
    relevant_start_message_id: str,
    relevant_end_message_id: str,
    trailing_context_end_message_id: str,
) -> tuple[int, int, int, int]:
    context_start = hit_index_for_message(ordered_message_ids, leading_context_start_message_id)
    relevant_start = hit_index_for_message(ordered_message_ids, relevant_start_message_id)
    relevant_end = hit_index_for_message(ordered_message_ids, relevant_end_message_id) + 1
    context_end = hit_index_for_message(ordered_message_ids, trailing_context_end_message_id) + 1
    message_count = len(ordered_message_ids)
    context_start = max(0, min(context_start, message_count))
    relevant_start = max(context_start, min(relevant_start, message_count))
    relevant_end = max(relevant_start, min(relevant_end, message_count))
    context_end = max(relevant_end, min(context_end, message_count))
    return context_start, relevant_start, relevant_end, context_end
