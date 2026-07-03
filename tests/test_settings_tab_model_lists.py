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
from message_evidence_workstation.llm.errors import ModelError
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


def test_settings_tab_refresh_clears_stale_provider_list_on_partial_failure(
    tmp_path, qapp, monkeypatch
) -> None:
    monkeypatch.setenv("MEW_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "ui.evw"
    conn = connect(db_path)
    logger = ProcessLogger(conn, log_bus=get_log_bus())
    initialize_schema(conn, logger)

    settings = load_settings()
    settings.nim.api_base_url = "https://featherless.example/v1"
    settings.provider_model_lists = {
        PROVIDER_NIM: ["stale/nim-model"],
        PROVIDER_GOOGLE: ["stale/google-model"],
    }
    settings.model_metadata = {
        "stale/nim-model": {"owned_by": "nvidia"},
    }
    save_settings(settings)

    tab = SettingsTab(conn, logger, get_log_bus(), db_path=db_path)

    def run_now(_parent, fn, *, on_success, on_error):
        try:
            result = fn()
        except BaseException as exc:
            on_error(exc)
        else:
            on_success(result)
        return None

    monkeypatch.setattr(
        "message_evidence_workstation.ui.background_tasks.run_background",
        run_now,
    )

    def fake_list_models_for_provider(self, provider: str):
        if provider == PROVIDER_NIM:
            raise ModelError(
                message="auth failed",
                error_type="auth_failure",
                provider=provider,
            )
        from message_evidence_workstation.llm.types import ModelInfo

        return [ModelInfo(id="gemini-2.5-flash", metadata={})]

    monkeypatch.setattr(
        "message_evidence_workstation.llm.router.ModelRouter.list_models_for_provider",
        fake_list_models_for_provider,
    )

    tab._refresh_models()
    qapp.processEvents()

    assert tab._models_by_provider[PROVIDER_NIM] == []
    assert tab._models_by_provider[PROVIDER_GOOGLE][0].id == "gemini-2.5-flash"
    assert tab.settings.provider_model_lists[PROVIDER_NIM] == []
    assert "nim: nim authentication failed" in tab.model_list_status.text().lower()

    conn.close()


def test_settings_tab_refresh_tolerates_unconfigured_google_provider(
    tmp_path, qapp, monkeypatch
) -> None:
    monkeypatch.setenv("MEW_WORKSPACE_DIR", str(tmp_path))
    db_path = tmp_path / "ui.evw"
    conn = connect(db_path)
    logger = ProcessLogger(conn, log_bus=get_log_bus())
    initialize_schema(conn, logger)

    settings = load_settings()
    settings.nim.api_base_url = "https://api.featherless.ai/v1"
    settings.provider_model_lists = {
        PROVIDER_NIM: ["stale/nim-model"],
        PROVIDER_GOOGLE: ["stale/google-model"],
    }
    settings.model_metadata = {
        "stale/nim-model": {"owned_by": "nvidia"},
    }
    save_settings(settings)

    tab = SettingsTab(conn, logger, get_log_bus(), db_path=db_path)

    def run_now(_parent, fn, *, on_success, on_error):
        try:
            result = fn()
        except BaseException as exc:
            on_error(exc)
        else:
            on_success(result)
        return None

    monkeypatch.setattr(
        "message_evidence_workstation.ui.background_tasks.run_background",
        run_now,
    )

    def fake_list_models_for_provider(self, provider: str):
        from message_evidence_workstation.llm.router import ModelRouterError
        from message_evidence_workstation.llm.types import ModelInfo

        if provider == PROVIDER_GOOGLE:
            raise ModelRouterError("No Google model configured. Set a model in Settings -> Model Routing.")
        return [ModelInfo(id="featherless/fast-model", metadata={})]

    monkeypatch.setattr(
        "message_evidence_workstation.llm.router.ModelRouter.list_models_for_provider",
        fake_list_models_for_provider,
    )

    tab._refresh_models()
    qapp.processEvents()

    assert [model.id for model in tab._models_by_provider[PROVIDER_NIM]] == ["featherless/fast-model"]
    assert tab._models_by_provider[PROVIDER_GOOGLE] == []
    assert "Model lists refreshed (NIM 1)" in tab.model_list_status.text()
    assert "google: No Google model configured." in tab.model_list_status.text()

    conn.close()
