# T91 - Virtual Transcript Visible Renderer

## Goal
Render a document-like transcript surface using only the visible message window plus overscan.

## Background
The virtual widget should keep the Gen 1 document-like look while avoiding full-document layout and paint work.

**Spec reference:** `08_virtual_transcript_widget_spec.md` section `Visible Rendering`

## Depends On
- T90

## Scope
- Implement the core `VirtualTranscriptWidget` paint path
- Compute visible ordinal range from scroll offset and viewport height
- Fetch missing messages for visible range plus overscan
- Measure visible/overscan messages only
- Update height index with measured heights
- Paint page/document background and transcript text
- Avoid child widgets per message
- Expose debug/status values for visible range and cached/measured counts

## Guardrails
- Do not paint all messages
- Do not fetch all messages
- Do not make the transcript look like a table
- Preserve Gen 1 typography/layout as much as practical

## Non-Goals
- Draggable annotations
- Hit/highlight editing
- Search integration

## Acceptance Criteria
- First visible transcript range renders after selecting a thread
- Scrolling repaints bounded windows
- Visible text looks like transcript text, not rows or cards
- Measured height count remains bounded during initial paint

## Tests
- Add/extend `tests/test_virtual_transcript_widget.py`
- Assert initial paint/range load does not materialize all messages
- Assert measured message count remains bounded
- Add a smoke test for visible text rendering

