# T42 - Printable Artifact Editor And Block Order Controls

## Goal
Add the lower-left editor for printable artifact metadata and included evidence block ordering.

## Fields
For selected printable artifact:
- `Title`
- `Exhibit Number`
- `Case Number`

Rules:
- `Exhibit Number` is plain text with no validation.
- `Case Number` is plain text with no validation.
- Metadata should persist with an explicit save button for the MVP.
- Saving metadata refreshes preview immediately.

Included block list:
- Shows every evidence block included in the selected artifact, in artifact order.
- Each entry should include the automatic block label and evidence block title:
  - `Block A - <title>`
  - `Block B - <title>`
  - `Block C - <title>`
- Provide `Move Up`, `Move Down`, and `Remove` controls.
- Reordering updates preview immediately.
- Removing an included block updates preview immediately and does not delete the source evidence block.

## Block Labeling
- Assign labels by current artifact order.
- Use letters: A, B, C, etc.
- If later more than 26 blocks are needed, continue with AA, AB, AC. MVP can implement this helper now because it is small and prevents a future weird edge.
- Labels are display labels only; do not persist them.

## Acceptance Criteria
- Selecting an artifact fills metadata fields and ordered block list.
- Saving metadata persists and survives refresh/restart.
- Moving a block up/down changes the stored order.
- Block labels update after reordering.
- Preview refreshes after metadata save, move up/down, remove, and append.

## Tests
- Metadata save/reload test.
- Block label helper test: A, B, Z, AA.
- Move down/up changes order.
- Remove block keeps artifact and evidence block.
- UI smoke test covers selecting an artifact and seeing fields populated.
