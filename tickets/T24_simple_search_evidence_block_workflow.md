# T24 - Simple Search Evidence Block Workflow

## Goal

Replace the lower pane of Simple Search with the reusable evidence transcript widget so search results can immediately drive evidence block review and creation.

## Dependencies

T07, T08, evidence block schema/workflow work, transcript widget prototype work.

## Implementation Notes

The Simple Search page should stop using `SourceThreadView` in its lower pane and instead host the transcript widget surface and controls already proven in `TranscriptWidgetTab`.

Do not duplicate the transcript widget implementation inside `SimpleSearchTab`. For this ticket, promote the reusable transcript/evidence-block UI into a shared widget/module that both the dedicated `TranscriptWidgetTab` and `SimpleSearchTab` can host. This extraction should be done now because the same widget is expected to be reused later on the conversational search page as well.

Preferred shape:

- Keep `TranscriptWidgetTab` as a thin tab wrapper.
- Move the reusable transcript/evidence-block behavior into a shared widget such as `EvidenceBlockTranscriptWidget` or similarly named module under `message_evidence_workstation/ui/`.
- That shared widget should own:
  - thread loading into `EvidenceTranscriptModel`
  - speaker tint bar
  - transcript surface
  - create-from-viewport-center behavior
  - create-from-specific-hit behavior
  - overlay persistence
  - select/reveal existing evidence block behavior
- `TranscriptWidgetTab` may continue to own the thread picker combo box if that remains tab-specific.
- `SimpleSearchTab` should use the shared widget without a thread picker combo box.

The shared widget should expose a small explicit API instead of requiring callers to poke internal model state. Minimum expected methods/signals:

- `set_dataset(dataset_id: int | None) -> None`
- `load_source_thread(source_thread_id: str) -> None`
- `focus_message(message_id: str) -> None` or equivalent hit-centering helper
- `create_evidence_block_from_viewport_center(category_id: int | None = None) -> EvidenceBlock | None`
- `create_evidence_block_for_message(message_id: str, category_id: int | None = None) -> EvidenceBlock | None`
- signal `evidence_block_created(int)` for sidebar reveal/selection wiring

The creation methods above should be the only supported block-creation paths in the UI layer for this ticket. They should always:

- persist existing overlays before insert
- resolve `category_id=None` to `Uncategorized`
- compute default slots using the existing slot helper
- append the created block to the active transcript model
- scroll to the created block's core hit after insertion
- emit `evidence_block_created`

Single-clicking a grouped search result should load the source thread into the transcript widget, scroll to the hit message, and center that hit in the viewport. This is a navigation action only; it should not create or mutate an evidence block.

Double-clicking a grouped search result should perform the same navigation, then create a new evidence block anchored on that hit message using the existing default slot helper. The created block should go to `Uncategorized`, be appended to the transcript model, and remain visible in the transcript surface after creation.

The current Simple Search action that creates a workstation conversation from a selected search result should be removed or renamed so the user-facing action is now `Add evidence block`. That action should create a new uncategorized evidence block anchored on the transcript widget's current viewport-center message, matching the shared transcript widget behavior.

Dragging a search result into the left `Evidence Blocks` tree should keep the current drag payload shape, but the drop behavior should be treated as evidence-block creation only. Dropping onto blank space or outside a specific category should create the block in `Uncategorized`. Dropping onto a category header should create the block in that category. After drop, the sidebar should reveal/select the new block, and the Simple Search transcript widget should load that thread and scroll to the created block's core hit so the user sees the created artifact in context.

To support that reveal flow cleanly, the search-drop path should return the created `EvidenceBlock` from the sidebar/drop handler instead of only mutating sidebar state. Avoid re-deriving the created block from UI labels. The main window can then coordinate sidebar reveal plus transcript synchronization in one place.

Required event wiring:

1. Search-result single click:
   - `SimpleSearchTab` loads the result thread into the shared transcript widget.
   - `SimpleSearchTab` centers the primary hit message.
   - No block is created.
2. Search-result double click:
   - do the same navigation as single click
   - call shared-widget `create_evidence_block_for_message(primary_hit_message_id)`
   - reveal/select the created block in the sidebar
3. `Add evidence block` button:
   - call shared-widget `create_evidence_block_from_viewport_center()`
   - reveal/select the created block in the sidebar
4. Search-result drag/drop onto sidebar:
   - sidebar creates the block using the drop target category or `Uncategorized`
   - sidebar returns the created block or emits a dedicated signal containing its id and source thread
   - main window or tab wiring tells the shared transcript widget to load that thread and reveal the new block

Do not make the sidebar reach into `SimpleSearchTab` directly. Cross-panel coordination should happen through signals and `MainWindow`, keeping the sidebar reusable and decoupled.

The existing sidebar behavior of selecting an evidence block currently routes the user to the dedicated transcript tab. For this ticket, preserve that behavior unless it conflicts with the new Simple Search flow. The new requirement is only that block creation initiated from Simple Search leaves the user looking at the created block in the Simple Search transcript pane at the moment of creation.

Keep logging explicit for:

- result selection scroll
- result double-click create
- button create from viewport center
- drag-drop create with target category
- transcript widget thread load when triggered from search

Each log entry should include enough detail for debugging:

- `dataset_id`
- `source_thread_id`
- `message_id` or `core_hit_message_id`
- `evidence_block_id` when created
- `category_id` when created or moved
- source action (`result_select`, `result_double_click`, `search_drop`, `viewport_button`)

## Suggested Execution Plan

1. Extract the shared transcript/evidence-block widget from `TranscriptWidgetTab` without changing behavior.
2. Update `TranscriptWidgetTab` to wrap the shared widget and ensure existing transcript-widget tests still pass.
3. Replace the Simple Search lower pane with the shared widget and implement single-click result centering.
4. Implement double-click result creation and the `Add evidence block` action.
5. Update sidebar search-drop handling to return/emit the created block and wire the reveal flow back into Simple Search.
6. Add or update smoke tests for all three creation paths and the selection-only path.

## Files / Areas Likely Touched

- `message_evidence_workstation/ui/simple_search_tab.py`
- `message_evidence_workstation/ui/main_window.py`
- `message_evidence_workstation/ui/transcript_widget_tab.py`
- `message_evidence_workstation/ui/evidence_block_transcript_widget.py` (new shared module, preferred)
- `message_evidence_workstation/ui/transcript_surface.py`
- `message_evidence_workstation/ui/sidebar.py`
- `message_evidence_workstation/db/evidence_blocks.py`
- `tests/test_ui_smoke.py`

## Acceptance Criteria

- The lower pane of Simple Search shows the evidence transcript widget instead of the old search-context message list.
- Selecting a search result loads the matching source thread and scrolls the transcript widget to center on the primary hit message.
- Double-clicking a search result creates exactly one new uncategorized evidence block anchored on that hit message.
- The `Add evidence block` action creates an uncategorized evidence block anchored on the transcript viewport-center message.
- Creating a block from selection, button, or drag-drop preserves existing transcript overlay edits before inserting the new block.
- Dragging a search result onto blank sidebar space creates an uncategorized evidence block.
- Dragging a search result onto a category header creates the block in that category.
- After any creation path, the sidebar reveals/selects the new evidence block and the Simple Search transcript view scrolls to show it.
- The implementation introduces one shared transcript/evidence-block widget used by both `TranscriptWidgetTab` and `SimpleSearchTab`.
- All creation and navigation actions write process-log entries with source thread, hit message, evidence block id, and target category when applicable.

## Tests / Verification

- UI smoke test: selecting a search result updates the transcript widget thread and centers on the hit.
- UI smoke test: double-clicking a search result creates an uncategorized block and reveals it in the sidebar.
- UI smoke test: `Add evidence block` uses the viewport center, not merely the selected search result row.
- UI smoke test: drag-drop onto a category creates a categorized evidence block and scrolls the transcript widget to it.
- UI smoke test: drag-drop onto blank sidebar space creates an uncategorized block and reveals it.
- UI smoke test: the dedicated `TranscriptWidgetTab` still loads and creates evidence blocks through the extracted shared widget.
- Regression test: existing transcript widget creation still preserves prior overlay edits.

## Guardrails for Executor Agent

- Do not reintroduce workstation-conversation creation into Simple Search for this ticket.
- Do not keep two divergent transcript-widget implementations.
- Do not make category-drop behavior depend on visible sidebar text.
- Do not break existing sidebar selection behavior for evidence blocks outside the new Simple Search creation flow.
- Prefer adding a new shared widget module over stuffing more conditional behavior into `TranscriptWidgetTab`.

## Non-Goals

- No output-formatting tab changes.
- No automatic categorization beyond explicit category drop target.
- No redesign of evidence block title generation beyond current heuristics.
