"""Database repository helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from message_evidence_workstation.domain.models import (
    Category,
    Dataset,
    Message,
    ModelRunSummary,
    SourceThread,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    return json.loads(value)


_MESSAGE_IN_CHUNK_SIZE = 500


_MESSAGE_SELECT_COLUMNS = """
    message_id, dataset_id, source_thread_id, source_platform,
    source_message_id, timestamp, sender_id, sender_display, body,
    body_normalized, has_attachment, attachment_summary, sort_index,
    source_metadata_json, thread_ordinal
"""


def _message_from_row(row: sqlite3.Row) -> Message:
    thread_ordinal = row["thread_ordinal"]
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
        source_metadata_json=_json_loads(row["source_metadata_json"]),
        thread_ordinal=int(thread_ordinal) if thread_ordinal is not None else None,
    )


def fetch_messages_by_ids(
    conn: sqlite3.Connection,
    dataset_id: int,
    message_ids: list[str],
) -> dict[str, Message]:
    """Return messages keyed by message_id; chunk large IN clauses."""
    if not message_ids:
        return {}
    unique_ids = list(dict.fromkeys(message_ids))
    result: dict[str, Message] = {}
    for start in range(0, len(unique_ids), _MESSAGE_IN_CHUNK_SIZE):
        chunk = unique_ids[start : start + _MESSAGE_IN_CHUNK_SIZE]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"""
            SELECT {_MESSAGE_SELECT_COLUMNS}
            FROM message
            WHERE dataset_id = ? AND message_id IN ({placeholders})
            """,
            (dataset_id, *chunk),
        ).fetchall()
        for row in rows:
            result[row["message_id"]] = _message_from_row(row)
    return result


def get_latest_dataset(conn: sqlite3.Connection) -> Dataset | None:
    row = conn.execute(
        """
        SELECT dataset_id, name, created_at, schema_version, notes
        FROM dataset
        ORDER BY dataset_id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return Dataset(
        dataset_id=row["dataset_id"],
        name=row["name"],
        created_at=row["created_at"],
        schema_version=row["schema_version"],
        notes=row["notes"],
    )


def list_source_threads(conn: sqlite3.Connection, dataset_id: int) -> list[SourceThread]:
    rows = conn.execute(
        """
        SELECT source_thread_id, dataset_id, source_platform, platform_thread_id,
               display_title, participant_summary, start_ts, end_ts, message_count,
               metadata_json
        FROM source_thread
        WHERE dataset_id = ?
        ORDER BY display_title COLLATE NOCASE, source_thread_id
        """,
        (dataset_id,),
    ).fetchall()
    return [
        SourceThread(
            source_thread_id=row["source_thread_id"],
            dataset_id=row["dataset_id"],
            source_platform=row["source_platform"],
            platform_thread_id=row["platform_thread_id"],
            display_title=row["display_title"],
            participant_summary=row["participant_summary"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            message_count=row["message_count"],
            metadata_json=_json_loads(row["metadata_json"]),
        )
        for row in rows
    ]


def thread_message_count(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS message_count
        FROM message
        WHERE dataset_id = ? AND source_thread_id = ?
        """,
        (dataset_id, source_thread_id),
    ).fetchone()
    return int(row["message_count"] or 0)


def backfill_thread_ordinals(conn: sqlite3.Connection, dataset_id: int) -> int:
    """Assign per-thread ordinals in chronological order; idempotent."""
    rows = conn.execute(
        """
        SELECT source_thread_id, message_id
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id, timestamp, sort_index, message_id
        """,
        (dataset_id,),
    ).fetchall()
    if not rows:
        return 0

    batch: list[tuple[int, int, str]] = []
    current_thread_id = ""
    current_ordinal = -1
    for row in rows:
        source_thread_id = str(row["source_thread_id"])
        if source_thread_id != current_thread_id:
            current_thread_id = source_thread_id
            current_ordinal = 0
        else:
            current_ordinal += 1
        batch.append((current_ordinal, dataset_id, str(row["message_id"])))

    conn.executemany(
        """
        UPDATE message
        SET thread_ordinal = ?
        WHERE dataset_id = ? AND message_id = ?
        """,
        batch,
    )
    conn.commit()
    return len(batch)


def message_ordinal(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
    message_id: str,
) -> int | None:
    row = conn.execute(
        """
        SELECT thread_ordinal
        FROM message
        WHERE dataset_id = ? AND source_thread_id = ? AND message_id = ?
        """,
        (dataset_id, source_thread_id, message_id),
    ).fetchone()
    if row is None or row["thread_ordinal"] is None:
        return None
    return int(row["thread_ordinal"])


def message_ids_for_ordinal_range(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
    start_ordinal: int,
    end_ordinal: int,
) -> list[str]:
    """Return message ids for a half-open ordinal range [start_ordinal, end_ordinal)."""
    if end_ordinal <= start_ordinal:
        return []
    rows = conn.execute(
        """
        SELECT message_id
        FROM message
        WHERE dataset_id = ?
          AND source_thread_id = ?
          AND thread_ordinal >= ?
          AND thread_ordinal < ?
        ORDER BY thread_ordinal
        """,
        (dataset_id, source_thread_id, start_ordinal, end_ordinal),
    ).fetchall()
    return [str(row["message_id"]) for row in rows]


def fetch_message_ids_for_thread(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT message_id
        FROM message
        WHERE dataset_id = ? AND source_thread_id = ?
        ORDER BY thread_ordinal, timestamp, sort_index, message_id
        """,
        (dataset_id, source_thread_id),
    ).fetchall()
    return [str(row["message_id"]) for row in rows]


def message_index_in_thread(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
    message_id: str,
) -> int | None:
    return message_ordinal(conn, dataset_id, source_thread_id, message_id)


def fetch_messages_for_slot_range(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
    start_slot: int,
    end_slot: int,
) -> list[Message]:
    """Return chronologically ordered messages for a half-open slot range."""
    if end_slot <= start_slot:
        return []
    rows = conn.execute(
        f"""
        SELECT {_MESSAGE_SELECT_COLUMNS}
        FROM message
        WHERE dataset_id = ?
          AND source_thread_id = ?
          AND thread_ordinal >= ?
          AND thread_ordinal < ?
        ORDER BY thread_ordinal
        """,
        (dataset_id, source_thread_id, start_slot, end_slot),
    ).fetchall()
    return [_message_from_row(row) for row in rows]


def fetch_thread_participant_map(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(sender_id), ''), NULLIF(TRIM(sender_display), '')) AS sender_key
        FROM message
        WHERE dataset_id = ? AND source_thread_id = ?
          AND sender_key IS NOT NULL
        ORDER BY sender_key COLLATE NOCASE
        """,
        (dataset_id, source_thread_id),
    ).fetchall()
    sender_keys = [str(row["sender_key"]) for row in rows if row["sender_key"]]
    return {sender_key: index % 8 for index, sender_key in enumerate(sender_keys)}


def list_messages_for_thread(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
) -> list[Message]:
    rows = conn.execute(
        f"""
        SELECT {_MESSAGE_SELECT_COLUMNS}
        FROM message
        WHERE dataset_id = ? AND source_thread_id = ?
        ORDER BY thread_ordinal, timestamp, sort_index, message_id
        """,
        (dataset_id, source_thread_id),
    ).fetchall()
    return [_message_from_row(row) for row in rows]


def list_categories(conn: sqlite3.Connection, dataset_id: int) -> list[Category]:
    rows = conn.execute(
        """
        SELECT category_id, dataset_id, name, description, color, is_collapsed,
               created_at, updated_at
        FROM category
        WHERE dataset_id = ?
        ORDER BY name COLLATE NOCASE, category_id
        """,
        (dataset_id,),
    ).fetchall()
    return [
        Category(
            category_id=row["category_id"],
            dataset_id=row["dataset_id"],
            name=row["name"],
            description=row["description"],
            color=row["color"],
            is_collapsed=bool(row["is_collapsed"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def create_category(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    name: str,
    description: str = "",
    color: str = "",
) -> Category:
    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO category (
            dataset_id, name, description, color, is_collapsed, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (dataset_id, name, description, color, now, now),
    )
    conn.commit()
    category_id = int(cursor.lastrowid)
    logger.info(
        component="db.repositories",
        operation="category_create",
        message=f"Created category '{name}'",
        details={"category_id": category_id, "dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    return Category(
        category_id=category_id,
        dataset_id=dataset_id,
        name=name,
        description=description,
        color=color,
        is_collapsed=False,
        created_at=now,
        updated_at=now,
    )


def rename_category(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    category_id: int,
    name: str,
) -> None:
    now = utc_now_iso()
    conn.execute(
        "UPDATE category SET name = ?, updated_at = ? WHERE category_id = ?",
        (name, now, category_id),
    )
    conn.commit()
    logger.info(
        component="db.repositories",
        operation="category_rename",
        message=f"Renamed category {category_id} to '{name}'",
        details={"category_id": category_id, "name": name},
    )


def delete_category(conn: sqlite3.Connection, logger: ProcessLogger, category_id: int) -> None:
    conn.execute(
        "DELETE FROM evidence_block_highlight WHERE evidence_block_id IN "
        "(SELECT evidence_block_id FROM evidence_block WHERE category_id = ?)",
        (category_id,),
    )
    conn.execute("DELETE FROM evidence_block WHERE category_id = ?", (category_id,))
    conn.execute("DELETE FROM category WHERE category_id = ?", (category_id,))
    conn.commit()
    logger.info(
        component="db.repositories",
        operation="category_delete",
        message=f"Deleted category {category_id}",
        details={"category_id": category_id},
    )


def set_category_collapsed(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    category_id: int,
    is_collapsed: bool,
) -> None:
    now = utc_now_iso()
    conn.execute(
        "UPDATE category SET is_collapsed = ?, updated_at = ? WHERE category_id = ?",
        (int(is_collapsed), now, category_id),
    )
    conn.commit()
    logger.info(
        component="db.repositories",
        operation="category_set_collapsed",
        message=f"Category {category_id} collapsed={is_collapsed}",
        details={"category_id": category_id, "is_collapsed": is_collapsed},
    )
