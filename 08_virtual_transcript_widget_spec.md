# Virtual Transcript Widget Spec

## Goal
Build a third, nondestructive transcript tab that preserves the Gen 1 transcript widget's evidence-editing behavior while replacing its full-document layout with a SQL-backed virtual layout engine that can handle 15,000+ messages.

The result should feel like one continuous transcript document. The virtualization is an implementation detail only.

## Background
The Gen 1 transcript widget had the correct product behavior: context and relevant passage dividers, shading, hit-message selection, highlighting, and evidence block editing. Its failure mode was scale.

The document-backed Gen 2 widget improved some loading paths but failed the evidence annotation interaction model. Do not continue expanding Gen 2 as the primary solution during this stack.

This stack creates a third tab:

- `Transcript Widget`: existing Gen 1 reference
- `New Transcript Widget`: existing document-backed experiment
- `Virtual Transcript Widget`: new Gen 1-style behavior with virtualized internals

## Product Requirements
The user experience must remain document-like, not table-like.

The virtual widget must support:

- read-only transcript text
- continuous transcript scrolling
- context range shading
- relevant passage shading
- one hit message per evidence block
- message-level highlights
- four labeled draggable evidence boundaries:
  - context start
  - relevant start
  - relevant end
  - context end
- evidence block creation from a message or viewport center
- evidence block reveal and editing
- scroll-to-message by `message_id`
- jump-to-ordinal test controls
- persistence and reload of boundaries, hit message, and highlights

The user must not see pagination, fixed-height rows, or database chunks.

## Architecture
Introduce a virtual transcript implementation alongside the existing widgets.

Recommended modules:

- `ui/virtual_transcript_widget_tab.py`
- `ui/virtual_transcript_widget.py`
- `ui/virtual_transcript_model.py`
- `ui/virtual_transcript_height_index.py`
- `ui/virtual_transcript_renderer.py`
- `ui/virtual_transcript_annotations.py`

The architecture should be:

`SqlTranscriptDataSource` -> `VirtualTranscriptModel` -> `TranscriptHeightIndex` -> `VirtualTranscriptWidget`

### SQL Data Source
Use indexed ordinal range queries. Do not hydrate all message bodies on tab switch.

Required query shape:

```sql
SELECT ...
FROM messages
WHERE dataset_id = ?
  AND source_thread_id = ?
  AND thread_ordinal >= ?
  AND thread_ordinal < ?
ORDER BY thread_ordinal
```

Required indexes should already exist or be added if missing:

- `(dataset_id, source_thread_id, thread_ordinal)`
- `(dataset_id, message_id)`
- evidence blocks by `(dataset_id, source_thread_id)`

### Virtual Transcript Model
The model owns:

- active dataset id
- active source thread id
- message count
- visible ordinal window
- fetched message cache
- ordinal to message id lookup for fetched messages
- message id to ordinal lookup through SQL/cache
- active evidence overlay state

It must expose bounded operations:

- `load_thread(source_thread_id)`
- `messages_for_range(start_ordinal, end_ordinal)`
- `ordinal_for_message_id(message_id)`
- `message_id_for_ordinal(ordinal)`
- `load_evidence_blocks()`
- `append_or_update_evidence_block(block)`

### Height Index
The height index maps between virtual document pixels and message ordinals.

Use a Fenwick tree, segment tree, or equivalent prefix-sum structure:

- initialize every message with an estimated height
- update individual measured heights as messages become visible
- compute total virtual document height
- compute ordinal to scroll offset
- compute scroll offset to ordinal

No recursive reflow. No full-document measurement on scroll.

### Visible Rendering
The widget paints only the visible ordinal range plus overscan.

On scroll:

1. Convert scroll offset to first visible ordinal.
2. Compute visible range plus overscan.
3. Fetch missing messages for that bounded range.
4. Measure visible/overscan messages.
5. Update height index.
6. Repaint.

Do not create child widgets per message.

### Annotation Rendering
Annotations are semantic, not pixel-persisted.

Boundary and shading positions are derived from:

- evidence block slot ordinals
- visible message positions
- height index offsets

The active evidence block must show:

- context shading for visible messages within context slots
- stronger relevant shading for visible messages within relevant slots
- hit marker for `core_hit_message_id`
- highlight marker/shading for highlighted messages
- four labeled draggable boundary handles when visible

Controls must scroll naturally with the transcript because their positions are recomputed from the virtual layout.

## Demo Tab
Add a third tab named `Virtual Transcript Widget`.

The tab should include:

- source thread selector
- status label with message count and visible range
- jump to message 50
- jump to message 500
- jump to message 14,000
- jump random
- create evidence block at viewport center
- create evidence block at random message
- reveal active evidence block
- reload current thread

These controls are test scaffolding and must not be wired into search/conversational pages yet.

## Performance Targets
For a 15,000-message thread:

- tab activation should not hydrate all message bodies
- first visible paint should complete in under 1 second on normal local hardware
- scrolling should not hang
- jump to message near the end should be bounded and responsive
- evidence block create/reveal near the end should be bounded and responsive
- resizing should preserve anchor position and lazily remeasure visible messages only

## Persistence Requirements
Evidence state remains persisted through existing evidence block APIs.

Persist:

- evidence block id
- source thread id
- context/relevant slot ordinals
- core hit message id
- highlighted message ids

Never persist:

- pixel positions
- visible row indexes
- temporary cache state

## Guardrails
Do not:

- remove or rewrite the existing Gen 1 tab
- remove or rewrite the Gen 2 tab
- integrate this widget into simple search or conversational search yet
- make transcript messages fixed-height rows
- make the surface look like a table
- load all message bodies on tab switch
- use QTextEdit as the main implementation for this stack
- persist annotation geometry as pixels

Use the Gen 1 widget as the behavior reference.

## Acceptance Criteria
The stack is complete when:

- the app shows all three transcript tabs
- the virtual tab loads a large thread quickly
- visible transcript text renders immediately
- scrolling top/middle/end does not hang
- jump to ordinal 50, 500, and 14,000 works
- creating an evidence block near ordinal 14,000 works
- context/relevant shading appears
- four labeled boundary handles appear and follow scroll
- dragging boundaries updates the active block and persists on release
- hit-message selection works and remains unique
- message highlighting works and persists
- reload restores the evidence block state
- tests prove range loading and rendering remain bounded

