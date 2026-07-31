# Flutter Client Layout Intentionality - Ticket Orchestrator

## Goal

Implement the requested transcript-sidebar, evidence-category, Conversation-tab, and runtime pane-resizing changes without redesigning unrelated behavior.

## Execution Order

Run these tickets sequentially.

| Order | Ticket | Summary |
|------:|--------|---------|
| 1 | [T106](T106_flutter_evidence_category_persistence_and_default_titles.md) | Add explicit category lifecycle operations, explicit block-targeted mutations, category-aware creation, and hit-message default titles |
| 2 | [T107](T107_flutter_evidence_category_sidebar.md) | Build the collapsible category tree, category rename/delete/merge UI, category-aware creation, drag/drop, and explicit sidebar block selection |
| 3 | [T108](T108_flutter_transcript_sidebar_layout_cleanup.md) | Move the evidence sidebar left, make it the only deletion surface, relocate New/Delete, and remove the specified toolbar and copy |
| 4 | [T109](T109_flutter_conversation_chrome_cleanup.md) | Remove the scoped-question description and Ready card while changing Send to Stop during an active request |
| 5 | [T110](T110_flutter_persisted_resizable_work_areas.md) | Make vertical sidebars and top/bottom work areas runtime-resizable with persisted, safely clamped sizes |
| 6 | [T111](T111_flutter_layout_regression_and_smoke.md) | Lock the complete behavior with widget, persistence, and real-EVW smoke coverage |

## Global Guardrails

- Do not redesign unrelated Flutter surfaces.
- Do not change transcript rendering, virtual scrolling, evidence boundary behavior, primary-message behavior, highlighting, or hide/show behavior.
- Evidence-block deletion must always receive an immutable block ID from an explicit sidebar selection or direct right-click on that sidebar row. Viewport activity is never a deletion target.
- Category removal must never delete evidence blocks. A non-empty category can only be removed by an atomic merge into another category.
- Preserve `Uncategorized` as the permanent default category; it cannot be renamed, deleted, or used as a merge source.
- Do not add category colors, descriptions, category ordering, or block ordering.
- Do not add instructional or explanatory copy.
- Do not add keyboard shortcuts in this stack.
- Do not introduce a schema migration. EVW schema v15 already has `category.is_collapsed`, `evidence_block.category_id`, and `workspace_setting`.
- Do not truncate stored evidence titles. The two-line truncation is a sidebar presentation rule only.
- Persist category mutations, block moves, title edits, and pane sizes before reporting success.
- Surface the original error when a persistence operation fails; do not silently retry or leave the UI showing an unpersisted result.

## Completion Standard

The stack is complete only when T111 passes and the manual smoke confirms persistence after closing and reopening a disposable real schema-v15 EVW.
