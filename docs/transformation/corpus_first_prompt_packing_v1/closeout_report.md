# Corpus-First Prompt Packing V1 - Closeout Report

## Outcome

The production extraction path now uses one authoritative corpus-first user
object constructor. Every window extraction request serializes the stable
window identity and complete message stream before query-dependent fields:

```text
task -> window_id -> messages -> question -> analysis_plan
     -> retrieval_queries -> suggestion_ranges
```

Planning, retrieval reservation, actual fit checks, debug capture, and provider
execution use the same generated object. No public API, client, EVW, model,
provider, prompt text, synthesis packing, retry, cancellation, or ledger
validation contract was changed.

## Files changed

- `server/conversation_unified.py`: authoritative constructor and all extraction
  call sites; internal packing observability.
- `tests/test_corpus_first_prompt_packing.py`: exact-order, prefix-stability,
  escaping, changed-window, and fake-provider integration tests.
- `docs/transformation/corpus_first_prompt_packing_v1/spec.md`: implementation
  specification.
- `docs/transformation/corpus_first_prompt_packing_v1/execution_log.md`: exact
  execution record.

Previously dirty files were not reverted or rewritten as part of this work.

## Test results

- Focused: 24 passed.
- Full Python suite: 200 passed, 2 deselected.
- Python compilation: passed.
- Diff whitespace check: passed for tracked implementation files.
- Direct question-first extraction-constructor residue: none in production.

## Production smoke

The ready 700K corpus was run end-to-end through the live server with the
question “When did we fight about school?”. The run used 9 windows and reached
structured synthesis. It accepted 40 evidence ranges, rejected none, and
reported 6 high-probability and 7 lower-probability results. The result was
`complete_with_warnings`; the warnings were existing ledger/synthesis behavior,
not packing failures.

The request’s debug capture proves all nine extraction requests used the exact
corpus-first key order and the `corpus_first_v1` packing identifier. The first
production cache signal was observed: 512 cache-read input tokens and 105,565
cache-miss input tokens on window 6. Other windows did not report cache fields.
Those counters are now persisted in the admin usage totals.

## Deferred quality work

The run still exposed endpoint-order normalizations and synthesis omissions,
and the model can produce overlapping or lower-relevance ranges. Those issues
were deliberately preserved and are not silently filtered by this change.
They require a separate prompt-engineering/quality pass.

## Handoff

The server is running with corpus-first extraction packing. The complete live
artifacts are under:

`.tmp/700k-corpus-first-live/20260801T201205Z-2f78159a`
