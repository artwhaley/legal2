"""Application entry point."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from message_evidence_workstation.app_bootstrap import StartupLoadOptions, bootstrap_app
from message_evidence_workstation.diagnostics.trace_log import install_diagnostics, trace
from message_evidence_workstation.ui.main_window import MainWindow


def main() -> int:
    trace_path = install_diagnostics()
    trace("app", "main_enter", trace_path=str(trace_path))

    app = QApplication(sys.argv)
    app.setApplicationName("Message Evidence Workstation")

    dataset_path: Path | None = None
    db_path: Path | None = None
    reload_dataset = False
    with_embedding = False
    args = sys.argv[1:]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--dataset" and index + 1 < len(args):
            dataset_path = Path(args[index + 1])
            index += 2
            continue
        if arg == "--db" and index + 1 < len(args):
            db_path = Path(args[index + 1])
            index += 2
            continue
        if arg == "--workspace" and index + 1 < len(args):
            db_path = Path(args[index + 1])
            index += 2
            continue
        if arg == "--reload-dataset":
            reload_dataset = True
            index += 1
            continue
        if arg == "--with-embedding":
            with_embedding = True
            index += 1
            continue
        index += 1

    startup_load = None
    if dataset_path is not None:
        startup_load = StartupLoadOptions(
            dataset_path=dataset_path,
            reload=reload_dataset,
            skip_embedding=not with_embedding,
        )

    context = bootstrap_app(db_path=db_path, startup_load=startup_load)
    window = MainWindow(context, startup_load=startup_load)
    window.show()
    app.processEvents()
    trace("app", "exec_begin")
    code = app.exec()
    trace("app", "exec_end", exit_code=code)
    return code


if __name__ == "__main__":
    sys.exit(main())
