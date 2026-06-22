"""Qt embedding job smoke test against real workspace DB."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from message_evidence_workstation.config.paths import default_db_path
from message_evidence_workstation.config.settings import load_settings
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.repositories import get_latest_dataset
from message_evidence_workstation.diagnostics.trace_log import install_diagnostics, trace
from message_evidence_workstation.embeddings.index_jobs import IndexBuildResult
from message_evidence_workstation.embeddings.model_registry import get_model_spec
from message_evidence_workstation.ui.embedding_worker import EmbeddingJobSpec, run_embedding_job


def main() -> int:
    install_diagnostics()
    app = QApplication(sys.argv)
    db_path = default_db_path()
    conn = connect(db_path)
    dataset = get_latest_dataset(conn)
    conn.close()
    if dataset is None:
        print("no dataset")
        return 1
    settings = load_settings()
    spec = get_model_spec(settings.embedding_model)
    if spec is None:
        print("bad model")
        return 1

    holder: dict[str, object] = {}

    def on_success(result: object) -> None:
        trace("qt_smoke", "on_success", result_type=type(result).__name__)
        holder["result"] = result
        app.quit()

    def on_error(exc: BaseException) -> None:
        trace("qt_smoke", "on_error", error=str(exc))
        holder["error"] = exc
        app.quit()

    # Dummy parent on main thread
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    job = EmbeddingJobSpec(
        job_type="message_index",
        db_path=db_path,
        dataset_id=dataset.dataset_id,
        adapter_key=spec.adapter_key,
        model_id=spec.model_id,
        force_restart=True,
    )
    trace("qt_smoke", "submit")
    run_embedding_job(parent, job, on_success=on_success, on_error=on_error)

    QTimer.singleShot(600_000, app, app.quit)
    code = app.exec()
    trace("qt_smoke", "exec_done", code=code, holder=repr(holder)[:500])
    print("holder", holder)
    if "error" in holder:
        return 2
    result = holder.get("result")
    if isinstance(result, IndexBuildResult):
        return 0 if result.success else 3
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
