# Corpus-First Prompt Packing V1 - Execution Log

## Baseline

- Repository: `C:\Users\artwh\OneDrive\Documents\legal2`
- Branch: `main`
- HEAD at start: `60e731f9dd6c02696d8ab43cd012eba1bfacc061` (`Status reports`)
- Worktree was already dirty. Existing user changes were preserved; no reset,
  clean, checkout, commit, push, or PR operation was performed.
- The authoritative implementation specification was read before editing:
  `docs/transformation/corpus_first_prompt_packing_v1/spec.md`.

## Implementation

- Added `_window_extraction_user` in `server/conversation_unified.py`.
- Replaced extraction user-object construction in window planning, retrieval
  reservation, actual fit checks, and live extraction calls.
- Exact production extraction order is:
  `task`, `window_id`, `messages`, `question`, `analysis_plan`,
  `retrieval_queries`, `suggestion_ranges`.
- Added internal extraction observability:
  `packing_strategy=corpus_first_v1` and the existing window-plan hash are
  attached to provider-attempt context.
- Added `tests/test_corpus_first_prompt_packing.py` for exact order, stable
  prefix behavior, escaping, changed-window behavior, and a live fake-provider
  request assertion.

## Validation

Focused command:

```text
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.tmp\pytest-corpus-first-focused tests/test_corpus_first_prompt_packing.py tests/test_sfv1_conversation_hardening.py tests/test_sfv1_conversation_unified.py tests/test_qpa1_orchestration.py
```

Result: **24 passed**, 1 existing Starlette/httpx deprecation warning.

Full command:

```text
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.tmp\pytest-corpus-first-full
```

Result: **200 passed, 2 deselected**, 1 existing Starlette/httpx deprecation
warning.

Additional checks:

- Changed Python files compiled successfully.
- `git diff --check` passed for tracked implementation files.
- Residue scan found no direct production `_user("window_evidence_extraction", ...)`
  construction; remaining `_user` calls are planning/synthesis/compaction paths.
- Existing cache-accounting tests remained green.

## Server restart

- Restarted the loopback server after implementation.
- New listener PID: `25024`.
- `GET /admin/events`: HTTP 200.

## Live 700K production run

Runner output directory:

`.tmp/700k-corpus-first-live/20260801T201205Z-2f78159a`

- Requested question: `When did we fight about school?`
- Ready corpus: EVW revision 4, 12,402 messages, 720,646 counted transcript
  tokens / approximately 700K stored membership tokens.
- The historical revision 2 was attempted first and correctly refused before
  provider work because its embedding index was stale/missing. The requested
  run then used ready revision 4.
- Production route completed planning, retrieval, 9 extraction windows, and
  synthesis.
- Window plan hash:
  `798b2ddc064424761259b2326b0cdbdf3738d4fb1b740dac12e7e0d152e0b561`.
- All 9 extraction requests used the exact corpus-first key order and
  `packing_strategy=corpus_first_v1`.
- Extraction: 40 accepted ranges, 0 rejected ranges, 4 deterministic endpoint
  normalizations, 0 unavailable windows.
- Final result: `complete_with_warnings`, structured synthesis,
  `multi_window_ledger`, 6 high-probability results, 7 lower-probability
  results, 8 unclassified ledger ranges, 0 unverified model statements.
- Provider cache telemetry: window 6 reported 512 cache-read input tokens and
  105,565 cache-miss input tokens. The other 8 extraction windows omitted
  cache fields. No cache-write tokens were reported.
- Persisted admin totals after the run: 512 cache-read tokens, 105,565
  cache-miss tokens, 0 cache-write tokens, 1 provider-reported cache row.
- The runner restored the temporary 60% window-utilization setting and stopped
  debug capture. No automatic rerun or provider fallback occurred.

## Deferred work

Nested evidence-range cleanup, lower-relevance precision, and prompt-definition
tuning were intentionally not changed by this implementation. They remain
separate prompt-quality work as required by the specification.
