from message_evidence_workstation.config.settings import (
    PROVIDER_GOOGLE,
    PROVIDER_NIM,
    load_settings,
    save_settings,
)
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.logging_ui.log_bus import get_log_bus
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.llm.types import UserFacingModelRole
from message_evidence_workstation.ui.settings_tab import SettingsTab


def test_settings_tab_hydrates_cached_provider_model_lists(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "ui.evw"
    conn = connect(db_path)
    logger = ProcessLogger(conn, log_bus=get_log_bus())
    initialize_schema(conn, logger)

    settings = load_settings()
    settings.model_metadata = {
        "meta/llama-3.1-8b-instruct": {"owned_by": "meta"},
    }
    settings.provider_model_lists = {
        PROVIDER_GOOGLE: ["gemini-2.0-flash"],
    }
    save_settings(settings)

    tab = SettingsTab(conn, logger, get_log_bus(), db_path=db_path)

    assert [model.id for model in tab._models_by_provider[PROVIDER_NIM]] == [
        "meta/llama-3.1-8b-instruct"
    ]
    assert [model.id for model in tab._models_by_provider[PROVIDER_GOOGLE]] == [
        "gemini-2.0-flash"
    ]

    provider = tab.role_provider[UserFacingModelRole.WRITING]
    provider.setCurrentIndex(provider.findData(PROVIDER_NIM))
    assert tab.role_model[UserFacingModelRole.WRITING].count() >= 1
    provider.setCurrentIndex(provider.findData(PROVIDER_GOOGLE))
    assert tab.role_model[UserFacingModelRole.WRITING].count() >= 1

    conn.close()


def test_settings_tab_autosaves_api_and_routing_changes(tmp_path, qapp, monkeypatch) -> None:
    monkeypatch.setenv("MEW_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "ui.evw"
    conn = connect(db_path)
    logger = ProcessLogger(conn, log_bus=get_log_bus())
    initialize_schema(conn, logger)

    tab = SettingsTab(conn, logger, get_log_bus(), db_path=db_path)
    tab.nim_api_key.setText("nim-key-1")
    tab.nim_api_key.editingFinished.emit()
    tab.google_api_key.setText("google-key-1")
    tab.google_api_key.editingFinished.emit()
    provider = tab.role_provider[UserFacingModelRole.WRITING]
    provider.setCurrentIndex(provider.findData(PROVIDER_GOOGLE))
    tab.role_model[UserFacingModelRole.WRITING].setCurrentText("gemini-2.0-flash")

    saved = load_settings()
    assert saved.nim.api_key == "nim-key-1"
    assert saved.model_routing is not None
    assert saved.model_routing.writing.provider == PROVIDER_GOOGLE
    assert saved.model_routing.writing.model == "gemini-2.0-flash"
    assert saved.model_routing.writing.api_key == "google-key-1"

    conn.close()
