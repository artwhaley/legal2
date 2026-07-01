Solid plan — it matches `AGENTS.md` and the forensic-tool posture. A few gaps and tensions worth resolving before execution.

**Strengths**

- Philosophy is clear and actionable; the “log fallbacks, don’t hide them” pattern for items 1, 6, 12, 14, 15 is the right default for this codebase.
- Block ordering (visibility → behavior → integrity → router → config → threading) is sensible.
- Item 8 (`hit_index_for_message` → raise) is high-value; returning `0` is genuinely dangerous in an evidence tool.
- Item 10 correctly separates `import_succeeded` from overall `success`; that’s the right semantic split.

**Internal tensions**

- **Item 7 vs philosophy:** The doc says “no silent retry / no hidden fallbacks,” then marks context-limit auto-recovery as acceptable. That’s a real product exception — worth stating explicitly (like item 13 retries), not “no change required.”
- **Item 4 vs** `05_large_dataset_performance_patch_spec.md`**:** That spec says malformed FTS queries should return empty results, not propagate errors. Pick one contract before Block B; they contradict each other.
- **Item 13 vs** `AGENTS.md` **“No silent retries”:** Logging at WARNING isn’t enough if the user never sees retries. Either require UI/status surfacing for retries, or document router retries as an approved exception with visible feedback (status bar, conversational system message, etc.).

**Already partly done / duplicate**

- **Item 2:** `model_runs.py` already emits `system_role_folded` when the fold succeeds via the router path. Client-level logging still helps for direct `NimClient` callers, but this isn’t fully silent today — scope item 2 as “close the gap for non-router paths” or merge with item 2’s verification step.

**Scope gaps**

- **Item 5 is too narrow:** `background_tasks.py:64` also catches `BaseException` and is used app-wide (search, conversational, home load). Same Ctrl+C issue lives there; fixing only `embedding_worker.py` leaves most background work broken on interrupt.
- `llm/retry.py:27`**:** Also catches `BaseException`; item 13 should include fixing that when wiring retries.
- **Logging mechanism:** The plan mixes `logging.getLogger(...)` with the app’s dominant `ProcessLogger` pattern. For user-visible audit trails, prefer `ProcessLogger` (or pass logger into those modules) so fixes show up in the process log UI, not only stderr.

**Item-specific notes**

- **Item 4:** Re-raising is right for “fail hard,” but raw `sqlite3.OperationalError` in the status bar will be opaque. Consider a typed `FtsQueryError` with the user’s query preserved — still fails loud, but readable.
- **Item 8:** Raising will surface corrupt evidence-block boundaries; good, but audit callers in `evidence_blocks.py` / transcript UI so users get a clear message, not a stack trace.
- **Item 10:** `home_tab.py` often uses `handoff=True` and checks `import_succeeded` / `embedding_available` separately, so `success=False` may be fine there — but trace every `DatasetLoadResult.success` consumer (settings load, tests, any automation) before changing the flag.
- **Item 9:** Dropping the hardcoded Gemini default is correct. Keeping the NIM base URL default is reasonable (endpoint, not model).
- **Item 14:** Table lists 9 sites but the heading says 10 — reconcile the inventory.
- **Item 16:** `atexit` + daemon threads is a weak fix on Qt shutdown; fine as “minimum viable,” but don’t treat it as closing the SQLite corruption risk. The example runner still uses `except BaseException`, which conflicts with item 5.

**Verification section**

- Block B manual tests are right; add automated tests for FTS syntax failure propagation and `hit_index_for_message` raise.
- Block D needs a test that asserts retry attempts are logged (and ideally visible), not just that a second call happens.
- Full `pytest tests/` after a large pull is slow; call out the relevant subsets per block (e.g. `test_load_dataset_pipeline`, `test_search_worker`, `test_model_router_retry`).

**Bottom line:** The plan is worth executing. Before starting, resolve the FTS contract conflict, widen item 5 to `background_tasks.py`, align logging with `ProcessLogger`, and explicitly carve out which retries/recoveries are product-approved exceptions vs violations of the “fail hard” ethos.

Investigating FTS query construction, `DatasetLoadResult` usage, and logging paths so we can answer your questions and draft a hardened plan spec.

## **Item 4 — the tension, and your instinct is right**

**What the tension actually is**

- `04_audit_remediation_plan.md` says: re-raise FTS syntax errors so the user knows the query was bad.
- `05_large_dataset_performance_patch_spec.md` says: malformed queries should return empty, not throw.

Those are two different failure contracts. Neither is what you want.

**Important nuance: this is not a “slow query” problem.** A bad FTS `MATCH` string fails immediately with `OperationalError`. It does not scan the dataset for days. The real harm of the current code is **lying** (“0 results”) not **lag**.

**Can user input in the search box cause this?**

Mostly no — if our builders work correctly.

Today the pipeline is:

- **Exact / keyword chips:** `escape_fts_phrase()` → quoted phrase (generally safe).
- **Partial / prefix lane:** `build_prefix_query()` → space-separated tokens, strips `"` and `*`, but does **not** fully neutralize FTS5 operators.
- **Paginated path:** `_candidate_specs_for_query()` unions many generated candidates; **one bad candidate kills the whole page query**.
- **Legacy non-paginated path:** per-candidate calls in `_run_fts_query()`; syntax errors on one variant are swallowed into `[]`.

So malformed MATCH strings are mostly an **internal query-generation bug**, not “user typed something crazy.” Likely sources:


| **Source**                                                             | **Risk**                    |
| ---------------------------------------------------------------------- | --------------------------- |
| Prefix tokens that are FTS keywords (`OR`, `AND`, `NOT`, `NEAR`, etc.) | Operator interpretation     |
| Spellfix / variant tokens with odd punctuation                         | Bad prefix query            |
| Empty/near-empty token after normalization                             | Edge-case MATCH             |
| One bad candidate in SQL UNION pagination                              | Entire search returns empty |


`test_malformed_partial_query_returns_empty` (`":::"`) never hits FTS at all — tokenization returns nothing. That test is about empty input, not syntax recovery.

**Recommendation (replaces current item 4):**

Don’t choose between “re-raise” and “return []”. **Make invalid MATCH strings impossible from app code**, and isolate failures at the candidate level:

1. Add a single FTS query validator/sanitizer used by all builders before SQL.
2. Quote or reject FTS reserved tokens in prefix mode.
3. In `_search_candidates_sql`, run/count per candidate (or skip invalid specs at build time) — never fail the whole search because one variant is bad.
4. Log skipped/invalid candidates via **ProcessLogger** at WARNING with `raw_query`, `fts_query`, `match_type`.
5. User-facing outcome: valid searches always return results; if **all** candidates are invalid, show a clear status message (“Search could not run — no valid search terms after normalization”), not fake zero hits.

Also add a line to reconcile `05_large_dataset_performance_patch_spec.md`: replace “return empty on malformed” with “app must not emit malformed MATCH strings; skip bad candidates and log.”

---



## **Item 13 — retries**

Agreed: **every retry attempt** must land in the Setup process log (ProcessLogger), including attempt number, delay, error type, provider/model/role, and final outcome. Optionally mirror a one-line summary to the status bar for conversational/search paths — but ProcessLog is the source of truth.

Also fix `llm/retry.py` to catch `Exception`, not `BaseException`, when wiring retries.

---



## **Three scope gaps — what to change**


| **Gap**                                           | **Change**                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `background_tasks.py` **catches** `BaseException` | Same fix as item 5: `except Exception` in the runner. Add tracked shutdown: registry of active worker threads + `shutdown_event` checked before starting new work.                                                                                                                                                                 |
| `llm/retry.py` **catches** `BaseException`        | Change to `Exception`. Document that retries never intercept Ctrl+C.                                                                                                                                                                                                                                                               |
| **stdlib** `logging.getLogger` **in the plan**    | **Policy:** all audit remediation logs use `ProcessLogger` (SQLite + LogBus → Settings log UI). Modules without a logger param get `logger: ProcessLogger` added, or receive it from caller. Stdlib logging only for pre-bootstrap failures (extension load before DB), and even then queue/replay into ProcessLog once available. |


**Yes — ProcessLogger is what feeds the day-to-day log.** It writes to `process_log` in the workspace DB and publishes on `LogBus`; Settings tab subscribes live and `refresh_persisted_logs()` reloads from DB. Stderr alone is not acceptable for anything users need when debugging.

---



## **Item 8 — human-readable errors**

Raise a dedicated error (e.g. `MessageIdNotFoundError`) with: message id, caller context (evidence block id / artifact id if known), list length. UI catches it and shows something like: *“Evidence block references message msg_042, which is not in this thread (847 messages loaded).”* ProcessLogger ERROR with full details.

---



## **Item 10 — trace of** `DatasetLoadResult.success`

**Current contract is muddy.** `success=True` is used for import OK, embedding failed, embedding skipped, and embedding cancelled.

**Consumers:**


| **Location**                         | **Uses** `success` **how**                                                                              |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `run_dataset_load_pipeline`          | Always `success=True` when import OK, even if embedding failed (line 492) — **misleading**              |
| `run_embedding_pipeline` except path | `success=True`, `embedding_available=False` (line 436)                                                  |
| `home_tab._on_pipeline_finished`     | `handoff or result.success` for `load_completed` (line 390) — but most paths pass `handoff=True` anyway |
| `home_tab` generally                 | Already branches on `import_succeeded`, `embedding_available`, `embedding_error`                        |
| `main_window`                        | Uses `dataset_id`, `embedding_available`; does **not** gate on `success`                                |
| `test_load_dataset_pipeline`         | Asserts `import_succeeded` / `embedding_available`; barely uses `success`                               |


**Recommended contract (put in plan):**

import_succeeded  — dataset rows are in DB

embedding_available — vector search ready

embedding_error   — why embedding failed (if applicable)

success           — import_succeeded AND (

```
                    embedding not requested

                    OR embedding skipped by user

                    OR embedding_available

                  )
```

- Import failed → `success=False`, `import_succeeded=False`
- Import OK, embedding failed → `success=False`, `import_succeeded=True`, `embedding_available=False`
- Import OK, embedding skipped → `success=True`, `embedding_available=False` (intentional partial product state)
- Import OK, embedding OK → `success=True`, `embedding_available=True`

**UI change:** `home_tab` handoff should use `import_succeeded`, not `success` — dataset should open after import even when embedding failed (that already works via status + retry button).

**Tests to update:** `test_embedding_skip_smoke`, add explicit `success=False` assertion for embedding failure path.

---



## **Item 9 — remove NIM base URL default**

Agree. Remove defaults in:

- `NimSettings.api_base_url` (currently `"https://integrate.api.nvidia.com/v1"`)
- `llm/providers/nim_provider.py` `or "https://..."`
- Any other hidden fallback

Fresh install: blank fields in settings JSON. Router raises `ModelRouterError("NIM API base URL is not configured")` when empty — same pattern as missing model. Settings UI can show placeholder hint text, but persisted value stays blank until user saves.

**Do not** remove env-var API key injection on fresh install — that’s separate from URL defaults.

---



## **Item 14 — who is right on the count?**

The table lists **9 sites**. The “10” heading is wrong unless you add a 10th intentionally.

Sites **correctly in item 14** (corrupt DB JSON → empty default + log): all 9 listed.

Sites **correctly excluded** (different items):

- `keyword_expansion.py` → item 6
- `tool_runner.py` → item 12
- `normalized_loader.py` → import integrity; should **fail import**, not silent default (optional new item 14b or footnote)

**Fix:** Change heading to “9 sites” OR add `normalized_loader.py` as #10 with policy “re-raise / fail import, do not substitute `{}`.”

---



## **Item 16 — recommendation**

Skip `atexit` as the primary mechanism (Qt shutdown order is unreliable). Prefer:

**Phase 1 (in plan):**

- `background_tasks`: `except Exception`; thread registry; `request_shutdown()` from `MainWindow.closeEvent`
- Before starting work: if shutdown requested, don’t start
- DB workers: `try/finally` with `conn.close()` on worker connection (each thread owns its connection — already mostly true)

**Phase 2 (future ticket):**

- `join(timeout=…)` on active workers during shutdown
- Cancel tokens for embedding/search pipelines (partially exists)

**Phase 3 (future):**

- Non-daemon threads for DB-writing jobs only

Drop the plan’s `atexit` snippet or mark it as explicitly rejected.

---



## **Item 7 — document as approved exception**

Context-limit auto-recovery stays, but label it under **“Approved product exceptions”** alongside router retries: visible system message + status + ProcessLogger WARNING + original error preserved.

---



# **Complete patch spec for** `04_audit_remediation_plan.md`

Apply these edits to the plan document (not code yet):

### **1. Add section after Philosophy: “Logging contract”**

**## Logging Contract**

All remediation work logs through `ProcessLogger`, not stdlib `logging`, except pre-bootstrap failures before a workspace connection exists (and those must be replayed or duplicated into ProcessLog once bootstrap completes).

The Settings tab process log is the primary user-facing diagnostic surface. Every item below must produce entries visible there (live via LogBus or on refresh).

Required fields where applicable: `component`, `operation`, `severity`, human-readable `message`, structured `details`, optional `exc`, `dataset_id`.

### **2. Add section: “Approved product exceptions”**

**## Approved Product Exceptions**

These are intentional recoveries, not silent degradation:

- **Item 7 — Context limit auto-recovery:** whole-transcript fails → visible system message, status label, ProcessLogger WARNING with model/generation/learned limit, then exhaustive window scan.
- **Item 13 — Router retries:** transient 429/5xx/timeout/network only; each attempt logged at WARNING; final failure logged at ERROR and raised.
- **Item 2 — System role fold:** one retry after model rejects system role; ProcessLogger WARNING before retry (client) and on success (model_runs); no further retries.



### **3. Replace item 4 entirely**

**Title:** `search/fts.py` — Prevent malformed FTS MATCH strings (do not rely on runtime syntax catch)

**Problem:** Syntax-error handling returns empty results or would re-raise, masking query-builder bugs. Paginated SQL UNION fails entirely when one candidate is bad.

**Fix:**

1. Centralize FTS query validation/sanitization for exact, prefix, and keyword paths.
2. Neutralize or reject FTS5 reserved tokens in prefix mode.
3. Validate every candidate in `_candidate_specs_for_query` / `_candidate_specs_for_keyword_terms` before SQL.
4. Per-candidate failure: skip candidate, ProcessLogger WARNING (never fail whole search).
5. If zero valid candidates remain: return empty with explicit reason code; UI status: human-readable message (not “0 results”).
6. Remove special-case `if "syntax error"...: return []` branches once builders are hardened; keep as defensive assert/log in dev tests only if desired.

**Cross-doc:** Update `05_large_dataset_performance_patch_spec.md` guardrail to match.

**Tests:** Reserved-token queries, punctuation-only queries, multi-candidate union with one bad variant, regression that normal queries still paginate.

**Block:** Move from B to new **Block B2 — FTS query builder hardening** (before Block B crash-fix).

### **4. Update item 2**

Add note: “Verify `model_runs` already logs `system_role_folded`; item 2 closes gap for direct `NimClient` calls. Log **before** retry at client level via ProcessLogger passed into client or injected callback.”

Remove `logging.getLogger("nim.client")`.

### **5. Update items 1, 3, 6, 11, 12, 14, 15**

Replace all `logging.getLogger(...)` / `logging.error()` / `logging.warning()` with `ProcessLogger` pattern. Note modules needing `logger` parameter threading (`db/connection.py`, `db/workspace.py`, etc.).

### **6. Expand item 5 → “Background exception handling (items 5 + 16 phase 1)”**

**Files:**

- `ui/embedding_worker.py` (3 sites)
- `ui/background_tasks.py` (runner)
- `llm/retry.py` (retry loop)

**Fix:** `except Exception` everywhere listed. Add shutdown registry + `request_shutdown()` hook from main window close.

Remove `atexit` example from item 16; replace with Phase 1/2/3 above.

### **7. Rewrite item 8**

Add `MessageIdNotFoundError` (or `ValueError` subclass). UI surfaces human-readable message. ProcessLogger ERROR. List callers to audit: `evidence_blocks.py`, `slots_from_message_boundary_ids`, transcript widgets.

### **8. Rewrite item 9**

Remove NIM `api_base_url` default in:

- `config/settings.py` `NimSettings`
- `llm/providers/nim_provider.py`
- Any merge/migration that injects default URL

Raise `ModelRouterError` when URL blank. Fresh install leaves blank; settings UI shows non-persisted placeholder hint only.

Remove “evaluate whether NIM base URL default is acceptable.”

### **9. Rewrite item 10 with explicit contract**

Include the success/import_succeeded/embedding_available table above.

**Files:** `dataset_load_pipeline.py` (lines 436, 492), `home_tab.py` (line 390 → use `import_succeeded` for handoff).

**Tests:** `test_load_dataset_pipeline.py::test_embedding_skip_smoke` + new assertion embedding failure → `success=False`.

### **10. Fix item 14 heading**

Change “10 sites” → **“9 sites (corrupt persisted JSON metadata)”**.

Add footnote or item **14b:** `importers/normalized_loader.py` — JSON decode failures during import must fail import with line number, not silent substitute.

Remove duplicate sites covered by items 6 and 12 from item 14 count.

### **11. Expand item 13**

Add:

- ProcessLogger WARNING on each retry attempt with `attempt`, `max_attempts`, `delay_seconds`, `error_type`, `provider`, `model`, `task_role`
- ProcessLogger ERROR on exhaustion with full chain
- Fix `retry.py` BaseException
- UI optional one-line status for user-initiated operations (conversational/search)
- `retry_max_attempts` in settings (default 2), persisted

Clarify: retries are **approved exception** when logged.

### **12. Replace Verification section entirely**

**## Verification**

**### After every block**

- `pytest tests/` (or block-specific subset below)
- `python -m message_evidence_workstation.app` starts
- Spot-check Settings → process log shows new entries at expected severity

**### Block A (logging visibility)**

- Subset: tests touching each modified module
- Manual: trigger one known fallback (e.g. corrupt JSON fixture) → WARNING appears in Settings log

**### Block B2 (FTS hardening)**

- `pytest tests/test_fts.py tests/test_search_worker.py tests/test_fts_pagination_hydration.py`
- Manual: search `OR`, `:::`, `"unbalanced`, expanded-keyword chips with punctuation
- Confirm: no fake “0 results” when candidates invalid; status message is human-readable

**### Block B (crash-fix)**

- `pytest tests/test_embedding_completion_no_ui_block.py`
- Manual: Ctrl+C during embedding job and during simple search

**### Block C (data integrity)**

- `pytest tests/test_load_dataset_pipeline.py tests/test_model_router.py`
- Manual: misconfigured Google model → clear settings error, not silent gemini-2.0-flash
- Manual: evidence block with stale message id → human-readable error, not wrong highlight

**### Block D (retry)**

- `pytest tests/test_model_router_retry.py`
- Manual: simulate 429 → ProcessLog shows attempt 1 failed, attempt 2 (or final ERROR)
- Confirm: auth/400 errors do not retry

**### Block E (settings)**

- `pytest tests/test_model_routing_settings.py` + keyword expansion tests
- Manual: change max expansion terms → truncation logged when capped

**### Block F (threading phase 1)**

- Manual: close app during background search → no hang; ProcessLog shows cancel/shutdown if applicable

**### Block G (NIM system-role fold)**

- `pytest tests/test_message_roles.py tests/test_nim_client.py`
- Confirm: WARNING in ProcessLog before fold retry



### **13. Update Execution Order**

Block A — Error visibility (items 1, 3, 6, 11, 12, 14, 15)

Block B2 — FTS query builder hardening (replaces old item 4)

Block B — Background exception handling (items 5, 16 phase 1, retry.py BaseException)

Block C — Data integrity (items 8, 9, 10)

Block D — Router retry wiring (item 13)

Block E — Configuration (item 17)

Block F — Threading phase 2 (future ticket; phase 1 merged into Block B)

Block G — NIM system-role fold logging (item 2)

### **14. Add cross-reference note at top**

> Resolves tension with `05_large_dataset_performance_patch_spec.md` §4 guardrail: see Item 4 (FTS hardening).

> Resolves tension with `AGENTS.md`: Items 7 and 13 are documented approved exceptions when fully logged and visible.

---

**Bottom line:** Your direction on item 4 is the right one — fix query generation, don’t debate empty vs throw. ProcessLogger is the right sink for everything users will actually read. Item 10’s fix is a clear boolean contract plus one line in `home_tab`. Item 14’s table is right at 9; fix the heading. Item 16 should be shutdown-aware threading, not `atexit`.

Want me to apply this patch spec directly to `04_audit_remediation_plan.md` in the repo next?