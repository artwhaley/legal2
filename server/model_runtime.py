"""One strict, observable execution path for every chat-model operation."""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeVar

from pydantic import BaseModel, ValidationError

from server.config import OperationConfig, ServerConfig
from server.provider import ProviderError
from server.token_accounting import (
    build_provider_payload,
    canonical_json,
    count_provider_payload,
    estimate_cost,
)


class ModelOutputInvalid(ValueError):
    code = "MODEL_OUTPUT_INVALID"


class WorkloadTooLarge(ValueError):
    code = "WORKLOAD_TOO_LARGE"


class AccountingPersistenceFailed(RuntimeError):
    code = "ACCOUNTING_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True)
class UsageEntry:
    input_tokens: int
    output_tokens: int
    source: str
    cost: float | None


@dataclass(frozen=True, slots=True)
class RawModelOutput:
    content: str
    usage: UsageEntry
    provider_request_id: str | None


class UsageCollector:
    def __init__(self) -> None:
        self.entries: list[UsageEntry] = []

    def add(self, entry: UsageEntry) -> None:
        self.entries.append(entry)

    def summary(self) -> dict[str, Any]:
        inputs = sum(entry.input_tokens for entry in self.entries)
        outputs = sum(entry.output_tokens for entry in self.entries)
        sources = {entry.source for entry in self.entries}
        source = next(iter(sources)) if len(sources) == 1 else "mixed"
        costs = [entry.cost for entry in self.entries]
        complete = bool(costs) and all(cost is not None for cost in costs)
        return {
            "input_tokens": inputs,
            "output_tokens": outputs,
            "source": source,
            "estimated_cost": sum(cost for cost in costs if cost is not None) if complete else None,
            "cost_complete": complete,
            "currency": "USD",
        }


ModelT = TypeVar("ModelT", bound=BaseModel)


def parse_model_output(content: str, model: type[ModelT]) -> ModelT:
    """Accept exactly one JSON object and validate it without coercion/defaults."""
    text = content.strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise ModelOutputInvalid("model did not return one bare JSON object")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelOutputInvalid("model returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise ModelOutputInvalid("model output root must be an object")
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise ModelOutputInvalid("model output failed its exact response schema") from exc


async def _persist_usage(service, **fields: Any) -> None:
    try:
        await service.store_call("record_usage", **fields)
    except Exception as exc:
        raise AccountingPersistenceFailed("usage accounting could not be committed") from exc


async def run_model_operation(
    app,
    *,
    snapshot: ServerConfig,
    request_id: str,
    product_endpoint: str,
    operation_name: str,
    user_object: dict[str, Any],
    response_schema: dict[str, Any],
    output_model: type[ModelT],
    collector: UsageCollector,
    progress_queue: asyncio.Queue[tuple[str, dict[str, Any]]] | None = None,
    observability: Mapping[str, str | int] | None = None,
    preserve_raw_output: bool = False,
    retry_unusable_output: bool = False,
    unusable_output: Callable[[str], bool] | None = None,
    attempt_started: Callable[[int], None] | None = None,
    raw_output_received_event: tuple[str, Mapping[str, Any]] | None = None,
) -> tuple[ModelT | RawModelOutput, UsageEntry]:
    operation: OperationConfig = snapshot.operations[operation_name]
    wire = [
        {"role": "system", "content": operation.system_prompt},
        {"role": "user", "content": canonical_json(user_object)},
    ]
    payload = build_provider_payload(
        operation,
        operation=operation_name,
        messages=wire,
        user_object=user_object,
        response_schema=response_schema,
    )
    accounting = count_provider_payload(payload, operation)
    if not accounting.fits:
        raise WorkloadTooLarge(
            f"generated {operation_name} payload exceeds its configured input budget"
        )
    events = app.state.events
    service = app.state.config_service
    event_context = dict(observability or {})
    operation_instance = (
        str(event_context["window_id"])
        if "window_id" in event_context
        else None
    )

    async def call(attempt: int) -> tuple[ModelT, UsageEntry]:
        if attempt_started is not None:
            attempt_started(attempt)
        app.state.debug_capture.record_for_request(
            request_id,
            "provider_request",
            {
                "product_endpoint": product_endpoint,
                "operation": operation_name,
                "operation_instance": operation_instance,
                "attempt": attempt,
                "provider": operation.provider_kind,
                "provider_base_url": operation.base_url,
                "model": operation.model_id,
                "configuration": operation.to_dict(include_secret=False),
                "user_object": user_object,
                "response_schema": response_schema,
                "payload": payload,
                "observability": event_context,
            },
        )
        events.emit(
            "provider_attempt_start",
            request_id=request_id,
            config_version=snapshot.config_version,
            product_endpoint=product_endpoint,
            internal_operation=operation_name,
            provider=operation.provider_kind,
            model=operation.model_id,
            attempt=attempt,
            **event_context,
        )
        try:
            runtime = app.state.runtimes[snapshot.config_version]
            result = await runtime.provider.chat(
                operation_name,
                operation,
                messages=wire,
                user_object=user_object,
                response_schema=response_schema,
                api_key=runtime.resolve_secret(operation_name),
            )
        except asyncio.CancelledError:
            app.state.debug_capture.record_for_request(
                request_id,
                "provider_cancelled",
                {
                    "product_endpoint": product_endpoint,
                    "operation": operation_name,
                    "operation_instance": operation_instance,
                    "attempt": attempt,
                    "observability": event_context,
                },
            )
            raise
        except ProviderError as exc:
            app.state.debug_capture.record_for_request(
                request_id,
                "provider_error_response",
                {
                    "product_endpoint": product_endpoint,
                    "operation": operation_name,
                    "operation_instance": operation_instance,
                    "attempt": attempt,
                    "code": exc.code,
                    "status_code": exc.status_code,
                    "retryable": exc.retryable,
                    "provider_request_id": exc.provider_request_id,
                    "response_body": exc.response_body,
                    "observability": event_context,
                },
            )
            entry = UsageEntry(
                accounting.input_tokens,
                0,
                "estimated",
                estimate_cost(operation, accounting.input_tokens, 0),
            )
            await _persist_usage(
                service,
                request_id=request_id,
                config_version=snapshot.config_version,
                product_endpoint=product_endpoint,
                internal_operation=operation_name,
                operation_instance=operation_instance,
                attempt=attempt,
                provider_or_profile=operation.model_id,
                outcome="failure",
                error_code=exc.code,
                input_tokens=entry.input_tokens,
                output_tokens=0,
                usage_source=entry.source,
                input_price_per_million=operation.input_price_per_million,
                output_price_per_million=operation.output_price_per_million,
                estimated_cost=entry.cost,
                currency="USD",
                provider_request_id=exc.provider_request_id,
            )
            collector.add(entry)
            events.emit(
                "provider_attempt_failure",
                request_id=request_id,
                config_version=snapshot.config_version,
                product_endpoint=product_endpoint,
                internal_operation=operation_name,
                provider=operation.provider_kind,
                model=operation.model_id,
                attempt=attempt,
                error_code=exc.code,
                http_status=exc.status_code,
                provider_request_id=exc.provider_request_id,
                **event_context,
            )
            raise

        app.state.debug_capture.record_for_request(
            request_id,
            "provider_response",
            {
                "product_endpoint": product_endpoint,
                "operation": operation_name,
                "operation_instance": operation_instance,
                "attempt": attempt,
                "provider_request_id": result.provider_request_id,
                "latency_ms": result.latency_ms,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "usage_source": result.usage_source,
                "response": result.raw_response,
                "observability": event_context,
            },
        )
        entry = UsageEntry(
            result.input_tokens,
            result.output_tokens,
            result.usage_source,
            estimate_cost(operation, result.input_tokens, result.output_tokens),
        )
        if raw_output_received_event is not None and progress_queue is not None:
            event_name, base_data = raw_output_received_event
            progress_queue.put_nowait((
                event_name,
                {
                    **dict(base_data),
                    "content_nonblank": bool(result.content.strip()),
                    "input_tokens": entry.input_tokens,
                    "output_tokens": entry.output_tokens,
                    "usage_source": entry.source,
                    "estimated_cost": entry.cost,
                },
            ))
        try:
            if preserve_raw_output:
                if retry_unusable_output and (unusable_output(result.content) if unusable_output is not None else not result.content.strip()):
                    raise ProviderError(
                        "MODEL_OUTPUT_UNUSABLE",
                        "model returned no usable content",
                        retryable=True,
                        provider_request_id=result.provider_request_id,
                    )
                parsed: Any = RawModelOutput(result.content, entry, result.provider_request_id)
            else:
                parsed = parse_model_output(result.content, output_model)
        except (ModelOutputInvalid, ProviderError) as exc:
            error_code = getattr(exc, "code", "MODEL_OUTPUT_INVALID")
            provider_request_id = getattr(exc, "provider_request_id", None) or result.provider_request_id
            await _persist_usage(
                service,
                request_id=request_id,
                config_version=snapshot.config_version,
                product_endpoint=product_endpoint,
                internal_operation=operation_name,
                operation_instance=operation_instance,
                attempt=attempt,
                provider_or_profile=operation.model_id,
                outcome="failure",
                error_code=error_code,
                input_tokens=entry.input_tokens,
                output_tokens=entry.output_tokens,
                usage_source=entry.source,
                input_price_per_million=operation.input_price_per_million,
                output_price_per_million=operation.output_price_per_million,
                estimated_cost=entry.cost,
                currency="USD",
                latency_ms=result.latency_ms,
                provider_request_id=provider_request_id,
            )
            collector.add(entry)
            events.emit(
                "provider_attempt_failure",
                request_id=request_id,
                config_version=snapshot.config_version,
                product_endpoint=product_endpoint,
                internal_operation=operation_name,
                provider=operation.provider_kind,
                model=operation.model_id,
                attempt=attempt,
                latency_ms=result.latency_ms,
                input_tokens=entry.input_tokens,
                output_tokens=entry.output_tokens,
                usage_source=entry.source,
                error_code=error_code,
                provider_request_id=provider_request_id,
                **event_context,
            )
            raise

        await _persist_usage(
            service,
            request_id=request_id,
            config_version=snapshot.config_version,
            product_endpoint=product_endpoint,
            internal_operation=operation_name,
            operation_instance=operation_instance,
            attempt=attempt,
            provider_or_profile=operation.model_id,
            outcome="success",
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            usage_source=entry.source,
            input_price_per_million=operation.input_price_per_million,
            output_price_per_million=operation.output_price_per_million,
            estimated_cost=entry.cost,
            currency="USD",
            latency_ms=result.latency_ms,
            provider_request_id=result.provider_request_id,
        )
        collector.add(entry)
        events.emit(
            "provider_attempt_success",
            request_id=request_id,
            config_version=snapshot.config_version,
            product_endpoint=product_endpoint,
            internal_operation=operation_name,
            provider=operation.provider_kind,
            model=operation.model_id,
            attempt=attempt,
            latency_ms=result.latency_ms,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            usage_source=entry.source,
            estimated_cost=entry.cost,
            provider_request_id=result.provider_request_id,
            **event_context,
        )
        return parsed, entry

    runtime = app.state.runtimes[snapshot.config_version]
    def emit_resilience(name: str, data: dict[str, Any]) -> None:
        contextual_data = {**data, **event_context}
        events.emit(
            name,
            request_id=request_id,
            config_version=snapshot.config_version,
            product_endpoint=product_endpoint,
            internal_operation=operation_name,
            **contextual_data,
        )
        if progress_queue is not None and name in {"queued", "retry_wait"}:
            progress_queue.put_nowait((name, contextual_data))

    return await runtime.resilience.run(
        operation_name,
        call,
        emit=emit_resilience,
    )
