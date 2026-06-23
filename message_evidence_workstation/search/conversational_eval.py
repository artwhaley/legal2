"""Evaluation helpers for conversational recall (T10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from message_evidence_workstation.search.conversational_answer import ConversationalAnswerResult

EVAL_QUESTIONS: list[dict[str, Any]] = [
    {
        "question": "What was discussed about the allergy form?",
        "expected_message_ids": ["msg_001", "msg_002"],
        "expects_insufficient_evidence": False,
    },
    {
        "question": "What should be packed for the cabin trip?",
        "expected_message_ids": ["msg_097", "msg_098"],
        "expects_insufficient_evidence": False,
        "tags": ["multi_day", "scattered"],
    },
    {
        "question": "Who won the 2032 presidential election?",
        "expected_message_ids": [],
        "expects_insufficient_evidence": True,
    },
    {
        "question": "travel chess set",
        "expected_message_ids": ["msg_098"],
        "expects_insufficient_evidence": False,
        "tags": ["regression_whole_transcript"],
    },
]


@dataclass(slots=True)
class ConversationalEvalScore:
    question: str
    expected_message_ids: list[str]
    cited_message_ids: list[str]
    candidate_message_ids: list[str]
    recall_hits: list[str]
    recall_misses: list[str]
    passed: bool
    notes: list[str]


def candidate_message_ids(result: ConversationalAnswerResult) -> list[str]:
    ids: list[str] = []
    for block in result.candidate_evidence_blocks:
        for message_id in (
            block.core_message_id,
            block.relevant_start_message_id,
            block.relevant_end_message_id,
            block.leading_context_start_message_id,
            block.trailing_context_end_message_id,
            *block.highlighted_message_ids,
        ):
            if message_id and message_id not in ids:
                ids.append(message_id)
    return ids


def score_conversational_answer(
    result: ConversationalAnswerResult,
    *,
    question: str,
    expected_message_ids: list[str],
    expects_insufficient_evidence: bool = False,
) -> ConversationalEvalScore:
    cited = list(result.cited_message_ids)
    candidates = candidate_message_ids(result)
    found = {message_id for message_id in cited + candidates}
    expected = list(expected_message_ids)
    hits = [message_id for message_id in expected if message_id in found]
    misses = [message_id for message_id in expected if message_id not in found]
    notes: list[str] = []
    passed = True
    if expects_insufficient_evidence:
        passed = not expected or not hits
        if result.answer and "not enough" not in result.answer.lower():
            notes.append("Expected an insufficient-evidence style answer.")
    else:
        passed = not misses
    if result.uncertainties:
        notes.extend(result.uncertainties[:3])
    return ConversationalEvalScore(
        question=question,
        expected_message_ids=expected,
        cited_message_ids=cited,
        candidate_message_ids=candidates,
        recall_hits=hits,
        recall_misses=misses,
        passed=passed,
        notes=notes,
    )
