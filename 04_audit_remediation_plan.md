# Audit Remediation Plan: Fail Noisy, Fail Hard

## Philosophy

This project (`message_evidence_workstation`) is a forensic evidence review tool. Every data point, every provenance chain, and every error matters.

We do not:

- Silently retry.
- Hide fallback paths.
- Swallow exceptions with `except: pass`.
- Invent operational defaults that make a broken configuration look valid.
- Run speculative background work without an explicit product reason.
- Truncate or cap user-relevant evidence silently.

We do:

- Fail noisy: every error is logged with context.
- Fail hard when data is missing, corrupted, or misconfigured.
- Log every fallback and recovery path.
- Surface retries when a retry is an approved product behavior.
- Preserve all valid evidence and provenance.

## Out Of Scope

Embedding startup, model loading, embedding background work, and embedding status semantics are owned by the embedding service refactor currently in progress. Do not implement embedding-related remediation from this plan.

Specifically excluded here:

- Any changes to `ui/embedding_worker.py`.
- Any changes to embedding model preload behavior.
- Any changes to embedding model cache/network behavior.
- Any changes to `DatasetLoadResult` semantics that are specifically about embedding failure or embedding availability.

The remediation work below should not duplicate, partially patch, or route around that service.

## Logging Contract

All audit remediation logs must be visible in the app's process log UI. Use `ProcessLogger` where a workspace connection exists.

Stdlib logging is acceptable only before a workspace connection or `ProcessLogger` exists. If a pre-bootstrap warning matters to the user, duplicate or replay it into `ProcessLogger` after bootstrap when practical.

Required log fields where applicable:

- `component`
- `operation`
- severity
- human-readable `message`
- structured `details`
- optional `exc`
- optional `dataset_id`

Do not add stderr-only logging for anything users need when diagnosing normal app behavior.

## Approved Product Exceptions

These behaviors are recoveries, not silent degradation. They are allowed only when the original failure and recovery path are visible.

- Context-limit auto-recovery: whole-transcript answer fails due to context limit, the user sees a system/status message, `ProcessLogger` records the original error and recovery details, then exhaustive window scan may run.
- Router retries: transient 429, 5xx, timeout, and network failures only. Every attempt is logged at WARNING, final exhaustion is logged at ERROR, and the final error is raised.
- System-role fold retry: one retry after a provider rejects system role messages. The retry is logged before it happens, and successful folded calls remain auditable in model run metadata.

Retries for auth failures, missing models, missing API keys, invalid requests, safety blocks, parse failures, or configuration errors are not approved.

## Architecture Context

The app is a Python 3.11+ PySide6 desktop application with:

- SQLite database backend using FTS5 and sqlite-vec.
- LLM routing across NVIDIA NIM and Google AI Studio.
- Search combining FTS, vector search, and keyword expansion.
- Conversational answer workflows with whole-transcript and exhaustive-window paths.
- Process logging persisted into the workspace database and surfaced in Settings.

## Remediation Items

### 1. `search/token_budget.py` - tiktoken fallback visibility

Problem: import or tokenizer failures fall back to heuristic token counting without user-visible diagnostics.

Fix:

- Replace silent fallback with a `ProcessLogger` warning where a logger is available.
- Include the tokenizer name, exception, and the heuristic fallback that will be used.
- If this module cannot receive a logger at call time, return structured fallback metadata to the caller so the caller logs it.

Tests:

- Simulate tokenizer import/use failure.
- Assert fallback still works.
- Assert the caller emits a visible warning.

### 2. `nim/client.py` - system-role fold retry visibility

Problem: when a NIM model rejects system role messages, the client may fold system messages into user content and retry. This is an approved recovery only when visible.

Fix:

- Verify router/model-run paths already record `system_role_folded`.
- Close the gap for direct `NimClient` callers.
- Log before retry via `ProcessLogger` passed into the client or via an injected callback.
- Include provider, model, message count before/after folding, task role if known, and original error.
- Allow only one fold retry.

Do not use `logging.getLogger("nim.client")` for normal app-visible diagnostics.

Tests:

- Provider rejects system role.
- Warning is emitted before retry.
- Folded call succeeds and metadata records the fallback.
- Second failure raises visibly.

### 3. `db/connection.py` - SQLite extension loading support visibility

Problem: missing extension-loading support can be ignored, leading to later sqlite-vec failures with less useful errors.

Fix:

- If extension loading is unavailable before `ProcessLogger` exists, capture a pre-bootstrap warning.
- Replay or duplicate the warning into `ProcessLogger` after workspace bootstrap if sqlite-vec validation or vector features are used.
- Keep the original exception detail.

Tests:

- Simulate missing `enable_load_extension`.
- Assert connection still opens.
- Assert warning can be surfaced after bootstrap.

### 4. `search/fts.py` - prevent malformed FTS MATCH strings

Problem: runtime syntax handling either returns empty results or would raise raw SQLite errors. Both are the wrong primary contract. App code should not emit malformed `MATCH` strings, and one bad generated candidate should not collapse an otherwise valid search.

Fix:

1. Centralize FTS query validation/sanitization for exact, prefix, and keyword paths.
2. Neutralize or reject FTS5 reserved tokens in prefix mode.
3. Validate every candidate produced by `_candidate_specs_for_query` and `_candidate_specs_for_keyword_terms` before SQL execution.
4. For per-candidate failures, skip that candidate and emit a `ProcessLogger` WARNING with `raw_query`, `fts_query`, `match_type`, and candidate source.
5. If zero valid candidates remain, return an explicit invalid-query outcome and show a human-readable UI status message. Do not show fake "0 results" without explanation.
6. Remove special-case syntax-error-to-empty branches after builders are hardened, or keep them only as defensive logs around impossible states.

Cross-document note:

- This resolves the tension with `05_large_dataset_performance_patch_spec.md`: the app should not rely on "return empty on malformed FTS." It should avoid malformed FTS, skip invalid generated candidates with logging, and explain when no valid candidates remain.

Tests:

- Reserved-token queries such as `OR`, `AND`, `NOT`, and `NEAR`.
- Punctuation-only input such as `:::`.
- Unbalanced quote input.
- Multi-candidate search where one generated candidate is invalid.
- Normal paginated search still returns expected hits.

### 5. Background exception handling and shutdown phase 1

Problem: background runners catch `BaseException`, which can intercept `KeyboardInterrupt` and `SystemExit`. Daemon background work also lacks a clear shutdown contract.

Embedding worker changes are intentionally excluded from this plan.

Files:

- `ui/background_tasks.py`
- `llm/retry.py`
- Any non-embedding background runner discovered during implementation

Fix:

- Change broad `except BaseException` handlers to `except Exception` in the listed non-embedding paths.
- Add a shutdown registry for background tasks.
- Add `request_shutdown()` and call it from `MainWindow.closeEvent`.
- Before starting new work, check whether shutdown was requested.
- Ensure worker-owned database connections close in `finally` blocks.

Do not treat an `atexit` handler as the primary fix. Qt shutdown order is too important here.

Future ticket:

- Join active non-daemon DB-writing workers with a bounded timeout during app shutdown.

Tests:

- Background task exception still surfaces through UI callback.
- `KeyboardInterrupt` and `SystemExit` are not swallowed.
- Closing the app during non-embedding background work requests shutdown cleanly.

### 6. `search/keyword_expansion.py` - parse fallback visibility

Problem: several parse strategies are attempted in sequence. If earlier strategies fail and later strategies salvage output, the model malformed-output event is hidden.

Fix:

- Pass `ProcessLogger` into keyword expansion from workflow callers.
- Log each failed parse strategy at WARNING with strategy name and raw content preview.
- On success after one or more failures, log which strategy succeeded and how many strategies failed first.
- Keep output parsing deterministic.

Tests:

- Valid JSON root parse emits no warning.
- Bracket extraction salvage emits warning.
- Quoted-string fallback emits warning.
- Total parse failure logs and returns the intended explicit fallback.

### 7. Context-limit auto-recovery verification

Problem: this is an approved product exception, but the plan must verify visibility rather than assuming it.

Fix:

- Confirm whole-transcript context-limit recovery logs original error, model, generation/run id, learned context limit, selected fallback strategy, and final outcome.
- Confirm the user sees a system/status message before fallback work begins.
- If any field is missing, add it through `ProcessLogger` and UI status surfaces.

Tests:

- Simulated context-limit error produces visible warning.
- Recovery path records the original error and fallback strategy.
- Non-context errors do not use this recovery path.

### 8. `domain/slots.py` - missing message IDs must raise typed errors

Problem: returning index `0` for a missing `message_id` creates false provenance and wrong highlights.

Fix:

- Add `MessageIdNotFoundError`, preferably a `ValueError` subclass.
- Include message id, ordered id count, and caller context if available.
- Replace `return 0` with raising this error.
- Audit callers including `evidence_blocks.py`, `slots_from_message_boundary_ids`, transcript widgets, and artifact/export paths.
- UI callers should surface a human-readable message and log `ProcessLogger` ERROR with structured details.

Tests:

- Missing message id raises `MessageIdNotFoundError`.
- UI boundary catches and displays a clear message.
- Valid message id behavior is unchanged.

### 9. Model configuration must not invent model or endpoint defaults

Problem: hardcoded provider/model defaults make misconfiguration look valid.

Fix:

- Remove hardcoded Google model fallback such as `gemini-2.0-flash`.
- Remove hidden NIM base URL defaults from persisted settings and provider construction.
- Fresh install should leave provider endpoint/model fields blank.
- Settings UI may show placeholder hints, but placeholders must not become persisted configuration.
- Router raises a clear `ModelRouterError` when a provider endpoint, API key, or model is not configured.
- Preserve environment-variable API key injection; that is explicit deployment configuration, not an invented model.

Files to audit:

- `config/settings.py`
- `llm/router.py`
- `llm/providers/nim_provider.py`
- `llm/providers/google_provider.py`
- Settings UI hydration/migration paths

Tests:

- Fresh settings do not persist default model names.
- Missing Google model raises clear router error.
- Missing NIM base URL raises clear router error.
- Placeholder UI text does not save as config.

### 10. `db/workspace.py` - missing metadata table visibility

Problem: returning `{}` when `workspace_metadata` is absent hides schema/setup damage.

Fix:

- Use `ProcessLogger` where available.
- Before bootstrap logging is available, capture a pre-bootstrap warning.
- Include workspace path and current schema state if available.
- Continue returning `{}` only if callers can safely proceed; otherwise raise a typed workspace/schema error.

Tests:

- Missing metadata table logs warning.
- Normal empty metadata table does not log corruption warning.

### 11. `search/tool_runner.py` - JSON repair visibility

Problem: planner JSON repair tries multiple candidate strings. A salvage success hides malformed model output.

Fix:

- Track each candidate strategy and exception details.
- Log each failed strategy at DEBUG or structured trace level.
- On success after prior failures, log WARNING with winning strategy and failed strategy summaries.
- On total failure, include attempted strategies in `PlannerParseError` details.
- Use `ProcessLogger` from caller context.

Tests:

- Clean JSON parses with no warning.
- Substring repair logs warning.
- Trailing-comma repair logs warning.
- Total failure raises `PlannerParseError` with attempted strategies.

### 12. Persisted JSON metadata decode failures - 9 sites

Problem: corrupt persisted JSON metadata is sometimes replaced with empty defaults. That may be acceptable for non-critical metadata, but corruption must be visible.

Policy:

- For corrupt persisted metadata fields where the app can continue, return the safe empty/default value and log a `ProcessLogger` WARNING.
- For import-time source JSON failures, fail import with line/file context instead of substituting empty data.

Sites to remediate:

| File | Context to log |
| --- | --- |
| `embeddings/index_jobs.py` | existing JSON preview or `embedding_index_id` |
| `search/session_map.py` | `message_id` or `session_id` |
| `search/window_planner.py` | `message_id` |
| `nim/context_limits.py` | body preview |
| `nim/message_roles.py` | body preview |

Note: embedding implementation details are owned by the embedding service refactor. Do not edit embedding code under this plan unless the embedding service work explicitly leaves one of these call sites in place for audit remediation.

Add item 12b for imports:

- `importers/normalized_loader.py`: JSON decode failures during import should fail import with file/line/source context and a visible process log entry.

Tests:

- Corrupt persisted metadata logs warning and continues where policy allows.
- Corrupt import JSON fails import and reports source context.

### 13. Malformed value fallback visibility

Problem: malformed timestamps, message IDs, and indices can fall back to `None`, `0`, or `"unknown"` without context.

Fix:

- Log a `ProcessLogger` WARNING before returning any safe fallback.
- Include raw value and local context such as message id, source thread id, dataset id, or UI surface.
- Missing message id in `domain/slots.py` is not a fallback case; item 8 raises.

Sites to audit:

| File | Context to log |
| --- | --- |
| `search/session_map.py` | raw timestamp value |
| `search/grouping.py` | raw value |
| `search/transcript.py` | raw timestamp and message id |
| `ui/transcript_display.py` | raw timestamp |
| `ui/transcript_surface.py` | raw value and context |
| `ui/transcript_data_source.py` | raw value |

Embedding-specific malformed value handling is excluded from this plan.

Tests:

- Each fallback path logs warning.
- Valid values produce no warning.

### 14. Router retry strategy

Problem: retry behavior must be centralized, typed, and visible. Hidden retries violate the app posture.

Fix:

- Wire `call_with_retry` into `ModelRouter.chat()`.
- Fix `llm/retry.py` to catch `Exception`, not `BaseException`.
- Add `retry_max_attempts` to settings, defaulting to `2` only if product-approved. If not product-approved, default to `1`.
- Retry only transient error types:
  - `quota_exceeded`
  - `server_error`
  - `timeout`
  - `connection_error`
- Do not retry:
  - auth failures
  - missing model
  - missing API key
  - invalid request
  - model not configured
  - safety block
  - parse errors
- Add NIM/Google error classification for HTTP 5xx as `server_error`.
- Log every retry attempt at WARNING with attempt, max attempts, delay seconds, error type, provider, model, and task role.
- Log final exhaustion at ERROR with the full error chain and raise the last error.
- For user-initiated operations, mirror a concise status line when a retry happens.

Tests:

- 429 retries and logs attempts.
- 5xx retries and logs attempts.
- Timeout retries and logs attempts.
- 400/401/403/404 do not retry.
- Final failure raises last error.
- Ctrl+C/SystemExit is not caught by retry loop.

### 15. Search expansion term cap must be explicit

Problem: `MAX_EXPANSION_TERMS = 20` silently discards extra query-expansion terms.

Policy:

- This cap is for generated search-query expansion terms, not evidence.
- It must never drop evidence records or search hits.
- Prefer constraining the model prompt to request the configured maximum.
- If returned expansion terms still exceed the configured maximum, log the cap visibly.

Fix:

- Add `max_expansion_terms` to `SearchSettings`.
- Persist it in settings JSON.
- Surface it in Settings search controls.
- Pass it into keyword expansion instead of reading a module-level hardcoded constant.
- Log when generated expansion terms are capped, including requested cap and returned count.

Tests:

- Settings migration persists default.
- Custom setting changes expansion cap.
- Over-limit expansion logs warning.
- Capping expansion terms does not cap evidence results.

### 16. NIM system-role fold verification

Problem: item 2 is the implementation work; this item verifies all paths that can make NIM calls are covered.

Fix:

- Inventory direct `NimClient` callers.
- Confirm router callers log model-run metadata.
- Confirm non-router callers receive `ProcessLogger` or a logging callback.
- Remove or route direct callers where practical.

Tests:

- Direct client path logs fold retry.
- Router path logs fold retry and model-run metadata.

## Execution Order

Block A - Plan prep:

- Apply this plan document.
- Confirm embedding service work owns all embedding-related changes.
- Remove embedding work from remediation tickets created from this plan.

Block B - Error visibility:

- Items 1, 3, 6, 10, 11, 12, 13.
- Low behavior risk; mostly logging and typed surfaced diagnostics.

Block C - FTS query builder hardening:

- Item 4.
- Must happen before any "raise on syntax error" style cleanup.

Block D - Background exception handling:

- Item 5.
- Excludes embedding worker/service paths.

Block E - Data integrity and configuration:

- Items 8 and 9.
- Raises or blocks bad state instead of pretending it is usable.

Block F - Router retry wiring:

- Item 14.
- Implement only with visible logging and product-approved retry count.

Block G - Search expansion configuration:

- Item 15.
- Settings + keyword expansion behavior.

Block H - NIM system-role fold coverage:

- Items 2 and 16.
- Close direct-client gaps after router behavior is verified.

Future threading ticket:

- Non-daemon DB-writing workers.
- Join active workers with timeout during shutdown.
- Broader cancellation and progress reporting.

## Verification

After every implementation block:

- Run the relevant test subset for touched modules.
- Run broader `pytest tests/` before merging the full remediation branch.
- Launch `python -m message_evidence_workstation.app`.
- Spot-check Settings process log for expected WARNING/ERROR entries.
- Confirm no remediation work changes embedding service behavior unless explicitly coordinated.

Block B - Error visibility:

- Trigger at least one known fallback.
- Confirm warning appears in Settings process log with structured details.

Block C - FTS hardening:

- `pytest tests/test_fts.py tests/test_search_worker.py tests/test_fts_pagination_hydration.py`
- Manual searches: `OR`, `AND`, `NOT`, `NEAR`, `:::`, `"unbalanced`, and punctuation-heavy keyword expansion.
- Confirm invalid generated candidates are logged and do not collapse valid candidates.
- Confirm all-invalid input yields human-readable status, not fake "0 results."

Block D - Background exception handling:

- Manual Ctrl+C during non-embedding background search or model call.
- Confirm `KeyboardInterrupt`/`SystemExit` are not swallowed.
- Confirm app close requests shutdown for active non-embedding workers.

Block E - Data integrity and configuration:

- `pytest tests/test_model_routing_settings.py tests/test_model_router_retry.py`
- Missing Google model produces clear settings/router error.
- Blank NIM endpoint produces clear settings/router error.
- Stale evidence-block message id produces human-readable error, not wrong highlight.

Block F - Router retry:

- `pytest tests/test_model_router_retry.py`
- Simulated 429 or 5xx logs attempt 1 and final outcome.
- Auth/400 errors do not retry.
- ProcessLog contains provider, model, task role, attempt, delay, and error type.

Block G - Search expansion configuration:

- Keyword expansion tests.
- Settings persistence tests.
- Manual over-limit model output shows cap warning.

Block H - NIM system-role fold:

- `pytest tests/test_message_roles.py tests/test_nim_client.py`
- Confirm ProcessLogger warning before fold retry.
- Confirm model-run metadata records folded system role where applicable.
