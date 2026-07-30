"""Stable headless launcher for the Server-First V1 control plane."""

from __future__ import annotations

import argparse
from pathlib import Path

from server.config_service import ConfigurationService


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Server-First V1 message evidence server")
    parser.add_argument("--state-dir", default=None, help="Optional control-plane state directory")
    args = parser.parse_args(argv)
    service = ConfigurationService(Path(args.state_dir) if args.state_dir else None)
    service.startup()
    listener = service.maybe_snapshot()
    from server.app import create_app
    import uvicorn

    app = create_app(config_service=service)
    # The app lifespan owns startup/close; this one-process invocation reads
    # the active listener only after bootstrap/configuration validation.
    uvicorn.run(app, host=listener.host if listener else "127.0.0.1", port=listener.port if listener else 8710, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
