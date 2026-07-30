import asyncio

import pytest

from server.config import GlobalConfig, OperationConfig
from server.observability import EventSink, map_error
from server.evidence_ledger import LedgerError
from server.provider import ProviderError
from server.resilience import CircuitOpenError, FifoLimiter, QueueFullError, ResilienceController


def op(**changes):
    base = OperationConfig(base_url="https://provider.example", model_id="m", system_prompt="p", context_window_tokens=100, max_output_tokens=10, safety_margin_tokens=1, api_key="x", max_in_flight=1, max_queued=1, max_attempts=1)
    return base.__class__(**{**base.to_dict(include_secret=True), **changes})


def test_queue_full_and_retry_policy_are_observable():
    async def run():
        controller = ResilienceController({"x": op(max_attempts=2, retryable_statuses=(503,), backoff_base_seconds=0)}, GlobalConfig(product_max_in_flight=2, product_max_queued=2), sleep=lambda delay: asyncio.sleep(0), random_fn=lambda: 0)
        attempts = []
        async def call(attempt):
            attempts.append(attempt)
            if attempt == 1:
                raise ProviderError("PROVIDER_UNAVAILABLE", "temporary", status_code=503, retryable=True)
            return "ok"
        emitted = []
        result = await controller.run("x", call, emit=lambda name, data: emitted.append((name, data)))
        assert result == "ok"
        assert attempts == [1, 2]
        assert emitted[0][0] == "retry_wait"
    asyncio.run(run())


def test_retry_exhaustion_fails_after_exact_configured_attempt_count():
    async def run():
        controller = ResilienceController(
            {
                "x": op(
                    max_attempts=3,
                    retryable_statuses=(503,),
                    backoff_base_seconds=0,
                )
            },
            GlobalConfig(product_max_in_flight=2, product_max_queued=2),
            sleep=lambda delay: asyncio.sleep(0),
            random_fn=lambda: 0,
        )
        attempts = []
        emitted = []

        async def call(attempt):
            attempts.append(attempt)
            raise ProviderError(
                "PROVIDER_UNAVAILABLE",
                "temporary",
                status_code=503,
                retryable=True,
            )

        with pytest.raises(ProviderError, match="temporary"):
            await controller.run(
                "x",
                call,
                emit=lambda name, data: emitted.append((name, data)),
            )
        assert attempts == [1, 2, 3]
        assert [name for name, _data in emitted] == [
            "retry_wait",
            "retry_wait",
        ]
        assert [data["next_attempt"] for _name, data in emitted] == [2, 3]

    asyncio.run(run())


def test_circuit_opens_and_redaction_is_scalar_only(capsys):
    async def run():
        controller = ResilienceController({"x": op(circuit_threshold=1, retryable_statuses=(503,))}, GlobalConfig(product_max_in_flight=2, product_max_queued=2))
        async def call(_attempt):
            raise ProviderError("PROVIDER_UNAVAILABLE", "temporary", status_code=503)
        with pytest.raises(ProviderError):
            await controller.run("x", call)
        with pytest.raises(CircuitOpenError):
            await controller.run("x", call)
    asyncio.run(run())
    sink = EventSink(2)
    sink.emit("request", request_id="r", config_version=1, question="secret", vector=[1.0])
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "1.0" not in output
    assert map_error(ProviderError("PROVIDER_RATE_LIMITED", "safe", status_code=429)).status == 429


def test_ledger_failure_preserves_safe_exact_diagnostics():
    error = LedgerError(
        "evidence range is reversed in supplied message order",
        details={
            "reason": "reversed_in_supplied_message_order",
            "window_id": "w000004",
            "range_index": 4,
            "start_message_id": "source:583",
            "end_message_id": "source:602",
        },
    )
    mapped = map_error(error, stage="ledger")
    assert mapped.code == "LEDGER_INTERNAL_INTEGRITY_FAILED"
    assert mapped.status == 500
    assert mapped.details == error.details


def test_cancelled_queued_waiter_cannot_release_an_ungranted_lease():
    async def run():
        limiter = FifoLimiter(max_in_flight=1, max_queued=1)
        await limiter.acquire(1)
        queued = asyncio.create_task(limiter.acquire(1))
        while limiter.queued != 1:
            await asyncio.sleep(0)

        # Reproduce the important ordering: wait_for has cancelled the queued
        # future, then the current lease is released before the waiter handles
        # cancellation.  Queue removal is not proof that a lease transferred.
        limiter._waiters[0].future.cancel()
        await limiter.release()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert limiter.in_flight == 0

        await limiter.acquire(1)
        await limiter.release()
        assert limiter.in_flight == 0

    asyncio.run(run())
