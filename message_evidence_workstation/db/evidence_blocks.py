"""Evidence block persistence APIs."""

from __future__ import annotations

import sqlite3
from typing import Any

from message_evidence_workstation.domain.constants import (
    CREATED_BY_MANUAL,
    CREATED_BY_SIMPLE_SEARCH,
    UNCATEGORIZED_CATEGORY_NAME,
)
from message_evidence_workstation.domain.models import Category, EvidenceBlock
from message_evidence_workstation.domain.slots import (
    default_slots_for_hit_index,
    hit_index_for_message,
    validate_slot_bounds,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso


def _row_to_evidence_block(row: sqlite3.Row, highlights: frozenset[str]) -> EvidenceBlock:
    return EvidenceBlock(
        evidence_block_id=int(row["evidence_block_id"]),
        dataset_id=int(row["dataset_id"]),
        category_id=int(row["category_id"]),
        source_thread_id=str(row["source_thread_id"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        core_hit_message_id=str(row["core_hit_message_id"]),
        context_start_slot=int(row["context_start_slot"]),
        relevant_start_slot=int(row["relevant_start_slot"]),
        relevant_end_slot=int(row["relevant_end_slot"]),
        context_end_slot=int(row["context_end_slot"]),
        highlighted_message_ids=highlights,
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _load_highlights(conn: sqlite3.Connection, evidence_block_id: int) -> frozenset[str]:
    rows = conn.execute(
        "SELECT message_id FROM evidence_block_highlight WHERE evidence_block_id = ?",
        (evidence_block_id,),
    ).fetchall()
    return frozenset(str(row["message_id"]) for row in rows)


def ensure_uncategorized_category(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
) -> Category:
    row = conn.execute(
        """
        SELECT category_id, dataset_id, name, description, color, is_collapsed,
               created_at, updated_at
        FROM category
        WHERE dataset_id = ? AND name = ?
        """,
        (dataset_id, UNCATEGORIZED_CATEGORY_NAME),
    ).fetchone()
    if row is not None:
        return Category(
            category_id=int(row["category_id"]),
            dataset_id=int(row["dataset_id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            color=str(row["color"]),
            is_collapsed=bool(row["is_collapsed"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            is_system=True,
        )
    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO category (
            dataset_id, name, description, color, is_collapsed, created_at, updated_at
        ) VALUES (?, ?, '', '', 0, ?, ?)
        """,
        (dataset_id, UNCATEGORIZED_CATEGORY_NAME, now, now),
    )
    conn.commit()
    category_id = int(cursor.lastrowid)
    logger.info(
        component="db.evidence_blocks",
        operation="uncategorized_category_created",
        message="Created default Uncategorized category",
        details={"category_id": category_id, "dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    return Category(
        category_id=category_id,
        dataset_id=dataset_id,
        name=UNCATEGORIZED_CATEGORY_NAME,
        description="",
        color="",
        is_collapsed=False,
        created_at=now,
        updated_at=now,
        is_system=True,
    )


def get_uncategorized_category(
    conn: sqlite3.Connection,
    dataset_id: int,
) -> Category | None:
    row = conn.execute(
        """
        SELECT category_id, dataset_id, name, description, color, is_collapsed,
               created_at, updated_at
        FROM category
        WHERE dataset_id = ? AND name = ?
        """,
        (dataset_id, UNCATEGORIZED_CATEGORY_NAME),
    ).fetchone()
    if row is None:
        return None
    return Category(
        category_id=int(row["category_id"]),
        dataset_id=int(row["dataset_id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        color=str(row["color"]),
        is_collapsed=bool(row["is_collapsed"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        is_system=True,
    )


def list_evidence_blocks(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    category_id: int | None = None,
    source_thread_id: str | None = None,
) -> list[EvidenceBlock]:
    query = """
        SELECT evidence_block_id, dataset_id, category_id, source_thread_id,
               title, summary, core_hit_message_id, context_start_slot,
               relevant_start_slot, relevant_end_slot, context_end_slot,
               created_by, created_at, updated_at
        FROM evidence_block
        WHERE dataset_id = ?
    """
    params: list[Any] = [dataset_id]
    if category_id is not None:
        query += " AND category_id = ?"
        params.append(category_id)
    if source_thread_id is not None:
        query += " AND source_thread_id = ?"
        params.append(source_thread_id)
    query += " ORDER BY updated_at DESC, evidence_block_id DESC"
    rows = conn.execute(query, params).fetchall()
    return [
        _row_to_evidence_block(row, _load_highlights(conn, int(row["evidence_block_id"])))
        for row in rows
    ]


def get_evidence_block(conn: sqlite3.Connection, evidence_block_id: int) -> EvidenceBlock | None:
    row = conn.execute(
        """
        SELECT evidence_block_id, dataset_id, category_id, source_thread_id,
               title, summary, core_hit_message_id, context_start_slot,
               relevant_start_slot, relevant_end_slot, context_end_slot,
               created_by, created_at, updated_at
        FROM evidence_block
        WHERE evidence_block_id = ?
        """,
        (evidence_block_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_evidence_block(row, _load_highlights(conn, evidence_block_id))


def create_evidence_block(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    category_id: int,
    source_thread_id: str,
    title: str,
    core_hit_message_id: str,
    ordered_message_ids: list[str],
    summary: str = "",
    context_start_slot: int | None = None,
    relevant_start_slot: int | None = None,
    relevant_end_slot: int | None = None,
    context_end_slot: int | None = None,
    highlighted_message_ids: list[str] | None = None,
    created_by: str = CREATED_BY_MANUAL,
) -> EvidenceBlock:
    message_count = len(ordered_message_ids)
    if (
        context_start_slot is None
        or relevant_start_slot is None
        or relevant_end_slot is None
        or context_end_slot is None
    ):
        hit_index = hit_index_for_message(ordered_message_ids, core_hit_message_id)
        context_start_slot, relevant_start_slot, relevant_end_slot, context_end_slot = (
            default_slots_for_hit_index(message_count, hit_index)
        )
    validate_slot_bounds(
        message_count,
        context_start_slot,
        relevant_start_slot,
        relevant_end_slot,
        context_end_slot,
    )
    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO evidence_block (
            dataset_id, category_id, source_thread_id, title, summary,
            core_hit_message_id, context_start_slot, relevant_start_slot,
            relevant_end_slot, context_end_slot, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            category_id,
            source_thread_id,
            title,
            summary,
            core_hit_message_id,
            context_start_slot,
            relevant_start_slot,
            relevant_end_slot,
            context_end_slot,
            created_by,
            now,
            now,
        ),
    )
    evidence_block_id = int(cursor.lastrowid)
    for message_id in highlighted_message_ids or []:
        conn.execute(
            """
            INSERT INTO evidence_block_highlight (evidence_block_id, message_id)
            VALUES (?, ?)
            """,
            (evidence_block_id, message_id),
        )
    conn.commit()
    logger.info(
        component="db.evidence_blocks",
        operation="evidence_block_create",
        message=f"Created evidence block '{title}'",
        details={
            "evidence_block_id": evidence_block_id,
            "category_id": category_id,
            "source_thread_id": source_thread_id,
        },
        dataset_id=dataset_id,
    )
    block = get_evidence_block(conn, evidence_block_id)
    assert block is not None
    return block


def create_evidence_block_from_search(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    source_thread_id: str,
    primary_hit_message_id: str,
    title: str,
    ordered_message_ids: list[str],
    category_id: int | None = None,
    summary: str = "",
) -> EvidenceBlock:
    if category_id is None:
        category_id = ensure_uncategorized_category(conn, logger, dataset_id).category_id
    return create_evidence_block(
        conn,
        logger,
        dataset_id=dataset_id,
        category_id=category_id,
        source_thread_id=source_thread_id,
        title=title,
        core_hit_message_id=primary_hit_message_id,
        ordered_message_ids=ordered_message_ids,
        summary=summary,
        created_by=CREATED_BY_SIMPLE_SEARCH,
    )


def update_evidence_block_slots(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    evidence_block_id: int,
    message_count: int,
    context_start_slot: int,
    relevant_start_slot: int,
    relevant_end_slot: int,
    context_end_slot: int,
) -> EvidenceBlock:
    validate_slot_bounds(
        message_count,
        context_start_slot,
        relevant_start_slot,
        relevant_end_slot,
        context_end_slot,
    )
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE evidence_block
        SET context_start_slot = ?, relevant_start_slot = ?, relevant_end_slot = ?,
            context_end_slot = ?, updated_at = ?
        WHERE evidence_block_id = ?
        """,
        (
            context_start_slot,
            relevant_start_slot,
            relevant_end_slot,
            context_end_slot,
            now,
            evidence_block_id,
        ),
    )
    conn.commit()
    logger.info(
        component="db.evidence_blocks",
        operation="evidence_block_slots_update",
        message="Updated evidence block slot boundaries",
        details={"evidence_block_id": evidence_block_id},
    )
    block = get_evidence_block(conn, evidence_block_id)
    assert block is not None
    return block


def move_evidence_block_to_category(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    evidence_block_id: int,
    category_id: int,
) -> EvidenceBlock:
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE evidence_block
        SET category_id = ?, updated_at = ?
        WHERE evidence_block_id = ?
        """,
        (category_id, now, evidence_block_id),
    )
    conn.commit()
    logger.info(
        component="db.evidence_blocks",
        operation="evidence_block_move_category",
        message="Moved evidence block to category",
        details={"evidence_block_id": evidence_block_id, "category_id": category_id},
    )
    block = get_evidence_block(conn, evidence_block_id)
    assert block is not None
    return block


def set_evidence_block_highlights(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    evidence_block_id: int,
    highlighted_message_ids: list[str],
) -> EvidenceBlock:
    conn.execute(
        "DELETE FROM evidence_block_highlight WHERE evidence_block_id = ?",
        (evidence_block_id,),
    )
    for message_id in highlighted_message_ids:
        conn.execute(
            """
            INSERT INTO evidence_block_highlight (evidence_block_id, message_id)
            VALUES (?, ?)
            """,
            (evidence_block_id, message_id),
        )
    now = utc_now_iso()
    conn.execute(
        "UPDATE evidence_block SET updated_at = ? WHERE evidence_block_id = ?",
        (now, evidence_block_id),
    )
    conn.commit()
    logger.info(
        component="db.evidence_blocks",
        operation="evidence_block_highlights_update",
        message="Updated evidence block highlights",
        details={
            "evidence_block_id": evidence_block_id,
            "highlight_count": len(highlighted_message_ids),
        },
    )
    block = get_evidence_block(conn, evidence_block_id)
    assert block is not None
    return block


def update_evidence_block_metadata(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    evidence_block_id: int,
    title: str | None = None,
    summary: str | None = None,
) -> EvidenceBlock:
    updates: list[str] = []
    params: list[Any] = []
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if summary is not None:
        updates.append("summary = ?")
        params.append(summary)
    if not updates:
        block = get_evidence_block(conn, evidence_block_id)
        assert block is not None
        return block
    now = utc_now_iso()
    updates.append("updated_at = ?")
    params.append(now)
    params.append(evidence_block_id)
    conn.execute(
        f"UPDATE evidence_block SET {', '.join(updates)} WHERE evidence_block_id = ?",
        params,
    )
    conn.commit()
    block = get_evidence_block(conn, evidence_block_id)
    assert block is not None
    return block
