"""Token-bounded transcript window planning for exhaustive scan."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.search.session_map import TranscriptSession, load_thread_messages
from message_evidence_workstation.search.token_budget import estimate_tokens
from message_evidence_workstation.search.transcript import serialize_messages

DEFAULT_WINDOW_PLANNING_BATCH_SIZE = 500
MIN_WINDOW_TARGET_TOKENS = 256


@dataclass(slots=True)
class TranscriptWindow:
    window_id: str
    session_id: str
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
        except json.JSONDecodeError:
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


def _session_messages(
    conn: sqlite3.Connection,
    dataset_id: int,
    session: TranscriptSession,
) -> list[Message]:
    messages = load_thread_messages(conn, dataset_id, session.source_thread_id)
    ordered_ids = [message.message_id for message in messages]
    if session.start_message_id not in ordered_ids or session.end_message_id not in ordered_ids:
        return []
    start_index = ordered_ids.index(session.start_message_id)
    end_index = ordered_ids.index(session.end_message_id)
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    return messages[start_index : end_index + 1]


def _serialize_window(messages: list[Message], session: TranscriptSession) -> tuple[str, list[str]]:
    transcript = serialize_messages(messages, source_thread_id=session.source_thread_id)
    header = f"=== Session {session.session_id} ({session.title}) ==="
    return f"{header}\n{transcript.text}", transcript.message_ids


def _serialize_thread_window(
    messages: list[Message],
    *,
    source_thread_id: str,
    window_label: str,
) -> tuple[str, list[str]]:
    transcript = serialize_messages(messages, source_thread_id=source_thread_id)
    header = f"=== Transcript window {window_label} ({source_thread_id}) ==="
    return f"{header}\n{transcript.text}", transcript.message_ids


def _pack_messages_into_windows(
    messages: list[Message],
    *,
    source_thread_id: str,
    window_id_prefix: str,
    session_id: str,
    target_tokens: int,
    overlap_messages: int,
    model_id: str,
    serialize_chunk: Callable[[list[Message]], tuple[str, list[str]]],
    window_counter_start: int = 0,
) -> tuple[list[TranscriptWindow], int]:
    windows: list[TranscriptWindow] = []
    window_counter = window_counter_start
    if not messages:
        return windows, window_counter

    start_index = 0
    while start_index < len(messages):
        best_end = start_index
        probe_end = start_index
        while probe_end < len(messages):
            chunk = messages[start_index : probe_end + 1]
            text, _message_ids = serialize_chunk(chunk)
            tokens = estimate_tokens(text, model_id).estimated_tokens
            if tokens <= target_tokens:
                best_end = probe_end
                probe_end += 1
            else:
                break
        chunk = messages[start_index : best_end + 1]
        text, message_ids = serialize_chunk(chunk)
        token_estimate = estimate_tokens(text, model_id)
        window_counter += 1
        windows.append(
            TranscriptWindow(
                window_id=f"{window_id_prefix}__window_{window_counter:03d}",
                session_id=session_id,
                source_thread_id=source_thread_id,
                start_message_id=chunk[0].message_id,
                end_message_id=chunk[-1].message_id,
                message_ids=message_ids,
                estimated_tokens=token_estimate.estimated_tokens,
                text=text,
            )
        )
        if best_end >= len(messages) - 1:
            break
        next_start = best_end + 1 - overlap_messages
        if next_start <= start_index:
            next_start = best_end + 1
        start_index = next_start
    return windows, window_counter


def _pack_message_stream_into_windows(
    message_iter: Iterator[Message],
    *,
    source_thread_id: str,
    window_id_prefix: str,
    session_id: str,
    target_tokens: int,
    overlap_messages: int,
    model_id: str,
    serialize_chunk: Callable[[list[Message]], tuple[str, list[str]]],
    window_counter_start: int = 0,
) -> tuple[list[TranscriptWindow], int]:
    """Pack a chronological message stream without materializing the full thread."""
    windows: list[TranscriptWindow] = []
    window_counter = window_counter_start
    current: list[Message] = []

    def emit_window(chunk: list[Message]) -> None:
        nonlocal window_counter
        if not chunk:
            return
        text, message_ids = serialize_chunk(chunk)
        token_estimate = estimate_tokens(text, model_id)
        window_counter += 1
        windows.append(
            TranscriptWindow(
                window_id=f"{window_id_prefix}__window_{window_counter:03d}",
                session_id=session_id,
                source_thread_id=source_thread_id,
                start_message_id=chunk[0].message_id,
                end_message_id=chunk[-1].message_id,
                message_ids=message_ids,
                estimated_tokens=token_estimate.estimated_tokens,
                text=text,
            )
        )

    for message in message_iter:
        if not current:
            current = [message]
            continue
        trial = current + [message]
        trial_text, _ = serialize_chunk(trial)
        if estimate_tokens(trial_text, model_id).estimated_tokens <= target_tokens:
            current = trial
            continue
        emit_window(current)
        if overlap_messages > 0:
            current = current[-overlap_messages:] + [message]
        else:
            current = [message]
        solo_text, _ = serialize_chunk(current)
        if estimate_tokens(solo_text, model_id).estimated_tokens > target_tokens:
            emit_window(current)
            current = []

    if current:
        emit_window(current)
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
    windows: list[TranscriptWindow] = []
    window_counter = 0
    for row in rows:
        thread_id = str(row["source_thread_id"])
        thread_windows, window_counter = _pack_message_stream_into_windows(
            iter_thread_messages_for_window_planning(conn, dataset_id, thread_id),
            source_thread_id=thread_id,
            window_id_prefix=thread_id,
            session_id=thread_id,
            target_tokens=target_tokens,
            overlap_messages=overlap_messages,
            model_id=model_id,
            serialize_chunk=lambda chunk, tid=thread_id: _serialize_thread_window(
                chunk,
                source_thread_id=tid,
                window_label="scan",
            ),
            window_counter_start=window_counter,
        )
        windows.extend(thread_windows)
    return windows


def build_token_bounded_windows(
    conn: sqlite3.Connection,
    dataset_id: int,
    sessions: list[TranscriptSession],
    *,
    target_tokens: int,
    overlap_messages: int,
    model_id: str,
) -> list[TranscriptWindow]:
    ordered_sessions = sorted(
        sessions,
        key=lambda session: (session.source_thread_id, session.session_index, session.session_id),
    )
    windows: list[TranscriptWindow] = []
    window_counter = 0
    target_tokens = max(MIN_WINDOW_TARGET_TOKENS, target_tokens)
    overlap_messages = max(0, overlap_messages)

    for session in ordered_sessions:
        session_messages = _session_messages(conn, dataset_id, session)
        if not session_messages:
            continue

        def _serialize_session_chunk(
            chunk: list[Message],
            active_session: TranscriptSession = session,
        ) -> tuple[str, list[str]]:
            return _serialize_window(chunk, active_session)

        session_windows, window_counter = _pack_messages_into_windows(
            session_messages,
            source_thread_id=session.source_thread_id,
            window_id_prefix=session.session_id,
            session_id=session.session_id,
            target_tokens=target_tokens,
            overlap_messages=overlap_messages,
            model_id=model_id,
            serialize_chunk=_serialize_session_chunk,
            window_counter_start=window_counter,
        )
        windows.extend(session_windows)

    return windows


def all_session_message_ids(
    conn: sqlite3.Connection,
    dataset_id: int,
    sessions: list[TranscriptSession],
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for session in sorted(
        sessions,
        key=lambda row: (row.source_thread_id, row.session_index, row.session_id),
    ):
        for message in _session_messages(conn, dataset_id, session):
            if message.message_id not in seen:
                seen.add(message.message_id)
                ordered.append(message.message_id)
    return ordered
