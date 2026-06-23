"""Token-bounded transcript window planning for exhaustive scan."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

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
        start_index = 0
        while start_index < len(session_messages):
            best_end = start_index
            probe_end = start_index
            while probe_end < len(session_messages):
                chunk = session_messages[start_index : probe_end + 1]
                text, _message_ids = _serialize_window(chunk, session)
                tokens = estimate_tokens(text, model_id).estimated_tokens
                if tokens <= target_tokens:
                    best_end = probe_end
                    probe_end += 1
                else:
                    break
            chunk = session_messages[start_index : best_end + 1]
            text, message_ids = _serialize_window(chunk, session)
            token_estimate = estimate_tokens(text, model_id)
            window_counter += 1
            windows.append(
                TranscriptWindow(
                    window_id=f"{session.session_id}__window_{window_counter:03d}",
                    session_id=session.session_id,
                    source_thread_id=session.source_thread_id,
                    start_message_id=chunk[0].message_id,
                    end_message_id=chunk[-1].message_id,
                    message_ids=message_ids,
                    estimated_tokens=token_estimate.estimated_tokens,
                    text=text,
                )
            )
            if best_end >= len(session_messages) - 1:
                break
            next_start = best_end + 1 - overlap_messages
            if next_start <= start_index:
                next_start = best_end + 1
            start_index = next_start

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
