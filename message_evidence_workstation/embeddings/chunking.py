"""Message-boundary-preserving chunking for embedding indexes."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 1200


@dataclass(slots=True)
class MessageChunkSpec:
    source_thread_id: str
    start_message_id: str
    end_message_id: str
    message_count: int
    char_count: int
    text_checksum: str
    body_text: str


@dataclass(slots=True)
class _MessageRow:
    message_id: str
    source_thread_id: str
    body: str
    sort_index: int


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_thread_chunks(
    messages: list[_MessageRow],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[MessageChunkSpec]:
    """Pack whole messages into chunks without splitting message bodies."""
    if not messages:
        return []
    ordered = sorted(messages, key=lambda row: (row.sort_index, row.message_id))
    chunks: list[MessageChunkSpec] = []
    current_ids: list[str] = []
    current_parts: list[str] = []

    def flush() -> None:
        if not current_ids:
            return
        body_text = "\n".join(current_parts)
        chunks.append(
            MessageChunkSpec(
                source_thread_id=ordered[0].source_thread_id,
                start_message_id=current_ids[0],
                end_message_id=current_ids[-1],
                message_count=len(current_ids),
                char_count=len(body_text),
                text_checksum=_checksum(body_text),
                body_text=body_text,
            )
        )

    for message in ordered:
        piece = message.body.strip()
        if not piece:
            continue
        prospective_len = len("\n".join([*current_parts, piece])) if current_parts else len(piece)
        if current_parts and prospective_len > max_chars:
            flush()
            current_ids = []
            current_parts = []
        current_ids.append(message.message_id)
        current_parts.append(piece)
    flush()
    return chunks


def build_dataset_chunks(
    messages_by_thread: dict[str, list[_MessageRow]],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[MessageChunkSpec]:
    chunks: list[MessageChunkSpec] = []
    for source_thread_id in sorted(messages_by_thread):
        thread_messages = messages_by_thread[source_thread_id]
        if not thread_messages:
            continue
        chunks.extend(build_thread_chunks(thread_messages, max_chars=max_chars))
    return chunks


def iter_dataset_chunks(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Iterator[MessageChunkSpec]:
    """Yield chunks one thread at a time to avoid loading the whole dataset into RAM."""
    thread_rows = conn.execute(
        """
        SELECT DISTINCT source_thread_id
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id
        """,
        (dataset_id,),
    ).fetchall()
    for thread_row in thread_rows:
        source_thread_id = thread_row["source_thread_id"]
        message_rows = conn.execute(
            """
            SELECT message_id, source_thread_id, body_normalized, sort_index
            FROM message
            WHERE dataset_id = ? AND source_thread_id = ?
            ORDER BY sort_index, message_id
            """,
            (dataset_id, source_thread_id),
        ).fetchall()
        messages = [
            _MessageRow(
                message_id=row["message_id"],
                source_thread_id=row["source_thread_id"],
                body=row["body_normalized"] or "",
                sort_index=row["sort_index"],
            )
            for row in message_rows
        ]
        yield from build_thread_chunks(messages, max_chars=max_chars)


def count_dataset_chunks(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> int:
    return sum(1 for _ in iter_dataset_chunks(conn, dataset_id, max_chars=max_chars))
