"""Dataset load pipeline for the Load Dataset tab and CLI startup."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from message_evidence_workstation.db.evidence_blocks import ensure_uncategorized_category
from message_evidence_workstation.db.printable_artifacts import ensure_default_printable_artifact_group
from message_evidence_workstation.db.repositories import get_latest_dataset
from message_evidence_workstation.db.workspace import touch_workspace_updated
from message_evidence_workstation.domain.constants import IMPORT_VALIDITY_READY
from message_evidence_workstation.importers.normalized_loader import (
    DatasetLoadError,
    get_dataset_import_validity,
    load_normalized_dataset,
    mark_dataset_import_failed,
    mark_dataset_import_ready,
)
from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso

LARGEST_THREAD_WARNING_THRESHOLD = 5000
Narrator = Callable[[str], None]
CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[str, int, int], None]


@dataclass(slots=True)
class DatasetLoadResult:
    success: bool
    dataset_id: int | None = None
    import_succeeded: bool = False
    embedding_available: bool = False
    embedding_error: str | None = None
    error: str | None = None
    narration: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DatasetLoadRequest:
    dataset_path: Path
    reload: bool = False
    skip_import_if_existing: bool = True
    run_embedding: bool = True
    skip_embedding: bool = False


def _default_narrator() -> Narrator:
    return lambda _message: None


def _default_cancel_check() -> CancelCheck:
    return lambda: False


def _append_narration(
    narrator: Narrator,
    narration: list[str],
    message: str,
) -> None:
    line = f"[{utc_now_iso()}] {message}"
    narration.append(line)
    narrator(line)


def _largest_thread_watchdog(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    narrator: Narrator,
    narration: list[str],
) -> None:
    row = conn.execute(
        """
        SELECT source_thread_id, COUNT(*) AS message_count
        FROM message
        WHERE dataset_id = ?
        GROUP BY source_thread_id
        ORDER BY message_count DESC
        LIMIT 1
        """,
        (dataset_id,),
    ).fetchone()
    if row is None:
        return
    count = int(row["message_count"] or 0)
    if count <= LARGEST_THREAD_WARNING_THRESHOLD:
        return
    thread_id = str(row["source_thread_id"])
    _append_narration(
        narrator,
        narration,
        (
            f"Warning: thread '{thread_id}' has {count} messages; "
            "transcript uses virtualized scrolling."
        ),
    )


def run_import_pipeline(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    request: DatasetLoadRequest,
    *,
    narrator: Narrator | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DatasetLoadResult:
    """Run workspace import and post-import steps (through default groups)."""
    narrate = narrator or _default_narrator()
    cancelled = cancel_check or _default_cancel_check()
    narration: list[str] = []
    dataset_id: int | None = None

    def _progress(phase: str, lines_read: int, lines_written: int) -> None:
        if progress_callback is not None:
            progress_callback(phase, lines_read, lines_written)
        _append_narration(
            narrate,
            narration,
            f"{phase}: read {lines_read}, wrote {lines_written}",
        )

    try:
        _append_narration(narrate, narration, "Step 1/6: Workspace database is open.")
        if cancelled():
            return DatasetLoadResult(success=False, error="Cancelled", narration=narration)

        _append_narration(narrate, narration, "Step 2/6: Schema migration complete (idempotent).")
        if cancelled():
            return DatasetLoadResult(success=False, error="Cancelled", narration=narration)

        existing = get_latest_dataset(conn)
        skip_import = False
        if existing is not None and request.skip_import_if_existing and not request.reload:
            if get_dataset_import_validity(conn, existing.dataset_id) == IMPORT_VALIDITY_READY:
                dataset_id = existing.dataset_id
                skip_import = True
                _append_narration(
                    narrate,
                    narration,
                    f"Step 3/6: Using existing dataset (dataset_id={dataset_id}).",
                )

        if not skip_import:
            _append_narration(
                narrate,
                narration,
                f"Step 3/6: Streaming import from {request.dataset_path}…",
            )
            with logger.batch() as batch_log:
                batch_log.info(
                    component="dataset_load_pipeline",
                    operation="import_start",
                    message="Starting streaming dataset import",
                    details={"dataset_path": str(request.dataset_path), "reload": request.reload},
                )
            dataset_id = load_normalized_dataset(
                conn,
                logger,
                request.dataset_path,
                reload=request.reload,
                progress_callback=_progress,
                run_post_import_steps=False,
            )
            logger.dataset_id = dataset_id
            if cancelled():
                return DatasetLoadResult(
                    success=False,
                    dataset_id=dataset_id,
                    error="Cancelled",
                    narration=narration,
                )

            _append_narration(narrate, narration, "Step 4/6: Rebuilding FTS index…")
            from message_evidence_workstation.search.fts import rebuild_message_fts

            rebuild_message_fts(
                conn,
                logger,
                dataset_id,
                progress_callback=progress_callback,
            )
            if cancelled():
                return DatasetLoadResult(
                    success=False,
                    dataset_id=dataset_id,
                    error="Cancelled",
                    narration=narration,
                )

            _append_narration(narrate, narration, "Step 5/6: Rebuilding spellfix index…")
            from message_evidence_workstation.search.spellfix import rebuild_spellfix_for_dataset

            rebuild_spellfix_for_dataset(
                conn,
                logger,
                dataset_id,
                progress_callback=progress_callback,
            )
            if cancelled():
                return DatasetLoadResult(
                    success=False,
                    dataset_id=dataset_id,
                    error="Cancelled",
                    narration=narration,
                )

        assert dataset_id is not None
        _append_narration(narrate, narration, "Step 6/6: Ensuring default categories and groups…")
        ensure_uncategorized_category(conn, logger, dataset_id)
        ensure_default_printable_artifact_group(conn, logger, dataset_id)
        mark_dataset_import_ready(conn, dataset_id)
        _largest_thread_watchdog(conn, dataset_id, narrator=narrate, narration=narration)
        touch_workspace_updated(conn)

        logger.info(
            component="dataset_load_pipeline",
            operation="import_complete",
            message="Dataset import pipeline completed",
            details={"dataset_id": dataset_id},
            dataset_id=dataset_id,
        )
        return DatasetLoadResult(
            success=True,
            dataset_id=dataset_id,
            import_succeeded=True,
            narration=narration,
        )
    except DatasetLoadError as exc:
        mark_dataset_import_failed(conn, dataset_id, str(exc))
        _append_narration(narrate, narration, f"Import failed: {exc}")
        logger.error(
            component="dataset_load_pipeline",
            operation="import_failed",
            message=str(exc),
            exc=exc,
            dataset_id=dataset_id,
        )
        return DatasetLoadResult(
            success=False,
            dataset_id=dataset_id,
            error=str(exc),
            narration=narration,
        )
    except Exception as exc:
        mark_dataset_import_failed(conn, dataset_id, str(exc))
        _append_narration(narrate, narration, f"Import failed: {exc}")
        logger.error(
            component="dataset_load_pipeline",
            operation="import_failed",
            message="Unexpected import failure",
            exc=exc,
            dataset_id=dataset_id,
        )
        return DatasetLoadResult(
            success=False,
            dataset_id=dataset_id,
            error=str(exc),
            narration=narration,
        )


def run_embedding_pipeline(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    dataset_id: int,
    *,
    narrator: Narrator | None = None,
    cancel_check: CancelCheck | None = None,
    adapter: Any | None = None,
    adapter_info: Any | None = None,
) -> DatasetLoadResult:
    """Auto-embedding phase using T62 resume-aware index jobs."""
    narrate = narrator or _default_narrator()
    cancelled = cancel_check or _default_cancel_check()
    narration: list[str] = []
    settings = load_settings()

    if cancelled():
        return DatasetLoadResult(
            success=True,
            dataset_id=dataset_id,
            import_succeeded=True,
            embedding_available=False,
            embedding_error="Cancelled",
            narration=narration,
        )

    _append_narration(narrate, narration, "Embedding: preloading model…")
    try:
        if adapter is None or adapter_info is None:
            from message_evidence_workstation.embeddings.adapters import create_adapter
            from message_evidence_workstation.embeddings.model_registry import get_model_spec

            model_id = settings.embedding_model
            spec = get_model_spec(model_id)
            if spec is None:
                raise RuntimeError(f"Unknown embedding model: {model_id}")
            adapter = create_adapter(spec.adapter_key, spec.model_id)
            adapter_info = adapter.load()

        if cancelled():
            return DatasetLoadResult(
                success=True,
                dataset_id=dataset_id,
                import_succeeded=True,
                embedding_available=False,
                embedding_error="Cancelled",
                narration=narration,
            )

        _append_narration(
            narrate,
            narration,
            f"Embedding: model ready ({adapter_info.model_name}, {adapter_info.dimensions} dims).",
        )

        from message_evidence_workstation.embeddings.sqlite_vec_backend import (
            record_validation_status,
            validate_sqlite_vec,
        )

        _append_narration(narrate, narration, "Embedding: validating sqlite-vec…")
        validation = validate_sqlite_vec(conn, logger, dimensions=adapter_info.dimensions)
        record_validation_status(
            conn,
            logger,
            dataset_id=dataset_id,
            result=validation,
        )
        if not validation.success:
            raise RuntimeError(validation.message)

        from message_evidence_workstation.embeddings.index_jobs import (
            build_chunk_embedding_index,
            build_message_embedding_index,
        )

        _append_narration(narrate, narration, "Embedding: building message vectors (resume-aware)…")
        started = time.perf_counter()
        message_result = build_message_embedding_index(
            conn,
            logger,
            dataset_id=dataset_id,
            adapter=adapter,
            adapter_info=adapter_info,
        )
        if not message_result.success:
            raise RuntimeError(message_result.error or "Message embedding index failed")

        from message_evidence_workstation.embeddings.chunking import ChunkingConfig

        chunking = ChunkingConfig(
            max_chars=int(settings.chunking.get("max_chars", 1200)),
            desired_average_chunk_messages=int(
                settings.chunking.get("desired_average_chunk_messages", 8)
            ),
            session_gap_hours=float(settings.chunking.get("session_gap_hours", 4)),
            use_semantic_boundaries=bool(settings.chunking.get("use_semantic_boundaries", True)),
            split_on_date_change=bool(settings.chunking.get("split_on_date_change", True)),
        )

        _append_narration(narrate, narration, "Embedding: building chunk vectors (resume-aware)…")
        chunk_result = build_chunk_embedding_index(
            conn,
            logger,
            dataset_id=dataset_id,
            adapter=adapter,
            adapter_info=adapter_info,
            chunking_config=chunking,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if not chunk_result.success:
            raise RuntimeError(chunk_result.error or "Chunk embedding index failed")

        _append_narration(
            narrate,
            narration,
            (
                f"Embedding complete: messages {message_result.count}/{message_result.total_target}, "
                f"chunks {chunk_result.count}/{chunk_result.total_target}, "
                f"elapsed {elapsed_ms}ms."
            ),
        )
        logger.info(
            component="dataset_load_pipeline",
            operation="embedding_complete",
            message="Auto-embedding pipeline completed",
            details={
                "message_count": message_result.count,
                "chunk_count": chunk_result.count,
                "elapsed_ms": elapsed_ms,
            },
            dataset_id=dataset_id,
        )
        return DatasetLoadResult(
            success=True,
            dataset_id=dataset_id,
            import_succeeded=True,
            embedding_available=True,
            narration=narration,
        )
    except Exception as exc:
        _append_narration(
            narrate,
            narration,
            f"Embedding unavailable: {exc}. Re-run from Settings or Retry here.",
        )
        logger.warning(
            component="dataset_load_pipeline",
            operation="embedding_failed",
            message=str(exc),
            exc=exc,
            dataset_id=dataset_id,
        )
        return DatasetLoadResult(
            success=True,
            dataset_id=dataset_id,
            import_succeeded=True,
            embedding_available=False,
            embedding_error=str(exc),
            narration=narration,
        )


def run_dataset_load_pipeline(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    request: DatasetLoadRequest,
    *,
    narrator: Narrator | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    adapter: Any | None = None,
    adapter_info: Any | None = None,
) -> DatasetLoadResult:
    """Full load pipeline: import through optional auto-embedding."""
    import_result = run_import_pipeline(
        conn,
        logger,
        request,
        narrator=narrator,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    if not import_result.success or import_result.dataset_id is None:
        return import_result

    if not request.run_embedding or request.skip_embedding:
        skip_reason = "skipped by request" if request.skip_embedding else "disabled"
        narration = list(import_result.narration)
        if narrator is not None:
            narrator(f"[{utc_now_iso()}] Embedding {skip_reason}; opening app without vector search.")
        narration.append(f"[{utc_now_iso()}] Embedding {skip_reason}.")
        return DatasetLoadResult(
            success=True,
            dataset_id=import_result.dataset_id,
            import_succeeded=True,
            embedding_available=False,
            narration=narration,
        )

    embed_result = run_embedding_pipeline(
        conn,
        logger,
        import_result.dataset_id,
        narrator=narrator,
        cancel_check=cancel_check,
        adapter=adapter,
        adapter_info=adapter_info,
    )
    return DatasetLoadResult(
        success=True,
        dataset_id=import_result.dataset_id,
        import_succeeded=True,
        embedding_available=embed_result.embedding_available,
        embedding_error=embed_result.embedding_error,
        narration=[*import_result.narration, *embed_result.narration],
    )


class PipelineCancelToken:
    """Thread-safe cancel flag for background pipeline workers."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        self._event.clear()
