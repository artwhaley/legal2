# T61 - Process Log Batch Mode

## Goal
Reduce SQLite churn during long operations by batching process log writes and emitting summary lines instead of per-row noise. This is foundation work for streaming import, embedding, and the Load Dataset pipeline.

## Background
`ProcessLogger.log` commits every insert. Embedding and import jobs generate excessive log volume. This ticket must land before T51/T55 integration work so those pipelines can use the batch API without reinventing logging.

**Spec reference:** `04_pre_scale_hardening_spec.md` Section 18

## Depends On
- None. This is a foundation ticket.

## Scope
- Add `ProcessLogger.batch()` context manager:
  - Accumulate entries in memory.
  - Single commit on exit, or periodic flush for very long operations.
  - Flush promptly on error before re-raising.
- Add an explicit summary-log helper or pattern for batch progress, for example: `"Embedded messages 32000-33000 of 100000, 2.1s"`.
- Update existing long-running jobs where straightforward:
  - Embedding index jobs.
  - Any current import/index rebuild loops that already emit per-row/per-item process logs.
- Provide public API for later tickets:
  - T51 uses it for streaming import.
  - T55 uses it for narrated load pipeline and auto-embedding.
- UI live log cap (500) unchanged.
- `fetch_process_logs` limits unchanged.

## Guardrails
- Errors/exceptions still logged promptly.
- Do not lose critical failure visibility for embedding failures.
- Do not change log schema unless unavoidable.

## Non-Goals
- External log service.
- Load Dataset tab UI (T55).
- Streaming import implementation (T51).

## Acceptance Criteria
- Batch context commits once for a short operation.
- Periodic flush or bounded in-memory queue exists for very long operations.
- Embedding 10k messages produces O(batches) persisted log rows, not O(messages).
- Fatal errors still appear in live log promptly.

## Tests
- Unit test: batch context commits once.
- Unit test: batch context flushes on exception.
- Embedding job test mocks/asserts log row count is bounded.
- `python -m pytest -q`
