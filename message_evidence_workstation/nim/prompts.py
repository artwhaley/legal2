"""Prompt template defaults and helpers."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from message_evidence_workstation.logging_ui.process_log import utc_now_iso

if TYPE_CHECKING:
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger

RUN_TYPE_KEYWORD_EXPANSION = "keyword_expansion"
RUN_TYPE_CONVERSATIONAL_PLANNER = "conversational_search_planner"
RUN_TYPE_CONVERSATIONAL_SYNTHESIS = "conversational_search_synthesis"
RUN_TYPE_RANGE_SUGGESTION = "evidence_range_suggestion"
RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER = "whole_transcript_answer"
RUN_TYPE_COVERAGE_SESSION_ANSWER = "coverage_session_answer"
RUN_TYPE_COVERAGE_AUDIT = "coverage_audit"
RUN_TYPE_SESSION_SUMMARY = "session_summary"
RUN_TYPE_SESSION_CLASSIFICATION = "session_classification"
RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN = "exhaustive_window_scan"
RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE = "exhaustive_window_merge"

ALL_RUN_TYPES = (
    RUN_TYPE_KEYWORD_EXPANSION,
    RUN_TYPE_CONVERSATIONAL_PLANNER,
    RUN_TYPE_CONVERSATIONAL_SYNTHESIS,
    RUN_TYPE_RANGE_SUGGESTION,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
    RUN_TYPE_COVERAGE_SESSION_ANSWER,
    RUN_TYPE_COVERAGE_AUDIT,
    RUN_TYPE_SESSION_SUMMARY,
    RUN_TYPE_SESSION_CLASSIFICATION,
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
)

DEFAULT_PROMPT_BODIES: dict[str, str] = {
    RUN_TYPE_KEYWORD_EXPANSION: (
        "You expand legal-evidence search queries into additional keyword terms. "
        'Return JSON only: {"terms": ["term1", "term2"]}. '
        "Return at most 15 short concrete terms likely to appear in family/message text. "
        "No markdown, no explanation, no nested JSON strings inside the terms array."
    ),
    RUN_TYPE_CONVERSATIONAL_PLANNER: (
        "You help search a message-evidence dataset. Python ALWAYS runs the full retrieval "
        "harness (FTS, keyword expansion, message embeddings, chunk embeddings, fusion, grouping). "
        "You do NOT choose which tools run. Return JSON only:\n"
        '{"strategy_summary": "plain-language search approach for the user", '
        '"extra_search_queries": ["optional extra FTS terms or phrases"]}\n'
        "extra_search_queries is optional — add alternate spellings, synonyms, or related terms. "
        "Do not return tool_calls unless you also include extra_search_queries inside them."
    ),
    RUN_TYPE_CONVERSATIONAL_SYNTHESIS: (
        "You synthesize message-evidence search results for a legal reviewer. "
        "You receive JSON with user_query, planner_strategy_summary, retrieval_summary, "
        "and candidate_groups (each has group_id, source_thread_id, hits, snippets). "
        "Return JSON only:\n"
        '{"answer": "plain-language answer grounded in the supplied groups", '
        '"strategy_summary": "brief recap of the search approach", '
        '"candidate_conversations": [{"group_id": "...", "title": "...", '
        '"explanation": "why this group matters", "confidence": "high|medium|low"}]}\n'
        "Only use group_id values from candidate_groups. Rank candidates by relevance. "
        "Do not invent message IDs. No markdown."
    ),
    RUN_TYPE_RANGE_SUGGESTION: (
        "You suggest evidence passage boundaries for a legal message review. "
        "You receive JSON with conversation_title, primary_hit_message_id, hit_messages, "
        "and a window of thread_messages. Return JSON only:\n"
        '{"lead_in_start_message_id": "...", "relevant_start_message_id": "...", '
        '"relevant_end_message_id": "...", "lead_out_end_message_id": "...", '
        '"explanation": "why these boundaries fit"}\n'
        "Use only message_id values from thread_messages. "
        "lead-in is context before the relevant passage; lead-out is context after. "
        "No markdown."
    ),
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER: (
        "You answer questions about a message-evidence transcript for a legal reviewer. "
        "You receive two user JSON payloads: first the stable transcript context "
        "(transcript, message_ids, source_thread_ids, messages_considered), then the "
        "user_query for this request. Answer ONLY from the supplied transcript. "
        "Cite message_id values for every factual claim. Prefer all relevant instances, "
        "not just examples. If evidence is insufficient, say so explicitly. "
        "Do not invent message IDs. Candidate evidence block boundaries must use message IDs "
        "from the transcript. Return JSON only:\n"
        '{"answer": "...", "cited_message_ids": ["msg_001"], '
        '"candidate_evidence_blocks": [{"title": "...", "summary": "...", '
        '"core_message_id": "msg_002", "relevant_start_message_id": "msg_001", '
        '"relevant_end_message_id": "msg_003", "leading_context_start_message_id": "msg_001", '
        '"trailing_context_end_message_id": "msg_004", '
        '"highlighted_message_ids": ["msg_002"]}], '
        '"uncertainties": ["..."], '
        '"coverage_summary": {"mode": "whole_transcript", "messages_considered": 100, '
        '"source_thread_ids": ["thread_001"]}}\n'
        "No markdown."
    ),
    RUN_TYPE_COVERAGE_SESSION_ANSWER: (
        "You answer questions about a large message-evidence corpus using session summaries "
        "and selected transcript windows. Return JSON only with answer, cited_message_ids, "
        "candidate_evidence_blocks, uncertainties, and coverage_summary including "
        "sessions_considered, sessions_inspected, and sessions_skipped. "
        "Use only message IDs present in supplied transcript windows. No markdown."
    ),
    RUN_TYPE_COVERAGE_AUDIT: (
        "You audit coverage before final synthesis in session-coverage mode. "
        "Review selected evidence, skipped session summaries, retrieval assists, and the "
        "user question. Return JSON only:\n"
        '{"additional_session_ids": ["session_001"], "residual_uncertainties": ["..."], '
        '"audit_notes": "..."}\n'
        "Request additional sessions when needed. No markdown."
    ),
    RUN_TYPE_SESSION_SUMMARY: (
        "You summarize a message transcript session for legal evidence review. "
        "Return JSON only with arrays for topics, people, events, commitments, conflicts, "
        "appointments, money, parenting_school, medical, travel, and notable_quotes. "
        "notable_quotes entries must be objects with message_id and quote. "
        "Use only message IDs from the transcript. No markdown."
    ),
    RUN_TYPE_SESSION_CLASSIFICATION: (
        "You classify transcript sessions for relevance to a user question. "
        "You receive JSON with user_query and session_summaries. "
        "Every session must appear exactly once. Return JSON only:\n"
        '{"session_classifications": [{"session_id": "...", '
        '"classification": "relevant|possibly_relevant|not_relevant", "reason": "..."}]}\n'
        "No markdown."
    ),
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN: (
        "You inspect ONE chronological transcript window for a legal evidence question. "
        "Answer only from this supplied window. If this window contains no relevant evidence, "
        "say that clearly and return no citations. If it contains relevant evidence, cite "
        "message IDs and propose candidate evidence blocks using only message IDs from this "
        "window. Return JSON only:\n"
        '{"answer": "...", "cited_message_ids": ["msg_001"], '
        '"candidate_evidence_blocks": [{"title": "...", "summary": "...", '
        '"core_message_id": "msg_001", "relevant_start_message_id": "msg_001", '
        '"relevant_end_message_id": "msg_002", "leading_context_start_message_id": "msg_001", '
        '"trailing_context_end_message_id": "msg_003", "highlighted_message_ids": ["msg_001"]}], '
        '"uncertainties": ["..."], '
        '"coverage_summary": {"mode": "exhaustive_window_scan", "messages_considered": 20, '
        '"source_thread_ids": ["thread_001"]}}\n'
        "No markdown."
    ),
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE: (
        "You merge per-window findings from an exhaustive scan of a message-evidence corpus. "
        "Every transcript window was already inspected. Synthesize a final answer from the "
        "window findings only. Preserve citations to message IDs. Prefer all relevant "
        "instances, not just examples. If all windows found insufficient evidence, say so. "
        "Return JSON only with answer, cited_message_ids, candidate_evidence_blocks, "
        "uncertainties, and coverage_summary. Use only message IDs present in the supplied "
        "window findings. No markdown."
    ),
}


def seed_default_prompts(conn: sqlite3.Connection, logger: ProcessLogger) -> None:
    now = utc_now_iso()
    for run_type in ALL_RUN_TYPES:
        existing = conn.execute(
            "SELECT prompt_template_id FROM prompt_template WHERE run_type = ? AND is_active = 1",
            (run_type,),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO prompt_template (
                name, run_type, body, version, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, 1, 1, ?, ?)
            """,
            (run_type.replace("_", " ").title(), run_type, DEFAULT_PROMPT_BODIES[run_type], now, now),
        )
    conn.commit()
    logger.info(
        component="nim.prompts",
        operation="seed_defaults",
        message="Default prompt templates ensured",
        details={"run_types": list(ALL_RUN_TYPES)},
    )


def get_active_prompt(conn: sqlite3.Connection, run_type: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT prompt_template_id, name, run_type, body, version, is_active, created_at, updated_at
        FROM prompt_template
        WHERE run_type = ? AND is_active = 1
        ORDER BY version DESC, prompt_template_id DESC
        LIMIT 1
        """,
        (run_type,),
    ).fetchone()


def save_prompt_version(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    run_type: str,
    body: str,
) -> int:
    now = utc_now_iso()
    current = get_active_prompt(conn, run_type)
    next_version = int(current["version"]) + 1 if current else 1
    if current:
        conn.execute(
            "UPDATE prompt_template SET is_active = 0 WHERE prompt_template_id = ?",
            (current["prompt_template_id"],),
        )
    cursor = conn.execute(
        """
        INSERT INTO prompt_template (
            name, run_type, body, version, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, ?, ?)
        """,
        (run_type.replace("_", " ").title(), run_type, body, next_version, now, now),
    )
    conn.commit()
    prompt_template_id = int(cursor.lastrowid)
    logger.info(
        component="nim.prompts",
        operation="prompt_version_saved",
        message=f"Saved prompt version for {run_type}",
        details={"run_type": run_type, "version": next_version, "prompt_template_id": prompt_template_id},
    )
    return prompt_template_id
