# Ticket Index

- [T00 - Repo Bootstrap](tickets/T00_repo_bootstrap.md)
- [T01 - SQLite Schema and Process Log](tickets/T01_sqlite_schema_and_process_log.md)
- [T02 - Normalized Dataset Loader](tickets/T02_normalized_dataset_loader.md)
- [T03 - PySide6 Shell Sidebar and Settings Log](tickets/T03_pyside6_shell_sidebar_and_settings_log.md)
- [T04 - Source Thread and Message Viewer](tickets/T04_source_thread_and_message_viewer.md)
- [T05 - Categories and Workstation Conversations](tickets/T05_categories_and_workstation_conversations.md)
- [T06 - FTS5 Indexing](tickets/T06_fts5_indexing.md)
- [T07 - Simple Search UI and Result Grouping](tickets/T07_simple_search_ui_and_result_grouping.md)
- [T08 - Drag Search Results to Categories](tickets/T08_drag_search_results_to_categories.md)
- [T09 - NIM Settings and Client](tickets/T09_nim_settings_and_client.md)
- [T10 - Prompt Templates and ModelRun Audit](tickets/T10_prompt_templates_and_modelrun_audit.md)
- [T11 - Keyword Expansion Search](tickets/T11_keyword_expansion_search.md)
- [T12 - Embedding Model Registry and Adapters](tickets/T12_embedding_model_registry_and_adapters.md)
- [T13 - sqlite vec Validation and Diagnostics](tickets/T13_sqlite_vec_validation_and_diagnostics.md)
- [T14 - Message Embedding Index](tickets/T14_message_embedding_index.md)
- [T15 - Chunk Embedding Index](tickets/T15_chunk_embedding_index.md)
- [T16 - Embedding Search UI Integration](tickets/T16_embedding_search_ui_integration.md)
- [T17 - Conversational Search Planner and Tools](tickets/T17_conversational_search_planner_and_tools.md)
- [T18 - Conversational Result Synthesis](tickets/T18_conversational_result_synthesis.md)
- [T19 - Output Formatting View](tickets/T19_output_formatting_view.md)
- [T20 - Range Suggestion and Highlight Overrides](tickets/T20_range_suggestion_and_highlight_overrides.md)
- [T21 - HTML Export Preview](tickets/T21_html_export_preview.md)
- [T22 - Audit and Log Export](tickets/T22_audit_and_log_export.md)
- [T23 - Packaging and Final Smoke Tests](tickets/T23_packaging_and_final_smoke_tests.md)
- [T24 - Simple Search Evidence Block Workflow](tickets/T24_simple_search_evidence_block_workflow.md)
- [T25 - Model Router Call Inventory and Task Roles](tickets/T25_model_router_call_inventory_and_task_roles.md)
- [T25B - Answer Strategy Cleanup and Obsolete LLM Paths](tickets/T25B_answer_strategy_cleanup_and_obsolete_llm_paths.md)
- [T26 - Role-Based Model Settings and Migration](tickets/T26_role_based_model_settings_and_migration.md)
- [T27 - Central Model Router and Provider Types](tickets/T27_central_model_router_and_provider_types.md)
- [T28 - Route Existing NIM Calls Through Model Router](tickets/T28_route_existing_nim_calls_through_model_router.md)
- [T29 - Router Retry, Error Normalization, and Metering Hooks](tickets/T29_router_retry_error_normalization_and_metering_hooks.md)
- [T30 - Google AI Studio Provider Support](tickets/T30_google_ai_studio_provider_support.md)
- [T31 - Role-Based Model Settings UI](tickets/T31_role_based_model_settings_ui.md)
- [T32 - Model Router Regression and Smoke Suite](tickets/T32_model_router_regression_and_smoke_suite.md)
- [T33 - Conversational Condensed Answer Contract](tickets/T33_conversational_condensed_answer_contract.md)
- [T34 - Conversational Turn And Action Model](tickets/T34_conversational_turn_and_action_model.md)
- [T35 - Conversational Stream UI](tickets/T35_conversational_stream_ui.md)
- [T36 - Conversational Result Navigation And Block Creation](tickets/T36_conversational_result_navigation_and_block_creation.md)
- [T37 - Conversational Prompt Migration And Regression](tickets/T37_conversational_prompt_migration_and_regression.md)
- [T38 - Remove Source Thread Viewer](tickets/T38_remove_source_thread_viewer.md)
- [T39 - Printable Artifact Schema](tickets/T39_printable_artifact_schema.md)
- [T40 - Printable Artifact Domain And Repositories](tickets/T40_printable_artifact_domain_repositories.md)
- [T41 - Output Formatting Printable Artifact Tree](tickets/T41_output_formatting_artifact_tree.md)
- [T42 - Printable Artifact Editor And Block Order Controls](tickets/T42_printable_artifact_editor_and_block_order.md)
- [T43 - Printable Artifact Preview Pagination](tickets/T43_printable_artifact_preview_pagination.md)
- [T44 - Printable Artifact Provenance Ledger](tickets/T44_printable_artifact_provenance_ledger.md)
- [T45 - Output Formatting Regression And Cleanup](tickets/T45_output_formatting_regression_and_cleanup.md)

## Pre-scale hardening (see `04_pre_scale_hardening_spec.md`)

**Orchestrator:** [pre_scale_hardening_orchestrator.md](tickets/pre_scale_hardening_orchestrator.md) — execute **T46 → T63 in order**.

- [T46 - Context Window Settings Only](tickets/T46_context_window_settings_only.md)
- [T47 - Remove Archaic Answer Settings](tickets/T47_remove_archaic_answer_settings.md)
- [T48 - SQL Dataset Budget Stats](tickets/T48_sql_dataset_budget_stats.md)
- [T49 - Exhaustive Window Scan Packing](tickets/T49_exhaustive_window_scan_packing.md)
- [T50 - Provenance Reference And Bounded Artifact Load](tickets/T50_provenance_reference_and_bounded_artifact_load.md)
- [T51 - Streaming JSONL Import](tickets/T51_streaming_jsonl_import.md)
- [T52 - Batch Message Hydration](tickets/T52_batch_message_hydration.md)
- [T53 - FTS Pagination API](tickets/T53_fts_pagination_api.md)
- [T54 - Simple Search Pagination UI](tickets/T54_simple_search_pagination_ui.md)
- [T61 - Process Log Batch Mode](tickets/T61_process_log_batch_mode.md) — execute before T55 if possible
- [T55 - Load Dataset Tab And Startup Pipeline](tickets/T55_load_dataset_tab_and_pipeline.md)
- [T56 - Virtualized Transcript](tickets/T56_virtualized_transcript.md)
- [T57 - Print Layout Engine](tickets/T57_print_layout_engine.md)
- [T58 - Print Preview Widget And PDF](tickets/T58_print_preview_widget_and_pdf.md)
- [T59 - Remove Workstation Conversation Legacy](tickets/T59_remove_workstation_conversation_legacy.md)
- [T60 - Remove Obsolete LLM Prompts](tickets/T60_remove_obsolete_llm_prompts.md)
- [T62 - Embedding Resume Optimization](tickets/T62_embedding_resume_optimization.md)
- [T63 - Pre Scale Hardening Regression](tickets/T63_pre_scale_hardening_regression.md)

## Large dataset performance (see `05_large_dataset_performance_patch_spec.md`)

**Orchestrator:** [large_dataset_performance_orchestrator.md](tickets/large_dataset_performance_orchestrator.md) - execute **T64 -> T72 in order**.

- [T64 - Thread Ordinals and Indexed Transcript Access](tickets/T64_thread_ordinals_and_indexed_transcript_access.md)
- [T65 - Transcript Virtualization Cleanup](tickets/T65_transcript_virtualization_cleanup.md)
- [T66 - Remove Dataset-Wide UI Maps](tickets/T66_remove_dataset_wide_ui_maps.md)
- [T67 - Background Search Worker and Cancel](tickets/T67_background_search_worker_and_cancel.md)
- [T68 - Real SQL FTS Pagination](tickets/T68_real_sql_fts_pagination.md)
- [T69 - Explicit Search Modes UI](tickets/T69_explicit_search_modes_ui.md)
- [T70 - Expanded Keyword Mode Pagination](tickets/T70_expanded_keyword_mode_pagination.md)
- [T71 - Embedding Modes and Background Integration](tickets/T71_embedding_modes_and_background_integration.md)
- [T72 - Large Dataset Performance Regression](tickets/T72_large_dataset_performance_regression.md)

## New transcript widget demonstrator (see `06_new_transcript_widget_spec.md`)

**Orchestrator:** [new_transcript_widget_orchestrator.md](tickets/new_transcript_widget_orchestrator.md) - execute **T73 -> T80 in order**.

- [T73 - Parallel New Transcript Tab Shell](tickets/T73_parallel_new_transcript_tab_shell.md)
- [T74 - Document Backed Transcript Surface](tickets/T74_document_backed_transcript_surface.md)
- [T75 - Transcript Navigation and Demo Controls](tickets/T75_transcript_navigation_and_demo_controls.md)
- [T76 - Evidence Block Creation and Reveal](tickets/T76_evidence_block_creation_and_reveal.md)
- [T77 - Document Annotation Overlays](tickets/T77_document_annotation_overlays.md)
- [T78 - Boundary Drag and Overlay Persistence](tickets/T78_boundary_drag_and_overlay_persistence.md)
- [T79 - Hit Message and Highlight Editing](tickets/T79_hit_message_and_highlight_editing.md)
- [T80 - New Transcript Widget Regression](tickets/T80_new_transcript_widget_regression.md)

## Home startup and smart embeddings (see `07_home_startup_and_embeddings_spec.md`)

**Orchestrator:** [home_startup_embeddings_orchestrator.md](tickets/home_startup_embeddings_orchestrator.md) — execute **T81 → T87 in order**.

- [T81 - Embedding Completion Hang Fix](tickets/T81_embedding_completion_hang_fix.md)
- [T82 - Home Cold-Start Tab](tickets/T82_home_cold_start_tab.md)
- [T83 - Background Embedding Pipeline](tickets/T83_background_embedding_pipeline.md)
- [T84 - Per-Model Vec Partition Key](tickets/T84_per_model_vec_partition_key.md)
- [T85 - Embedding Progress Status Bar](tickets/T85_embedding_progress_status_bar.md)
- [T86 - Embedding Search Readiness Gating](tickets/T86_embedding_search_readiness_gating.md)
- [T87 - Home Startup and Embeddings Regression](tickets/T87_home_startup_embeddings_regression.md)

## Virtual transcript widget (see `08_virtual_transcript_widget_spec.md`)

**Orchestrator:** [virtual_transcript_widget_orchestrator.md](tickets/virtual_transcript_widget_orchestrator.md) - execute **T88 -> T96 in order**.

- [T88 - Virtual Transcript Third Tab Shell](tickets/T88_virtual_transcript_third_tab_shell.md)
- [T89 - Virtual Transcript SQL Model](tickets/T89_virtual_transcript_sql_model.md)
- [T90 - Virtual Transcript Height Index](tickets/T90_virtual_transcript_height_index.md)
- [T91 - Virtual Transcript Visible Renderer](tickets/T91_virtual_transcript_visible_renderer.md)
- [T92 - Virtual Transcript Scroll and Jump](tickets/T92_virtual_transcript_scroll_and_jump.md)
- [T93 - Virtual Transcript Annotation Painting](tickets/T93_virtual_transcript_annotation_painting.md)
- [T94 - Virtual Transcript Annotation Editing](tickets/T94_virtual_transcript_annotation_editing.md)
- [T95 - Virtual Transcript Demo Controls](tickets/T95_virtual_transcript_demo_controls.md)
- [T96 - Virtual Transcript Regression and Handoff](tickets/T96_virtual_transcript_regression_and_handoff.md)

## Search date range (see `10_search_date_range_build_plan.md`)

**Orchestrator:** [search_date_range_orchestrator.md](tickets/search_date_range_orchestrator.md) - execute **T99 -> T105 in order**.

- [T99 - Shared Date Scope And Scoped Stats](tickets/T99_shared_date_scope_and_scoped_stats.md)
- [T100 - Simple Search Date Range For FTS And Keyword](tickets/T100_simple_search_date_range_fts_and_keyword.md)
- [T101 - Embedding Search Date Range](tickets/T101_embedding_search_date_range.md)
- [T102 - Conversational Whole Transcript Date Scope](tickets/T102_conversational_whole_transcript_date_scope.md)
- [T103 - Exhaustive Scan Date Scope](tickets/T103_exhaustive_scan_date_scope.md)
- [T104 - Conversational Date Range UI And Context Behavior](tickets/T104_conversational_date_range_ui_and_context_behavior.md)
- [T105 - Search Date Range Regression](tickets/T105_search_date_range_regression.md)

## Flutter client layout intentionality

**Orchestrator:** [flutter_client_layout_orchestrator.md](tickets/flutter_client_layout_orchestrator.md) - execute **T106 -> T111 in order**.

- [T106 - Flutter Evidence Category Persistence And Default Titles](tickets/T106_flutter_evidence_category_persistence_and_default_titles.md)
- [T107 - Flutter Evidence Category Sidebar](tickets/T107_flutter_evidence_category_sidebar.md)
- [T108 - Flutter Transcript Sidebar Layout And Safe Deletion](tickets/T108_flutter_transcript_sidebar_layout_cleanup.md)
- [T109 - Flutter Conversation Chrome Cleanup And Send/Stop Control](tickets/T109_flutter_conversation_chrome_cleanup.md)
- [T110 - Flutter Persisted Resizable Work Areas](tickets/T110_flutter_persisted_resizable_work_areas.md)
- [T111 - Flutter Layout Regression And Smoke](tickets/T111_flutter_layout_regression_and_smoke.md)
