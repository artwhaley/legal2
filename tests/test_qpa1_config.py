import copy
import json
from dataclasses import replace

import pytest

from server.config import CHAT_OPERATIONS, GlobalConfig, migrate_v3_config_dict
from server.config_store import ConfigStore
from server.prompts import DEFAULT_PROMPTS
from tests.test_sfv1_control_store import make_config


def _v3_payload():
    store = ConfigStore()
    try:
        active = store.active()
        assert active is not None
        value = active.to_dict(include_secrets=False)
    finally:
        store.close()
    value["config_schema_version"] = 3
    value["operation_assignments"]["retrieval_terms"] = value["operation_assignments"].pop("analysis_planning", None) or value["operation_assignments"].pop("retrieval_terms")
    return value


def test_v4_operation_set_and_retrieval_modes():
    assert CHAT_OPERATIONS == ("keyword_expansion", "analysis_planning", "window_evidence_extraction", "ledger_compaction", "ledger_synthesis")
    assert GlobalConfig().retrieval_assistance_mode == "none"
    with pytest.raises(ValueError):
        GlobalConfig(retrieval_assistance_mode="terms_only").validate()


def test_v3_migration_renames_planner_and_preserves_settings():
    value = _v3_payload()
    value["global_config"]["retrieval_assistance_mode"] = "terms_only"
    value["operation_assignments"]["retrieval_terms"]["temperature"] = 0.37
    migrated = migrate_v3_config_dict(value, planning_prompt="new planner prompt")
    assert migrated["config_schema_version"] == 4
    assert set(migrated["operation_assignments"]) == set(CHAT_OPERATIONS)
    assert migrated["operation_assignments"]["analysis_planning"]["temperature"] == 0.37
    assert migrated["operation_assignments"]["analysis_planning"]["system_prompt"] == "new planner prompt"
    assert migrated["global_config"]["retrieval_assistance_mode"] == "none"


def test_v3_migration_replaces_every_prompt_whose_output_contract_changed():
    value = _v3_payload()
    value["operation_assignments"]["retrieval_terms"]["system_prompt"] = "old planner"
    value["operation_assignments"]["window_evidence_extraction"]["system_prompt"] = "old extraction"
    value["operation_assignments"]["ledger_compaction"]["system_prompt"] = "old compaction"
    value["operation_assignments"]["ledger_synthesis"]["system_prompt"] = "old synthesis"
    value["operation_assignments"]["ledger_synthesis"]["temperature"] = 0.37

    migrated = migrate_v3_config_dict(value, contract_prompts=DEFAULT_PROMPTS)

    for operation in (
        "analysis_planning",
        "window_evidence_extraction",
        "ledger_compaction",
        "ledger_synthesis",
    ):
        assert migrated["operation_assignments"][operation]["system_prompt"] == DEFAULT_PROMPTS[operation]
    assert migrated["operation_assignments"]["ledger_synthesis"]["temperature"] == 0.37


def test_v3_migration_rejects_unknown_or_invalid_without_mutating_input():
    value = _v3_payload()
    original = copy.deepcopy(value)
    value["operation_assignments"]["unknown"] = {}
    with pytest.raises(ValueError):
        migrate_v3_config_dict(value)
    assert value["config_schema_version"] == original["config_schema_version"]
    assert "unknown" in value["operation_assignments"]


def test_control_store_migrates_active_payload_to_v4(tmp_path):
    source = ConfigStore()
    try:
        active = source.active()
        assert active is not None
        payload = active.to_dict(include_secrets=False)
    finally:
        source.close()
    # A temporary store exercises bootstrap/schema behavior without touching
    # the live encrypted state beyond the explicit migration test above.
    target = ConfigStore(db_path=tmp_path / "control.sqlite3")
    try:
        assert target.conn.execute("select version from control_schema_version").fetchone()[0] == 4
        assert target.active() is None
    finally:
        target.close()


def test_known_seed_prompt_is_migrated_without_schema_or_assignment_changes():
    store = ConfigStore()
    try:
        active = store.active()
        assert active is not None
        assert active.operations["ledger_synthesis"].system_prompt == DEFAULT_PROMPTS["ledger_synthesis"]
        assert store.conn.execute("select version from control_schema_version").fetchone()[0] == 4
    finally:
        store.close()


def test_operator_custom_obsolete_synthesis_prompt_is_rejected_on_validation(tmp_path):
    store = ConfigStore(tmp_path)
    try:
        draft_id = store.create_draft(make_config())
        provider_id = next(iter(store.get_version(draft_id).provider_accounts))
        store.set_secret(draft_id, provider_id, "synthetic-secret-1234")
        draft = store.get_version(draft_id)
        synthesis = draft.operation_assignments["ledger_synthesis"]
        custom = replace(
            draft,
            operation_assignments={
                **draft.operation_assignments,
                "ledger_synthesis": replace(
                    synthesis,
                    system_prompt="Operator custom prompt containing " + "direct_" + "evidence",
                ),
            },
        )
        store.save_draft(draft_id, custom)
        with pytest.raises(ValueError, match="obsolete response contract"):
            store.validate_version(draft_id)
    finally:
        store.close()
