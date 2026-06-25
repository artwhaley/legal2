# T57 - Print Layout Engine

## Goal
Replace character-line pagination with a real measured layout engine for printable artifacts — reusable for preview and PDF.

## Background
Current preview uses `LINES_PER_PAGE = 32` and QLabel HTML. Page layout is the core product deliverable.

**Spec reference:** `04_pre_scale_hardening_spec.md` §14.1, §14.3

## Depends On
- T50 (bounded artifact message load for layout input)

## Scope
- Extend `output/printable_preview.py` (or sibling `print_layout.py`) into layout engine:
  - Input: `PrintableArtifactContext`
  - Output: `PrintLayoutDocument` with measured pages
  - US Letter default (8.5×11 in), margins (1 in top/bottom, 0.75 in sides) as named constants
  - Font roles: title, body, metadata, footer, provenance
  - Accept metrics callback (QFontMetrics in Qt; fixed metrics in tests)
- **Authoritative layout rules:**
  - Centered artifact title at top of **every** page
  - Block header: `Block A — {title}`
  - Message: subordinate metadata line + wrapped body
  - Footer every page: Exhibit / Case / Page X of Y
  - Provenance ledger after all blocks only; may span pages
- Greedy page fill by measured box heights — not char line counts
- Remove `LINES_PER_PAGE` / `WRAP_WIDTH` as primary pagination mechanism
- Keep provenance builders; layout consumes formatted ledger entries

## Guardrails
- One layout function serves preview and PDF (WYSIWYG prep for T58)
- Do not change printable artifact DB schema

## Non-Goals
- Qt preview widget (T58)
- Delete old `PrintablePreviewWidget` until T58 lands

## Acceptance Criteria
- Layout engine unit tests: deterministic page breaks on fixed metrics fixture
- Title on every page; footer on every page; provenance only at end
- Multi-block artifact with long bodies breaks at word wrap boundaries

## Tests
- Layout engine tests with stub metrics (no Qt required)
- Golden or snapshot-style page count tests for known fixture artifact
- `python -m pytest -q`
