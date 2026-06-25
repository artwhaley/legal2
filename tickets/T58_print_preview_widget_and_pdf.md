# T58 - Print Preview Widget And PDF Export

## Goal
Replace QLabel HTML preview with a true print preview widget: WYSIWYG pages, zoom, print dialog, and PDF export from one layout path.

## Background
Operators must see exactly what will print. Preview and PDF must share the T57 layout engine.

**Spec reference:** `04_pre_scale_hardening_spec.md` §14.2–14.4

## Depends On
- T57 (layout engine)

## Scope
- New `PrintPreviewWidget` (replace `PrintablePreviewWidget`):
  - `QGraphicsView` or `QPrinter`/`QPdfWriter` preview pattern
  - Render pages from `PrintLayoutDocument` at zoom level
  - Previous / Next / zoom controls (retain existing affordances)
  - **Print** → system print dialog via `QPrinter`
  - **Export PDF** → write PDF from same layout
- Wire into `OutputFormattingTab` right pane
- Delete QLabel/HTML preview implementation and char-heuristic pagination
- Update/remove tests tied to old preview model pagination

## Guardrails
- Preview pixels/vectors from same layout function as PDF — no second code path
- Do not regress artifact editor/metadata/block list (left pane)

## Non-Goals
- User-editable typography controls
- Drag-select/copy in preview

## Acceptance Criteria
- Footer on every page; title on every page; provenance at end
- PDF export matches preview at 100% zoom (vector or pixel equivalence)
- Print dialog produces output consistent with preview
- Block reorder updates preview correctly

## Tests
- Layout + render smoke test (Qt headless or widget test)
- PDF written to temp file has expected page count
- UI smoke: select artifact → preview shows pages
- `python -m pytest -q`
