# TKT-05 — Tests + Verification

## Goal

Create `tests/test_evidence_ledger.py` and update `tests/test_conversational_answer.py`
to cover the new evidence-ledger merge path and verify no regressions in the old path.

---

## Depends On

- TKT-01 (evidence ledger module)
- TKT-02 (run type wiring)
- TKT-03 (ledger validator)
- TKT-04 (merge function + call site swap)

---

## Context

All prior tickets produce testable artifacts. This ticket validates the full stack:

- Pure logic tests for `search/evidence_ledger.py` functions
- Pure logic tests for `search/ledger_validator.py` functions
- Integration test for `_run_evidence_ledger_window_merge` (mocked `run_nim_chat`)
- Integration test for `run_exhaustive_window_scan_answer` with the new flag
- Integration test for `run_exhaustive_window_scan_answer` with `use_evidence_ledger_merge=False`
- Verification that existing `test_conversational_answer.py` tests still pass

---

## Deliverables

### 1. `tests/test_evidence_ledger.py`

New test file. Use the same test patterns as the existing `test_conversational_answer.py`
and `spikes/window_merge_lab/tests/test_ledger_synthesis.py`.

#### Required Tests

| # | Test Name | What It Verifies |
|---|---|---|
| 1 | `test_build_ledger_from_production_window_results` | Production-shaped `window_results` (list of dicts with `window_id`, `source_thread_id`, `answer_ranges` list) flatten into correct `EvidenceLedgerEntry` list. |
| 2 | `test_ledger_range_ids_sequential` | 3 windows × 2 ranges each → 6 entries with IDs `r000001`…`r000006`. |
| 3 | `test_ledger_source_range_key_stable` | Same input twice → identical `range_id` and `source_range_key`. |
| 4 | `test_ledger_preserves_every_range` | Input has 5 ranges; output has exactly 5 entries. No merge/dedup. |
| 5 | `test_ledger_batch_context` | Windows with non-empty `answer_summary` produce `SourceBatchContext` entries. |
| 6 | `test_ledger_empty_input` | `build_evidence_ledger([])` returns `([], [])`. |
| 7 | `test_ledger_preserves_sparse_text_fields_with_valid_ids` | Range with valid message IDs but empty title/display text is still included; display text fallback happens during assembly. |
| 8 | `test_profile_full_when_fits` | Large context window (1M tokens) → `mode="full"`, `answer_format="detailed"`, `fallback_reason=None`. |
| 9 | `test_profile_compact_when_over_budget` | Small context window (8K tokens) → `mode="compact"`, `answer_format="brief"`, non-None `fallback_reason`. |
| 10 | `test_planner_flags_impossible_budget_as_overflow` | Impossible budget (0 context or too-small output budget) returns `mode="compact"` with `overflow=True` and clear token math in `fallback_reason`. |
| 11 | `test_prompt_returns_chat_messages` | `build_evidence_ledger_synthesis_messages` returns `[{"role": "system", ..., "role": "user", ...}]`. |
| 12 | `test_prompt_no_answer_ranges_schema` | `LEDGER_ANALYSIS_JSON_SCHEMA` string does not contain `answer_ranges`. |
| 13 | `test_prompt_no_reconstruct_ranges_instruction` | System content contains "Do not reconstruct answer_ranges". |
| 14 | `test_prompt_injection_hardening` | System content contains injection hardening keywords. |
| 15 | `test_prompt_anti_window_language` | System content says not to organize by window number. |
| 16 | `test_prompt_accepts_config_none` | Passing `config=None` produces valid messages with `"detailed"` profile language. |
| 17 | `test_assembled_result_has_deterministic_ranges` | `assemble_ledger_result` output `answer_ranges` match ledger input exactly. |
| 18 | `test_assembled_result_coverage_summary` | Coverage summary has correct `input_range_count`, `output_range_count`, `represented_range_count`. |
| 19 | `test_assembled_result_includes_model_fields` | Model-owned fields (`answer`, `answer_summary`, `themes`) pass through. |
| 20 | `test_raw_validator_passes_valid_output` | Valid model JSON with correct theme IDs passes. |
| 21 | `test_raw_validator_rejects_non_dict` | Non-dict response fails with `not_object`. |
| 22 | `test_raw_validator_rejects_empty_answer` | Missing/empty `answer` fails. |
| 23 | `test_raw_validator_rejects_unknown_theme_range_id` | Theme references unknown `range_id` → error. |
| 24 | `test_raw_validator_does_not_require_answer_ranges` | Valid response without `answer_ranges` passes. |
| 25 | `test_assembled_validator_passes_perfect_bijection` | Perfect range alignment passes. |
| 26 | `test_assembled_validator_rejects_missing_range` | One input range absent in output → error. |
| 27 | `test_assembled_validator_rejects_extra_range` | Output has `range_id` not in input → error. |
| 28 | `test_assembled_validator_rejects_duplicate_range` | Same `range_id` twice in output → error. |
| 29 | `test_assembled_validator_rejects_changed_message_id` | Output range has different `hit_message_id` → error. |

#### Test patterns

Use pytest with plain assertions (same style as existing tests). No pytest plugins
beyond what the project already uses. Fixtures can create synthetic window_results
dicts.

Example fixture:

```python
@pytest.fixture
def sample_window_results():
    return [
        {
            "window_id": "w_001",
            "session_id": "session_a",
            "source_thread_id": "thread_a",
            "estimated_tokens": 500,
            "message_ids": ["m1", "m2", "m3"],
            "answer_summary": "First window findings.",
            "answer_format": "detailed",
            "answer": "Window 1 analysis...",
            "cited_message_ids": ["m1", "m2"],
            "answer_ranges": [
                {
                    "title": "Range 1",
                    "summary": "Summary 1",
                    "display_text": "Display 1",
                    "date_description": "On Jan 1",
                    "hit_message_id": "m1",
                    "start_message_id": "m1",
                    "end_message_id": "m3",
                },
                {
                    "title": "Range 2",
                    "summary": "Summary 2",
                    "display_text": "Display 2",
                    "date_description": "On Jan 2",
                    "hit_message_id": "m2",
                    "start_message_id": "m2",
                    "end_message_id": "m3",
                },
            ],
            "uncertainties": [],
        },
    ]
```

### 2. Update `tests/test_conversational_answer.py`

#### Modify `test_run_exhaustive_window_scan_answer_inspects_every_planned_window`

This test currently expects `RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE` as the final call.
With the default `use_evidence_ledger_merge=True`, it should expect
`RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS` instead, and the fake `run_nim_chat` should
return a `LEDGER_ANALYSIS_JSON_SCHEMA`-shaped response.

Update the fake:

```python
def fake_run_nim_chat(_conn, _logger, _client, *, run_type, user_content=None, messages=None, dataset_id=None, **kwargs):
    ...
    if run_type == RUN_TYPE_EVIDENCE_LEDGER_SYNTHESIS:
        return NimChatResult(
            content=json.dumps({
                "answer_summary": "Evidence-ledger synthesis result.",
                "answer": "Analysis of all window findings...",
                "themes": [],
                "notable_patterns": [],
                "contradictions_or_tensions": [],
                "uncertainties": [],
            }),
            raw_response={},
            latency_ms=1,
        )
    ...
```

#### Add `test_exhaustive_window_scan_answer_legacy_merge_path`

New test that sets `use_evidence_ledger_merge=False` on `AnswerSettings` and verifies
the old `RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE` path is used. This test proves the flag
preserves backward compatibility.

---

## Guard Rails

1. Do not mock `run_exhaustive_window_scan_answer` itself. Mock `run_nim_chat` at
   the module level (`message_evidence_workstation.search.conversational_answer.run_nim_chat`).
2. Tests for `search/evidence_ledger.py` functions must not perform DB operations
   or model calls. They test pure functions only.
3. The legacy-flag test must verify that `RUN_TYPE_EXHAUSTIVE_WINDOW_MERGE` is
   called, not just that the flag doesn't crash.
4. All existing tests in `test_conversational_answer.py` must still pass.
5. Use the same fixture patterns (`answer_db`, `router_with_role_models`) as the
   existing tests.
6. Do not add tests for deferred work (multi-call splitting, UI flags, broader
   budget architecture).

---

## Acceptance Criteria

- `pytest tests/test_evidence_ledger.py -v` — all 29+ tests pass.
- `pytest tests/test_conversational_answer.py -v` — all existing tests pass plus
  the new/modified tests.
- The existing `test_run_exhaustive_window_scan_answer_inspects_every_planned_window`
  test passes with the new default flag (ledger merge).
- The new `test_exhaustive_window_scan_answer_legacy_merge_path` test confirms the
  old merge path is still callable.
- `pytest` (full suite) — no regressions.
