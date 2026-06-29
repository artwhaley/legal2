# T74 - Document Backed Transcript Surface

## Goal
Build the first real `NewTranscriptWidget` as a read-only document-backed transcript surface using Qt's text document stack instead of custom row virtualization.

## Background
The old transcript surface owns scrolling, layout, variable-height measurement, and boundary painting itself. The new architecture should hand layout and scrolling to Qt and keep our code focused on transcript identity and evidence annotations.

**Spec reference:** `06_new_transcript_widget_spec.md` sections `Architecture`, `Document Model`, `Visual Formatting`, `Data Access`

## Depends On
- T73

## Scope
- Add `message_evidence_workstation/ui/new_transcript_widget.py`
- Build on `QTextEdit` + `QTextDocument` unless a documented performance blocker forces a `QPlainTextEdit` spike
- Load one active source thread into the document from SQL
- Build document content in bounded batches for large threads
- Store message metadata in `QTextBlockUserData`
- Maintain stable maps:
  - `message_id -> block_number`
  - `block_number -> message_id`
  - `message_id -> thread_ordinal`
  - `thread_ordinal -> message_id`
- Make transcript text read-only
- Apply page-like document styling that reads as transcript text, not a table

## Guardrails
- Do not parse visible text to recover message identity
- Do not concatenate the entire dataset into a single backing string as the source of truth
- Keep DB access scoped to the active source thread
- Avoid custom variable-height scroll math

## Non-Goals
- Evidence block editing
- Draggable boundaries
- Search-page integration

## Acceptance Criteria
- Loading a thread produces a readable document-style transcript
- Message blocks resolve back to stable message IDs and ordinals
- Text is not editable through normal typing/paste/delete flows
- Large-thread document construction is batched enough to avoid apparent deadlock

## Tests
- Add `tests/test_new_transcript_widget.py`
- Add a test that thread load populates document blocks and metadata maps
- Add a read-only regression test
- `python -m pytest tests/test_new_transcript_widget.py -q`
