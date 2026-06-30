# WML20 - Ledger Synthesis Tests And Handoff

## Goal

Add regression tests and handoff docs for the new unified ledger synthesis strategy.

## Depends On

- WML19

## Scope

Add tests for:

- ledger record generation
- stable `range_id`
- stable `source_range_key`
- source-batch context generation
- full prompt profile
- compact prompt profile
- anti-window-language guidance
- payload-based budget estimation (provisional-build path + mode selection)
- injection-hardening language
- deterministic validation success path
- deterministic validation failure paths
- compact mode accepted as valid when structurally correct
- **end-to-end flow**: ledger → budget → prompt builder → execute → validate → evaluator display
  (wire the full chain in one test; use `_noop_model_call` to avoid real API calls)
- **bijection enforcement**: input with N `range_id`s → output with same N `range_id`s = pass;
  missing one = fail; extra one = fail; duplicate = fail

Update docs:

- mention `evidence_ledger_synthesis` as the recommended spike path
- explain that full and compact are both normal modes
- explain that compact is preservation-first, not a failure
- explain that source windows are token-packed implementation artifacts
- explain remaining future work belongs in a later production integration stack

## Handoff Notes

Remaining concerns before production integration (document, do not implement here):

1. **Provisional-build overhead**: The WML16 flow builds candidate messages once or
   twice before selecting a profile. Production may want a single-pass estimator
   that does not require building messages, or caching of provisional messages.
   The spike proves it works; production can optimize.
2. **`range_id` collision across runs**: The spike generates `range_id` within a
   single run. Production will need to ensure IDs are either globally unique or
   scoped per search/query to avoid cross-contamination in cached results.
3. **No synthesis-time refusal**: The LEDGER explicitly excludes refusal behavior.
   Production should evaluate whether refusal (e.g., "I cannot answer this
   question") should be a valid mode or a hard validation error.
4. **Message ID normalization beyond trimming**: The spike normalizes by
   whitespace-stripping only. Production may need case normalization or
   prefix stripping depending on data source conventions.

## Guardrails

- Do not claim production readiness beyond what the spike actually proves
- Do not reintroduce synthesis-time refusal behavior
- Do not blur the spike-only boundary

## Acceptance Criteria

- Spike-local tests cover the new ledger strategy end to end
- End-to-end wire test covers ledger → budget → run → validate → display
- Bijection tests cover pass, missing, extra, and duplicate cases
- Docs clearly describe the recommended path
- Handoff explains what still remains before production integration

