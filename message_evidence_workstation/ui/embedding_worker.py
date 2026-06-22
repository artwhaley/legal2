"""Dedicated background thread for embedding model load and index builds.

PyTorch / sentence-transformers must load and run on the same non-UI thread.
Use a plain ``threading.Thread`` — NOT ``QThread``. Mixing PyTorch with QThread
causes STATUS_STACK_BUFFER_OVERRUN (0xC0000409) on Windows during teardown.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer

from message_evidence_workstation.diagnostics.trace_log import trace
from message_evidence_workstation.embeddings.adapters import EmbeddingAdapter, EmbeddingAdapterInfo


@dataclass(slots=True)
class EmbeddingLoadResult:
    model_name: str
    dimensions: int
    normalization_mode: str


@dataclass(slots=True)
class EmbeddingJobSpec:
    job_type: str  # load | message_index | chunk_index | vector_search | conversational_search
    db_path: Path
    dataset_id: int
    adapter_key: str
    model_id: str
    force_restart: bool = False
    vector_query: str = ""
    use_message_vectors: bool = False
    use_chunk_vectors: bool = False
    harness_user_query: str = ""
    harness_strategy_summary: str = ""
    harness_extra_queries: list[str] = field(default_factory=list)
    sort_index_by_message: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _QueuedWork:
    spec: EmbeddingJobSpec
    on_success: Callable[[Any], None]
    on_error: Callable[[BaseException], None]
    parent: QObject


_STOP = object()
_adapter: EmbeddingAdapter | None = None
_adapter_info: EmbeddingAdapterInfo | None = None
_loaded_model_id: str | None = None
_job_queue: queue.Queue[_QueuedWork | object] = queue.Queue()
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None


def _ensure_adapter(
    adapter_key: str,
    model_id: str,
    logger,
) -> tuple[EmbeddingAdapter, EmbeddingAdapterInfo]:
    global _adapter, _adapter_info, _loaded_model_id
    if (
        _adapter is not None
        and _adapter_info is not None
        and _loaded_model_id == model_id
    ):
        logger.info(
            component="ui.embedding_worker",
            operation="reuse_loaded_model",
            message=f"Reusing embedding model {model_id}",
        )
        return _adapter, _adapter_info

    from message_evidence_workstation.embeddings.adapters import create_adapter

    logger.info(
        component="ui.embedding_worker",
        operation="load_model_start",
        message=f"Loading embedding model {model_id}…",
    )
    adapter = create_adapter(adapter_key, model_id)
    info = adapter.load()
    _adapter = adapter
    _adapter_info = info
    _loaded_model_id = model_id
    logger.info(
        component="ui.embedding_worker",
        operation="load_model_complete",
        message=f"Embedding model ready: {info.model_name} ({info.dimensions} dims)",
        details={"model_name": info.model_name, "dimensions": info.dimensions},
    )
    return adapter, info


def _execute(spec: EmbeddingJobSpec) -> Any:
    from message_evidence_workstation.db.connection import connect
    from message_evidence_workstation.embeddings.index_jobs import (
        build_chunk_embedding_index,
        build_message_embedding_index,
    )
    from message_evidence_workstation.logging_ui.log_bus import get_log_bus
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger

    conn = connect(spec.db_path)
    try:
        logger = ProcessLogger(conn, log_bus=get_log_bus(), dataset_id=spec.dataset_id)
        logger.info(
            component="ui.embedding_worker",
            operation="job_start",
            message=f"Embedding job started: {spec.job_type}",
            details={"job_type": spec.job_type, "model_id": spec.model_id},
            dataset_id=spec.dataset_id,
        )
        adapter, info = _ensure_adapter(spec.adapter_key, spec.model_id, logger)
        if spec.job_type == "load":
            return EmbeddingLoadResult(
                model_name=info.model_name,
                dimensions=info.dimensions,
                normalization_mode=info.normalization_mode,
            )
        if spec.job_type == "message_index":
            return build_message_embedding_index(
                conn,
                logger,
                dataset_id=spec.dataset_id,
                adapter=adapter,
                adapter_info=info,
                force_restart=spec.force_restart,
            )
        if spec.job_type == "chunk_index":
            return build_chunk_embedding_index(
                conn,
                logger,
                dataset_id=spec.dataset_id,
                adapter=adapter,
                adapter_info=info,
                force_restart=spec.force_restart,
            )
        if spec.job_type == "vector_search":
            from message_evidence_workstation.search.embedding_search import (
                search_chunk_embeddings,
                search_message_embeddings,
            )
            from message_evidence_workstation.search.result_models import SearchHit

            vector_hits: list[SearchHit] = []
            if spec.use_message_vectors:
                vector_hits.extend(
                    search_message_embeddings(
                        conn,
                        logger,
                        dataset_id=spec.dataset_id,
                        query=spec.vector_query,
                        model_name=spec.model_id,
                        adapter=adapter,
                    )
                )
            if spec.use_chunk_vectors:
                vector_hits.extend(
                    search_chunk_embeddings(
                        conn,
                        logger,
                        dataset_id=spec.dataset_id,
                        query=spec.vector_query,
                        model_name=spec.model_id,
                        adapter=adapter,
                    )
                )
            return vector_hits
        if spec.job_type == "conversational_search":
            from message_evidence_workstation.config.settings import nim_settings_for_client
            from message_evidence_workstation.nim.client import NimClient
            from message_evidence_workstation.search.tool_runner import (
                SearchPlannerPlan,
                ToolRunnerDeps,
                execute_full_search_harness,
            )

            nim = nim_settings_for_client()
            nim_client = NimClient(nim) if nim.model else None
            plan = SearchPlannerPlan(
                strategy_summary=spec.harness_strategy_summary or "Full search harness",
                extra_search_queries=list(spec.harness_extra_queries),
            )
            deps = ToolRunnerDeps(
                nim_client=nim_client,
                embedding_adapter=adapter,
                embedding_model_name=info.model_name,
            )
            return execute_full_search_harness(
                conn,
                logger,
                dataset_id=spec.dataset_id,
                user_query=spec.harness_user_query,
                plan=plan,
                deps=deps,
                sort_index_by_message=dict(spec.sort_index_by_message),
            )
        raise ValueError(f"Unknown embedding job type: {spec.job_type}")
    finally:
        conn.close()


def _deliver_success(parent: QObject, callback: Callable[[Any], None], result: Any) -> None:
    trace("embedding_worker", "deliver_success_ui", result_type=type(result).__name__)
    try:
        callback(result)
    except BaseException as exc:
        trace("embedding_worker", "on_success_exception", error=str(exc))


def _deliver_error(parent: QObject, callback: Callable[[BaseException], None], exc: BaseException) -> None:
    trace("embedding_worker", "deliver_error_ui", error=str(exc))
    try:
        callback(exc)
    except BaseException as callback_exc:
        trace("embedding_worker", "on_error_exception", error=str(callback_exc))


def _worker_loop() -> None:
    while True:
        item = _job_queue.get()
        if item is _STOP:
            trace("embedding_worker", "worker_stop")
            return
        work = item
        assert isinstance(work, _QueuedWork)
        trace("embedding_worker", "run_job_enter", job_type=work.spec.job_type)
        try:
            result = _execute(work.spec)
        except BaseException as exc:
            trace("embedding_worker", "run_job_exception", error=str(exc))
            QTimer.singleShot(
                0,
                work.parent,
                lambda w=work, e=exc: _deliver_error(w.parent, w.on_error, e),
            )
            continue
        trace("embedding_worker", "run_job_success", job_type=work.spec.job_type)
        QTimer.singleShot(
            0,
            work.parent,
            lambda w=work, r=result: _deliver_success(w.parent, w.on_success, r),
        )


def _ensure_worker_thread() -> None:
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="mew-embedding",
            daemon=True,
        )
        _worker_thread.start()
        trace("embedding_worker", "worker_thread_started")


def invalidate_embedding_model_cache(parent: QObject | None = None) -> None:
    global _adapter, _adapter_info, _loaded_model_id
    _adapter = None
    _adapter_info = None
    _loaded_model_id = None
    trace("embedding_worker", "adapter_cache_cleared")


def run_embedding_job(
    parent: QObject | None,
    spec: EmbeddingJobSpec,
    *,
    on_success: Callable[[Any], None],
    on_error: Callable[[BaseException], None],
) -> None:
    if parent is None:
        raise ValueError("run_embedding_job requires a QObject parent for UI-thread delivery")
    _ensure_worker_thread()
    trace("embedding_worker", "enqueue", job_type=spec.job_type, queue_depth=_job_queue.qsize())
    _job_queue.put(_QueuedWork(spec, on_success, on_error, parent))


def preload_embedding_model(
    parent: QObject,
    *,
    db_path: Path,
    dataset_id: int | None = None,
    model_id: str | None = None,
    on_success: Callable[[EmbeddingLoadResult], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> bool:
    """Queue embedding model load on the dedicated worker thread (e.g. at app startup)."""
    from message_evidence_workstation.config.settings import load_settings
    from message_evidence_workstation.embeddings.model_registry import get_model_spec

    resolved_model = model_id or load_settings().embedding_model
    spec = get_model_spec(resolved_model)
    if spec is None:
        return False
    job = EmbeddingJobSpec(
        job_type="load",
        db_path=db_path,
        dataset_id=dataset_id or 0,
        adapter_key=spec.adapter_key,
        model_id=spec.model_id,
    )

    def _success(result: object) -> None:
        if on_success is not None:
            on_success(result)  # type: ignore[arg-type]

    def _error(exc: BaseException) -> None:
        if on_error is not None:
            on_error(exc)

    run_embedding_job(parent, job, on_success=_success, on_error=_error)
    return True
