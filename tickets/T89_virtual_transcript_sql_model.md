# T89 - Virtual Transcript SQL Model

## Goal
Build the bounded SQL-backed model for the virtual transcript widget.

## Background
The widget must not load all message bodies on tab switch. It should load message count and fetch message windows by ordinal range.

**Spec reference:** `08_virtual_transcript_widget_spec.md` sections `SQL Data Source`, `Virtual Transcript Model`

## Depends On
- T88

## Scope
- Add `message_evidence_workstation/ui/virtual_transcript_model.py`
- Reuse or extend `SqlTranscriptDataSource` where appropriate
- Implement bounded ordinal range fetching
- Implement message count lookup
- Implement `ordinal_for_message_id(message_id)`
- Implement `message_id_for_ordinal(ordinal)` with cache/SQL fallback
- Implement evidence block loading for active source thread
- Add bounded message cache with a clear max size or eviction strategy

## Guardrails
- Do not hydrate all message bodies during `load_thread`
- Do not build dataset-wide message maps
- Preserve database as source of truth
- Use existing repository/data-source helpers when they are already bounded and indexed

## Non-Goals
- Painting
- Scrollbar behavior
- Annotation editing

## Acceptance Criteria
- `load_thread(source_thread_id)` loads count and metadata only
- `messages_for_range(start, end)` fetches only the requested ordinal window
- `ordinal_for_message_id` works for unloaded messages
- Evidence blocks for the thread can be loaded without full transcript hydration
- Unit tests prove large-thread operations do not fetch all rows

## Tests
- Add `tests/test_virtual_transcript_model.py`
- Cover message count, range fetch, ordinal lookup, message-id lookup, and evidence block load
- Include a fake 15k-message source and assert bounded fetch counts

