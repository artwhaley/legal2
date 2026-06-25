# T43 - Printable Artifact Preview Pagination

## Goal
Render a basic paged preview of the selected printable artifact with title, messages, footer metadata, zoom, and page navigation.

## Preview Model
Create a small rendering/model module, suggested:
- `message_evidence_workstation/output/printable_preview.py`

It should build a deterministic preview model from `PrintableArtifactContext`:
- artifact metadata
- ordered block sections
- rendered message entries
- page list
- footer text
- provenance ledger entries

The preview model should be separate from the Qt widgets so PDF export can reuse it later.

## Page Layout Rules
Each page shows:
- Centered artifact title at the top.
- Body content below title.
- Bottom-right footer on every page:
  - `Exhibit: <exhibit_number>`
  - `Case: <case_number>`
  - `Page X of Y`

Each message shows:
- sender
- timestamp
- message body

Sender and timestamp must be clearly present but visually subordinate to message text. Use a smaller/lighter metadata line or equivalent.

Block sections:
- Each evidence block starts with a section label:
  - `Block A`
  - `Block B`
  - `Block C`
- Include the evidence block title near the block label.
- Render blocks in user-controlled artifact order, not globally chronological order.

Controls:
- Previous page
- Page `X / Y`
- Next page
- Zoom out
- Zoom percentage
- Zoom in

## Pagination
- MVP pagination may be approximate and text-measurement-based as long as it is deterministic and usable.
- Preview should support multiple pages.
- Rebuilding preview after metadata/order changes should preserve page bounds where reasonable, but correctness matters more than preserving scroll position.

## Non-Goals
- Do not implement PDF export in this ticket.
- Do not implement user-editable typography controls.
- Do not implement drag selection/copy behavior in the preview.

## Acceptance Criteria
- Selecting an artifact renders a preview page.
- Multi-block artifacts render blocks in artifact order.
- Every rendered message includes sender and timestamp.
- Footer appears on every page with exhibit, case, and page count.
- Zoom and next/previous controls work.
- Preview updates when metadata or block order changes.

## Tests
- Preview model test for one-page artifact.
- Preview model test for multi-block artifact order.
- Preview model test verifies sender/timestamp are included.
- Preview model test verifies footer includes exhibit/case/page count.
- UI smoke test verifies next/previous buttons enable appropriately for multi-page preview.
