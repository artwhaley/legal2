"""NIM-backed evidence range suggestion (T20)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from message_evidence_workstation.domain.models import Message, OutputConversationContext
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.client import NimClient
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import RUN_TYPE_RANGE_SUGGESTION
from message_evidence_workstation.search.tool_runner import PlannerParseError, _extract_json_object


class RangeSuggestionParseError(ValueError):
    pass


@dataclass(slots=True)
class RangeSuggestionResult:
    lead_in_start_message_id: str
    relevant_start_message_id: str
    relevant_end_message_id: str
    lead_out_end_message_id: str
    explanation: str
    raw_payload: dict[str, Any]


def _window_messages(context: OutputConversationContext, *, radius: int = 20) -> list[Message]:
    messages = context.messages
    if not messages:
        return []
    primary_id = context.conversation.primary_hit_message_id
    center = 0
    for index, message in enumerate(messages):
        if message.message_id == primary_id:
            center = index
            break
    start = max(center - radius, 0)
    end = min(center + radius + 1, len(messages))
    return messages[start:end]


def build_range_suggestion_user_content(context: OutputConversationContext) -> str:
    window = _window_messages(context)
    payload = {
        "conversation_title": context.conversation.title,
        "source_thread_id": context.conversation.source_thread_id,
        "primary_hit_message_id": context.conversation.primary_hit_message_id,
        "hit_messages": [
            {
                "message_id": hit.message_id,
                "retrieval_method": hit.retrieval_method,
                "query_text": hit.query_text,
                "matched_term": hit.matched_term,
                "explanation": hit.explanation,
            }
            for hit in context.hits
        ],
        "thread_messages": [
            {
                "message_id": message.message_id,
                "timestamp": message.timestamp,
                "sender": message.sender_display,
                "body": message.body[:500],
                "sort_index": message.sort_index,
            }
            for message in window
        ],
    }
    return json.dumps(payload, indent=2)


def parse_range_suggestion_response(content: str) -> RangeSuggestionResult:
    payload = _extract_json_object(content)
    fields = (
        "lead_in_start_message_id",
        "relevant_start_message_id",
        "relevant_end_message_id",
        "lead_out_end_message_id",
    )
    values: dict[str, str] = {}
    for field in fields:
        raw = payload.get(field)
        if not isinstance(raw, str) or not raw.strip():
            raise RangeSuggestionParseError(f"Missing or empty {field}")
        values[field] = raw.strip()
    explanation = str(payload.get("explanation", "")).strip()
    return RangeSuggestionResult(
        lead_in_start_message_id=values["lead_in_start_message_id"],
        relevant_start_message_id=values["relevant_start_message_id"],
        relevant_end_message_id=values["relevant_end_message_id"],
        lead_out_end_message_id=values["lead_out_end_message_id"],
        explanation=explanation,
        raw_payload=payload,
    )


def fallback_range_from_hits(context: OutputConversationContext) -> RangeSuggestionResult:
    primary = context.conversation.primary_hit_message_id
    hit_ids = [message.message_id for message in context.messages if message.message_id in context.hit_message_ids]
    if not hit_ids:
        hit_ids = [primary]
    start_id = hit_ids[0]
    end_id = hit_ids[-1]
    return RangeSuggestionResult(
        lead_in_start_message_id=start_id,
        relevant_start_message_id=start_id,
        relevant_end_message_id=end_id,
        lead_out_end_message_id=end_id,
        explanation="Fallback range from stored hit messages.",
        raw_payload={"fallback": True},
    )


def run_range_suggestion(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    client: NimClient,
    *,
    context: OutputConversationContext,
    dataset_id: int,
) -> RangeSuggestionResult:
    user_content = build_range_suggestion_user_content(context)
    logger.info(
        component="search.range_suggestion",
        operation="range_suggestion_start",
        message="Requesting NIM evidence range suggestion",
        details={
            "workstation_conversation_id": context.conversation.workstation_conversation_id,
            "payload_chars": len(user_content),
        },
        dataset_id=dataset_id,
    )
    chat = run_nim_chat(
        conn,
        logger,
        client,
        run_type=RUN_TYPE_RANGE_SUGGESTION,
        user_content=user_content,
        dataset_id=dataset_id,
    )
    try:
        result = parse_range_suggestion_response(chat.content)
    except (PlannerParseError, RangeSuggestionParseError) as exc:
        logger.warning(
            component="search.range_suggestion",
            operation="range_suggestion_parse_failed",
            message=f"Using fallback range after parse failure: {exc}",
            exc=exc,
            dataset_id=dataset_id,
        )
        result = fallback_range_from_hits(context)
    logger.info(
        component="search.range_suggestion",
        operation="range_suggestion_complete",
        message="Range suggestion finished",
        details={
            "lead_in_start_message_id": result.lead_in_start_message_id,
            "relevant_end_message_id": result.relevant_end_message_id,
            "explanation": result.explanation[:200],
        },
        dataset_id=dataset_id,
    )
    return result
