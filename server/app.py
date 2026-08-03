"""FastAPI composition for the four public Server-First V1 operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server.admin import register_admin
from server.config import ServerConfig
from server.config_service import ConfigurationRequired, ConfigurationService
from server.contracts import (
    AnalysisClarificationResponse,
    AnalysisOutOfScopeResponse,
    AnalysisPlanResponse,
    AnalysisPlanningOutput,
    AnalysisPlanningRequest,
    EmbeddingMetadata,
    FrozenAnalysisPlan,
    KeywordExpansionOutput,
    KeywordExpansionRequest,
    RetrievalQuery,
    SearchPolicy,
    SCHEMA_REGISTRY,
)
from server.debug_capture import DebugCaptureManager
from server.embeddings import EmbeddingService
from server.model_runtime import UsageCollector, WorkloadTooLarge, run_model_operation
from server.observability import EventSink, map_error
from server.provider import AsyncProvider
from server.resilience import FifoLimiter, ResilienceController
from server.token_accounting import canonical_json


@dataclass(slots=True)
class RuntimeSnapshot:
    config: ServerConfig
    provider: AsyncProvider
    resilience: ResilienceController
    embedding: EmbeddingService
    encrypted_secrets: dict[str, bytes]
    secret_manager: Any

    def resolve_secret(self, operation: str) -> str:
        assignment = self.config.operation_assignments[operation]
        profile = self.config.model_profiles[assignment.model_profile_id]
        provider_account_id = profile.provider_account_id
        try:
            ciphertext = self.encrypted_secrets[provider_account_id]
        except KeyError as exc:
            raise RuntimeError(
                f"active secret binding is missing for provider account {provider_account_id}"
            ) from exc
        return self.secret_manager.decrypt(ciphertext)


class AnalysisPlanEmpty(ValueError):
    code = "ANALYSIS_PLAN_EMPTY"


def _analysis_plan_compatibility_fingerprint(
    snapshot: ServerConfig,
    *,
    question: str,
    analysis_plan: FrozenAnalysisPlan,
    queries,
    embedding: EmbeddingMetadata | None,
    policy,
) -> str:
    payload = {
        "question": question.strip(),
        "analysis_plan": analysis_plan.model_dump(),
        "queries": [query.model_dump() for query in queries],
        "analysis_planning_operation": snapshot.operations["analysis_planning"].to_dict(
            include_secret=False
        ),
        "embedding": None if embedding is None else embedding.model_dump(),
        "search_policy": policy.model_dump(),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _error_content(request_id: str | None, exc: Exception, *, stage: str = "request") -> tuple[int, dict[str, Any]]:
    info = map_error(exc, stage=stage)
    return info.status, {
        "request_id": request_id,
        "code": info.code,
        "message": info.message,
        "stage": info.stage,
        "retryable": info.retryable,
        "details": info.details or {},
    }


def _json_error(request_id: str | None, exc: Exception, *, stage: str = "request") -> JSONResponse:
    status, content = _error_content(request_id, exc, stage=stage)
    return JSONResponse(status_code=status, content=content)


class ProductAdmissionMiddleware:
    """Enforce byte ceilings and global FIFO admission before body decoding."""

    def __init__(
        self,
        app,
        *,
        service: ConfigurationService,
        events: EventSink,
        debug_capture: DebugCaptureManager,
    ):
        self.app = app
        self.service = service
        self.events = events
        self.debug_capture = debug_capture
        self.limiters: dict[int, FifoLimiter] = {}

    def limiter(self, config: ServerConfig) -> FifoLimiter:
        existing = self.limiters.get(config.config_version)
        if existing is None:
            existing = FifoLimiter(
                config.global_config.product_max_in_flight,
                config.global_config.product_max_queued,
            )
            self.limiters[config.config_version] = existing
        return existing

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") != "http" or path not in {
            "/v1/keyword-expansion",
            "/v1/conversational-plan",
            "/v1/conversational-analysis",
            "/v1/embeddings",
        }:
            await self.app(scope, receive, send)
            return
        try:
            config = self.service.snapshot()
        except ConfigurationRequired:
            await self.app(scope, receive, send)
            return
        limit = (
            min(
                config.global_config.maximum_embedding_request_bytes,
                config.embedding.maximum_request_bytes,
            )
            if path == "/v1/embeddings"
            else config.global_config.maximum_product_request_bytes
        )
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = -1
            if declared < 0:
                await self._send_error(send, None, ValueError("invalid Content-Length"))
                return
            if declared > limit:
                await self._send_error(send, None, WorkloadTooLarge("request body exceeds configured ceiling"))
                return
        limiter = self.limiter(config)
        acquired = False
        try:
            wait_ms = await limiter.acquire(config.global_config.global_queue_wait_timeout_seconds)
            acquired = True
            if wait_ms > 0:
                self.events.emit(
                    "product_queue_leave",
                    config_version=config.config_version,
                    product_endpoint=path,
                    queue_wait_ms=wait_ms,
                )
            body = bytearray()
            more = True
            while more:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    continue
                body.extend(message.get("body", b""))
                if len(body) > limit:
                    await self._send_error(
                        send,
                        None,
                        WorkloadTooLarge("request body exceeds configured ceiling"),
                    )
                    return
                more = bool(message.get("more_body", False))
            try:
                decoded_body: Any = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                decoded_body = body.decode("utf-8", errors="replace")
            supplied_request_id = (
                decoded_body.get("request_id")
                if isinstance(decoded_body, dict)
                else None
            )
            capture_request_id = (
                str(supplied_request_id)
                if supplied_request_id
                else f"transport-{uuid.uuid4()}"
            )
            account_id = (
                scope.get("state", {}).get("account_id")
                if isinstance(scope.get("state"), dict)
                else None
            )
            capture_session_id = self.debug_capture.bind_request(
                capture_request_id,
                account_id=str(account_id) if account_id is not None else None,
            )
            self.debug_capture.record_session(
                capture_session_id,
                "public_request",
                request_id=capture_request_id,
                data={
                    "method": scope.get("method"),
                    "path": path,
                    "account_id": account_id,
                    "body": decoded_body,
                },
            )
            sent = False

            async def replay_receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                message = await receive()
                if message["type"] == "http.disconnect":
                    self.debug_capture.record_session(
                        capture_session_id,
                        "client_disconnected",
                        request_id=capture_request_id,
                        data={"path": path},
                    )
                return message

            async def capture_send(message):
                if message["type"] == "http.response.start":
                    safe_headers = {
                        key.decode("latin-1"): value.decode("latin-1")
                        for key, value in message.get("headers", [])
                        if key.lower()
                        not in {b"authorization", b"set-cookie", b"cookie"}
                    }
                    self.debug_capture.record_session(
                        capture_session_id,
                        "public_response_start",
                        request_id=capture_request_id,
                        data={
                            "path": path,
                            "status": message["status"],
                            "headers": safe_headers,
                        },
                    )
                elif message["type"] == "http.response.body":
                    self.debug_capture.record_session(
                        capture_session_id,
                        "public_response_body",
                        request_id=capture_request_id,
                        data={
                            "path": path,
                            "body": message.get("body", b"").decode(
                                "utf-8", errors="replace"
                            ),
                            "more_body": bool(message.get("more_body", False)),
                        },
                    )
                await send(message)

            try:
                await self.app(scope, replay_receive, capture_send)
            finally:
                self.debug_capture.record_session(
                    capture_session_id,
                    "public_request_finished",
                    request_id=capture_request_id,
                    data={"path": path},
                )
                self.debug_capture.release_request(capture_request_id)
        except Exception as exc:
            if not acquired:
                await self._send_error(send, None, exc)
            else:
                raise
        finally:
            if acquired:
                await limiter.release()

    @staticmethod
    async def _send_error(send, request_id: str | None, exc: Exception) -> None:
        status, content = _error_content(request_id, exc)
        body = json.dumps(content, separators=(",", ":")).encode("utf-8")
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def create_app(
    *,
    config_service: ConfigurationService | None = None,
    provider: AsyncProvider | None = None,
    embedding_service: EmbeddingService | None = None,
    embedding_factory: Callable[[Any], EmbeddingService] | None = None,
) -> FastAPI:
    service = config_service or ConfigurationService()
    events = EventSink()
    debug_capture = DebugCaptureManager(
        service.store.state_dir,
        failure_callback=lambda message: events.emit(
            "debug_capture_failed",
            error_code="DEBUG_CAPTURE_WRITE_FAILED",
            severity="ERROR",
        ),
    )
    injected_provider = provider
    injected_embedding = embedding_service
    build_embedding = embedding_factory or (lambda config: EmbeddingService(config))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.startup()
        await debug_capture.startup()
        active = service.maybe_snapshot()
        listener_config = active
        if listener_config is None:
            from server.config_store import fresh_bootstrap_config
            listener_config = fresh_bootstrap_config()
        app.state.listener_current = f"{listener_config.host}:{listener_config.port}"
        app.state.embedding_reconfiguring = False
        app.state.runtime_activation_lock = asyncio.Lock()
        app.state.runtimes = {}
        if active is not None:
            active_provider = injected_provider or AsyncProvider()
            await active_provider.start(active)
            active_embedding = injected_embedding or build_embedding(active.embedding)
            await active_embedding.prepare()
            runtime = RuntimeSnapshot(
                active,
                active_provider,
                ResilienceController(active.operations, active.global_config, config_version=active.config_version),
                active_embedding,
                service.store.encrypted_secret_bindings(active.config_version),
                service.store.secrets,
            )
            app.state.runtimes[active.config_version] = runtime
            app.state.current_runtime = runtime
            app.state.provider = active_provider
            app.state.resilience = runtime.resilience
            app.state.embedding = active_embedding
            events.resize(active.global_config.recent_event_ring_size)
        else:
            bootstrap_provider = injected_provider or AsyncProvider()
            from server.config_store import fresh_bootstrap_config
            await bootstrap_provider.start(fresh_bootstrap_config())
            app.state.bootstrap_provider = bootstrap_provider
            app.state.provider = bootstrap_provider
            app.state.resilience = None
            app.state.embedding = injected_embedding
            app.state.current_runtime = None
        try:
            yield
        finally:
            await debug_capture.close()
            providers = {id(runtime.provider): runtime.provider for runtime in app.state.runtimes.values()}
            if hasattr(app.state, "bootstrap_provider"):
                providers[id(app.state.bootstrap_provider)] = app.state.bootstrap_provider
            embeddings = {id(runtime.embedding): runtime.embedding for runtime in app.state.runtimes.values()}
            if injected_embedding is not None:
                embeddings[id(injected_embedding)] = injected_embedding
            for model_service in embeddings.values():
                await model_service.close_async()
            for provider_service in providers.values():
                await provider_service.close()
            await service.close_async()

    app = FastAPI(
        title="Message Evidence Server",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.config_service = service
    app.state.events = events
    app.state.debug_capture = debug_capture

    async def activate_runtime(version_id: int) -> ServerConfig:
        async with app.state.runtime_activation_lock:
            candidate = await service.store_call("get_version", version_id)
            candidate.validate(require_complete=True)
            candidate.validate_local_model_artifacts()
            encrypted_secrets = await service.store_call("encrypted_secret_bindings", version_id)
            previous: RuntimeSnapshot | None = app.state.current_runtime
            embedding_changed = previous is None or previous.config.embedding != candidate.embedding
            new_embedding = previous.embedding if previous is not None and not embedding_changed else build_embedding(candidate.embedding)
            new_provider = injected_provider or AsyncProvider()
            await new_provider.start(candidate)
            app.state.embedding_reconfiguring = embedding_changed
            try:
                if embedding_changed:
                    if previous is not None:
                        await previous.embedding.stop_accepting_and_drain()
                    await new_embedding.prepare()
                prepared_config = candidate.without_secrets()
                prepared_runtime = RuntimeSnapshot(
                    prepared_config,
                    new_provider,
                    ResilienceController(
                        prepared_config.operations,
                        prepared_config.global_config,
                        config_version=prepared_config.config_version,
                    ),
                    new_embedding,
                    encrypted_secrets,
                    service.store.secrets,
                )
                activated_with_secrets = await service.store_call("activate", version_id)
                activated = activated_with_secrets.without_secrets()
                if activated != prepared_config:
                    raise RuntimeError(
                        "activated configuration differs from the prepared runtime"
                    )
                # Install every dependency before publishing the new snapshot.
                # Requests already in progress retain their old immutable snapshot;
                # requests accepted after publish can always resolve this runtime.
                app.state.runtimes[activated.config_version] = prepared_runtime
                app.state.current_runtime = prepared_runtime
                app.state.provider = new_provider
                app.state.resilience = prepared_runtime.resilience
                app.state.embedding = new_embedding
                events.resize(activated.global_config.recent_event_ring_size)
                service.publish_activated(activated_with_secrets)
                if embedding_changed and previous is not None:
                    await previous.embedding.close_async()
                return activated
            except Exception:
                await new_provider.close()
                if embedding_changed and new_embedding is not (previous.embedding if previous else None):
                    await new_embedding.close_async()
                if embedding_changed and previous is not None:
                    await previous.embedding.resume_accepting()
                raise
            finally:
                app.state.embedding_reconfiguring = False

    app.state.activate_runtime = activate_runtime
    app.state.embedding_factory = build_embedding
    app.add_middleware(
        ProductAdmissionMiddleware,
        service=service,
        events=events,
        debug_capture=debug_capture,
    )
    register_admin(app, service, events)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        request_id = exc.body.get("request_id") if isinstance(exc.body, dict) else None
        return _json_error(request_id, ValueError("request validation failed"))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        return _json_error(request.headers.get("x-request-id"), exc)

    @app.get("/internal/live", include_in_schema=False)
    async def live() -> dict[str, Any]:
        return {"status": "alive", "api_version": 1}

    @app.post("/v1/keyword-expansion", response_model=None)
    async def keyword_expansion(request: KeywordExpansionRequest):
        try:
            snapshot = service.snapshot()
            collector = UsageCollector()
            events.emit("request_accepted", request_id=request.request_id, config_version=snapshot.config_version, product_endpoint="/v1/keyword-expansion")
            output, usage = await run_model_operation(
                app,
                snapshot=snapshot,
                request_id=request.request_id,
                product_endpoint="/v1/keyword-expansion",
                operation_name="keyword_expansion",
                user_object={"task": "keyword_expansion", "query": request.query},
                response_schema=SCHEMA_REGISTRY["keyword_expansion"]["model_output"],
                output_model=KeywordExpansionOutput,
                collector=collector,
            )
            events.emit("request_completed", request_id=request.request_id, config_version=snapshot.config_version, product_endpoint="/v1/keyword-expansion")
            return {
                "request_id": request.request_id,
                "config_version": snapshot.config_version,
                "terms": output.terms,
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "source": usage.source,
                    "estimated_cost": usage.cost,
                    "cost_complete": usage.cost is not None,
                    "currency": "USD",
                },
            }
        except Exception as exc:
            info = map_error(exc, stage="provider")
            events.emit("request_failed", request_id=request.request_id, product_endpoint="/v1/keyword-expansion", stage=info.stage, error_code=info.code, http_status=info.status)
            return _json_error(request.request_id, exc, stage="provider")

    @app.post("/v1/conversational-plan", response_model=None)
    async def conversational_plan(request: AnalysisPlanningRequest):
        try:
            snapshot = service.snapshot()
            collector = UsageCollector()
            output, usage = await run_model_operation(
                app,
                snapshot=snapshot,
                request_id=request.request_id,
                product_endpoint="/v1/conversational-plan",
                operation_name="analysis_planning",
                user_object={
                    "task": "analysis_planning",
                    "question": request.question,
                    "clarification_history": [
                        exchange.model_dump() for exchange in request.clarification_history
                    ],
                },
                response_schema=SCHEMA_REGISTRY["analysis_planning"]["model_output"],
                output_model=AnalysisPlanningOutput,
                collector=collector,
            )
            if output.disposition == "needs_clarification":
                response = AnalysisClarificationResponse(
                    request_id=request.request_id,
                    config_version=snapshot.config_version,
                    disposition="needs_clarification",
                    clarification_question=output.clarification_question,
                    usage=collector.summary(),
                )
                app.state.events.emit(
                    "analysis_clarification_requested",
                    request_id=request.request_id,
                    config_version=snapshot.config_version,
                    product_endpoint="/v1/conversational-plan",
                    clarification_round=len(request.clarification_history) + 1,
                )
                app.state.debug_capture.record_for_request(
                    request.request_id,
                    "analysis_plan_generated",
                    response.model_dump(),
                )
                return response.model_dump()
            if output.disposition == "out_of_scope":
                response = AnalysisOutOfScopeResponse(
                    request_id=request.request_id,
                    config_version=snapshot.config_version,
                    disposition="out_of_scope",
                    response_message=output.response_message,
                    usage=collector.summary(),
                )
                app.state.events.emit(
                    "analysis_request_out_of_scope",
                    request_id=request.request_id,
                    config_version=snapshot.config_version,
                    product_endpoint="/v1/conversational-plan",
                    clarification_round=len(request.clarification_history),
                )
                app.state.debug_capture.record_for_request(
                    request.request_id,
                    "analysis_plan_generated",
                    response.model_dump(),
                )
                return response.model_dump()

            analysis_plan = FrozenAnalysisPlan.model_validate(
                output.model_dump(
                    exclude={
                        "disposition",
                        "retrieval_queries",
                        "clarification_question",
                        "response_message",
                    }
                )
            )
            queries = [
                RetrievalQuery(query_id=f"q{index:04d}", text=query)
                for index, query in enumerate(output.retrieval_queries, start=1)
            ]
            mode = snapshot.global_config.retrieval_assistance_mode
            profile = None
            embedding = None
            if mode == "semantic_ranges":
                profile = await app.state.embedding.prepare()
                embedding = EmbeddingMetadata(
                    embedding_profile_id=profile.profile_id,
                    artifact_fingerprint=profile.artifact_fingerprint,
                    dimensions=profile.dimensions,
                    normalization=profile.normalization,
                )
            maximum_prompt_suggestion_messages = (
                request.maximum_prompt_suggestion_messages
                if request.maximum_prompt_suggestion_messages is not None
                else snapshot.global_config.retrieval_maximum_prompt_suggestion_messages
            )
            policy = SearchPolicy(
                mode=mode,
                top_k_per_query=snapshot.global_config.retrieval_top_k_per_query,
                fusion_method="reciprocal_rank_fusion",
                rrf_constant=snapshot.global_config.retrieval_rrf_constant,
                maximum_prompt_suggestion_messages=maximum_prompt_suggestion_messages,
            )
            compatibility_fingerprint = _analysis_plan_compatibility_fingerprint(
                snapshot,
                question=request.question,
                analysis_plan=analysis_plan,
                queries=queries,
                embedding=embedding,
                policy=policy,
            )
            response = AnalysisPlanResponse(
                request_id=request.request_id,
                config_version=snapshot.config_version,
                disposition="analyze_corpus",
                analysis_plan_id=str(uuid.uuid4()),
                compatibility_fingerprint=compatibility_fingerprint,
                analysis_plan=analysis_plan,
                retrieval_queries=queries,
                embedding=embedding,
                search_policy=policy,
                usage=collector.summary(),
            )
            app.state.events.emit(
                "analysis_plan_generated",
                request_id=request.request_id,
                config_version=snapshot.config_version,
                product_endpoint="/v1/conversational-plan",
                retrieval_mode=mode,
                retrieval_query_count=len(queries),
                disposition="analyze_corpus",
            )
            app.state.debug_capture.record_for_request(
                request.request_id,
                "analysis_plan_generated",
                response.model_dump(),
            )
            return response.model_dump()
        except Exception as exc:
            info = map_error(exc, stage="analysis_plan")
            app.state.events.emit(
                "analysis_plan_failed",
                request_id=request.request_id,
                config_version=service.maybe_snapshot().config_version if service.maybe_snapshot() else None,
                product_endpoint="/v1/conversational-plan",
                error_code=info.code,
                http_status=info.status,
            )
            return _json_error(request.request_id, exc, stage="analysis_plan")

    @app.post("/v1/conversational-analysis", response_model=None)
    async def conversational_analysis(request: Request):
        body: Any = None
        try:
            service.snapshot()
            try:
                body = await request.json()
            except json.JSONDecodeError as exc:
                return _json_error(None, ValueError("request body is not valid JSON"))
            if not isinstance(body, dict):
                return _json_error(None, ValueError("request body must be a JSON object"))
            from server.conversation import run_conversational_stream
            return await run_conversational_stream(app, body)
        except Exception as exc:
            request_id = body.get("request_id") if isinstance(body, dict) else None
            return _json_error(request_id, exc)

    @app.post("/v1/embeddings", response_model=None)
    async def embeddings(request: Request):
        body: Any = None
        try:
            service.snapshot()
            try:
                body = await request.json()
            except json.JSONDecodeError:
                return _json_error(None, ValueError("request body is not valid JSON"), stage="embedding")
            if not isinstance(body, dict):
                return _json_error(None, ValueError("request body must be a JSON object"), stage="embedding")
            from server.embeddings import run_embedding_stream
            return await run_embedding_stream(app, body)
        except Exception as exc:
            request_id = body.get("request_id") if isinstance(body, dict) else None
            return _json_error(request_id, exc, stage="embedding")

    return app
