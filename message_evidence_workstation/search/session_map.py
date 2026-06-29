"""Session/day mapping for large-transcript coverage answering."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.embeddings.chunking import (
    ChunkingConfig,
    MessageChunkSpec,
    iter_dataset_chunks,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso
from message_evidence_workstation.search.transcript import (
    load_thread_messages,
    serialize_message_range,
    serialize_messages,
    sort_messages_chronologically,
)

DEFAULT_SESSION_GAP_MINUTES = 120
CONVERSATIONAL_SESSION_MAX_CHARS = 10_000_000
SESSION_STATUS_BUILT = "built"
SUMMARY_STATUS_PENDING = "pending"
SUMMARY_STATUS_READY = "ready"
SUMMARY_STATUS_FAILED = "failed"


@dataclass(slots=True)
class TranscriptSession:
    session_id: str
    dataset_id: int
    source_thread_id: str
    session_index: int
    calendar_date: str
    start_message_id: str
    end_message_id: str
    start_timestamp: str
    end_timestamp: str
    participants: list[str]
    message_count: int
    title: str
    status: str = SESSION_STATUS_BUILT
    summary_json: dict | None = None
    summary_status: str = SUMMARY_STATUS_PENDING


def _parse_timestamp(timestamp: str) -> datetime | None:
    if not timestamp:
        return None
    normalized = timestamp.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _calendar_date(timestamp: str) -> str:
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return "unknown"
    return parsed.date().isoformat()


def _session_title(messages: list[Message]) -> str:
    if not messages:
        return "Empty session"
    start_date = _calendar_date(messages[0].timestamp)
    participants = sorted({message.sender_display for message in messages if message.sender_display})
    participant_text = ", ".join(participants[:3])
    if len(participants) > 3:
        participant_text += ", …"
    return f"{start_date} | {participant_text} ({len(messages)} msgs)"


def build_sessions_for_thread(
    messages: list[Message],
    *,
    dataset_id: int,
    source_thread_id: str,
    gap_minutes: int = DEFAULT_SESSION_GAP_MINUTES,
) -> list[TranscriptSession]:
    ordered = sort_messages_chronologically(messages)
    if not ordered:
        return []
    gap = timedelta(minutes=max(1, gap_minutes))
    sessions: list[TranscriptSession] = []
    current: list[Message] = []
    current_day: str | None = None
    last_ts: datetime | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        participants = sorted({message.sender_display for message in current if message.sender_display})
        index = len(sessions) + 1
        sessions.append(
            TranscriptSession(
                session_id=f"{source_thread_id}__session_{index:03d}",
                dataset_id=dataset_id,
                source_thread_id=source_thread_id,
                session_index=index,
                calendar_date=_calendar_date(current[0].timestamp),
                start_message_id=current[0].message_id,
                end_message_id=current[-1].message_id,
                start_timestamp=current[0].timestamp,
                end_timestamp=current[-1].timestamp,
                participants=participants,
                message_count=len(current),
                title=_session_title(current),
            )
        )
        current = []

    for message in ordered:
        parsed = _parse_timestamp(message.timestamp)
        day = _calendar_date(message.timestamp)
        gap_break = (
            current
            and parsed is not None
            and last_ts is not None
            and parsed - last_ts > gap
        )
        day_break = current and current_day is not None and day != current_day
        if current and (gap_break or day_break):
            flush()
        current.append(message)
        current_day = day
        if parsed is not None:
            last_ts = parsed
    flush()
    return sessions


def build_sessions_for_dataset(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    gap_minutes: int = DEFAULT_SESSION_GAP_MINUTES,
    chunking_config: ChunkingConfig | None = None,
    use_semantic_chunks: bool = True,
) -> list[TranscriptSession]:
    if use_semantic_chunks:
        sessions = build_sessions_from_semantic_chunks(
            conn,
            dataset_id,
            gap_minutes=gap_minutes,
            chunking_config=chunking_config,
        )
        if sessions:
            return sessions
    rows = conn.execute(
        """
        SELECT DISTINCT source_thread_id
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id
        """,
        (dataset_id,),
    ).fetchall()
    sessions: list[TranscriptSession] = []
    for row in rows:
        thread_id = str(row["source_thread_id"])
        messages = load_thread_messages(conn, dataset_id, thread_id)
        sessions.extend(
            build_sessions_for_thread(
                messages,
                dataset_id=dataset_id,
                source_thread_id=thread_id,
                gap_minutes=gap_minutes,
            )
        )
    return sessions


def _message_lookup_for_dataset(conn: sqlite3.Connection, dataset_id: int) -> dict[str, Message]:
    rows = conn.execute(
        """
        SELECT message_id, dataset_id, source_thread_id, source_platform, source_message_id,
               timestamp, sender_id, sender_display, body, body_normalized,
               has_attachment, attachment_summary, sort_index, source_metadata_json
        FROM message
        WHERE dataset_id = ?
        """,
        (dataset_id,),
    ).fetchall()
    messages: dict[str, Message] = {}
    for row in rows:
        try:
            metadata = json.loads(row["source_metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        messages[str(row["message_id"])] = Message(
            message_id=str(row["message_id"]),
            dataset_id=int(row["dataset_id"]),
            source_thread_id=str(row["source_thread_id"]),
            source_platform=str(row["source_platform"]),
            source_message_id=str(row["source_message_id"]),
            timestamp=str(row["timestamp"]),
            sender_id=str(row["sender_id"]),
            sender_display=str(row["sender_display"]),
            body=str(row["body"] or ""),
            body_normalized=str(row["body_normalized"] or ""),
            has_attachment=bool(row["has_attachment"]),
            attachment_summary=str(row["attachment_summary"] or ""),
            sort_index=int(row["sort_index"]),
            source_metadata_json=metadata if isinstance(metadata, dict) else {},
        )
    return messages


def _messages_for_chunk(
    conn: sqlite3.Connection,
    dataset_id: int,
    chunk: MessageChunkSpec,
    lookup: dict[str, Message],
) -> list[Message]:
    rows = conn.execute(
        """
        SELECT message_id
        FROM message
        WHERE dataset_id = ? AND source_thread_id = ?
        ORDER BY sort_index, message_id
        """,
        (dataset_id, chunk.source_thread_id),
    ).fetchall()
    ordered_ids = [str(row["message_id"]) for row in rows]
    if chunk.start_message_id not in ordered_ids or chunk.end_message_id not in ordered_ids:
        return []
    start = ordered_ids.index(chunk.start_message_id)
    end = ordered_ids.index(chunk.end_message_id)
    if start > end:
        start, end = end, start
    return [lookup[message_id] for message_id in ordered_ids[start : end + 1] if message_id in lookup]


def build_sessions_from_semantic_chunks(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    gap_minutes: int = DEFAULT_SESSION_GAP_MINUTES,
    chunking_config: ChunkingConfig | None = None,
) -> list[TranscriptSession]:
    """Build transcript sessions from the same semantic boundaries used for chunk embeddings."""
    config = chunking_config or ChunkingConfig(
        session_gap_hours=max(1, gap_minutes) / 60.0,
        use_semantic_boundaries=True,
        split_on_date_change=True,
    )
    # LLM analysis sessions should follow semantic/time boundaries, not the embedding
    # chunker's storage-size ceiling. Embedding chunks can stay small elsewhere.
    config.max_chars = CONVERSATIONAL_SESSION_MAX_CHARS
    lookup = _message_lookup_for_dataset(conn, dataset_id)
    sessions: list[TranscriptSession] = []
    per_thread_index: dict[str, int] = defaultdict(int)
    for chunk in iter_dataset_chunks(conn, dataset_id, config=config):
        messages = _messages_for_chunk(conn, dataset_id, chunk, lookup)
        if not messages:
            continue
        per_thread_index[chunk.source_thread_id] += 1
        index = per_thread_index[chunk.source_thread_id]
        participants = sorted({message.sender_display for message in messages if message.sender_display})
        sessions.append(
            TranscriptSession(
                session_id=f"{chunk.source_thread_id}__session_{index:03d}",
                dataset_id=dataset_id,
                source_thread_id=chunk.source_thread_id,
                session_index=index,
                calendar_date=_calendar_date(messages[0].timestamp),
                start_message_id=chunk.start_message_id,
                end_message_id=chunk.end_message_id,
                start_timestamp=messages[0].timestamp,
                end_timestamp=messages[-1].timestamp,
                participants=participants,
                message_count=len(messages),
                title=_session_title(messages),
            )
        )
    return sessions


def clear_dataset_sessions(conn: sqlite3.Connection, dataset_id: int) -> None:
    conn.execute("DELETE FROM transcript_session WHERE dataset_id = ?", (dataset_id,))


def persist_sessions(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    sessions: list[TranscriptSession],
) -> None:
    clear_dataset_sessions(conn, dataset_id)
    now = utc_now_iso()
    for session in sessions:
        conn.execute(
            """
            INSERT INTO transcript_session (
                session_id, dataset_id, source_thread_id, session_index, calendar_date,
                start_message_id, end_message_id, start_timestamp, end_timestamp,
                participants_json, message_count, title, status, summary_json,
                summary_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                dataset_id,
                session.source_thread_id,
                session.session_index,
                session.calendar_date,
                session.start_message_id,
                session.end_message_id,
                session.start_timestamp,
                session.end_timestamp,
                json.dumps(session.participants),
                session.message_count,
                session.title,
                session.status,
                json.dumps(session.summary_json or {}),
                session.summary_status,
                now,
                now,
            ),
        )
    conn.commit()
    logger.info(
        component="search.session_map",
        operation="sessions_persisted",
        message="Persisted transcript sessions",
        details={"dataset_id": dataset_id, "session_count": len(sessions)},
        dataset_id=dataset_id,
    )


def rebuild_dataset_sessions(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    *,
    gap_minutes: int = DEFAULT_SESSION_GAP_MINUTES,
    chunking_config: ChunkingConfig | None = None,
    use_semantic_chunks: bool = True,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> list[TranscriptSession]:
    sessions = build_sessions_for_dataset(
        conn,
        dataset_id,
        gap_minutes=gap_minutes,
        chunking_config=chunking_config,
        use_semantic_chunks=use_semantic_chunks,
    )
    persist_sessions(conn, logger, dataset_id, sessions)
    if progress_callback is not None:
        progress_callback("sessions", len(sessions), len(sessions))
    return sessions


def _row_to_session(row: sqlite3.Row) -> TranscriptSession:
    summary_raw = row["summary_json"]
    try:
        summary_json = json.loads(summary_raw) if summary_raw else {}
    except json.JSONDecodeError:
        summary_json = {}
    participants_raw = row["participants_json"]
    try:
        participants = json.loads(participants_raw) if participants_raw else []
    except json.JSONDecodeError:
        participants = []
    return TranscriptSession(
        session_id=str(row["session_id"]),
        dataset_id=int(row["dataset_id"]),
        source_thread_id=str(row["source_thread_id"]),
        session_index=int(row["session_index"]),
        calendar_date=str(row["calendar_date"]),
        start_message_id=str(row["start_message_id"]),
        end_message_id=str(row["end_message_id"]),
        start_timestamp=str(row["start_timestamp"]),
        end_timestamp=str(row["end_timestamp"]),
        participants=[str(item) for item in participants],
        message_count=int(row["message_count"]),
        title=str(row["title"]),
        status=str(row["status"]),
        summary_json=summary_json if isinstance(summary_json, dict) else {},
        summary_status=str(row["summary_status"]),
    )


def list_sessions(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    source_thread_id: str | None = None,
) -> list[TranscriptSession]:
    query = """
        SELECT session_id, dataset_id, source_thread_id, session_index, calendar_date,
               start_message_id, end_message_id, start_timestamp, end_timestamp,
               participants_json, message_count, title, status, summary_json,
               summary_status
        FROM transcript_session
        WHERE dataset_id = ?
    """
    params: list[object] = [dataset_id]
    if source_thread_id is not None:
        query += " AND source_thread_id = ?"
        params.append(source_thread_id)
    query += " ORDER BY source_thread_id, session_index"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_session(row) for row in rows]


def get_session(
    conn: sqlite3.Connection,
    dataset_id: int,
    session_id: str,
) -> TranscriptSession | None:
    row = conn.execute(
        """
        SELECT session_id, dataset_id, source_thread_id, session_index, calendar_date,
               start_message_id, end_message_id, start_timestamp, end_timestamp,
               participants_json, message_count, title, status, summary_json,
               summary_status
        FROM transcript_session
        WHERE dataset_id = ? AND session_id = ?
        """,
        (dataset_id, session_id),
    ).fetchone()
    if row is None:
        return None
    return _row_to_session(row)


def update_session_summary(
    conn: sqlite3.Connection,
    *,
    dataset_id: int,
    session_id: str,
    summary_json: dict,
    summary_status: str,
) -> None:
    conn.execute(
        """
        UPDATE transcript_session
        SET summary_json = ?, summary_status = ?, updated_at = ?
        WHERE dataset_id = ? AND session_id = ?
        """,
        (json.dumps(summary_json), summary_status, utc_now_iso(), dataset_id, session_id),
    )
    conn.commit()


def serialize_session_transcript(
    conn: sqlite3.Connection,
    dataset_id: int,
    session: TranscriptSession,
    *,
    padding: int = 0,
) -> tuple[str, list[str]]:
    messages = load_thread_messages(conn, dataset_id, session.source_thread_id)
    ordered_ids = [message.message_id for message in messages]
    if session.start_message_id not in ordered_ids or session.end_message_id not in ordered_ids:
        transcript = serialize_messages([])
        return transcript.text, transcript.message_ids
    start_index = ordered_ids.index(session.start_message_id)
    end_index = ordered_ids.index(session.end_message_id)
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    padded_start = max(0, start_index - max(0, padding))
    padded_end = min(len(messages) - 1, end_index + max(0, padding))
    window = messages[padded_start : padded_end + 1]
    transcript = serialize_messages(window, source_thread_id=session.source_thread_id)
    header = f"=== Session {session.session_id} ({session.title}) ==="
    return f"{header}\n{transcript.text}", transcript.message_ids


def sessions_by_thread(sessions: list[TranscriptSession]) -> dict[str, list[TranscriptSession]]:
    grouped: dict[str, list[TranscriptSession]] = defaultdict(list)
    for session in sessions:
        grouped[session.source_thread_id].append(session)
    return dict(grouped)
