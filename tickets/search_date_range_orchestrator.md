# Search Date Range - Ticket Orchestrator

## Source Spec
[10_search_date_range_build_plan.md](../10_search_date_range_build_plan.md)

## Execution Order

Run tickets **sequentially**. This stack changes shared search contracts, so do not parallelize implementation.

| Order | Ticket | Summary |
|------:|--------|---------|
| 1 | [T99](T99_shared_date_scope_and_scoped_stats.md) | Shared date scope contract, SQL predicates, scoped budget stats, scoped transcript loading |
| 2 | [T100](T100_simple_search_date_range_fts_and_keyword.md) | Simple search date range for FTS5 and expanded keyword, including UI and pagination |
| 3 | [T101](T101_embedding_search_date_range.md) | Date-scoped message and chunk embedding search before final top-K |
| 4 | [T102](T102_conversational_whole_transcript_date_scope.md) | Conversational scoped budgeting, whole-transcript mode, scoped validation |
| 5 | [T103](T103_exhaustive_scan_date_scope.md) | Date-scoped exhaustive window planning and retrieval hints |
| 6 | [T104](T104_conversational_date_range_ui_and_context_behavior.md) | Conversational UI wiring, logging, and explicit context-expansion behavior |
| 7 | [T105](T105_search_date_range_regression.md) | Regression pass, edge cases, and stress-test readiness |

## Global Decisions

- Date range is an explicit retrieval and analysis scope for both simple and conversational search.
- Date filtering happens before token budgeting, answer-mode selection, transcript serialization, exhaustive window planning, embedding filtering, and retrieval-hint generation.
- No hidden fallback to unscoped search is allowed.
- Evidence/context expansion remains normal and may include neighboring messages outside the selected date range.
- Chunk embedding scope is **intersection-based**: a chunk is in scope if any part of its message range intersects the selected date range.
- Date bounds are **inclusive**.
- Empty scoped result sets must fail visibly with a clear user-facing message before any model call.

## Guardrails

- Do not add speculative convenience behavior.
- Do not add multiple date-filter implementations that can drift apart.
- Keep one shared date-scope contract and reuse it everywhere.
- Preserve existing logging style and add scope visibility at important boundaries.
- Do not silently truncate in-scope results.
- Do not date-limit evidence-block context expansion.

## Review Standard

Before closing the stack, verify:

1. Simple search result counts are scoped and accurate.
2. Conversational mode selection is computed from scoped stats.
3. Whole transcript payloads contain only scoped message IDs.
4. Exhaustive scan windows and hint blocks contain only scoped messages.
5. Embedding search scopes candidates before final top-K return.
6. Context expansion still shows nearby out-of-range messages when the user opens evidence.
