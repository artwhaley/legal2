"""Bounded FIFO admission, configured retry, and in-memory circuits."""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from server.config import GlobalConfig, OperationConfig
from server.provider import ProviderError


class QueueFullError(RuntimeError):
    code = "SERVER_BUSY"


class QueueTimeoutError(RuntimeError):
    code = "QUEUE_TIMEOUT"


class CircuitOpenError(RuntimeError):
    code = "CIRCUIT_OPEN"


@dataclass(slots=True)
class _Waiter:
    future: asyncio.Future[None]
    enqueued_at: float
    granted: bool = False


class FifoLimiter:
    def __init__(self, max_in_flight: int, max_queued: int):
        if max_in_flight < 1 or max_queued < 0:
            raise ValueError("invalid limiter bounds")
        self.max_in_flight = max_in_flight
        self.max_queued = max_queued
        self.in_flight = 0
        self._waiters: deque[_Waiter] = deque()
        self._lock = asyncio.Lock()

    @property
    def queued(self) -> int:
        return len(self._waiters)

    async def acquire(self, timeout: float) -> float:
        started = time.perf_counter()
        async with self._lock:
            if self.in_flight < self.max_in_flight and not self._waiters:
                self.in_flight += 1
                return 0.0
            if len(self._waiters) >= self.max_queued:
                raise QueueFullError("operation queue is full")
            loop = asyncio.get_running_loop()
            waiter = _Waiter(loop.create_future(), time.perf_counter())
            self._waiters.append(waiter)
        try:
            await asyncio.wait_for(waiter.future, timeout=timeout)
            return (time.perf_counter() - started) * 1000
        except asyncio.TimeoutError as exc:
            async with self._lock:
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    # Queue removal alone does not prove ownership: wait_for
                    # cancels its future before this task reacquires the lock.
                    # Only the releaser may mark a waiter as granted.
                    if waiter.granted:
                        return (time.perf_counter() - started) * 1000
            raise QueueTimeoutError("operation queue wait timed out") from exc
        except asyncio.CancelledError:
            async with self._lock:
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    pass
                granted = waiter.granted
            if granted:
                await self.release()
            raise

    async def release(self) -> None:
        async with self._lock:
            while self._waiters:
                waiter = self._waiters.popleft()
                if not waiter.future.done():
                    waiter.granted = True
                    waiter.future.set_result(None)
                    return
            if self.in_flight <= 0:
                raise RuntimeError("limiter released without a lease")
            self.in_flight -= 1


@dataclass(slots=True)
class CircuitState:
    failures: deque[float] = field(default_factory=deque)
    state: str = "closed"
    opened_at: float = 0.0
    probe_in_flight: bool = False


class ResilienceController:
    def __init__(self, operations: dict[str, OperationConfig], global_config: GlobalConfig, *, config_version: int = 1, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, random_fn: Callable[[], float] = random.random):
        self.config_version = config_version
        self.operations = operations
        self.limiters = {name: FifoLimiter(value.max_in_flight, value.max_queued) for name, value in operations.items()}
        self.circuits = {name: CircuitState() for name in operations}
        self.sleep = sleep
        self.random_fn = random_fn

    async def _circuit_before(self, operation: str) -> bool:
        config = self.operations[operation]
        state = self.circuits[operation]
        if config.circuit_threshold <= 0:
            return False
        now = time.monotonic()
        while state.failures and now - state.failures[0] > config.circuit_observation_seconds:
            state.failures.popleft()
        if state.state == "open":
            if now - state.opened_at < config.circuit_cooldown_seconds:
                raise CircuitOpenError("operation circuit is open")
            if state.probe_in_flight:
                raise CircuitOpenError("operation circuit half-open probe is busy")
            state.state = "half_open"
            state.probe_in_flight = True
        return state.state == "half_open"

    def _circuit_success(self, operation: str) -> str | None:
        state = self.circuits[operation]
        previous = state.state
        state.failures.clear()
        state.state = "closed"
        state.probe_in_flight = False
        return "closed" if previous != "closed" else None

    def _circuit_failure(self, operation: str, exc: Exception) -> str | None:
        config = self.operations[operation]
        state = self.circuits[operation]
        state.probe_in_flight = False
        transient = isinstance(exc, ProviderError) and (
            (exc.status_code is not None and exc.status_code in config.retryable_statuses)
            or (exc.status_code is None and exc.retryable)
        )
        if config.circuit_threshold <= 0 or not transient:
            return None
        state.failures.append(time.monotonic())
        if len(state.failures) >= config.circuit_threshold:
            changed = state.state != "open"
            state.state = "open"
            state.opened_at = time.monotonic()
            return "open" if changed else None
        return None

    async def run(self, operation: str, call: Callable[[int], Awaitable[Any]], *, emit: Callable[[str, dict[str, Any]], None] | None = None) -> Any:
        if operation not in self.limiters:
            raise ValueError(f"unknown operation {operation}")
        config = self.operations[operation]
        deadline = time.monotonic() + config.operation_deadline_seconds
        operation_acquired = False
        try:
            queue_timeout = min(config.queue_wait_timeout_seconds, max(0.001, deadline - time.monotonic()))
            wait_ms = await self.limiters[operation].acquire(queue_timeout)
            operation_acquired = True
            if emit and wait_ms:
                emit("queued", {"operation": operation, "queued_count": self.limiters[operation].queued, "wait_timeout_ms": int(config.queue_wait_timeout_seconds * 1000)})
            for attempt in range(1, config.max_attempts + 1):
                await self._circuit_before(operation)
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProviderError("PROVIDER_TIMEOUT", "operation deadline expired", retryable=False)
                    result = await asyncio.wait_for(call(attempt), timeout=remaining)
                    transition = self._circuit_success(operation)
                    if transition and emit:
                        emit("circuit_transition", {"operation": operation, "state": transition})
                    return result
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError as exc:
                    error = ProviderError("PROVIDER_TIMEOUT", "operation deadline expired", retryable=False)
                    transition = self._circuit_failure(operation, error)
                    if transition and emit:
                        emit("circuit_transition", {"operation": operation, "state": transition})
                    raise error from exc
                except Exception as exc:
                    transition = self._circuit_failure(operation, exc)
                    if transition and emit:
                        emit("circuit_transition", {"operation": operation, "state": transition})
                    retryable_provider = isinstance(exc, ProviderError) and (
                        (exc.status_code is not None and exc.status_code in config.retryable_statuses)
                        or (exc.status_code is None and exc.retryable)
                    )
                    retryable = retryable_provider and attempt < config.max_attempts
                    if not retryable:
                        raise
                    delay = min(config.backoff_base_seconds * (config.backoff_multiplier ** (attempt - 1)), config.backoff_cap_seconds)
                    delay += self.random_fn() * config.backoff_jitter_seconds
                    if time.monotonic() + delay >= deadline:
                        raise ProviderError("PROVIDER_TIMEOUT", "operation deadline prevents another retry", retryable=False) from exc
                    if emit:
                        emit("retry_wait", {"operation": operation, "failed_attempt": attempt, "next_attempt": attempt + 1, "delay_ms": int(delay * 1000), "error_code": getattr(exc, "code", "PROVIDER_UNAVAILABLE")})
                    await self.sleep(delay)
            raise RuntimeError("retry loop ended without result")
        finally:
            if operation_acquired:
                await self.limiters[operation].release()

    def reset_circuit(self, operation: str) -> None:
        if operation not in self.circuits:
            raise ValueError(f"unknown operation {operation}")
        self.circuits[operation] = CircuitState()

    def state(self, operation: str) -> dict[str, Any]:
        circuit = self.circuits[operation]
        limiter = self.limiters[operation]
        return {"circuit": circuit.state, "in_flight": limiter.in_flight, "queued": limiter.queued}
