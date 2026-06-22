"""Application entry point."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from message_evidence_workstation.app_bootstrap import bootstrap_app
from message_evidence_workstation.diagnostics.trace_log import install_diagnostics, trace
from message_evidence_workstation.ui.main_window import MainWindow


def main() -> int:
    trace_path = install_diagnostics()
    trace("app", "main_enter", trace_path=str(trace_path))

    app = QApplication(sys.argv)
    app.setApplicationName("Message Evidence Workstation")

    dataset_path = None
    db_path = None
    reload_dataset = False
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
        index += 1

    context = bootstrap_app(
        db_path=db_path,
        dataset_path=dataset_path,
        reload_dataset=reload_dataset,
    )
    window = MainWindow(context)
    window.show()
    trace("app", "exec_begin")
    code = app.exec()
    trace("app", "exec_end", exit_code=code)
    return code


if __name__ == "__main__":
    sys.exit(main())
