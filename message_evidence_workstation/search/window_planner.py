"""Token-bounded transcript window planning for exhaustive scan."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

_log = logging.getLogger(__name__)

from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.search.token_budget import estimate_tokens as _estimate_tokens
from message_evidence_workstation.search.transcript import estimate_token_count, load_dataset_messages, serialize_messages

DEFAULT_WINDOW_PLANNING_BATCH_SIZE = 500
MIN_WINDOW_TARGET_TOKENS = 256


@dataclass(slots=True)
class TranscriptWindow:
    window_id: str
    source_thread_id: str
    start_message_id: str
    end_message_id: str
    message_ids: list[str]
    estimated_tokens: int
    text: str


def _row_to_message(row: sqlite3.Row) -> Message:
    metadata = row["source_metadata_json"]
    if isinstance(metadata, str) and metadata.strip():
        try:
            metadata_obj = json.loads(metadata)
        except json.JSONDecodeError as exc:
            _log.warning(
                "Corrupt source_metadata_json for message_id=%s: %s",
                row["message_id"], exc,
            )
            metadata_obj = {}
    elif isinstance(metadata, dict):
        metadata_obj = metadata
    else:
        metadata_obj = {}
    return Message(
        message_id=row["message_id"],
        dataset_id=row["dataset_id"],
        source_thread_id=row["source_thread_id"],
        source_platform=row["source_platform"],
        source_message_id=row["source_message_id"],
        timestamp=row["timestamp"],
        sender_id=row["sender_id"],
        sender_display=row["sender_display"],
        body=row["body"],
        body_normalized=row["body_normalized"],
        has_attachment=bool(row["has_attachment"]),
        attachment_summary=row["attachment_summary"],
        sort_index=row["sort_index"],
        source_metadata_json=metadata_obj,
    )


def iter_thread_messages_for_window_planning(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
    *,
    batch_size: int = DEFAULT_WINDOW_PLANNING_BATCH_SIZE,
) -> Iterator[Message]:
    """Yield thread messages in chronological order without loading the full thread."""
    last_timestamp = ""
    last_sort_index = -1
    last_message_id = ""
    while True:
        rows = conn.execute(
            """
            SELECT message_id, dataset_id, source_thread_id, source_platform,
                   source_message_id, timestamp, sender_id, sender_display, body,
                   body_normalized, has_attachment, attachment_summary, sort_index,
                   source_metadata_json
            FROM message
            WHERE dataset_id = ?
              AND source_thread_id = ?
              AND (
                    timestamp > ?
                    OR (timestamp = ? AND sort_index > ?)
                    OR (timestamp = ? AND sort_index = ? AND message_id > ?)
                  )
            ORDER BY timestamp, sort_index, message_id
            LIMIT ?
            """,
            (
                dataset_id,
                source_thread_id,
                last_timestamp,
                last_timestamp,
                last_sort_index,
                last_timestamp,
                last_sort_index,
                last_message_id,
                batch_size,
            ),
        ).fetchall()
        if not rows:
            break
        for row in rows:
            message = _row_to_message(row)
            yield message
            last_timestamp = message.timestamp
            last_sort_index = message.sort_index
            last_message_id = message.message_id
        if len(rows) < batch_size:
            break


def _serialize_thread_window(
    messages: list[Message],
    *,
    source_thread_id: str,
    window_label: str,
) -> tuple[str, list[str]]:
    transcript = serialize_messages(messages, source_thread_id=source_thread_id)
    header = f"=== Transcript window {window_label} ({source_thread_id}) ==="
    return f"{header}\n{transcript.text}", transcript.message_ids


def _compute_chars_per_token(conn: sqlite3.Connection, dataset_id: int) -> int:
    """Call tiktoken once on the full dataset transcript to derive actual chars/token ratio.

    Returns ceil(total_chars / actual_tokens) so downstream ``window_planner`` can use
    ``ceil(chars / chars_per_token)`` instead of guessing ``ceil(chars / 4)``.
    """
    all_messages = load_dataset_messages(conn, dataset_id)
    serialized = serialize_messages(all_messages)
    if not serialized.text:
        return estimate_token_count(1)  # fallback: chars/4, returns 1
    result = _estimate_tokens(serialized.text)
    if result.method != "tiktoken":
        return estimate_token_count(1)  # tiktoken unavailable, same fallback
    actual_tokens = result.estimated_tokens
    if actual_tokens <= 0:
        return estimate_token_count(1)
    return max(1, math.ceil(serialized.char_count / actual_tokens))


def _pack_thread_message_stream_into_windows(
    message_iter: Iterator[Message],
    *,
    source_thread_id: str,
    window_id_prefix: str,
    target_tokens: int,
    overlap_messages: int,
    chars_per_token: int,
    window_counter_start: int = 0,
) -> tuple[list[TranscriptWindow], int]:
    """Pack a chronological thread stream using incremental char accounting.

    This avoids repeated full-window reserialization/tokenization for giant
    single-thread datasets during exhaustive scan planning.
    """

    windows: list[TranscriptWindow] = []
    window_counter = window_counter_start
    header = f"=== Transcript window scan ({source_thread_id}) ==="
    header_chars = len(header) + 1
    current_messages: list[Message] = []
    current_lines: list[str] = []
    current_line_chars = 0

    def _prepare_line(message: Message) -> tuple[str, int]:
        serialized = serialize_messages([message], source_thread_id=source_thread_id)
        return serialized.text, serialized.char_count

    def _window_char_count(line_chars: int, line_count: int) -> int:
        if line_count <= 0:
            return 0
        return header_chars + line_chars + max(0, line_count - 1)

    def _window_tokens(line_chars: int, line_count: int) -> int:
        return max(1, math.ceil(_window_char_count(line_chars, line_count) / chars_per_token))

    def _emit_current() -> None:
        nonlocal window_counter
        if not current_messages:
            return
        text = f"{header}\n" + "\n".join(current_lines)
        window_counter += 1
        windows.append(
            TranscriptWindow(
                window_id=f"{window_id_prefix}__window_{window_counter:03d}",
                source_thread_id=source_thread_id,
                start_message_id=current_messages[0].message_id,
                end_message_id=current_messages[-1].message_id,
                message_ids=[message.message_id for message in current_messages],
                estimated_tokens=max(1, math.ceil(len(text) / chars_per_token)),
                text=text,
            )
        )

    for message in message_iter:
        line_text, line_chars = _prepare_line(message)
        trial_line_count = len(current_lines) + 1
        trial_line_chars = current_line_chars + line_chars
        if not current_messages or _window_tokens(trial_line_chars, trial_line_count) <= target_tokens:
            current_messages.append(message)
            current_lines.append(line_text)
            current_line_chars = trial_line_chars
            continue

        _emit_current()
        if overlap_messages > 0:
            current_messages = current_messages[-overlap_messages:]
            current_lines = current_lines[-overlap_messages:]
            current_line_chars = sum(len(line) for line in current_lines)
        else:
            current_messages = []
            current_lines = []
            current_line_chars = 0

        current_messages.append(message)
        current_lines.append(line_text)
        current_line_chars += line_chars
        if _window_tokens(current_line_chars, len(current_lines)) > target_tokens:
            _emit_current()
            current_messages = []
            current_lines = []
            current_line_chars = 0

    if current_messages:
        _emit_current()
    return windows, window_counter


def build_token_bounded_windows_for_dataset(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    target_tokens: int,
    overlap_messages: int,
    model_id: str,
) -> list[TranscriptWindow]:
    """Pack each source thread's messages into token-bounded windows with overlap.

    Uses keyset iteration per thread so giant threads are not loaded into memory.
    """
    target_tokens = max(MIN_WINDOW_TARGET_TOKENS, target_tokens)
    overlap_messages = max(0, overlap_messages)
    rows = conn.execute(
        """
        SELECT DISTINCT source_thread_id
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id
        """,
        (dataset_id,),
    ).fetchall()
    chars_per_token = _compute_chars_per_token(conn, dataset_id)
    windows: list[TranscriptWindow] = []
    window_counter = 0
    for row in rows:
        thread_id = str(row["source_thread_id"])
        thread_windows, window_counter = _pack_thread_message_stream_into_windows(
            iter_thread_messages_for_window_planning(conn, dataset_id, thread_id),
            source_thread_id=thread_id,
            window_id_prefix=thread_id,
            target_tokens=target_tokens,
            overlap_messages=overlap_messages,
            chars_per_token=chars_per_token,
            window_counter_start=window_counter,
        )
        windows.extend(thread_windows)
    return windows
