"""Printable artifact persistence APIs."""

from __future__ import annotations

import sqlite3

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.constants import DEFAULT_PRINTABLE_ARTIFACT_GROUP_NAME
from message_evidence_workstation.domain.models import (
    EvidenceBlock,
    PrintableArtifact,
    PrintableArtifactBlockContext,
    PrintableArtifactContext,
    PrintableArtifactEvidenceBlock,
    PrintableArtifactGroup,
    SourceThread,
)
from message_evidence_workstation.domain.slots import message_ids_for_slot_range
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso
from message_evidence_workstation.output.block_labels import block_label_for_index


def _row_to_group(row: sqlite3.Row) -> PrintableArtifactGroup:
    return PrintableArtifactGroup(
        printable_artifact_group_id=int(row["printable_artifact_group_id"]),
        dataset_id=int(row["dataset_id"]),
        name=str(row["name"]),
        sort_order=int(row["sort_order"]),
        is_collapsed=bool(row["is_collapsed"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _row_to_artifact(row: sqlite3.Row) -> PrintableArtifact:
    return PrintableArtifact(
        printable_artifact_id=int(row["printable_artifact_id"]),
        dataset_id=int(row["dataset_id"]),
        group_id=int(row["group_id"]),
        title=str(row["title"]),
        exhibit_number=str(row["exhibit_number"]),
        case_number=str(row["case_number"]),
        sort_order=int(row["sort_order"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _row_to_join(row: sqlite3.Row) -> PrintableArtifactEvidenceBlock:
    return PrintableArtifactEvidenceBlock(
        printable_artifact_evidence_block_id=int(row["printable_artifact_evidence_block_id"]),
        printable_artifact_id=int(row["printable_artifact_id"]),
        evidence_block_id=int(row["evidence_block_id"]),
        sort_order=int(row["sort_order"]),
        created_at=str(row["created_at"]),
    )


def _next_group_sort_order(conn: sqlite3.Connection, dataset_id: int) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(sort_order), -1) AS max_order
        FROM printable_artifact_group
        WHERE dataset_id = ?
        """,
        (dataset_id,),
    ).fetchone()
    return int(row["max_order"]) + 1


def _next_artifact_sort_order(conn: sqlite3.Connection, group_id: int) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(sort_order), -1) AS max_order
        FROM printable_artifact
        WHERE group_id = ?
        """,
        (group_id,),
    ).fetchone()
    return int(row["max_order"]) + 1


def _next_block_sort_order(conn: sqlite3.Connection, printable_artifact_id: int) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(sort_order), -1) AS max_order
        FROM printable_artifact_evidence_block
        WHERE printable_artifact_id = ?
        """,
        (printable_artifact_id,),
    ).fetchone()
    return int(row["max_order"]) + 1


def _messages_for_evidence_block(
    conn: sqlite3.Connection,
    block: EvidenceBlock,
) -> list:
    ordered = repositories.list_messages_for_thread(
        conn,
        block.dataset_id,
        block.source_thread_id,
    )
    ordered_ids = [message.message_id for message in ordered]
    selected_ids = message_ids_for_slot_range(
        ordered_ids,
        block.context_start_slot,
        block.context_end_slot,
    )
    by_id = {message.message_id: message for message in ordered}
    return [by_id[message_id] for message_id in selected_ids if message_id in by_id]


def ensure_default_printable_artifact_group(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
) -> PrintableArtifactGroup:
    row = conn.execute(
        """
        SELECT printable_artifact_group_id, dataset_id, name, sort_order,
               is_collapsed, created_at, updated_at
        FROM printable_artifact_group
        WHERE dataset_id = ? AND name = ?
        """,
        (dataset_id, DEFAULT_PRINTABLE_ARTIFACT_GROUP_NAME),
    ).fetchone()
    if row is not None:
        return _row_to_group(row)
    now = utc_now_iso()
    sort_order = _next_group_sort_order(conn, dataset_id)
    cursor = conn.execute(
        """
        INSERT INTO printable_artifact_group (
            dataset_id, name, sort_order, is_collapsed, created_at, updated_at
        ) VALUES (?, ?, ?, 0, ?, ?)
        """,
        (dataset_id, DEFAULT_PRINTABLE_ARTIFACT_GROUP_NAME, sort_order, now, now),
    )
    conn.commit()
    group_id = int(cursor.lastrowid)
    logger.info(
        component="db.printable_artifacts",
        operation="default_group_created",
        message="Created default printable artifact group",
        details={"printable_artifact_group_id": group_id, "dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    return PrintableArtifactGroup(
        printable_artifact_group_id=group_id,
        dataset_id=dataset_id,
        name=DEFAULT_PRINTABLE_ARTIFACT_GROUP_NAME,
        sort_order=sort_order,
        is_collapsed=False,
        created_at=now,
        updated_at=now,
    )


def list_printable_artifact_groups(
    conn: sqlite3.Connection,
    dataset_id: int,
) -> list[PrintableArtifactGroup]:
    rows = conn.execute(
        """
        SELECT printable_artifact_group_id, dataset_id, name, sort_order,
               is_collapsed, created_at, updated_at
        FROM printable_artifact_group
        WHERE dataset_id = ?
        ORDER BY sort_order, printable_artifact_group_id
        """,
        (dataset_id,),
    ).fetchall()
    return [_row_to_group(row) for row in rows]


def list_printable_artifacts(
    conn: sqlite3.Connection,
    group_id: int,
) -> list[PrintableArtifact]:
    rows = conn.execute(
        """
        SELECT printable_artifact_id, dataset_id, group_id, title, exhibit_number,
               case_number, sort_order, created_at, updated_at
        FROM printable_artifact
        WHERE group_id = ?
        ORDER BY sort_order, printable_artifact_id
        """,
        (group_id,),
    ).fetchall()
    return [_row_to_artifact(row) for row in rows]


def create_printable_artifact_group(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    name: str,
) -> PrintableArtifactGroup:
    now = utc_now_iso()
    sort_order = _next_group_sort_order(conn, dataset_id)
    cursor = conn.execute(
        """
        INSERT INTO printable_artifact_group (
            dataset_id, name, sort_order, is_collapsed, created_at, updated_at
        ) VALUES (?, ?, ?, 0, ?, ?)
        """,
        (dataset_id, name, sort_order, now, now),
    )
    conn.commit()
    group_id = int(cursor.lastrowid)
    logger.info(
        component="db.printable_artifacts",
        operation="group_create",
        message=f"Created printable artifact group '{name}'",
        details={"printable_artifact_group_id": group_id, "dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    return PrintableArtifactGroup(
        printable_artifact_group_id=group_id,
        dataset_id=dataset_id,
        name=name,
        sort_order=sort_order,
        is_collapsed=False,
        created_at=now,
        updated_at=now,
    )


def rename_printable_artifact_group(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    group_id: int,
    name: str,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE printable_artifact_group
        SET name = ?, updated_at = ?
        WHERE printable_artifact_group_id = ?
        """,
        (name, now, group_id),
    )
    conn.commit()
    logger.info(
        component="db.printable_artifacts",
        operation="group_rename",
        message=f"Renamed printable artifact group to '{name}'",
        details={"printable_artifact_group_id": group_id},
    )


def set_printable_artifact_group_collapsed(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    group_id: int,
    is_collapsed: bool,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE printable_artifact_group
        SET is_collapsed = ?, updated_at = ?
        WHERE printable_artifact_group_id = ?
        """,
        (int(is_collapsed), now, group_id),
    )
    conn.commit()
    logger.info(
        component="db.printable_artifacts",
        operation="group_collapsed",
        message="Updated printable artifact group collapsed state",
        details={"printable_artifact_group_id": group_id, "is_collapsed": is_collapsed},
    )


def create_printable_artifact_from_evidence_block(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    group_id: int,
    evidence_block_id: int,
) -> PrintableArtifact:
    block = evidence_blocks.get_evidence_block(conn, evidence_block_id)
    if block is None:
        raise ValueError(f"Evidence block {evidence_block_id} not found")
    now = utc_now_iso()
    sort_order = _next_artifact_sort_order(conn, group_id)
    cursor = conn.execute(
        """
        INSERT INTO printable_artifact (
            dataset_id, group_id, title, exhibit_number, case_number,
            sort_order, created_at, updated_at
        ) VALUES (?, ?, ?, '', '', ?, ?, ?)
        """,
        (dataset_id, group_id, block.title, sort_order, now, now),
    )
    artifact_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO printable_artifact_evidence_block (
            printable_artifact_id, evidence_block_id, sort_order, created_at
        ) VALUES (?, ?, 0, ?)
        """,
        (artifact_id, evidence_block_id, now),
    )
    conn.commit()
    logger.info(
        component="db.printable_artifacts",
        operation="artifact_create_from_block",
        message=f"Created printable artifact from evidence block '{block.title}'",
        details={
            "printable_artifact_id": artifact_id,
            "group_id": group_id,
            "evidence_block_id": evidence_block_id,
        },
        dataset_id=dataset_id,
    )
    artifact = _row_to_artifact(
        conn.execute(
            """
            SELECT printable_artifact_id, dataset_id, group_id, title, exhibit_number,
                   case_number, sort_order, created_at, updated_at
            FROM printable_artifact
            WHERE printable_artifact_id = ?
            """,
            (artifact_id,),
        ).fetchone()
    )
    return artifact


def append_evidence_block_to_printable_artifact(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    printable_artifact_id: int,
    evidence_block_id: int,
) -> PrintableArtifactEvidenceBlock:
    sort_order = _next_block_sort_order(conn, printable_artifact_id)
    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO printable_artifact_evidence_block (
            printable_artifact_id, evidence_block_id, sort_order, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (printable_artifact_id, evidence_block_id, sort_order, now),
    )
    conn.commit()
    join_id = int(cursor.lastrowid)
    logger.info(
        component="db.printable_artifacts",
        operation="artifact_block_append",
        message="Appended evidence block to printable artifact",
        details={
            "printable_artifact_evidence_block_id": join_id,
            "printable_artifact_id": printable_artifact_id,
            "evidence_block_id": evidence_block_id,
            "sort_order": sort_order,
        },
    )
    row = conn.execute(
        """
        SELECT printable_artifact_evidence_block_id, printable_artifact_id,
               evidence_block_id, sort_order, created_at
        FROM printable_artifact_evidence_block
        WHERE printable_artifact_evidence_block_id = ?
        """,
        (join_id,),
    ).fetchone()
    return _row_to_join(row)


def move_printable_artifact_to_group(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    printable_artifact_id: int,
    group_id: int,
    sort_order: int | None = None,
) -> None:
    if sort_order is None:
        sort_order = _next_artifact_sort_order(conn, group_id)
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE printable_artifact
        SET group_id = ?, sort_order = ?, updated_at = ?
        WHERE printable_artifact_id = ?
        """,
        (group_id, sort_order, now, printable_artifact_id),
    )
    conn.commit()
    logger.info(
        component="db.printable_artifacts",
        operation="artifact_move_group",
        message="Moved printable artifact to group",
        details={
            "printable_artifact_id": printable_artifact_id,
            "group_id": group_id,
            "sort_order": sort_order,
        },
    )


def update_printable_artifact_metadata(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    printable_artifact_id: int,
    title: str,
    exhibit_number: str,
    case_number: str,
) -> PrintableArtifact:
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE printable_artifact
        SET title = ?, exhibit_number = ?, case_number = ?, updated_at = ?
        WHERE printable_artifact_id = ?
        """,
        (title, exhibit_number, case_number, now, printable_artifact_id),
    )
    conn.commit()
    logger.info(
        component="db.printable_artifacts",
        operation="artifact_metadata_update",
        message="Updated printable artifact metadata",
        details={"printable_artifact_id": printable_artifact_id},
    )
    row = conn.execute(
        """
        SELECT printable_artifact_id, dataset_id, group_id, title, exhibit_number,
               case_number, sort_order, created_at, updated_at
        FROM printable_artifact
        WHERE printable_artifact_id = ?
        """,
        (printable_artifact_id,),
    ).fetchone()
    return _row_to_artifact(row)


def reorder_printable_artifact_blocks(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    printable_artifact_id: int,
    ordered_join_ids: list[int],
) -> None:
    for index, join_id in enumerate(ordered_join_ids):
        conn.execute(
            """
            UPDATE printable_artifact_evidence_block
            SET sort_order = ?
            WHERE printable_artifact_evidence_block_id = ?
              AND printable_artifact_id = ?
            """,
            (index, join_id, printable_artifact_id),
        )
    conn.commit()
    logger.info(
        component="db.printable_artifacts",
        operation="artifact_blocks_reorder",
        message="Reordered printable artifact evidence blocks",
        details={
            "printable_artifact_id": printable_artifact_id,
            "ordered_join_ids": ordered_join_ids,
        },
    )


def remove_printable_artifact_block(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    printable_artifact_evidence_block_id: int,
) -> None:
    conn.execute(
        """
        DELETE FROM printable_artifact_evidence_block
        WHERE printable_artifact_evidence_block_id = ?
        """,
        (printable_artifact_evidence_block_id,),
    )
    conn.commit()
    logger.info(
        component="db.printable_artifacts",
        operation="artifact_block_remove",
        message="Removed evidence block from printable artifact",
        details={"printable_artifact_evidence_block_id": printable_artifact_evidence_block_id},
    )


def load_printable_artifact_context(
    conn: sqlite3.Connection,
    printable_artifact_id: int,
) -> PrintableArtifactContext | None:
    artifact_row = conn.execute(
        """
        SELECT printable_artifact_id, dataset_id, group_id, title, exhibit_number,
               case_number, sort_order, created_at, updated_at
        FROM printable_artifact
        WHERE printable_artifact_id = ?
        """,
        (printable_artifact_id,),
    ).fetchone()
    if artifact_row is None:
        return None
    artifact = _row_to_artifact(artifact_row)
    group_row = conn.execute(
        """
        SELECT name
        FROM printable_artifact_group
        WHERE printable_artifact_group_id = ?
        """,
        (artifact.group_id,),
    ).fetchone()
    dataset_row = conn.execute(
        "SELECT name FROM dataset WHERE dataset_id = ?",
        (artifact.dataset_id,),
    ).fetchone()
    join_rows = conn.execute(
        """
        SELECT printable_artifact_evidence_block_id, printable_artifact_id,
               evidence_block_id, sort_order, created_at
        FROM printable_artifact_evidence_block
        WHERE printable_artifact_id = ?
        ORDER BY sort_order, printable_artifact_evidence_block_id
        """,
        (printable_artifact_id,),
    ).fetchall()
    blocks: list[PrintableArtifactBlockContext] = []
    thread_cache: dict[str, SourceThread | None] = {}
    for index, join_row in enumerate(join_rows):
        join = _row_to_join(join_row)
        evidence_block = evidence_blocks.get_evidence_block(conn, join.evidence_block_id)
        if evidence_block is None:
            continue
        thread_key = evidence_block.source_thread_id
        if thread_key not in thread_cache:
            threads = repositories.list_source_threads(conn, artifact.dataset_id)
            thread_cache[thread_key] = next(
                (thread for thread in threads if thread.source_thread_id == thread_key),
                None,
            )
        blocks.append(
            PrintableArtifactBlockContext(
                join=join,
                evidence_block=evidence_block,
                block_label=block_label_for_index(index),
                messages=_messages_for_evidence_block(conn, evidence_block),
                source_thread=thread_cache[thread_key],
                dataset_name=str(dataset_row["name"]) if dataset_row else "",
            )
        )
    return PrintableArtifactContext(
        artifact=artifact,
        group_name=str(group_row["name"]) if group_row else "",
        dataset_name=str(dataset_row["name"]) if dataset_row else "",
        blocks=blocks,
    )
