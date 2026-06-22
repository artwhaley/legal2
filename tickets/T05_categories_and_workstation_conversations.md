# T05 — Categories and Workstation Conversations

## Goal

Implement category CRUD and the core WorkstationConversation records that categories contain.

## Dependencies

T01, T03, T04.

## Implementation Notes

Use the project terminology correctly: SourceThread is the raw app-level thread; WorkstationConversation is the topic/exhibit-sized passage. Add UI for creating, renaming, deleting, expanding/collapsing categories. Add a minimal manual creation path from a selected message or selected contiguous range so the object model can be tested before search drag/drop exists.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/sidebar.py
- message_evidence_workstation/domain/models.py
- message_evidence_workstation/db/repositories.py
- message_evidence_workstation/ui/source_thread_view.py
- tests/test_categories.py

## Acceptance Criteria

- User can create categories such as school/work/allergies.
- Categories persist across restart.
- Categories can collapse/expand.
- User can create a WorkstationConversation from selected message/range manually.
- Created conversation links category, source thread, primary hit message, and initial hit records.
- All creation/update/delete actions are logged.

## Tests / Verification

- Repository tests for category CRUD.
- Repository tests for WorkstationConversation + ConversationHit creation.
- Manual UI test create category and manual conversation.

## Non-Goals

- No search-based creation yet.
- No range suggestion.
- No export.
