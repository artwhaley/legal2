# Virtual Transcript Widget - Ticket Orchestrator

## Source Spec
[08_virtual_transcript_widget_spec.md](../08_virtual_transcript_widget_spec.md)

## Execution Order

Run tickets **sequentially** unless a dependency note explicitly allows parallel work.

| Order | Ticket | Spec Section | Summary |
|------:|--------|--------------|---------|
| 1 | [T88](T88_virtual_transcript_third_tab_shell.md) | Demo Tab, Guardrails | Add the third tab shell and dataset/thread wiring |
| 2 | [T89](T89_virtual_transcript_sql_model.md) | SQL Data Source, Virtual Transcript Model | Build bounded SQL range access and the virtual transcript model |
| 3 | [T90](T90_virtual_transcript_height_index.md) | Height Index | Add prefix-sum virtual height mapping |
| 4 | [T91](T91_virtual_transcript_visible_renderer.md) | Visible Rendering | Render only visible/overscan messages in a document-like surface |
| 5 | [T92](T92_virtual_transcript_scroll_and_jump.md) | Performance Targets, Demo Tab | Implement virtual scrolling and jump-to-message APIs |
| 6 | [T93](T93_virtual_transcript_annotation_painting.md) | Annotation Rendering | Paint context/relevant/hit/highlight state and labeled boundary handles |
| 7 | [T94](T94_virtual_transcript_annotation_editing.md) | Persistence Requirements, Product Requirements | Implement boundary drag, hit selection, highlights, and persistence |
| 8 | [T95](T95_virtual_transcript_demo_controls.md) | Demo Tab | Add stress/demo controls and runtime status diagnostics |
| 9 | [T96](T96_virtual_transcript_regression_and_handoff.md) | Acceptance Criteria | Add regression tests, smoke tests, and handoff notes |

## Global Guardrails

- Do not remove or rewrite the existing `Transcript Widget` tab.
- Do not remove or rewrite the existing `New Transcript Widget` tab.
- Do not integrate the virtual widget into Simple Search or Conversational Search during this stack.
- Treat the Gen 1 widget as the behavior reference.
- Treat the Gen 2 widget as an experiment, not the target implementation.
- The virtual widget must look like a continuous transcript document, not a table.
- Transcript text remains read-only.
- Only evidence boundaries, hit message, and highlights are editable.
- Do not hydrate all message bodies on tab switch.
- Do not measure or paint all messages on scroll.
- Do not persist pixel geometry.

## Reviewing Agent

Read `08_virtual_transcript_widget_spec.md` first. Before each ticket, inspect the current Gen 1 transcript widget behavior relevant to that ticket and preserve it unless the spec explicitly says otherwise.

