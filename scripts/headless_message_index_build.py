"""Build message embedding index without Qt — isolates UI vs native/model crashes."""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--dataset-id", type=int, default=None)
    parser.add_argument("--max-batches", type=int, default=0, help="0 = no limit")
    parser.add_argument("--force-restart", action="store_true")
    args = parser.parse_args()

    from message_evidence_workstation.config.paths import default_db_path
    from message_evidence_workstation.config.settings import load_settings
    from message_evidence_workstation.db.connection import connect
    from message_evidence_workstation.db.repositories import get_latest_dataset
    from message_evidence_workstation.diagnostics.trace_log import trace
    from message_evidence_workstation.embeddings.adapters import create_adapter
    from message_evidence_workstation.embeddings.index_jobs import build_message_embedding_index
    from message_evidence_workstation.embeddings.model_registry import get_model_spec
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger

    db_path = args.db or default_db_path()
    trace("headless", "start", db=str(db_path))
    conn = connect(db_path)
    logger = ProcessLogger(conn, log_bus=None)
    dataset = get_latest_dataset(conn)
    dataset_id = args.dataset_id or (dataset.dataset_id if dataset else None)
    if dataset_id is None:
        print("No dataset in DB")
        return 1
    settings = load_settings()
    spec = get_model_spec(settings.embedding_model)
    if spec is None:
        print("Unknown model", settings.embedding_model)
        return 1
    trace("headless", "load_model", model=spec.model_id)
    adapter = create_adapter(spec.adapter_key, spec.model_id)
    info = adapter.load()
    trace("headless", "model_ready", dimensions=info.dimensions)

    if args.max_batches > 0:
        # Patch batch loop for smoke test
        import message_evidence_workstation.embeddings.index_jobs as jobs

        original_iter = jobs._iter_pending_message_batches
        seen = {"count": 0}

        def limited_iter(*a, **kw):
            for batch in original_iter(*a, **kw):
                seen["count"] += 1
                if seen["count"] > args.max_batches:
                    return
                yield batch

        jobs._iter_pending_message_batches = limited_iter  # type: ignore[assignment]

    t0 = time.perf_counter()
    try:
        result = build_message_embedding_index(
            conn,
            logger,
            dataset_id=dataset_id,
            adapter=adapter,
            adapter_info=info,
            force_restart=args.force_restart,
        )
    except Exception:
        trace("headless", "exception", traceback=traceback.format_exc())
        raise
    trace(
        "headless",
        "done",
        success=result.success,
        count=result.count,
        error=result.error,
        elapsed_s=round(time.perf_counter() - t0, 2),
    )
    print(result)
    return 0 if result.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
