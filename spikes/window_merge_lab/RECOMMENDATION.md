# Window Merge Lab — Findings & Recommendations

## Summary

The spike tested five merge strategies for combining per-window LLM scan outputs into a coherent final answer. Strategies ranged from deterministic (no LLM) to multi-turn hierarchical merging, using the six saved scan windows from model runs 165-170 for the query "Show me all the times we talked about school."

## Strategy Observations

| Strategy | Calls | Dry-run Valid | Notes |
|----------|-------|--------------|-------|
| `one_shot_compact` | 1 | Yes | Simplest; single prompt with all six window summaries |
| `hierarchical_balanced` | 3 | Yes | Bounded merging; split into 1-3, 4-6, then final |
| `rolling_synthesis` | 6 | Yes | Sequential; each merge call depends on previous output |
| `evidence_table_then_synthesis` | 1 | Yes | Table normalization; may be best for deduplication |
| `deterministic_baseline` | 0 | Yes | Control only; no synthesis |

All strategies with non-zero call counts produced valid prompt payloads in dry-run mode. The deterministic baseline confirmed 67 total answer ranges across 6 windows, with no invalid message IDs and full window coverage.

## Recommendations for Production Merge Redesign

### 1. Parallel Scan Calls
The current production `run_exhaustive_window_scan_answer` scans windows sequentially. The scan calls for each window are independent and could run in parallel to reduce wall-clock time. Use a `ThreadPoolExecutor` or `asyncio` with timeouts.

### 2. Persisted/Resumable Scan and Merge Artifacts
The current design discards per-window scan results after the merge completes. Persisting intermediate artifacts (window findings with parsed ranges) enables:
- Resuming from a failed merge without rescanning all windows
- Comparing merge strategies against the same scan data
- Debugging and auditing scan quality per window

### 3. Bounded Merge Call Counts
The `hierarchical_balanced` and `rolling_synthesis` strategies demonstrate bounded merge patterns. The production `_run_bounded_exhaustive_window_merge` already has a recursive splitting approach. The spike's explicit strategies (3-call or 6-call bounded) provide clearer alternatives:
- **Hierarchical**: predictable 3 calls regardless of window count
- **One-shot**: single merge call if context window permits

### 4. Retry/Backoff for Transient Provider Failures
The production `ModelRouter` already supports retry via `call_with_retry` in `llm/retry.py`. Ensure retry is active for all scan and merge calls, not just expansion.

### 5. Better Progress UI
The spike GUI shows call count and status per strategy. The production UI should show:
- Number of scan calls completed / total
- Token budget per scan call
- Merge phase (scanning vs. merging)
- Per-call latency and any partial errors

### 6. Evidence Table as an Intermediate Step
The `evidence_table_then_synthesis` strategy normalizes ranges into a flat table before synthesis. This intermediate representation could serve as:
- An input for deterministic deduplication before the final LLM call
- A human-reviewable artifact showing what the model will receive
- A structured input that makes the final merge prompt more compact

### 7. Window Coverage Validation
The evaluator in this spike checks whether all source windows appear represented in the merge output. This check should be automated in production: if the merge output omits a window's findings, flag it immediately rather than silently discarding evidence.

## Next Steps

1. Run all five strategies against the same scan data with a real model call to assess output quality.
2. Compare output quality between `one_shot_compact` and `hierarchical_balanced` — the former may drop details from later windows, while the latter may over-preserve duplicate findings.
3. Consider the `evidence_table_then_synthesis` path as a candidate for production because it separates normalization from synthesis.
4. If the full transcript fits within the context window, prefer `whole_transcript` mode over scan+merge.
