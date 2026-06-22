"""Minimal: sqlite-vec insert on QThread."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget


class Worker(QObject):
    done = Signal(str)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            from message_evidence_workstation.config.paths import default_db_path
            from message_evidence_workstation.db.connection import connect
            from message_evidence_workstation.db.repositories import get_latest_dataset
            from message_evidence_workstation.embeddings.adapters import create_adapter
            from message_evidence_workstation.embeddings.index_jobs import build_message_embedding_index
            from message_evidence_workstation.embeddings.model_registry import get_model_spec
            from message_evidence_workstation.config.settings import load_settings
            from message_evidence_workstation.logging_ui.process_log import ProcessLogger

            db_path = default_db_path()
            conn = connect(db_path)
            logger = ProcessLogger(conn, log_bus=None)
            dataset = get_latest_dataset(conn)
            settings = load_settings()
            spec = get_model_spec(settings.embedding_model)
            assert spec is not None and dataset is not None
            adapter = create_adapter(spec.adapter_key, spec.model_id)
            info = adapter.load()
            result = build_message_embedding_index(
                conn,
                logger,
                dataset_id=dataset.dataset_id,
                adapter=adapter,
                adapter_info=info,
            )
            conn.close()
            self.done.emit(str(result))
        except Exception as exc:
            self.failed.emit(repr(exc))


def main() -> int:
    app = QApplication(sys.argv)
    parent = QWidget()
    thread = QThread(parent)
    worker = Worker()
    worker.moveToThread(thread)
    thread.start()

    def finish(msg: str) -> None:
        print(msg)
        app.quit()

    worker.done.connect(finish, Qt.ConnectionType.QueuedConnection)
    worker.failed.connect(finish, Qt.ConnectionType.QueuedConnection)
    from PySide6.QtCore import QMetaObject

    QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
