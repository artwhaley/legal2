"""Database repository helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from message_evidence_workstation.domain.constants import (
    CONVERSATION_STATUS_CANDIDATE,
    CREATED_BY_MANUAL,
    CREATED_BY_SIMPLE_SEARCH,
    RETRIEVAL_MANUAL,
)
from message_evidence_workstation.domain.models import (
    Category,
    ConversationHit,
    ConversationRange,
    Dataset,
    Message,
    ModelRunSummary,
    OutputConversationContext,
    SourceThread,
    WorkstationConversation,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    return json.loads(value)


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


def list_messages_for_thread(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_id: str,
) -> list[Message]:
    rows = conn.execute(
        """
        SELECT message_id, dataset_id, source_thread_id, source_platform,
               source_message_id, timestamp, sender_id, sender_display, body,
               body_normalized, has_attachment, attachment_summary, sort_index,
               source_metadata_json
        FROM message
        WHERE dataset_id = ? AND source_thread_id = ?
        ORDER BY timestamp, sort_index, message_id
        """,
        (dataset_id, source_thread_id),
    ).fetchall()
    return [
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
        "DELETE FROM conversation_hit WHERE workstation_conversation_id IN "
        "(SELECT workstation_conversation_id FROM workstation_conversation WHERE category_id = ?)",
        (category_id,),
    )
    conn.execute(
        "DELETE FROM conversation_range WHERE workstation_conversation_id IN "
        "(SELECT workstation_conversation_id FROM workstation_conversation WHERE category_id = ?)",
        (category_id,),
    )
    conn.execute(
        "DELETE FROM message_highlight_override WHERE workstation_conversation_id IN "
        "(SELECT workstation_conversation_id FROM workstation_conversation WHERE category_id = ?)",
        (category_id,),
    )
    conn.execute(
        "DELETE FROM workstation_conversation WHERE category_id = ?",
        (category_id,),
    )
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


def list_workstation_conversations(
    conn: sqlite3.Connection,
    dataset_id: int,
    category_id: int | None = None,
) -> list[WorkstationConversation]:
    if category_id is None:
        rows = conn.execute(
            """
            SELECT workstation_conversation_id, dataset_id, category_id, source_thread_id,
                   primary_hit_message_id, title, user_notes, status, created_by,
                   created_at, updated_at
            FROM workstation_conversation
            WHERE dataset_id = ?
            ORDER BY updated_at DESC
            """,
            (dataset_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT workstation_conversation_id, dataset_id, category_id, source_thread_id,
                   primary_hit_message_id, title, user_notes, status, created_by,
                   created_at, updated_at
            FROM workstation_conversation
            WHERE dataset_id = ? AND category_id = ?
            ORDER BY updated_at DESC
            """,
            (dataset_id, category_id),
        ).fetchall()
    return [
        WorkstationConversation(
            workstation_conversation_id=row["workstation_conversation_id"],
            dataset_id=row["dataset_id"],
            category_id=row["category_id"],
            source_thread_id=row["source_thread_id"],
            primary_hit_message_id=row["primary_hit_message_id"],
            title=row["title"],
            user_notes=row["user_notes"],
            status=row["status"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def create_workstation_conversation_manual(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    category_id: int,
    source_thread_id: str,
    primary_hit_message_id: str,
    hit_message_ids: list[str],
    title: str,
) -> WorkstationConversation:
    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO workstation_conversation (
            dataset_id, category_id, source_thread_id, primary_hit_message_id,
            title, user_notes, status, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?)
        """,
        (
            dataset_id,
            category_id,
            source_thread_id,
            primary_hit_message_id,
            title,
            CONVERSATION_STATUS_CANDIDATE,
            CREATED_BY_MANUAL,
            now,
            now,
        ),
    )
    conversation_id = int(cursor.lastrowid)
    for message_id in hit_message_ids:
        conn.execute(
            """
            INSERT INTO conversation_hit (
                workstation_conversation_id, message_id, retrieval_method,
                query_text, matched_term, explanation, metadata_json
            ) VALUES (?, ?, ?, '', '', 'manual selection', '{}')
            """,
            (conversation_id, message_id, RETRIEVAL_MANUAL),
        )
    conn.commit()
    logger.info(
        component="db.repositories",
        operation="workstation_conversation_create_manual",
        message=f"Created workstation conversation '{title}'",
        details={
            "workstation_conversation_id": conversation_id,
            "category_id": category_id,
            "source_thread_id": source_thread_id,
            "hit_count": len(hit_message_ids),
        },
        dataset_id=dataset_id,
    )
    return WorkstationConversation(
        workstation_conversation_id=conversation_id,
        dataset_id=dataset_id,
        category_id=category_id,
        source_thread_id=source_thread_id,
        primary_hit_message_id=primary_hit_message_id,
        title=title,
        user_notes="",
        status=CONVERSATION_STATUS_CANDIDATE,
        created_by=CREATED_BY_MANUAL,
        created_at=now,
        updated_at=now,
    )


def create_workstation_conversation_from_search(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    category_id: int,
    source_thread_id: str,
    primary_hit_message_id: str,
    title: str,
    hits: list[dict[str, Any]],
    merge_into_conversation_id: int | None = None,
    created_by: str = CREATED_BY_SIMPLE_SEARCH,
) -> WorkstationConversation:
    now = utc_now_iso()
    if merge_into_conversation_id is not None:
        conversation_id = merge_into_conversation_id
        conn.execute(
            """
            UPDATE workstation_conversation
            SET updated_at = ?
            WHERE workstation_conversation_id = ?
            """,
            (now, conversation_id),
        )
        operation = "workstation_conversation_merge_search_drop"
        log_message = f"Merged search drop into conversation {conversation_id}"
    else:
        cursor = conn.execute(
            """
            INSERT INTO workstation_conversation (
                dataset_id, category_id, source_thread_id, primary_hit_message_id,
                title, user_notes, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?)
            """,
            (
                dataset_id,
                category_id,
                source_thread_id,
                primary_hit_message_id,
                title,
                CONVERSATION_STATUS_CANDIDATE,
                created_by,
                now,
                now,
            ),
        )
        conversation_id = int(cursor.lastrowid)
        operation = "workstation_conversation_create_search_drop"
        log_message = f"Created workstation conversation from search drop '{title}'"

    for hit in hits:
        conn.execute(
            """
            INSERT INTO conversation_hit (
                workstation_conversation_id, message_id, retrieval_method,
                query_text, matched_term, score, rank, distance, explanation, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)
            """,
            (
                conversation_id,
                hit["message_id"],
                hit.get("retrieval_method", "fts_exact"),
                hit.get("query_text", ""),
                hit.get("matched_term", ""),
                hit.get("score"),
                hit.get("rank"),
                hit.get("distance"),
                json.dumps({"match_type": hit.get("match_type", "")}),
            ),
        )
    conn.commit()
    logger.info(
        component="db.repositories",
        operation=operation,
        message=log_message,
        details={
            "workstation_conversation_id": conversation_id,
            "category_id": category_id,
            "source_thread_id": source_thread_id,
            "hit_count": len(hits),
            "merged": merge_into_conversation_id is not None,
        },
        dataset_id=dataset_id,
    )
    row = conn.execute(
        """
        SELECT workstation_conversation_id, dataset_id, category_id, source_thread_id,
               primary_hit_message_id, title, user_notes, status, created_by,
               created_at, updated_at
        FROM workstation_conversation
        WHERE workstation_conversation_id = ?
        """,
        (conversation_id,),
    ).fetchone()
    assert row is not None
    return WorkstationConversation(
        workstation_conversation_id=row["workstation_conversation_id"],
        dataset_id=row["dataset_id"],
        category_id=row["category_id"],
        source_thread_id=row["source_thread_id"],
        primary_hit_message_id=row["primary_hit_message_id"],
        title=row["title"],
        user_notes=row["user_notes"],
        status=row["status"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def find_merge_candidate_for_search_drop(
    conn: sqlite3.Connection,
    *,
    category_id: int,
    source_thread_id: str,
    hit_message_ids: list[str],
) -> int | None:
    rows = conn.execute(
        """
        SELECT wc.workstation_conversation_id, ch.message_id
        FROM workstation_conversation wc
        JOIN conversation_hit ch ON ch.workstation_conversation_id = wc.workstation_conversation_id
        WHERE wc.category_id = ? AND wc.source_thread_id = ?
        """,
        (category_id, source_thread_id),
    ).fetchall()
    by_conversation: dict[int, set[str]] = {}
    for row in rows:
        by_conversation.setdefault(row["workstation_conversation_id"], set()).add(row["message_id"])
    incoming = set(hit_message_ids)
    for conversation_id, existing_ids in by_conversation.items():
        if incoming & existing_ids:
            return conversation_id
    return None


def list_conversation_hits(
    conn: sqlite3.Connection,
    workstation_conversation_id: int,
) -> list[ConversationHit]:
    rows = conn.execute(
        """
        SELECT conversation_hit_id, workstation_conversation_id, message_id,
               retrieval_method, query_text, matched_term, score, rank, distance,
               explanation, metadata_json
        FROM conversation_hit
        WHERE workstation_conversation_id = ?
        ORDER BY conversation_hit_id
        """,
        (workstation_conversation_id,),
    ).fetchall()
    return [
        ConversationHit(
            conversation_hit_id=row["conversation_hit_id"],
            workstation_conversation_id=row["workstation_conversation_id"],
            message_id=row["message_id"],
            retrieval_method=row["retrieval_method"],
            query_text=row["query_text"],
            matched_term=row["matched_term"],
            score=row["score"],
            rank=row["rank"],
            distance=row["distance"],
            explanation=row["explanation"],
            metadata_json=_json_loads(row["metadata_json"]),
        )
        for row in rows
    ]


def get_workstation_conversation(
    conn: sqlite3.Connection,
    workstation_conversation_id: int,
) -> WorkstationConversation | None:
    row = conn.execute(
        """
        SELECT workstation_conversation_id, dataset_id, category_id, source_thread_id,
               primary_hit_message_id, title, user_notes, status, created_by,
               created_at, updated_at
        FROM workstation_conversation
        WHERE workstation_conversation_id = ?
        """,
        (workstation_conversation_id,),
    ).fetchone()
    if row is None:
        return None
    return WorkstationConversation(
        workstation_conversation_id=row["workstation_conversation_id"],
        dataset_id=row["dataset_id"],
        category_id=row["category_id"],
        source_thread_id=row["source_thread_id"],
        primary_hit_message_id=row["primary_hit_message_id"],
        title=row["title"],
        user_notes=row["user_notes"],
        status=row["status"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def load_output_conversation_context(
    conn: sqlite3.Connection,
    workstation_conversation_id: int,
) -> OutputConversationContext | None:
    conversation = get_workstation_conversation(conn, workstation_conversation_id)
    if conversation is None:
        return None
    category_row = conn.execute(
        "SELECT name FROM category WHERE category_id = ?",
        (conversation.category_id,),
    ).fetchone()
    thread_row = conn.execute(
        """
        SELECT display_title, source_platform
        FROM source_thread
        WHERE dataset_id = ? AND source_thread_id = ?
        """,
        (conversation.dataset_id, conversation.source_thread_id),
    ).fetchone()
    hits = list_conversation_hits(conn, workstation_conversation_id)
    hit_message_ids = {hit.message_id for hit in hits}
    if conversation.primary_hit_message_id:
        hit_message_ids.add(conversation.primary_hit_message_id)
    messages = list_messages_for_thread(
        conn,
        conversation.dataset_id,
        conversation.source_thread_id,
    )
    conversation_range = get_conversation_range(conn, workstation_conversation_id)
    highlight_overrides = list_highlight_overrides(conn, workstation_conversation_id)
    from message_evidence_workstation.output.display_states import (
        boundary_labels_for_range,
        compute_message_display_states,
    )

    display_states = compute_message_display_states(
        messages,
        hit_message_ids=hit_message_ids,
        conversation_range=conversation_range,
        highlight_overrides=highlight_overrides,
    )
    boundary_labels = boundary_labels_for_range(messages, conversation_range)
    return OutputConversationContext(
        conversation=conversation,
        category_name=str(category_row["name"]) if category_row else "",
        thread_display_title=str(thread_row["display_title"]) if thread_row else conversation.source_thread_id,
        source_platform=str(thread_row["source_platform"]) if thread_row else "",
        messages=messages,
        hits=hits,
        hit_message_ids=hit_message_ids,
        conversation_range=conversation_range,
        highlight_overrides=highlight_overrides,
        display_states=display_states,
        boundary_labels=boundary_labels,
    )


def update_workstation_conversation_notes(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    workstation_conversation_id: int,
    user_notes: str,
    status: str | None = None,
) -> None:
    now = utc_now_iso()
    if status is None:
        conn.execute(
            """
            UPDATE workstation_conversation
            SET user_notes = ?, updated_at = ?
            WHERE workstation_conversation_id = ?
            """,
            (user_notes, now, workstation_conversation_id),
        )
    else:
        conn.execute(
            """
            UPDATE workstation_conversation
            SET user_notes = ?, status = ?, updated_at = ?
            WHERE workstation_conversation_id = ?
            """,
            (user_notes, status, now, workstation_conversation_id),
        )
    conn.commit()
    logger.info(
        component="db.repositories",
        operation="workstation_conversation_notes_updated",
        message="Updated workstation conversation notes",
        details={"workstation_conversation_id": workstation_conversation_id},
        dataset_id=None,
    )


def get_conversation_range(
    conn: sqlite3.Connection,
    workstation_conversation_id: int,
) -> ConversationRange | None:
    row = conn.execute(
        """
        SELECT conversation_range_id, workstation_conversation_id,
               lead_in_start_message_id, relevant_start_message_id,
               relevant_end_message_id, lead_out_end_message_id,
               llm_suggested_json, user_modified, locked
        FROM conversation_range
        WHERE workstation_conversation_id = ?
        """,
        (workstation_conversation_id,),
    ).fetchone()
    if row is None:
        return None
    return ConversationRange(
        conversation_range_id=int(row["conversation_range_id"]),
        workstation_conversation_id=int(row["workstation_conversation_id"]),
        lead_in_start_message_id=row["lead_in_start_message_id"],
        relevant_start_message_id=row["relevant_start_message_id"],
        relevant_end_message_id=row["relevant_end_message_id"],
        lead_out_end_message_id=row["lead_out_end_message_id"],
        llm_suggested_json=_json_loads(row["llm_suggested_json"]),
        user_modified=bool(row["user_modified"]),
        locked=bool(row["locked"]),
    )


def upsert_conversation_range(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    workstation_conversation_id: int,
    lead_in_start_message_id: str,
    relevant_start_message_id: str,
    relevant_end_message_id: str,
    lead_out_end_message_id: str,
    llm_suggested_json: dict[str, Any] | None = None,
    user_modified: bool = False,
    locked: bool = False,
) -> ConversationRange:
    payload = json.dumps(llm_suggested_json or {})
    existing = get_conversation_range(conn, workstation_conversation_id)
    if existing is None:
        cursor = conn.execute(
            """
            INSERT INTO conversation_range (
                workstation_conversation_id, lead_in_start_message_id,
                relevant_start_message_id, relevant_end_message_id,
                lead_out_end_message_id, llm_suggested_json, user_modified, locked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workstation_conversation_id,
                lead_in_start_message_id,
                relevant_start_message_id,
                relevant_end_message_id,
                lead_out_end_message_id,
                payload,
                int(user_modified),
                int(locked),
            ),
        )
        range_id = int(cursor.lastrowid)
    else:
        range_id = existing.conversation_range_id
        conn.execute(
            """
            UPDATE conversation_range
            SET lead_in_start_message_id = ?, relevant_start_message_id = ?,
                relevant_end_message_id = ?, lead_out_end_message_id = ?,
                llm_suggested_json = ?, user_modified = ?, locked = ?
            WHERE conversation_range_id = ?
            """,
            (
                lead_in_start_message_id,
                relevant_start_message_id,
                relevant_end_message_id,
                lead_out_end_message_id,
                payload,
                int(user_modified),
                int(locked),
                range_id,
            ),
        )
    conn.commit()
    logger.info(
        component="db.repositories",
        operation="conversation_range_upsert",
        message="Saved conversation range boundaries",
        details={
            "workstation_conversation_id": workstation_conversation_id,
            "user_modified": user_modified,
            "locked": locked,
        },
    )
    result = get_conversation_range(conn, workstation_conversation_id)
    assert result is not None
    return result


def list_highlight_overrides(
    conn: sqlite3.Connection,
    workstation_conversation_id: int,
) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT message_id, highlight_state
        FROM message_highlight_override
        WHERE workstation_conversation_id = ?
        """,
        (workstation_conversation_id,),
    ).fetchall()
    return {str(row["message_id"]): str(row["highlight_state"]) for row in rows}


def set_highlight_override(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    workstation_conversation_id: int,
    message_id: str,
    highlight_state: str,
) -> None:
    conn.execute(
        """
        INSERT INTO message_highlight_override (
            workstation_conversation_id, message_id, highlight_state, user_modified
        ) VALUES (?, ?, ?, 1)
        ON CONFLICT(workstation_conversation_id, message_id)
        DO UPDATE SET highlight_state = excluded.highlight_state, user_modified = 1
        """,
        (workstation_conversation_id, message_id, highlight_state),
    )
    conn.commit()
    logger.info(
        component="db.repositories",
        operation="highlight_override_set",
        message="Saved per-message highlight override",
        details={
            "workstation_conversation_id": workstation_conversation_id,
            "message_id": message_id,
            "highlight_state": highlight_state,
        },
    )

