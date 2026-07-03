"""Model task role inventory and mapping tests (T25)."""

from __future__ import annotations

import pytest

from message_evidence_workstation.llm import (
    LLM_CALL_SITES,
    ModelTaskRole,
    RUN_TYPE_TO_TASK_ROLE,
    UserFacingModelRole,
    call_sites_for_task_role,
    task_role_for_run_type,
    user_facing_role_for_task_role,
)
from message_evidence_workstation.nim.prompts import (
    ALL_RUN_TYPES,
    RUN_TYPE_CONVERSATIONAL_SYNTHESIS,
    RUN_TYPE_EXHAUSTIVE_SCAN_RETRIEVAL_TERMS,
    RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE,
    RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN,
    RUN_TYPE_KEYWORD_EXPANSION,
    RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER,
)
from message_evidence_workstation.search import keyword_expansion, synthesis
from message_evidence_workstation.ui import settings_tab


def test_model_task_role_enum_values() -> None:
    assert ModelTaskRole.SEARCH_EXPANSION.value == "search_expansion"
    assert ModelTaskRole.MODEL_TEST.value == "model_test"
    assert len(ModelTaskRole) == 8


def test_all_prompt_run_types_have_task_role_mapping() -> None:
    for run_type in ALL_RUN_TYPES:
        assert run_type in RUN_TYPE_TO_TASK_ROLE


def test_keyword_expansion_maps_to_search_expansion() -> None:
    assert task_role_for_run_type(RUN_TYPE_KEYWORD_EXPANSION) == ModelTaskRole.SEARCH_EXPANSION
    assert keyword_expansion.TASK_ROLE == ModelTaskRole.SEARCH_EXPANSION
    sites = call_sites_for_task_role(ModelTaskRole.SEARCH_EXPANSION)
    assert any(site.function == "expand_keywords" for site in sites)
    assert any(site.function == "collect_exhaustive_window_hints" for site in sites)


def test_exhaustive_scan_retrieval_terms_map_to_search_expansion() -> None:
    assert task_role_for_run_type(RUN_TYPE_EXHAUSTIVE_SCAN_RETRIEVAL_TERMS) == ModelTaskRole.SEARCH_EXPANSION


def test_synthesis_maps_to_windowed_result_merge() -> None:
    assert task_role_for_run_type(RUN_TYPE_CONVERSATIONAL_SYNTHESIS) == ModelTaskRole.WINDOWED_RESULT_MERGE
    assert synthesis.TASK_ROLE == ModelTaskRole.WINDOWED_RESULT_MERGE


def test_full_context_answer_run_types() -> None:
    assert task_role_for_run_type(RUN_TYPE_WHOLE_TRANSCRIPT_ANSWER) == ModelTaskRole.FULL_CONTEXT_ANSWER


def test_windowed_flow_run_types() -> None:
    assert task_role_for_run_type(RUN_TYPE_EXHAUSTIVE_WINDOW_SCAN) == ModelTaskRole.WINDOWED_CONTEXT_SEARCH
    assert task_role_for_run_type(RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE) == ModelTaskRole.WINDOWED_RESULT_MERGE


def test_settings_model_test_task_role() -> None:
    assert settings_tab.MODEL_TEST_TASK_ROLE == ModelTaskRole.MODEL_TEST
    sites = call_sites_for_task_role(ModelTaskRole.MODEL_TEST)
    assert len(sites) == 1
    assert sites[0].function == "SettingsTab._test_model"


def test_settings_model_list_task_role() -> None:
    assert settings_tab.MODEL_LIST_TASK_ROLE == ModelTaskRole.MODEL_LIST
    sites = call_sites_for_task_role(ModelTaskRole.MODEL_LIST)
    assert len(sites) == 1
    assert sites[0].function == "SettingsTab._refresh_models"


def test_user_facing_role_mapping() -> None:
    assert user_facing_role_for_task_role(ModelTaskRole.SEARCH_EXPANSION) == UserFacingModelRole.EXPANSION
    assert user_facing_role_for_task_role(ModelTaskRole.FULL_CONTEXT_SEARCH) == UserFacingModelRole.RESEARCH
    assert user_facing_role_for_task_role(ModelTaskRole.FULL_CONTEXT_ANSWER) == UserFacingModelRole.WRITING
    assert user_facing_role_for_task_role(ModelTaskRole.MODEL_TEST) is None


def test_unknown_run_type_raises() -> None:
    with pytest.raises(KeyError, match="No ModelTaskRole mapped"):
        task_role_for_run_type("not_a_real_run_type")


def test_inventory_covers_workflow_and_settings_categories() -> None:
    categories = {site.category for site in LLM_CALL_SITES}
    assert "workflow" in categories
    assert "settings" in categories
    assert "background" in categories
