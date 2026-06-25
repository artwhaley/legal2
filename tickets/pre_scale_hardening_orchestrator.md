# Pre-Scale Hardening - Ticket Orchestrator

## Source Spec
[04_pre_scale_hardening_spec.md](../04_pre_scale_hardening_spec.md)

## Execution Order

Run tickets **sequentially** unless a dependency note explicitly allows parallel work.

| Order | Ticket | Spec Section | Summary |
|------:|--------|--------------|---------|
| 1 | [T46](T46_context_window_settings_only.md) | 8 | Settings-only context window; no 8192 default |
| 2 | [T47](T47_remove_archaic_answer_settings.md) | 7 | Remove four dead answer settings; wire overlap |
| 3 | [T48](T48_sql_dataset_budget_stats.md) | 1 | SQL budget stats; no full dataset load for mode pick |
| 4 | [T49](T49_exhaustive_window_scan_packing.md) | 2 | Max-pack windows with bounded planning; remove scan session rebuild |
| 5 | [T50](T50_provenance_reference_and_bounded_artifact_load.md) | 6, E | Metadata reference model; bounded artifact SQL |
| 6 | [T61](T61_process_log_batch_mode.md) | 18 | Batch log writes foundation for import/embed/load |
| 7 | [T51](T51_streaming_jsonl_import.md) | 5, D | Stream JSONL; format version check; failed-import state |
| 8 | [T52](T52_batch_message_hydration.md) | 10 | `fetch_messages_by_ids`; batched highlights |
| 9 | [T53](T53_fts_pagination_api.md) | 3 | Paginated merged FTS + total count |
| 10 | [T54](T54_simple_search_pagination_ui.md) | 3 | Search UI pages; no silent caps |
| 11 | [T62](T62_embedding_resume_optimization.md) | 15 | Resume without 100k-ID set |
| 12 | [T55](T55_load_dataset_tab_and_pipeline.md) | 9, A | Load Dataset tab; auto-embed; narrated pipeline |
| 13 | [T56](T56_virtualized_transcript.md) | 4 | Virtualized infinite-scroll transcript |
| 14 | [T57](T57_print_layout_engine.md) | 14.1 | Measured print layout engine |
| 15 | [T58](T58_print_preview_widget_and_pdf.md) | 14.2-14.4 | WYSIWYG preview + print + PDF |
| 16 | [T59](T59_remove_workstation_conversation_legacy.md) | 11, 19 | Drop legacy tables + HTML export |
| 17 | [T60](T60_remove_obsolete_llm_prompts.md) | 16 | Obsolete prompt cleanup |
| 18 | [T63](T63_pre_scale_hardening_regression.md) | F, checklist | Docs, scale tests, full regression |

## Global Guardrails

- Do not revert unrelated dirty worktree changes.
- Run focused tests after each ticket; run `python -m pytest -q` before closing T63.
- Session-coverage conversational path: **leave in place**; do not invest in redesign.
- Deferred: service layer, raw importers, env var consolidation.
- Completeness principle: paginate and batch-fetch; do not silently cap search results.
- Large-data principle: no new path may load a full dataset or giant thread unless the ticket explicitly bounds that load and documents why it is safe.
- Existing workstation-conversation table data is disposable test data (T59).

## Reviewing Agent

Read `04_pre_scale_hardening_spec.md` executive summary, then verify each ticket's acceptance criteria map to the spec review checklist before execution begins.
