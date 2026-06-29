# New Transcript Widget - Ticket Orchestrator

## Source Spec
[06_new_transcript_widget_spec.md](../06_new_transcript_widget_spec.md)

## Execution Order

Run tickets **sequentially** unless a dependency note explicitly allows parallel work.

| Order | Ticket | Spec Section | Summary |
|------:|--------|--------------|---------|
| 1 | [T73](T73_parallel_new_transcript_tab_shell.md) | Main Window Integration, Demo Tab Controls | Add the parallel tab shell and dataset wiring without touching search/conversational |
| 2 | [T74](T74_document_backed_transcript_surface.md) | Architecture, Document Model, Visual Formatting | Build the read-only document-backed transcript surface and metadata maps |
| 3 | [T75](T75_transcript_navigation_and_demo_controls.md) | Public API Required For Future Integration, Demo Tab Controls | Implement scroll/jump/navigation APIs and demo buttons |
| 4 | [T76](T76_evidence_block_creation_and_reveal.md) | Current Behavior To Preserve, Public API Required For Future Integration | Add evidence block creation, reveal, and active-block selection workflows |
| 5 | [T77](T77_document_annotation_overlays.md) | Annotation Model, Boundary Rendering, Hit And Highlight Controls | Render context/relevant/highlight/hit state as document annotations |
| 6 | [T78](T78_boundary_drag_and_overlay_persistence.md) | Boundary Rendering, Current Behavior To Preserve | Implement draggable boundary editing and persistence round-trips |
| 7 | [T79](T79_hit_message_and_highlight_editing.md) | Hit And Highlight Controls | Implement hit-message and highlight editing with persistence |
| 8 | [T80](T80_new_transcript_widget_regression.md) | Acceptance Criteria, Tests, Handoff Notes | Close with UI tests, scale checks, and doc cleanup |

## Global Guardrails

- Do not remove or rewrite the old `Transcript Widget` tab during this stack.
- Do not integrate the new widget into `Simple Search` or `Conversational Interface` during this stack.
- Do not patch `transcript_surface.py` into a second architecture; treat it as a business-behavior reference only.
- The transcript must look and feel like a continuous document, not a table or fixed-height row list.
- Transcript text must remain read-only. Only evidence boundaries, hit message, and highlighting are editable.
- All evidence writes must go through existing `db.evidence_blocks` APIs unless a prior ticket explicitly approves a shared helper extraction.
- Message identity must be maintained through stable metadata/maps, never by parsing visible document text.
- The database remains the source of truth; the document is a view cache for one active source thread.

## Reviewing Agent

Read `06_new_transcript_widget_spec.md` first, then verify each ticket's acceptance criteria still map back to the spec before execution begins.
