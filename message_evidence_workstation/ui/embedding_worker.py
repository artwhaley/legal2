"""Dedicated background thread for embedding model load and index builds.

PyTorch / sentence-transformers must load and run on the same non-UI thread.
Use a plain ``threading.Thread`` — NOT ``QThread``. Mixing PyTorch with QThread
causes STATUS_STACK_BUFFER_OVERRUN (0xC0000409) on Windows during teardown.
"""

from __future__ import annotations

import queue
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from message_evidence_workstation.diagnostics.trace_log import trace
from message_evidence_workstation.embeddings.adapters import EmbeddingAdapter, EmbeddingAdapterInfo


class _EmbeddingDeliveryBridge(QObject):
    """Marshals embedding worker results onto the parent QObject thread."""

    succeeded = Signal(object, object, object)
    errored = Signal(object, object, object)


_delivery_bridges: weakref.WeakKeyDictionary[QObject, _EmbeddingDeliveryBridge] = (
    weakref.WeakKeyDictionary()
)


def _delivery_bridge(parent: QObject) -> _EmbeddingDeliveryBridge:
    bridge = _delivery_bridges.get(parent)
    if bridge is None:
        bridge = _EmbeddingDeliveryBridge(parent)
        bridge.succeeded.connect(_handle_delivery_success)
        bridge.errored.connect(_handle_delivery_error)
        _delivery_bridges[parent] = bridge
    return bridge


def _handle_delivery_success(parent: QObject, callback: Callable[[Any], None], result: object) -> None:
    _deliver_success(parent, callback, result)


def _handle_delivery_error(
    parent: QObject, callback: Callable[[BaseException], None], exc: BaseException
) -> None:
    _deliver_error(parent, callback, exc)


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
    embedding_selectivity: str = "balanced"
    chunking_config: dict[str, Any] = field(default_factory=dict)
    harness_user_query: str = ""
    harness_strategy_summary: str = ""
    harness_extra_queries: list[str] = field(default_factory=list)


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
        effective_dataset_id = spec.dataset_id if spec.dataset_id > 0 else None
        logger = ProcessLogger(conn, log_bus=get_log_bus(), dataset_id=effective_dataset_id)
        logger.info(
            component="ui.embedding_worker",
            operation="job_start",
            message=f"Embedding job started: {spec.job_type}",
            details={"job_type": spec.job_type, "model_id": spec.model_id},
            dataset_id=effective_dataset_id,
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
                chunking_config=spec.chunking_config,
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
                        selectivity=spec.embedding_selectivity,
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
                        selectivity=spec.embedding_selectivity,
                    )
                )
            return vector_hits
        raise ValueError(f"Unknown embedding job type: {spec.job_type}")
    finally:
        conn.close()


def _deliver_success(parent: QObject, callback: Callable[[Any], None], result: Any) -> None:
    from message_evidence_workstation.ui.ui_callback_watchdog import run_ui_callback

    trace("embedding_worker", "deliver_success_ui", result_type=type(result).__name__)
    try:
        run_ui_callback("embedding_worker.on_success", lambda: callback(result))
    except BaseException as exc:
        trace("embedding_worker", "on_success_exception", error=str(exc))


def _deliver_error(parent: QObject, callback: Callable[[BaseException], None], exc: BaseException) -> None:
    from message_evidence_workstation.ui.ui_callback_watchdog import run_ui_callback

    trace("embedding_worker", "deliver_error_ui", error=str(exc))
    try:
        run_ui_callback("embedding_worker.on_error", lambda: callback(exc))
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
            _delivery_bridge(work.parent).errored.emit(work.parent, work.on_error, exc)
            continue
        trace("embedding_worker", "run_job_success", job_type=work.spec.job_type)
        _delivery_bridge(work.parent).succeeded.emit(work.parent, work.on_success, result)


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
