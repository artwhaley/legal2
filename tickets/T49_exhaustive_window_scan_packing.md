# T49 - Exhaustive Window Scan Packing

## Goal
Pack exhaustive scan windows to minimize LLM call count using the full per-call input budget, remove redundant session rebuild from the scan path, and ensure scan planning does not load giant threads into memory.

## Background
Window planner logic exists but effective budgets were wrong because context windows could silently fall back to 8192. Product intent: one API call per maximally packed window per thread, with message overlap between windows. For donor-scale data, the planner itself must also be bounded: transcript UI virtualization does not protect the exhaustive scan planner from OOM if it loads a 50k-message thread at once.

**Spec reference:** `04_pre_scale_hardening_spec.md` Section 2

## Depends On
- T46 (context window from settings only)
- T47 (overlap wired)
- T48 (budget stats for mode selection; scan uses same budget formula)

## Scope
- Per-call input budget formula:
  ```text
  per_call_input_budget = floor(
      (context_window_tokens - prompt_overhead_tokens - max_output_tokens) * safety_ratio
  )
  ```
  All values come from `NimSettings` on the Settings page.
- Update `_pack_messages_into_windows` / `build_token_bounded_windows_for_dataset` to use `per_call_input_budget`.
- Replace any full-thread planning load with bounded streaming/keyset planning:
  - Fetch messages in chronological batches per thread.
  - Keep only the current candidate window plus overlap buffer in memory.
  - Emit a window when adding the next message would exceed budget.
  - Carry only the configured overlap messages into the next window.
  - Preserve deterministic ordering by `(timestamp, sort_index, message_id)`.
- Add repository/helper APIs as needed, for example `iter_thread_messages_for_window_planning(conn, dataset_id, thread_id, batch_size)`.
- Remove or lower `target_tokens = max(500, target_tokens)`; sanity floor may be 256 max, but it must not dominate when settings are correct.
- Remove `rebuild_dataset_sessions` from `run_exhaustive_window_scan_answer`.
- Remove `build_dataset_transcript` from exhaustive scan budget path; use T48 stats + settings.
- Pre-flight transparency before scan starts (log + UI status):
  - `context_window_tokens`, `per_call_input_budget`, `planned_window_count`, `overlap_messages`, estimated LLM calls.
  - Operator can cancel before spend (UI affordance in conversational tab).
- Optional topic-aware breaks: **not in scope**.

## Guardrails
- Do not invest in session-coverage redesign.
- Do not load full dataset or full giant thread into memory for scan planning.
- One LLM call per packed window; do not batch multiple windows per call.
- Window text may materialize one bounded window at a time only.

## Non-Goals
- Startup session build (T55)
- SQL stats implementation (T48)
- Transcript UI virtualization (T56)

## Acceptance Criteria
- With `context_window_tokens=128000`, 100-message fixture produces far fewer windows than with 8192-equivalent small budget in test.
- No `DEFAULT_CONTEXT_WINDOW_TOKENS` in scan path.
- No session rebuild during exhaustive scan.
- Unit test: synthetic 1000-message thread packs to approximately `ceil(total_tokens / budget)` windows plus overlap overhead, not O(message_count).
- Scale/planning test: 50k-message single thread can be planned with bounded memory; test may use instrumentation or a mock cursor to prove no full-thread list is built.
- Pre-flight log includes window count before first API call.

## Tests
- Window planner unit tests with configurable budget.
- Exhaustive scan mock test asserts window count bounded.
- Streaming/keyset planner test for a large generated thread.
- `python -m pytest -q`
