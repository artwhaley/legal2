# T48 - SQL Dataset Budget Stats

## Goal
Replace full-dataset message loading for answer mode selection and budget preview with cheap SQL aggregate statistics.

## Background
`build_dataset_transcript` -> `load_dataset_messages` loads every message body to estimate tokens and choose whole-transcript vs exhaustive scan. This will OOM on large donor data.

**Spec reference:** `04_pre_scale_hardening_spec.md` Section 1, Section C (auto mode documentation)

## Depends On
- T46 (usable input budget uses settings context window)

## Scope
- Add `DatasetBudgetStats` dataclass or equivalent with SQL-backed fields:
  - `message_count`, `thread_count`, `total_body_chars`, `total_body_normalized_chars`.
  - Largest-thread count via `GROUP BY source_thread_id`.
  - Optional stratified sample fields if used for calibration.
- Add repository/helper: `compute_dataset_budget_stats(conn, dataset_id) -> DatasetBudgetStats`.
- Add conservative transcript token estimator:
  - Starts from SQL aggregate body character counts.
  - Adds per-message overhead for timestamp, sender, message ID/reference text, separators, and formatting.
  - Adds per-thread overhead for thread headers and participant/source metadata.
  - Adds prompt/header overhead or coordinates with `prompt_overhead_tokens` without double-counting.
  - Applies a safety margin so undercounting favors exhaustive scan over risky whole-transcript mode.
  - Logs estimator method, assumptions, and margin.
- Refactor `resolve_answer_budget` to accept stats instead of `SerializedTranscript` for the **decision** step.
- Remove `load_dataset_messages` from budgeting path.
- Update Settings context budget readout to use SQL stats, not full dataset load.
- Log stats and estimate details in `answer_budget_resolved`.
- Document: whole-transcript mode still sends full serialized dataset in the LLM call when selected; only viable when conservative stats fit budget.

## Guardrails
- Do not change whole-transcript **execution** path yet; it still loads full transcript when selected.
- Do not let an optimistic estimate select whole-transcript near the limit. If uncertain, choose exhaustive scan.
- Do not break exhaustive scan entry when stats exceed budget.

## Non-Goals
- Window packing changes (T49).
- Virtualized transcript (T56).
- Whole-transcript execution streaming.

## Acceptance Criteria
- No `load_dataset_messages` on budgeting/readout path.
- Fixture dataset produces same mode decision as before T48 when clearly within budget.
- Mock stats with 10M estimated tokens always select exhaustive scan.
- Borderline stats select exhaustive scan unless conservative overhead still fits safely.
- Budget readout works with dataset loaded, no full-body fetch.
- Logs show message count, thread count, char totals, estimated transcript tokens, and estimator margin.

## Tests
- Unit tests for `compute_dataset_budget_stats` on fixture DB.
- Token estimator test includes message/thread overhead, not body chars alone.
- `resolve_answer_budget` tests with injected stats.
- Settings readout smoke test.
- `python -m pytest -q`
