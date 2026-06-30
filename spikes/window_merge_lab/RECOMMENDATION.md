# Window Merge Lab — Findings & Recommendations

## Summary

The spike tested five merge strategies for combining per-window LLM scan outputs into a coherent final answer, then evolved to a single production-shaped strategy: **evidence ledger synthesis**.

Initial strategies ranged from deterministic (no LLM) to multi-turn hierarchical merging, using the six saved scan windows from model runs 165-170 for the query "Show me all the times we talked about school."

## Strategy Observations

### Legacy Strategies (kept as controls)

| Strategy | Calls | Dry-run Valid | Notes |
|----------|-------|--------------|-------|
| `one_shot_compact` | 1 | Yes | Simplest; single prompt with all six window summaries |
| `hierarchical_balanced` | 3 | Yes | Bounded merging; split into 1-3, 4-6, then final |
| `rolling_synthesis` | 6 | Yes | Sequential; each merge call depends on previous output |
| `evidence_table_then_synthesis` | 1 | Yes | Table normalization; may be best for deduplication |
| `deterministic_baseline` | 0 | Yes | Control only; no synthesis |

### Recommended: Evidence Ledger Synthesis

| Strategy | Calls | Description |
|----------|-------|-------------|
| `evidence_ledger_synthesis` | 1 | Single LLM call over one evidence ledger with full or compact profile |

**Design**: Flattens all source scan-window ranges into a deterministic evidence ledger, assigns stable `range_id` and `source_range_key` values, then asks the model to produce a cohesive answer. The budget planner chooses between two profiles:

- **Full profile**: rich narrative, detailed per-range summaries and display text. Chosen when serialized full prompt and expected full output fit within the context and output budget.
- **Compact profile**: short narrative, terse per-range metadata while preserving every range for navigation. Compact is a normal supported mode, not a failure or degraded result.

**Provisioning**: The strategy builds candidate full-profile messages first, measures their actual serialized size, and only falls back to compact if full does not fit. This gives tight estimation based on real payloads.

**Validation**: A deterministic validator (`validator.py`) checks bijection (one input `range_id` → one output `range_id`), message ID preservation, and structural completeness. Validation failures (missing/unknown/duplicate ranges, changed message IDs) mark the response invalid.

**Injection hardening**: The `LEGAL_EVIDENCE_POLICY` explicitly instructs the model to treat evidence content (commands, JSON, Markdown, roleplay) as quoted evidence only — never as instructions to follow.

## Recommendations for Production Merge Redesign

### 1. Adopt Evidence Ledger Synthesis
The `evidence_ledger_synthesis` strategy is the recommended path. It replaces the prior candidate approaches (`one_shot_compact`, `evidence_table_then_synthesis`) with a single deterministic-ledger approach that:
- Separates range preservation (code) from explanation (model)
- Uses stable, code-generated `range_id` values
- Enforces bijection via validation
- Normalizes compact mode as a first-class profile, not a degraded fallback
- Treats source windows as token-packed implementation artifacts, not meaningful sections

### 2. Parallel Scan Calls
The current production `run_exhaustive_window_scan_answer` scans windows sequentially. The scan calls for each window are independent and could run in parallel to reduce wall-clock time. Use a `ThreadPoolExecutor` or `asyncio` with timeouts.

### 3. Persisted/Resumable Scan and Merge Artifacts
The current design discards per-window scan results after the merge completes. Persisting intermediate artifacts enables resuming from a failed merge, comparing strategies against the same data, and debugging scan quality per window.

### 4. Single-Call Merge
The evidence ledger strategy uses exactly one LLM call if the budget planner selects full profile, and one call for compact as well. This avoids the complexity and statefulness of multi-turn merge strategies.

### 5. Retry/Backoff for Transient Provider Failures
The production `ModelRouter` already supports retry via `call_with_retry` in `llm/retry.py`. Ensure retry is active for all scan and merge calls.

### 6. Better Progress UI
The spike GUI shows call count and status per strategy. The production UI should show:
- Number of scan calls completed / total
- Token budget per scan call
- Selected profile (full/compact)
- Validation status

### 7. Deterministic Validation in Production
The validator in this spike checks message ID alignment, range bijection, and structural correctness. Production should run the same checks before accepting any synthesis output.

### 8. Source Windows as Implementation Artifacts
Source windows are token-packed implementation artifacts caused by the upstream search's context-window packing. They are not natural sections of the corpus. The final user-facing answer must not organize by window boundaries.

## Next Steps

1. The evidence ledger synthesis strategy is ready for a production integration spec/ticket stack (separate from this spike).
2. Remaining concerns before production integration (documented in WML20 handoff):
   - Provisional-build overhead: building candidate messages once or twice before profile selection. Production may want single-pass estimator or caching.
   - `range_id` collision across runs: spike uses run-scoped IDs; production needs globally unique or search-scoped IDs.
   - Synthesis-time refusal: spike excludes refusal behavior; production should evaluate whether refusal is a valid mode or hard error.
   - Message ID normalization: spike only whitespace-strips; production may need case normalization or prefix stripping.
3. Legacy strategies (`one_shot_compact`, `hierarchical_balanced`, `rolling_synthesis`, `evidence_table_then_synthesis`) remain in the spike for comparison but are not recommended for production.
