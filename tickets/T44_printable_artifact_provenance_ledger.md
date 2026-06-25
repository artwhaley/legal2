# T44 - Printable Artifact Provenance Ledger

## Goal
Add an end-of-artifact provenance ledger keyed to printable block labels.

## Background
The provenance statement should help a forensic analyst verify messages efficiently. It should be concise, technical, and based on original imported data. Synthetic test data may not contain every field yet; the renderer should include available fields and omit unavailable ones without inventing values.

## Placement
- Do not place provenance after each block.
- Put all provenance entries together at the end of the artifact body, after the final evidence block.
- Use current artifact block labels:
  - `Block A: <provenance>`
  - `Block B: <provenance>`
  - `Block C: <provenance>`

## Provenance Content
For each block, include concise fields when available:
- app/dataset message IDs included in that evidence block
- original source message IDs
- source thread id
- platform thread id
- source platform
- message timestamp range
- sender identifiers/display names
- source file path/name if captured
- source file hash if captured
- dataset id/name
- import timestamp if captured
- import batch/id if captured
- relevant `source_metadata_json` and `source_thread.metadata_json` fields that help locate the original dump

## Data Rules
- Provenance must come from imported source metadata, dataset/thread/message fields, or future import metadata tables.
- Do not fabricate file names, hashes, import dates, or platform fields.
- If a field is absent, omit it.
- If synthetic data lacks original dump metadata, provenance should still identify dataset/thread/message IDs and timestamps.

## Prewiring For Donor Data
Add helper functions that can tolerate richer metadata later:
- `build_block_provenance(context_block) -> PrintableBlockProvenance`
- `format_block_provenance(label, provenance) -> str`

If current schema lacks source file/import batch fields, leave obvious TODO hooks in code comments and tests around omitted fields. Keep comments brief and technical.

## Acceptance Criteria
- Provenance ledger appears once at the end of the artifact.
- Ledger contains one entry per included evidence block instance, including duplicate evidence block entries if the user included the same block twice.
- Entries are keyed by current block label.
- Available source metadata is included.
- Missing source metadata is omitted, not replaced with placeholders.

## Tests
- Provenance model test with synthetic/minimal metadata.
- Provenance model test with enriched `source_metadata_json`/thread metadata.
- Test that duplicate block instances produce two ledger entries with different labels.
- Test that reordering blocks updates ledger labels.
