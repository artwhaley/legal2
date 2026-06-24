"""Token-bounded transcript window planning for exhaustive scan."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from collections.abc import Callable

from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.search.session_map import TranscriptSession, load_thread_messages
from message_evidence_workstation.search.token_budget import estimate_tokens
from message_evidence_workstation.search.transcript import serialize_messages


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


def build_token_bounded_windows_for_dataset(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    target_tokens: int,
    overlap_messages: int,
    model_id: str,
) -> list[TranscriptWindow]:
    """Pack each source thread's messages into token-bounded windows with overlap.

    Does not use embedding semantic chunks or transcript sessions — only chronological
    message order within each thread.
    """
    target_tokens = max(500, target_tokens)
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
        messages = load_thread_messages(conn, dataset_id, thread_id)
        thread_windows, window_counter = _pack_messages_into_windows(
            messages,
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
    target_tokens = max(500, target_tokens)
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
