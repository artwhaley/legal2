"""Validated embedding-model lifecycle and stateless streamed workloads."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol

from fastapi.responses import StreamingResponse

from server.contracts import EmbeddingsRequest, parse_ndjson_event
from server.model_runtime import AccountingPersistenceFailed, WorkloadTooLarge
from server.observability import map_error
from server.resilience import FifoLimiter


class EmbeddingValidationError(ValueError):
    code = "MODEL_OUTPUT_INVALID"


class EmbeddingReconfiguring(RuntimeError):
    code = "EMBEDDING_RECONFIGURING"


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    model: str
    requested_revision: str
    artifact_fingerprint: str
    dimensions: int
    normalization: str
    profile_id: str


class EmbeddingBackend(Protocol):
    """Server-internal provider seam; the HTTP contract never depends on it."""

    async def prepare(self) -> EmbeddingProfile: ...
    async def encode(self, texts: list[str]) -> list[list[float]]: ...
    async def drain(self) -> None: ...
    def status(self) -> dict[str, Any]: ...
    async def close_async(self) -> None: ...
    def close(self) -> None: ...


class LocalSentenceTransformerBackend:
    """Local sentence-transformer execution with exact worker ownership."""

    def __init__(self, config, *, model: Any | None = None):
        if model is not None and config.worker_count != 1:
            raise ValueError("an injected embedding model can only back one worker replica")
        self.config = config
        self._provided_model = model
        self._models: list[Any] = []
        self._executor = ThreadPoolExecutor(
            max_workers=config.worker_count,
            thread_name_prefix="evw-embedding",
        )
        self._profile: EmbeddingProfile | None = None
        self._prepare_lock: asyncio.Lock | None = None
        self._model_queue: asyncio.Queue[int] | None = None
        self._sync_prepare_lock = threading.Lock()
        self._active_jobs = 0
        self._jobs_drained = asyncio.Event()
        self._jobs_drained.set()
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    def _load_model(self):
        if self._provided_model is not None:
            return self._provided_model
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(
            self.config.model_name,
            revision=self.config.model_revision or None,
            device=self.config.device,
        )

    @staticmethod
    def _fingerprint(model: Any) -> str:
        digest = hashlib.sha256()
        state = model.state_dict() if hasattr(model, "state_dict") else None
        if isinstance(state, dict):
            for name in sorted(state):
                value = state[name]
                digest.update(str(name).encode())
                digest.update(str(getattr(value, "dtype", "")).encode())
                digest.update(str(getattr(value, "shape", "")).encode())
                if hasattr(value, "detach"):
                    value = value.detach().cpu().contiguous().numpy().tobytes()
                elif hasattr(value, "tobytes"):
                    value = value.tobytes()
                digest.update(bytes(value))
        else:
            digest.update(f"{type(model).__module__}.{type(model).__qualname__}".encode())
            material = getattr(model, "artifact_fingerprint_material", None)
            if material is None:
                material = {
                    key: value
                    for key, value in vars(model).items()
                    if isinstance(value, (str, int, float, bool, type(None)))
                } if hasattr(model, "__dict__") else {}
            digest.update(json.dumps(material, sort_keys=True, default=str).encode())
        digest.update(str(getattr(model, "_modules", None)).encode())
        return digest.hexdigest()

    def _prepare_sync(self) -> EmbeddingProfile:
        with self._sync_prepare_lock:
            if self._profile is not None:
                return self._profile
            if self._closed:
                raise RuntimeError("embedding service is closed")
            models = [self._load_model() for _ in range(self.config.worker_count)]
            dimensions = [
                int(
                    model.get_embedding_dimension()
                    if hasattr(model, "get_embedding_dimension")
                    else model.get_sentence_embedding_dimension()
                )
                for model in models
            ]
            if not dimensions or len(set(dimensions)) != 1:
                raise RuntimeError("embedding replicas disagree on dimensions")
            detected = dimensions[0]
            if self.config.required_dimensions and detected != self.config.required_dimensions:
                raise RuntimeError("configured embedding dimensions do not match loaded artifact")
            fingerprints = [self._fingerprint(model) for model in models]
            if len(set(fingerprints)) != 1:
                raise RuntimeError("embedding replicas disagree on artifact fingerprint")
            try:
                package_version = version("sentence-transformers")
            except PackageNotFoundError:
                package_version = "injected"
            identity = {
                "model": self.config.model_name,
                "requested_revision": self.config.model_revision,
                "artifact_fingerprint": fingerprints[0],
                "normalization": self.config.normalization,
                "dimensions": detected,
                "sentence_transformers_version": package_version,
            }
            profile_id = "emb-sha256:" + hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            self._models = models
            self._profile = EmbeddingProfile(
                self.config.model_name,
                self.config.model_revision,
                fingerprints[0],
                detected,
                self.config.normalization,
                profile_id,
            )
            return self._profile

    async def prepare(self) -> EmbeddingProfile:
        if self._profile is not None:
            return self._profile
        if self._prepare_lock is None:
            self._prepare_lock = asyncio.Lock()
        async with self._prepare_lock:
            if self._profile is None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self._executor, self._prepare_sync)
                queue: asyncio.Queue[int] = asyncio.Queue()
                for index in range(len(self._models)):
                    queue.put_nowait(index)
                self._model_queue = queue
        assert self._profile is not None
        return self._profile

    def _encode_sync(self, model: Any, texts: list[str]) -> list[list[float]]:
        vectors = model.encode(
            texts,
            normalize_embeddings=self.config.normalization == "unit_l2",
        )
        return [[float(value) for value in vector] for vector in vectors]

    async def _release_model(self, index: int) -> None:
        if self._model_queue is None:
            raise RuntimeError("embedding model queue is not initialized")
        self._model_queue.put_nowait(index)
        self._active_jobs -= 1
        if self._active_jobs == 0:
            self._jobs_drained.set()

    async def _release_when_finished(
        self, future: asyncio.Future[list[list[float]]], index: int
    ) -> None:
        try:
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    # Cancellation of the HTTP request or cleanup task never
                    # transfers ownership of a still-running model.
                    continue
                except Exception:
                    break
            if future.done():
                try:
                    future.result()
                except BaseException:
                    pass
        finally:
            await self._release_model(index)

    async def encode(self, texts: list[str]) -> list[list[float]]:
        await self.prepare()
        if self._closed:
            raise RuntimeError("embedding backend is closed")
        if self._model_queue is None:
            raise RuntimeError("embedding model queue is not initialized")
        index = await self._model_queue.get()
        self._active_jobs += 1
        self._jobs_drained.clear()
        deferred_release = False
        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                self._executor, self._encode_sync, self._models[index], texts
            )
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=self.config.executor_timeout_seconds,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            deferred_release = True
            cleanup = asyncio.create_task(self._release_when_finished(future, index))
            self._cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(self._cleanup_tasks.discard)
            raise
        finally:
            if not deferred_release:
                await self._release_model(index)

    def status(self) -> dict[str, Any]:
        profile = self._profile
        return {
            "backend_kind": "local_sentence_transformer",
            "loaded": profile is not None,
            "model": self.config.model_name,
            "device": self.config.device,
            "profile_id": profile.profile_id if profile else None,
            "dimensions": profile.dimensions if profile else None,
            "workers": self.config.worker_count,
            "backend_jobs_in_flight": self._active_jobs,
        }

    async def drain(self) -> None:
        await self._jobs_drained.wait()

    async def close_async(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.drain()
        await asyncio.to_thread(self._executor.shutdown, True, cancel_futures=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)


class EmbeddingService:
    """Own stateless workload admission/batching around one embedding backend."""

    def __init__(
        self,
        config,
        *,
        model: Any | None = None,
        backend: EmbeddingBackend | None = None,
    ):
        if backend is not None and model is not None:
            raise ValueError("provide either an embedding backend or a local model")
        self.config = config
        self.backend: EmbeddingBackend = backend or LocalSentenceTransformerBackend(
            config, model=model
        )
        self._workloads = FifoLimiter(config.worker_count, config.max_queued_workloads)
        self._drained = asyncio.Event()
        self._drained.set()
        self._reservation_lock = asyncio.Lock()
        self._reservations = 0
        self._accepting = True
        self._closed = False
        self.completed_items = 0
        self.started_at = time.monotonic()

    async def prepare(self) -> EmbeddingProfile:
        return await self.backend.prepare()

    @asynccontextmanager
    async def workload(self, queue_timeout: float):
        reserved = False
        acquired = False
        try:
            async with self._reservation_lock:
                if self._closed:
                    raise RuntimeError("embedding service is closed")
                if not self._accepting:
                    raise EmbeddingReconfiguring("embedding configuration is being activated")
                self._reservations += 1
                reserved = True
                self._drained.clear()
            wait_ms = await self._workloads.acquire(queue_timeout)
            acquired = True
            yield wait_ms
        finally:
            if acquired:
                await self._workloads.release()
            if reserved:
                async with self._reservation_lock:
                    self._reservations -= 1
                    if self._reservations == 0:
                        self._drained.set()

    async def drain(self) -> None:
        await self._drained.wait()
        await self.backend.drain()

    async def stop_accepting_and_drain(self) -> None:
        """Close admission and wait for queued, running, and timed-out work."""
        async with self._reservation_lock:
            self._accepting = False
            if self._reservations == 0:
                self._drained.set()
        await self.drain()

    async def resume_accepting(self) -> None:
        async with self._reservation_lock:
            if self._closed:
                raise RuntimeError("cannot resume a closed embedding service")
            self._accepting = True

    async def encode(self, texts: list[str]) -> list[list[float]]:
        return await self.backend.encode(texts)

    def status(self) -> dict[str, Any]:
        elapsed = max(time.monotonic() - self.started_at, 0.001)
        return {
            **self.backend.status(),
            "accepting": self._accepting and not self._closed,
            "in_flight": self._workloads.in_flight,
            "queued": self._workloads.queued,
            "items_per_second_since_start": self.completed_items / elapsed,
        }

    async def close_async(self) -> None:
        if self._closed:
            return
        await self.stop_accepting_and_drain()
        self._closed = True
        await self.backend.close_async()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.backend.close()


class EmbeddingSequencer:
    endpoint = "/v1/embeddings"

    def __init__(self, request_id: str, config_version: int):
        self.request_id = request_id
        self.config_version = config_version
        self.sequence = 0

    def event(self, name: str, *, data=None, result=None, error=None) -> str:
        from datetime import datetime, timezone
        self.sequence += 1
        value: dict[str, Any] = {
            "request_id": self.request_id,
            "sequence": self.sequence,
            "event": name,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "config_version": self.config_version,
        }
        if name == "failed":
            value["error"] = error
        elif name == "completed":
            value["result"] = result
        else:
            value["data"] = data or {}
        parse_ndjson_event(value, endpoint=self.endpoint)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


async def run_embedding_stream(app, raw_body: dict[str, Any]) -> StreamingResponse:
    snapshot = app.state.config_service.snapshot()
    if app.state.embedding_reconfiguring:
        raise EmbeddingReconfiguring("embedding configuration is being activated")
    request = EmbeddingsRequest.model_validate(raw_body)
    embedding_config = snapshot.embedding
    item_limit = min(
        embedding_config.maximum_items,
        snapshot.global_config.maximum_embedding_items,
    )
    if len(request.items) > item_limit:
        raise WorkloadTooLarge("embedding workload exceeds configured item ceiling")
    raw_size = len(json.dumps(raw_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    byte_limit = min(
        embedding_config.maximum_request_bytes,
        snapshot.global_config.maximum_embedding_request_bytes,
    )
    if raw_size > byte_limit:
        raise WorkloadTooLarge("embedding workload exceeds configured byte ceiling")
    embedding_service: EmbeddingService | None = app.state.embedding
    if embedding_service is None:
        raise RuntimeError("active embedding service is not initialized")
    profile = await embedding_service.prepare()
    sequencer = EmbeddingSequencer(request.request_id, snapshot.config_version)
    endpoint = "/v1/embeddings"
    items = list(request.items)

    async def stream():
        completed = 0
        failed_batch: tuple[int, int, int] | None = None
        started = time.monotonic()
        last_progress = 0.0
        try:
            async with embedding_service.workload(
                snapshot.global_config.global_queue_wait_timeout_seconds
            ) as wait_ms:
                app.state.events.emit(
                    "request_accepted",
                    request_id=request.request_id,
                    config_version=snapshot.config_version,
                    product_endpoint=endpoint,
                )
                yield sequencer.event(
                    "accepted",
                    data={
                        "endpoint": endpoint,
                        "total_items": len(items),
                        "embedding_profile_id": profile.profile_id,
                        "model": profile.model,
                        "requested_revision": profile.requested_revision,
                        "artifact_fingerprint": profile.artifact_fingerprint,
                        "dimensions": profile.dimensions,
                        "normalization": profile.normalization,
                    },
                )
                if wait_ms > 0:
                    yield sequencer.event(
                        "queued",
                        data={
                            "operation": "embeddings",
                            "queued_count": embedding_service._workloads.queued,
                            "wait_timeout_ms": int(snapshot.global_config.global_queue_wait_timeout_seconds * 1000),
                        },
                    )
                batch_size = embedding_config.internal_batch_size
                batch_count = (len(items) + batch_size - 1) // batch_size
                for batch_index, start in enumerate(range(0, len(items), batch_size)):
                    batch = items[start : start + batch_size]
                    end = start + len(batch) - 1
                    failed_batch = (batch_index, start, end)
                    app.state.events.emit(
                        "embedding_batch_start",
                        request_id=request.request_id,
                        config_version=snapshot.config_version,
                        product_endpoint=endpoint,
                        internal_operation="embeddings",
                        batch_index=batch_index,
                        item_count=len(batch),
                    )
                    yield sequencer.event(
                        "embedding_batch_started",
                        data={
                            "batch_index": batch_index,
                            "batch_count": batch_count,
                            "first_item_index": start,
                            "last_item_index": end,
                            "item_count": len(batch),
                        },
                    )
                    vectors = await embedding_service.encode([item.text for item in batch])
                    if len(vectors) != len(batch) or any(
                        len(vector) != profile.dimensions
                        or any(not math.isfinite(value) for value in vector)
                        for vector in vectors
                    ):
                        raise EmbeddingValidationError("embedding model returned invalid vectors")
                    yield sequencer.event(
                        "vector_batch",
                        data={
                            "batch_index": batch_index,
                            "items": [
                                {"message_id": item.message_id, "vector": vector}
                                for item, vector in zip(batch, vectors)
                            ],
                        },
                    )
                    completed += len(batch)
                    embedding_service.completed_items += len(batch)
                    now = time.monotonic()
                    if (
                        completed == len(items)
                        or last_progress == 0.0
                        or (now - last_progress) * 1000 >= embedding_config.progress_min_interval_ms
                    ):
                        rate = completed / max(now - started, 0.001)
                        yield sequencer.event(
                            "embedding_progress",
                            data={
                                "completed_items": completed,
                                "total_items": len(items),
                                "server_items_per_second": rate,
                            },
                        )
                        last_progress = now
                    app.state.events.emit(
                        "embedding_batch_success",
                        request_id=request.request_id,
                        config_version=snapshot.config_version,
                        product_endpoint=endpoint,
                        internal_operation="embeddings",
                        batch_index=batch_index,
                        item_count=len(batch),
                        completed_items=completed,
                        total_items=len(items),
                    )
                try:
                    await app.state.config_service.store_call(
                        "record_usage",
                        request_id=request.request_id,
                        config_version=snapshot.config_version,
                        product_endpoint=endpoint,
                        internal_operation=None,
                        attempt=None,
                        provider_or_profile=profile.profile_id,
                        outcome="success",
                        usage_source="estimated",
                        embedding_item_count=len(items),
                    )
                except Exception as exc:
                    raise AccountingPersistenceFailed("embedding accounting could not be committed") from exc
                app.state.events.emit(
                    "request_completed",
                    request_id=request.request_id,
                    config_version=snapshot.config_version,
                    product_endpoint=endpoint,
                    completed_items=completed,
                    total_items=len(items),
                )
                yield sequencer.event(
                    "completed",
                    result={"total_items": len(items), "embedding_profile_id": profile.profile_id},
                )
        except asyncio.CancelledError:
            app.state.events.emit(
                "client_cancelled",
                request_id=request.request_id,
                config_version=snapshot.config_version,
                product_endpoint=endpoint,
                completed_items=completed,
                total_items=len(items),
                severity="WARNING",
            )
            raise
        except Exception as exc:
            if not isinstance(exc, AccountingPersistenceFailed):
                try:
                    await app.state.config_service.store_call(
                        "record_usage",
                        request_id=request.request_id,
                        config_version=snapshot.config_version,
                        product_endpoint=endpoint,
                        provider_or_profile=profile.profile_id,
                        outcome="failure",
                        error_code=getattr(exc, "code", "EMBEDDING_ERROR"),
                        usage_source="estimated",
                        embedding_item_count=completed,
                    )
                except Exception as persistence_exc:
                    exc = AccountingPersistenceFailed("embedding failure accounting could not be committed")
                    exc.__cause__ = persistence_exc
            info = map_error(exc, stage="embedding")
            details = dict(info.details or {})
            if failed_batch is not None:
                details.update(
                    {
                        "batch_index": failed_batch[0],
                        "first_item_index": failed_batch[1],
                        "last_item_index": failed_batch[2],
                    }
                )
            app.state.events.emit(
                "request_failed",
                request_id=request.request_id,
                config_version=snapshot.config_version,
                product_endpoint=endpoint,
                stage="embedding",
                error_code=info.code,
                http_status=info.status,
            )
            yield sequencer.event(
                "failed",
                error={
                    "request_id": request.request_id,
                    "code": info.code,
                    "message": info.message,
                    "stage": "embedding",
                    "retryable": info.retryable,
                    "details": details,
                },
            )

    return StreamingResponse(stream(), media_type="application/x-ndjson")
