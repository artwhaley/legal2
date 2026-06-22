# T21 — HTML Export Preview

## Goal

Generate an HTML preview for a selected workstation conversation/category using current ranges and highlight overrides.

## Dependencies

T20.

## Implementation Notes

The preview should reflect category, conversation title, source platform/thread metadata, selected context/relevant messages, hit/relevant/context visual states, optional notes, and an optional audit appendix placeholder. Start with printable HTML in-app preview or save-to-file preview. PDF comes later.

## Files / Areas Likely Touched

- message_evidence_workstation/export/html_preview.py
- message_evidence_workstation/ui/output_formatting_tab.py
- tests/test_html_export.py

## Acceptance Criteria

- User can preview selected workstation conversation as HTML.
- HTML includes category and source-thread metadata.
- HTML includes context + relevant passage according to current boundaries.
- Hit/relevant/context styling is visually distinct.
- User overrides are honored.
- Export generation logs input IDs and output path/size.

## Tests / Verification

- Unit test HTML contains expected messages/styles.
- Manual preview from a real selected conversation.

## Non-Goals

- No court-ready PDF.
- No DOCX.
- No final exhibit numbering system unless trivial.
