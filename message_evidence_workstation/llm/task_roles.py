"""LLM call inventory and task-role mapping (T25)."""

from __future__ import annotations

from dataclasses import dataclass

from message_evidence_workstation.llm.types import ModelTaskRole, UserFacingModelRole
from message_evidence_workstation.nim.prompts import (
    RUN_TYPE_CONVERSATIONAL_PLANNER,
    RUN_TYPE_CONVERSATIONAL_SYNTHESIS,
    RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
    RUN_TYPE_EXHAUSTIVE_SCAN_RETRIEVAL_TERMS,
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    RUN_TYPE_KEYWORD_EXPANSION,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
)

CallSiteCategory = str  # "workflow" | "settings" | "background"


@dataclass(frozen=True, slots=True)
class LlmCallSite:
    """One inventoried LLM entry point."""

    module: str
    function: str
    task_role: ModelTaskRole
    category: CallSiteCategory
    run_type: str | None = None
    notes: str = ""


# Prompt run_type strings (model_run.run_type) -> internal task role.
RUN_TYPE_TO_TASK_ROLE: dict[str, ModelTaskRole] = {
    RUN_TYPE_KEYWORD_EXPANSION: ModelTaskRole.SEARCH_EXPANSION,
    RUN_TYPE_CONVERSATIONAL_PLANNER: ModelTaskRole.FULL_CONTEXT_SEARCH,
    RUN_TYPE_CONVERSATIONAL_SYNTHESIS: ModelTaskRole.WINDOWED_RESULT_MERGE,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER: ModelTaskRole.FULL_CONTEXT_ANSWER,
    RUN_TYPE_EXHAUSTIVE_SCAN_RETRIEVAL_TERMS: ModelTaskRole.SEARCH_EXPANSION,
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN: ModelTaskRole.WINDOWED_CONTEXT_SEARCH,
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE: ModelTaskRole.WINDOWED_RESULT_MERGE,
    RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS: ModelTaskRole.WINDOWED_RESULT_MERGE,
}

TASK_ROLE_TO_USER_FACING_ROLE: dict[ModelTaskRole, UserFacingModelRole | None] = {
    ModelTaskRole.SEARCH_EXPANSION: UserFacingModelRole.EXPANSION,
    ModelTaskRole.FULL_CONTEXT_SEARCH: UserFacingModelRole.RESEARCH,
    ModelTaskRole.WINDOWED_CONTEXT_SEARCH: UserFacingModelRole.RESEARCH,
    ModelTaskRole.WINDOWED_RESULT_MERGE: UserFacingModelRole.WRITING,
    ModelTaskRole.FULL_CONTEXT_ANSWER: UserFacingModelRole.WRITING,
    ModelTaskRole.CONVERSATIONAL_CANDIDATE: UserFacingModelRole.WRITING,
    ModelTaskRole.MODEL_TEST: None,
    ModelTaskRole.MODEL_LIST: None,
}

# Verified call-site inventory. run_nim_chat-backed sites share run_type keys.
LLM_CALL_SITES: tuple[LlmCallSite, ...] = (
    LlmCallSite(
        "search.exhaustive_hints",
        "collect_exhaustive_window_hints",
        ModelTaskRole.SEARCH_EXPANSION,
        "workflow",
        run_type=RUN_TYPE_EXHAUSTIVE_SCAN_RETRIEVAL_TERMS,
        notes="Planner-only retrieval-term extraction for exhaustive window hints.",
    ),
    LlmCallSite(
        "search.keyword_expansion",
        "expand_keywords",
        ModelTaskRole.SEARCH_EXPANSION,
        "workflow",
        run_type=RUN_TYPE_KEYWORD_EXPANSION,
    ),
    LlmCallSite(
        "search.tool_runner",
        "_keyword_expansion_hits",
        ModelTaskRole.SEARCH_EXPANSION,
        "workflow",
        run_type=RUN_TYPE_KEYWORD_EXPANSION,
        notes="Indirect via expand_keywords during retrieval harness.",
    ),
    LlmCallSite(
        "search.tool_runner",
        "run_conversational_planner",
        ModelTaskRole.FULL_CONTEXT_SEARCH,
        "workflow",
        run_type=RUN_TYPE_CONVERSATIONAL_PLANNER,
    ),
    LlmCallSite(
        "search.conversational_answer",
        "run_whole_transcript_answer",
        ModelTaskRole.FULL_CONTEXT_ANSWER,
        "workflow",
        run_type=RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
    ),
    LlmCallSite(
        "search.conversational_answer",
        "run_exhaustive_window_scan_answer",
        ModelTaskRole.WINDOWED_CONTEXT_SEARCH,
        "workflow",
        run_type=RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
        notes="Per-window scan calls; merge step uses WINDOWED_RESULT_MERGE.",
    ),
    LlmCallSite(
        "search.conversational_answer",
        "_run_bounded_exhaustive_window_merge",
        ModelTaskRole.WINDOWED_RESULT_MERGE,
        "workflow",
        run_type=RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
    ),
    LlmCallSite(
        "search.conversational_answer",
        "_run_evidence_ledger_window_merge",
        ModelTaskRole.WINDOWED_RESULT_MERGE,
        "workflow",
        run_type=RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS,
    ),
    LlmCallSite(
        "ui.settings_tab",
        "SettingsTab._refresh_models",
        ModelTaskRole.MODEL_LIST,
        "settings",
        notes="NimClient.list_models; provider-level operation.",
    ),
    LlmCallSite(
        "ui.settings_tab",
        "SettingsTab._test_model",
        ModelTaskRole.MODEL_TEST,
        "settings",
        notes="NimClient.test_model; exercises configured provider/model.",
    ),
    LlmCallSite(
        "ui.simple_search_tab",
        "SimpleSearchTab._request_keyword_expansion",
        ModelTaskRole.SEARCH_EXPANSION,
        "workflow",
        run_type=RUN_TYPE_KEYWORD_EXPANSION,
        notes="UI wrapper around expand_keywords.",
    ),
    LlmCallSite(
        "ui.conversational_tab",
        "ConversationalTab._run_whole_transcript_answer",
        ModelTaskRole.FULL_CONTEXT_ANSWER,
        "workflow",
        run_type=RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
    ),
    LlmCallSite(
        "ui.conversational_tab",
        "ConversationalTab._run_exhaustive_window_scan_answer",
        ModelTaskRole.WINDOWED_CONTEXT_SEARCH,
        "workflow",
        run_type=RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    ),
    LlmCallSite(
        "ui.embedding_worker",
        "_run_embedding_job",
        ModelTaskRole.SEARCH_EXPANSION,
        "background",
        run_type=RUN_TYPE_KEYWORD_EXPANSION,
        notes="Harness may invoke expand_keywords when NIM client is configured.",
    ),
)

AMBIGUOUS_CALL_NOTES: dict[str, str] = {}


def task_role_for_run_type(run_type: str) -> ModelTaskRole:
    """Resolve the internal task role for a prompt/model_run run_type string."""
    try:
        return RUN_TYPE_TO_TASK_ROLE[run_type]
    except KeyError as exc:
        raise KeyError(f"No ModelTaskRole mapped for run_type={run_type!r}") from exc


def user_facing_role_for_task_role(task_role: ModelTaskRole) -> UserFacingModelRole | None:
    """Map an internal task role to expansion/research/writing settings (T26+)."""
    return TASK_ROLE_TO_USER_FACING_ROLE[task_role]


def call_sites_for_task_role(task_role: ModelTaskRole) -> tuple[LlmCallSite, ...]:
    return tuple(site for site in LLM_CALL_SITES if site.task_role == task_role)


def call_sites_for_run_type(run_type: str) -> tuple[LlmCallSite, ...]:
    return tuple(site for site in LLM_CALL_SITES if site.run_type == run_type)
