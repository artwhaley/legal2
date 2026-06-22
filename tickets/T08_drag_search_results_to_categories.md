# T08 — Drag Search Results to Categories

## Goal

Let users drag Simple Search results into sidebar categories to create WorkstationConversations.

## Dependencies

T05, T07.

## Implementation Notes

The drag payload should carry grouped result IDs/hit message IDs, not raw UI text. Dropping onto a category creates a WorkstationConversation with ConversationHit records for all hits in the group. If a nearby conversation already exists in the same category/source thread, use the current merge rule only if explicitly visible/logged; otherwise create a separate candidate.

## Files / Areas Likely Touched

- message_evidence_workstation/ui/simple_search_tab.py
- message_evidence_workstation/ui/sidebar.py
- message_evidence_workstation/db/repositories.py
- message_evidence_workstation/search/result_models.py

## Acceptance Criteria

- Search result rows can be dragged.
- Category rows accept drops.
- Dropping creates a candidate WorkstationConversation.
- ConversationHit records preserve retrieval method, query text, matched term, score/rank if known.
- Sidebar shows the new conversation under the category.
- Drop/create/merge decisions are logged.

## Tests / Verification

- Manual drag/drop test.
- Repository assertion that hits are stored.
- Restart app and confirm created conversation persists.

## Non-Goals

- No output formatting yet.
- No conversational search mutation.
