# AGENTS.md

## Product Ethos
This app must be functionally correct, sequential, observable, and boring in the best way.
Do not optimize for the appearance of intelligence, smoothness, or cleverness at the cost of predictability.

Build a truly functional app, not an app that merely looks functional.

## Core Operating Rules
1. Prefer simple, explicit, linear flows over clever abstractions, speculative preloading, background coordination, or hidden automation.
2. Fail noisy. Do not silently retry, swallow exceptions, degrade invisibly, or continue after a broken prerequisite unless the product explicitly requires that behavior.
3. Do not invent convenience behavior. If a feature was not requested, do not add it just because it seems helpful.
4. Never hide state transitions. Important work must have visible start, progress, success, and failure reporting.
5. Never arbitrarily drop, truncate, cap, or suppress valid data or valid results unless the product spec explicitly requires it.
6. Treat every unexpected error as a real bug to surface and fix, not something to smooth over.
7. Build the actual functional contract first. UX polish, preload behavior, fallback behavior, and smart defaults come later and only if explicitly requested.
8. Prefer one obvious way to do something. Avoid duplicate code paths that appear equivalent but behave differently.
9. If a step depends on another step, execute them in order and prove each step works before starting the next.
10. When in doubt, choose the less magical implementation.

## Coding Rules
1. No silent retries.
2. No hidden fallbacks between strategies, providers, models, or execution paths unless explicitly specified.
3. No best-effort behavior that risks data loss, silent omission, or misleading partial success.
4. No placeholder logic left in production paths.
5. No no-op controls or UI that suggests capabilities that do not truly exist.
6. No speculative background work that races against the main user action unless the product explicitly requires concurrency there.
7. Every control-flow branch in a production path should exist for a concrete, documented reason.
8. Prefer direct, inspectable state changes over implicit coordination.

## Visibility And Logging
1. Important operations must emit clear start, progress, completion, and failure signals.
2. If the first attempt fails, the user should know that it failed.
3. Logging must clarify what the app is doing, not obscure it.
4. Error handling should preserve the original failure cause whenever possible.

## Data Integrity Rules
1. The app must never arbitrarily discard valid evidence, valid ranges, or valid model output.
2. If the system needs to reduce, merge, filter, rank, or summarize, that behavior must be explicit, justified, and reviewable.
3. Budgeting mechanisms must control orchestration cost, not silently erase valid information.
4. If completeness is a product requirement for a path, preserve completeness even when it is inconvenient.

## Review Standard
Before shipping a change, ask:
- Is this simpler than before?
- Is failure more visible than before?
- Is behavior more deterministic than before?
- Does this remove magic instead of adding it?
- Would a user be able to understand exactly what the app is doing?

If the answer is no, revise the implementation.

## Agent-Specific Guardrail
Do not add speculative helpful behavior to unblock yourself.
If the straightforward implementation is incomplete or failing, expose the real issue and fix it directly.

Do not optimize for looking finished.
Optimize for being correct, understandable, and trustworthy.

## Anchored Summary <!-- agent-summary -->

### Current State
TKT-01 through TKT-05 of the evidence-ledger merge feature are implemented and passing (31 evidence-ledger tests + 31 conversational-answer tests + existing tests = 88 total green).

**Session work (not ticket-tracked — prefix-agent work before checkpoint):**
- `window_planner.py`: replaced hardcoded `chars_per_token=4` with real ratio derived from tiktoken on the full dataset transcript during planning. Added `_compute_chars_per_token()`, added `chars_per_token` parameter to `_pack_thread_message_stream_into_windows`. All 9 window planner tests pass.
- **T97 — Hit-Only Range Repair**: added `RangeRepairRecord` dataclass, `repaired_answer_ranges` field on `ConversationalAnswerResult`, misorder → hit-only repair logic in `_parse_answer_range`, repair uncertainty text, logging. 2 new unit tests + 1 integration test.
- **T98 — Granular Recall**: added `EXHAUSTIVE_SCAN_TARGET_WINDOW_TOKENS = 128_000`, recall cap via `min(budget.usable_input_tokens, EXHAUSTIVE_SCAN_TARGET_WINDOW_TOKENS)`, updated `exhaustive_scan_preflight` logging. 1 integration test.

| Ticket | File(s) | Status |
|--------|---------|--------|
| TKT-01 | `search/evidence_ledger.py` | Done |
| TKT-02 | `nim/prompts.py`, `llm/task_roles.py` | Done |
| TKT-03 | `search/ledger_validator.py` | Done |
| TKT-04 | `config/settings.py`, `search/conversational_answer.py` | Done |
| TKT-05 | `tests/test_evidence_ledger.py` | Done |
| T97 | `search/conversational_answer.py` — `RangeRepairRecord`, hit-only repair in `_parse_answer_range`, logging | Done |
| T98 | `search/conversational_answer.py` — `EXHAUSTIVE_SCAN_TARGET_WINDOW_TOKENS`, recall cap in `exhaustive_scan_preflight` | Done |
| — | `search/window_planner.py` — real `chars_per_token` from tiktoken | Done |

### Next Steps (not yet started)
- Smoke-test the feature by running an exhaustive window scan answer with `use_evidence_ledger_merge=True`.
- Set `use_evidence_ledger_merge` as default `True` after live validation.
- Remove legacy `_run_bounded_exhaustive_window_merge` path once new path is stable in production.

### Key Architectural Context
- Evidence ledger replaces ad-hoc range deduplication with a deterministic range-ID assignment (`r000001`..`r00000N`) and a two-phase pipeline: build → model synthesize → validate → assemble.
- Feature is gated by `AnswerSettings.use_evidence_ledger_merge` (default `False`); legacy path preserved side-by-side.
- `plan_ledger_budget` profiles three tiers: full, compact, overflow — controls prompt format (detailed/brief) and output guardrails.
- Validator enforces bijection: every input range must produce exactly one output range with matching message IDs and source range keys.
- The synthesis prompt includes `LEGAL_EVIDENCE_POLICY` injection hardening and instructs the model to cite by `range_id` only, not reconstruct raw answer_ranges.
