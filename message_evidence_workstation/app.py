"""Application entry point."""

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QApplication

from message_evidence_workstation.app_bootstrap import StartupLoadOptions, bootstrap_app
from message_evidence_workstation.diagnostics.trace_log import install_diagnostics, trace
from message_evidence_workstation.ui.main_window import MainWindow


@dataclass(slots=True)
class CliOptions:
    dataset_path: Path | None = None
    db_path: Path | None = None
    reload_dataset: bool = False
    skip_embedding: bool = False


def parse_cli_options(args: list[str]) -> CliOptions:
    options = CliOptions()
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--dataset" and index + 1 < len(args):
            options.dataset_path = Path(args[index + 1])
            index += 2
            continue
        if arg == "--db" and index + 1 < len(args):
            options.db_path = Path(args[index + 1])
            index += 2
            continue
        if arg == "--workspace" and index + 1 < len(args):
            options.db_path = Path(args[index + 1])
            index += 2
            continue
        if arg == "--reload-dataset":
            options.reload_dataset = True
            index += 1
            continue
        if arg == "--skip-embedding":
            options.skip_embedding = True
            index += 1
            continue
        if arg == "--with-embedding":
            options.skip_embedding = False
            index += 1
            continue
        index += 1
    return options


def main() -> int:
    trace_path = install_diagnostics()
    trace("app", "main_enter", trace_path=str(trace_path))

    app = QApplication(sys.argv)
    app.setApplicationName("Message Evidence Workstation")

    options = parse_cli_options(sys.argv[1:])

    startup_load = None
    if options.dataset_path is not None:
        startup_load = StartupLoadOptions(
            dataset_path=options.dataset_path,
            reload=options.reload_dataset,
            skip_embedding=options.skip_embedding,
        )

    context = bootstrap_app(db_path=options.db_path, startup_load=startup_load)
    window = MainWindow(context, startup_load=startup_load)
    window.show()
    app.processEvents()
    trace("app", "exec_begin")
    code = app.exec()
    trace("app", "exec_end", exit_code=code)
    return code


if __name__ == "__main__":
    sys.exit(main())
