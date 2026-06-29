# NewTranscriptWidget Parallel Demonstrator Spec

## Goal

Build a new transcript widget architecture in parallel with the existing `Transcript Widget` tab. The new tab is a nondestructive demonstrator: it must prove the document-style transcript experience, evidence boundary editing, hit-message selection, and message highlighting on large datasets before we replace the old `Gen2TranscriptSurfaceWidget` in search and conversational workflows.

The user experience must look and behave like a continuous transcript document, not a table, row grid, or fixed-height list. The database remains the source of truth behind the scenes, but the user should feel like they are viewing a read-only Microsoft Word-style transcript with evidence markup controls layered on top.

## Non-Goals

- Do not remove or mutate the existing `Transcript Widget` tab.
- Do not integrate the new widget into Simple Search yet.
- Do not integrate the new widget into Conversational Interface yet.
- Do not rewrite evidence-block schema unless a demonstrable correctness issue appears.
- Do not allow transcript text editing. Users may edit only evidence metadata: boundaries, hit message, and highlights.

## Current Behavior To Preserve

The existing workflow is implemented mainly by:

- `message_evidence_workstation/ui/transcript_widget_tab.py`
- `message_evidence_workstation/ui/evidence_block_transcript_widget.py`
- `message_evidence_workstation/ui/transcript_surface.py`
- `message_evidence_workstation/db/evidence_blocks.py`
- `message_evidence_workstation/domain/slots.py`

The new widget must preserve these behaviors:

1. **Thread loading**
   - A dataset can contain one or more `source_thread` rows.
   - A selected source thread is loaded into the transcript surface.
   - Messages are ordered by `message.thread_ordinal`.
   - Loading a thread also loads existing evidence blocks for that source thread.

2. **Evidence block creation**
   - Creating from the viewport center resolves the message under the visual center.
   - Creating for a specific message ID resolves that message's `thread_ordinal`.
   - The new block is created in Uncategorized unless an explicit category is supplied.
   - Default slots come from `default_slots_for_hit_index_with_context`.
   - Created block stores:
     - `source_thread_id`
     - `core_hit_message_id`
     - `context_start_slot`
     - `relevant_start_slot`
     - `relevant_end_slot`
     - `context_end_slot`
     - optional `highlighted_message_ids`

3. **Boundary editing**
   - Each evidence block has four draggable dividers:
     - context start
     - relevant start
     - relevant end
     - context end
   - Slots remain half-open message ordinal boundaries.
   - Slot invariant must always hold:
     - `0 <= context_start <= relevant_start <= relevant_end <= context_end <= message_count`
   - Persistence uses `evidence_blocks.update_evidence_block_slots`.

4. **Hit message editing**
   - Each evidence block has exactly one hit/core message.
   - User can set the hit message to another message within the block's relevant passage.
   - Persistence uses `evidence_blocks.update_evidence_block_anchor`.

5. **Highlight editing**
   - Each evidence block can have zero or more highlighted messages.
   - User can toggle message highlight state for the active block.
   - Persistence uses `evidence_blocks.set_evidence_block_highlights`.

6. **Reveal and navigation**
   - Given an evidence block ID, the widget can load the block's source thread and scroll to its `core_hit_message_id`.
   - Given a message ID, the widget can scroll to that message.
   - These APIs are required later for Simple Search and Conversational Interface.

## Architecture

### New Files

Add these files:

- `message_evidence_workstation/ui/new_transcript_widget.py`
- `message_evidence_workstation/ui/new_transcript_widget_tab.py`
- `tests/test_new_transcript_widget.py`

Do not edit the old `transcript_surface.py` except for imports or shared constants if absolutely necessary.

### Main Window Integration

Add a new tab next to the old transcript tab:

- Existing tab label remains: `Transcript Widget`
- New tab label: `New Transcript Widget`

`MainWindow` should instantiate both tabs:

- `self.transcript_widget_tab = TranscriptWidgetTab(...)`
- `self.new_transcript_widget_tab = NewTranscriptWidgetTab(...)`

Dataset activation must call `set_dataset(dataset_id)` on both tabs. Sidebar selection may optionally select the same thread in both transcript tabs, but do not route search/conversational actions to the new widget yet.

### Widget Stack

The new tab owns demo controls plus the document widget:

```text
NewTranscriptWidgetTab
  top controls:
    Source thread combo
    New evidence block
    Jump 50
    Jump 500
    Jump random + create block
    Persist / reload current thread
    Status label
  NewTranscriptWidget
    QTextEdit/QTextDocument document surface
    non-editable transcript text
    overlay/annotation layer for boundaries and controls
```

### Recommended Qt Foundation

Use `QTextEdit` with a `QTextDocument` for the demonstrator.

Rationale:

- It gives us native scrolling, text layout, word wrapping, selection behavior, and document coordinates.
- It supports rich formatting and document-block metadata.
- It avoids custom variable-height row math, which is the core failure mode of the old surface.
- It can still be made read-only while allowing overlay interactions.

If `QTextEdit` proves too slow with the real 15k-message thread, run a focused spike with `QPlainTextEdit` plus `ExtraSelection` and margin overlay. Do not fall back to fixed-height row virtualization unless the product requirement changes.

## Document Model

### Message Blocks

Each source message must become one visually document-like unit. Prefer one `QTextBlock` per message unless preserving multi-line message bodies requires continuation blocks. If continuation blocks are needed, every continuation block must carry the same message metadata and resolve back to the same message ID.

Each message block stores metadata in `QTextBlockUserData`, not hidden text:

```python
class TranscriptBlockUserData(QTextBlockUserData):
    message_id: str
    source_thread_id: str
    thread_ordinal: int
    timestamp: str
    sender_display: str
```

Maintain explicit maps:

```python
message_id_to_block_number: dict[str, int]
block_number_to_message_id: dict[int, str]
message_id_to_thread_ordinal: dict[str, int]
thread_ordinal_to_message_id: dict[int, str]
```

These maps are the bridge between document coordinates and database rows. Do not parse visible text to recover IDs.

### Visual Formatting

The transcript must read as a continuous document:

- Page-like background, margins, and readable text width.
- Sender/timestamp/message layout should look transcript-like, not a spreadsheet.
- No hard row separators as the dominant visual structure.
- Evidence boundaries may appear as horizontal document dividers/handles.
- Relevant passages and context can be shaded, but should feel like markup on a document.
- The active evidence block should be visually distinct.

Text must be read-only:

- `QTextEdit.setReadOnly(True)`
- Block paste, typing, deletion, and drag text mutation.
- User text selection is allowed if it does not interfere with evidence controls.

## Data Access

Reuse `SqlTranscriptDataSource` initially, but add document-friendly helpers if needed.

The new widget may load all messages for the active source thread into the `QTextDocument` for the first demonstrator. A 15k-message active thread is acceptable for this pass if construction is batched and UI remains responsive after load.

Implementation requirements:

- Fetch by ordinal ranges from SQL, not by materializing the entire dataset.
- Never concatenate the entire dataset into one giant backing string as the source of truth.
- The document is a view cache for the active thread.
- The database remains authoritative for messages and evidence metadata.

Recommended build strategy:

- Query `message_count`.
- Fetch active thread messages in chunks, such as 500 or 1000 messages.
- Insert into `QTextDocument` in batches.
- Disable updates during initial document construction where safe.
- Emit progress/status in the demo tab for large threads.
- After document build, apply evidence overlays and restore scroll target if any.

## Annotation Model

Add an internal overlay object similar to the old `BlockOverlay`, but independent of `EvidenceTranscriptModel`:

```python
@dataclass(slots=True)
class TranscriptEvidenceOverlay:
    evidence_block_id: int
    context_start_slot: int
    relevant_start_slot: int
    relevant_end_slot: int
    context_end_slot: int
    core_hit_message_id: str
    highlighted_message_ids: frozenset[str]
    is_active: bool = False
```

The widget must support:

- `append_evidence_block(block: EvidenceBlock)`
- `set_active_evidence_block(evidence_block_id: int | None)`
- `overlay_by_id(evidence_block_id: int) -> TranscriptEvidenceOverlay | None`
- `persist_overlay(evidence_block_id: int)`
- `persist_all_overlays()`

### Boundary Rendering

Boundaries are anchored to slots, not rows.

Slot-to-document mapping:

- Slot `0` is before message ordinal `0`.
- Slot `N` for `0 < N < message_count` is before message ordinal `N`.
- Slot `message_count` is after the final message.

To render a boundary:

- Find the block for the boundary slot.
- Use `QTextEdit.cursorRect(QTextCursor(block))` or document layout coordinates to compute the y-position.
- Paint handles and lines in an overlay/margin area or via a lightweight child overlay widget.

Dragging a boundary:

- Convert mouse y-position to the nearest document block.
- Resolve that block's message ordinal.
- Convert to the nearest legal slot.
- Apply invariant clamping through the same logic as old `EvidenceTranscriptModel._resolve_boundary_move` or a new shared pure function.
- Persist on mouse release, not every mouse move.

### Hit And Highlight Controls

For active block messages in the relevant range:

- Show a hit-message control, visually like a radio target.
- Show a highlight toggle, visually like a checkbox or marker.
- These controls can be painted in a margin/overlay column so the transcript body remains document-like.

Interactions:

- Clicking hit control sets `core_hit_message_id`.
- Clicking highlight control toggles the message ID in `highlighted_message_ids`.
- Persist immediately or on a short debounce; test should assert DB state after event loop flush.

## Public API Required For Future Integration

The new widget must expose these methods, even if only the demo tab uses them now:

```python
set_dataset(dataset_id: int | None) -> None
load_source_thread(source_thread_id: str, *, source_action: str = "thread_load") -> None
focus_message(message_id: str, *, source_action: str = "focus_message") -> None
scroll_to_message(message_id: str) -> bool
scroll_to_ordinal(thread_ordinal: int) -> bool
viewport_center_message_id() -> str | None
viewport_center_ordinal() -> int | None
create_evidence_block_from_viewport_center(category_id: int | None = None, *, source_action: str = "viewport_button") -> EvidenceBlock | None
create_evidence_block_for_message(message_id: str, category_id: int | None = None, *, source_action: str = "message_hit") -> EvidenceBlock | None
reveal_created_evidence_block(block: EvidenceBlock, *, source_action: str = "search_drop") -> None
select_evidence_block(evidence_block_id: int) -> None
persist_all_overlays() -> None
```

These should intentionally match or supersede the existing `EvidenceBlockTranscriptWidget` API so replacement later is mechanical.

## Demo Tab Controls

`NewTranscriptWidgetTab` must include:

1. **Source thread combo**
   - Same behavior as old transcript tab.
   - Loads selected thread into the new document widget.

2. **New evidence block**
   - Creates an evidence block from viewport center.

3. **Jump 50**
   - Scrolls to ordinal/message 50 if available.
   - If fewer than 51 messages exist, scrolls to the last message.

4. **Jump 500**
   - Scrolls to ordinal/message 500 if available.
   - If fewer than 501 messages exist, scrolls to the last message.

5. **Jump random + create block**
   - Picks a random ordinal in the current thread.
   - Scrolls to it.
   - Creates an evidence block for that message.
   - Sets the created block active.
   - Emits `evidence_block_created`.

6. **Persist / reload current thread**
   - Persists overlays.
   - Reloads the current source thread from SQL.
   - Keeps the same selected thread.
   - Verifies visually that block boundaries, hit message, and highlights round-trip from the DB.

7. **Status label**
   - Shows loaded thread ID, message count, evidence block count, active block ID, and last demo action.

## Acceptance Criteria

### Functional

- App shows both `Transcript Widget` and `New Transcript Widget` tabs.
- Loading a dataset enables both tabs.
- New tab can load the same source thread as the old tab.
- New transcript display is document-like and read-only.
- Jump 50 and Jump 500 scroll to the expected message/ordinal.
- Jump random + create block creates a DB evidence block at the selected random message.
- Creating from viewport center creates a DB evidence block at the visible center message.
- Selecting/revealing an evidence block scrolls to its `core_hit_message_id`.
- Dragging each of the four boundaries updates the overlay and persists valid slots.
- Setting the hit message updates `core_hit_message_id` and preserves the exactly-one-hit invariant.
- Toggling highlights updates `evidence_block_highlight`.
- Persist/reload round-trips boundaries, hit message, and highlights.
- Old transcript tab still works as before.
- Simple Search and Conversational tabs are untouched by this patch.

### Performance

- Loading a 15k-message thread should not freeze indefinitely.
- After load, normal scrolling should remain responsive.
- Scrolling must not trigger recursive layout/reflow loops.
- Jumping to ordinal 500 or a random ordinal should be direct, not a linear scroll animation.
- Document construction should be batched enough that progress/status can update during large loads.

### Safety

- Transcript text cannot be edited by keyboard, paste, context menu paste, drag/drop text, or delete/backspace.
- All DB writes go through existing evidence block persistence APIs.
- Message identity uses metadata/maps, never visible text parsing.
- Slot invariants are enforced before persistence.
- Existing old-widget tests should keep passing unless intentionally updated for the new tab count/labels.

## Tests

Add focused tests in `tests/test_new_transcript_widget.py`:

1. `test_new_transcript_tab_loads_thread`
   - Builds UI context.
   - Calls `set_dataset`.
   - Asserts thread combo is populated and document has message blocks.

2. `test_new_transcript_text_is_read_only`
   - Attempts text insertion through cursor/key path.
   - Asserts document text and message maps remain unchanged.

3. `test_new_transcript_scroll_to_ordinal`
   - Loads synthetic thread with at least 600 messages.
   - Calls `scroll_to_ordinal(50)` and `scroll_to_ordinal(500)`.
   - Asserts viewport center or first visible block resolves near expected ordinal.

4. `test_new_transcript_create_block_from_message`
   - Creates block for known message ID.
   - Asserts DB block has expected `core_hit_message_id` and default slots.

5. `test_new_transcript_boundary_persist_reload`
   - Creates block.
   - Moves all four boundaries through widget/model API.
   - Persists and reloads.
   - Asserts DB and overlay slots match.

6. `test_new_transcript_hit_and_highlight_persist_reload`
   - Creates block.
   - Sets another message as hit.
   - Toggles at least two highlights.
   - Persists and reloads.
   - Asserts DB and overlay state match.

7. `test_main_window_includes_parallel_new_transcript_tab`
   - Asserts both tab labels exist:
     - `Transcript Widget`
     - `New Transcript Widget`

Keep GUI tests pragmatic: use direct widget APIs for boundary and highlight state where simulating drag/click is brittle. Add at least one smoke interaction test for a painted control after the overlay exists.

## Implementation Order

1. Add `NewTranscriptWidget` document surface with read-only document loading and message metadata maps.
2. Add `NewTranscriptWidgetTab` with source-thread combo and demo buttons.
3. Add main-window tab beside the old transcript tab and dataset activation wiring.
4. Implement scroll/jump APIs.
5. Implement evidence block creation APIs.
6. Implement overlay model and apply visual formatting for context/relevant/highlight/hit states.
7. Implement boundary rendering and drag persistence.
8. Implement hit-message and highlight controls.
9. Add persist/reload demo control.
10. Add tests and update existing tab-label tests only where necessary.

## Handoff Notes

The point of this patch is to prove the right architecture without destabilizing the rest of the app. Treat the old custom-painted virtualized widget as a reference for business behavior, not as a rendering architecture to extend. The new widget should make the document engine responsible for document layout and scrolling; our code should own only database identity, evidence annotations, and workflow commands.
