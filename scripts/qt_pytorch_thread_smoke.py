"""Minimal: PyTorch embed on QThread (no sqlite-vec)."""
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
            from message_evidence_workstation.config.settings import load_settings
            from message_evidence_workstation.embeddings.adapters import create_adapter
            from message_evidence_workstation.embeddings.model_registry import get_model_spec

            settings = load_settings()
            spec = get_model_spec(settings.embedding_model)
            assert spec is not None
            adapter = create_adapter(spec.adapter_key, spec.model_id)
            adapter.load()
            vectors = adapter.embed_texts(["hello", "world", "test"])
            self.done.emit(f"ok {len(vectors)} x {len(vectors[0])}")
        except Exception as exc:
            self.failed.emit(str(exc))


def main() -> int:
    app = QApplication(sys.argv)
    parent = QWidget()
    thread = QThread(parent)
    worker = Worker()
    worker.moveToThread(thread)
    thread.start()

    def ok(msg: str) -> None:
        print("SUCCESS", msg)
        app.quit()

    def err(msg: str) -> None:
        print("ERROR", msg)
        app.quit()

    worker.done.connect(ok, Qt.ConnectionType.QueuedConnection)
    worker.failed.connect(err, Qt.ConnectionType.QueuedConnection)
    from PySide6.QtCore import QMetaObject

    QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
