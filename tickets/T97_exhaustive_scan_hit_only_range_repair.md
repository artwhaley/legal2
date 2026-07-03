# T97 - Exhaustive Scan Hit-Only Range Repair

## Goal
Keep valid evidence ranges from exhaustive window scan when the model supplies a real `hit_message_id` but invalid start/end ordering.

## Background
The latest production GLM 5.1 exhaustive scan returned 40 raw ranges and only 38 validated ranges. The two rejected ranges were real evidence:

- `School Application Progress & Interview`
  - hit `decipher_message_1:5907`
  - invalid bracket `decipher_message_1:5962..decipher_message_1:5962`
- `Spark Homeschool dissolution and reformation`
  - hit `decipher_message_1:2118`
  - invalid bracket `decipher_message_1:2117..decipher_message_1:2111`

Both failed because `start_index <= hit_index <= end_index` was false. They should be repaired to hit-only ranges, not discarded.

**Spec reference:** `09_exhaustive_window_scan_recall_spec.md` Track 1

## Scope
Update exhaustive answer-range parsing in `message_evidence_workstation/search/conversational_answer.py`.

The likely touchpoint is `_parse_answer_range`.

## Implementation Notes
Add a deterministic repair path for range-order failures.

Eligible repair:

- `hit_message_id` is non-empty.
- `hit_message_id` is in `valid_ids`.
- `message_thread_by_id[hit_message_id]` exists.
- `start_message_id` and `end_message_id`, when present and valid, are in the same thread.
- The failure is bad range order or missing order for start/end, not an invented hit.

Repair output:

- Build `AnswerRangeDraft` with:
  - `hit_message_id = hit_id`
  - `start_message_id = hit_id`
  - `end_message_id = hit_id`
  - original title, summary, display text, date description
- Build matching `CandidateEvidenceBlockDraft` with hit-only relevant/context range behavior consistent with the current context expansion.
- Preserve existing behavior for valid ranges.

Track repair metadata:

- Extend `ConversationalAnswerResult` with `repaired_answer_range_ids` or a structured `range_repairs` field, whichever is cleaner.
- Include original `start_message_id`, `hit_message_id`, `end_message_id`, and reason code.
- Add uncertainty text only if the existing result model cannot carry structured repair data cleanly.

Logging:

- `exhaustive_window_scan_window_completed` details include:
  - `repaired_answer_range_count`
  - `rejected_answer_range_count`
  - `repair_reason_counts`
  - `rejection_reason_counts`
- Add a warning or info log when repairs occur:
  - operation `exhaustive_window_scan_window_repaired_ranges`
  - include window ID and repair records.

Do not:

- Sort start/hit/end into a larger range.
- Repair unknown hit IDs.
- Repair cross-thread ranges.
- Repair missing hit IDs.
- Hide repairs inside uncertainties only.

## Acceptance Criteria
- Misordered but valid hit range becomes a hit-only answer range.
- Repaired range is included in `window_results`.
- Repaired range is included in the evidence ledger.
- Invented hit ID still gets rejected.
- Cross-thread range still gets rejected.
- Logs distinguish clean accepted, repaired, and rejected ranges.

## Tests
- Unit test `_parse_answer_range` or `parse_exhaustive_window_scan_response` with a misordered valid range.
- Unit test invented hit ID remains rejected.
- Unit test cross-thread range remains rejected.
- Integration test `run_exhaustive_window_scan_answer` logs repaired counts and passes repaired ranges into evidence ledger.
- Run:
  ```text
  python -m pytest tests/test_conversational_answer.py tests/test_evidence_ledger.py -q
  ```

