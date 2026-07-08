"""Transcript serialization for conversational answering."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

_log = logging.getLogger(__name__)

from message_evidence_workstation.db import repositories
from message_evidence_workstation.db.repositories import _json_loads
from message_evidence_workstation.domain.models import Message
from message_evidence_workstation.search.date_scope import MessageDateScope, date_scope_sql_clauses

CHARS_PER_TOKEN_ESTIMATE = 4
_EMPTY_BODY_PLACEHOLDER = "(empty message)"


@dataclass(slots=True)
class TranscriptLine:
    message_id: str
    source_thread_id: str
    timestamp: str
    display_timestamp: str
    sender_display: str
    body: str
    sort_index: int
    line_text: str


@dataclass(slots=True)
class SerializedTranscript:
    source_thread_id: str
    lines: list[TranscriptLine]
    text: str
    message_ids: list[str]
    char_count: int
    approximate_token_count: int


def _display_timestamp(timestamp: str) -> str:
    if not timestamp:
        _log.warning("Empty timestamp value")
        return "unknown"
    normalized = timestamp.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        _log.warning("Malformed timestamp value: %r", timestamp)
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", timestamp)
        if match:
            return match.group(1)
        return timestamp[:16]


def _body_text(message: Message) -> str:
    body = (message.body or "").strip()
    return body if body else _EMPTY_BODY_PLACEHOLDER


def _format_line(message: Message) -> TranscriptLine:
    body = _body_text(message)
    display_ts = _display_timestamp(message.timestamp)
    line_text = f"[{message.message_id}] {display_ts} | {message.sender_display}: {body}"
    return TranscriptLine(
        message_id=message.message_id,
        source_thread_id=message.source_thread_id,
        timestamp=message.timestamp,
        display_timestamp=display_ts,
        sender_display=message.sender_display,
        body=body,
        sort_index=message.sort_index,
        line_text=line_text,
    )


def sort_messages_chronologically(messages: list[Message]) -> list[Message]:
    return sorted(messages, key=lambda row: (row.timestamp, row.sort_index, row.message_id))


def load_thread_messages(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
) -> list[Message]:
    return sort_messages_chronologically(
        repositories.list_messages_for_thread(conn, dataset_id, source_thread_id)
    )


def load_dataset_messages(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    date_scope: MessageDateScope | None = None,
) -> list[Message]:
    date_clause, date_params = date_scope_sql_clauses(date_scope)
    base_params = (dataset_id,)
    all_params = base_params + date_params
    sql = f"""
        SELECT message_id, dataset_id, source_thread_id, source_platform,
               source_message_id, timestamp, sender_id, sender_display, body,
               body_normalized, has_attachment, attachment_summary, sort_index,
               source_metadata_json
        FROM message
        WHERE dataset_id = ?
        {"AND " + date_clause if date_clause else ""}
        ORDER BY source_thread_id, timestamp, sort_index, message_id
        """
    rows = conn.execute(sql, all_params).fetchall()
    messages = [
        Message(
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
            source_metadata_json=_json_loads(row["source_metadata_json"]),
        )
        for row in rows
    ]
    return sort_messages_chronologically(messages)


def serialize_messages(
    messages: list[Message],
    *,
    source_thread_id: str | None = None,
) -> SerializedTranscript:
    if not messages:
        thread_id = source_thread_id or ""
        return SerializedTranscript(
            source_thread_id=thread_id,
            lines=[],
            text="",
            message_ids=[],
            char_count=0,
            approximate_token_count=0,
        )
    ordered = sort_messages_chronologically(messages)
    thread_id = source_thread_id or ordered[0].source_thread_id
    lines = [_format_line(message) for message in ordered]
    text = "\n".join(line.line_text for line in lines)
    char_count = len(text)
    return SerializedTranscript(
        source_thread_id=thread_id,
        lines=lines,
        text=text,
        message_ids=[line.message_id for line in lines],
        char_count=char_count,
        approximate_token_count=estimate_token_count(char_count),
    )


def serialize_thread_transcript(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
) -> SerializedTranscript:
    messages = load_thread_messages(conn, dataset_id, source_thread_id)
    return serialize_messages(messages, source_thread_id=source_thread_id)


def serialize_message_range(
    messages: list[Message],
    *,
    start_message_id: str,
    end_message_id: str,
    source_thread_id: str | None = None,
) -> SerializedTranscript:
    ordered = sort_messages_chronologically(messages)
    ids = [message.message_id for message in ordered]
    if start_message_id not in ids or end_message_id not in ids:
        return serialize_messages([], source_thread_id=source_thread_id)
    start_index = ids.index(start_message_id)
    end_index = ids.index(end_message_id)
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    return serialize_messages(
        ordered[start_index : end_index + 1],
        source_thread_id=source_thread_id or (ordered[0].source_thread_id if ordered else None),
    )


def estimate_token_count(char_count: int) -> int:
    if char_count <= 0:
        return 0
    return max(1, (char_count + CHARS_PER_TOKEN_ESTIMATE - 1) // CHARS_PER_TOKEN_ESTIMATE)


def transcript_fits_budget(transcript: SerializedTranscript, max_chars: int) -> bool:
    return transcript.char_count <= max_chars
