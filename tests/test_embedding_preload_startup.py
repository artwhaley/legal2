import sys
from pathlib import Path
from types import SimpleNamespace

from message_evidence_workstation.logging_ui.log_bus import get_log_bus
from message_evidence_workstation.embeddings.adapters import SentenceTransformerAdapter
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.embedding_worker import EmbeddingJobSpec, _execute
from message_evidence_workstation.ui.home_tab import HomeTab


def test_load_only_embedding_preload_does_not_open_workspace_db(monkeypatch) -> None:
    monkeypatch.setattr(
        "message_evidence_workstation.db.connection.connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("load-only preload should not open sqlite")),
    )

    class _FakeAdapter:
        def load(self):
            class _Info:
                model_name = "test-model"
                dimensions = 384
                normalization_mode = "cosine"

            return _Info()

    monkeypatch.setattr(
        "message_evidence_workstation.embeddings.adapters.create_adapter",
        lambda *_args, **_kwargs: _FakeAdapter(),
    )

    result = _execute(
        EmbeddingJobSpec(
            job_type="load",
            db_path=Path("ignored.evw"),
            dataset_id=0,
            adapter_key="sentence_transformer",
            model_id="test-model",
        )
    )

    assert result.model_name == "test-model"
    assert result.dimensions == 384


def test_home_tab_autorun_skips_redundant_preload(qapp, tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "message_evidence_workstation.ui.home_tab.preload_embedding_model",
        lambda *args, **kwargs: calls.append("preload") or True,
    )

    conn = __import__("message_evidence_workstation.db.connection", fromlist=["connect"]).connect(
        tmp_path / "ui.evw"
    )
    logger = ProcessLogger(conn, log_bus=get_log_bus())
    tab = HomeTab(
        conn,
        logger,
        db_path=tmp_path / "ui.evw",
        initial_dataset_path=Path(__file__).parent / "fixtures" / "sample_dataset",
        skip_embedding_on_load=False,
        auto_run_on_show=True,
    )
    tab.show()
    qapp.processEvents()

    assert calls == []
    tab.close()
    conn.close()


def test_home_tab_regular_startup_does_not_preload_embedding_model(qapp, tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "message_evidence_workstation.ui.home_tab.preload_embedding_model",
        lambda *args, **kwargs: calls.append("preload") or True,
    )

    conn = __import__("message_evidence_workstation.db.connection", fromlist=["connect"]).connect(
        tmp_path / "ui.evw"
    )
    logger = ProcessLogger(conn, log_bus=get_log_bus())
    tab = HomeTab(
        conn,
        logger,
        db_path=tmp_path / "ui.evw",
        auto_run_on_show=False,
    )
    tab.show()
    qapp.processEvents()

    assert calls == []
    tab.close()
    conn.close()


def test_sentence_transformer_adapter_loads_from_local_cache_only(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeModel:
        model_version = "local-test"

        def encode(self, texts, normalize_embeddings=True):
            return [[0.1, 0.2, 0.3] for _ in texts]

    class _FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs) -> None:
            captured["model_name"] = model_name
            captured["kwargs"] = kwargs

        def encode(self, texts, normalize_embeddings=True):
            return _FakeModel().encode(texts, normalize_embeddings=normalize_embeddings)

        @property
        def model_version(self):
            return _FakeModel.model_version

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer),
    )

    info = SentenceTransformerAdapter("sentence-transformers/all-MiniLM-L6-v2").load()

    assert captured["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert captured["kwargs"] == {"local_files_only": True}
    assert info.dimensions == 3
