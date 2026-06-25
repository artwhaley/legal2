# T41 - Output Formatting Printable Artifact Tree

## Goal
Replace the old Output Formatting left-side category/workstation-conversation UI with a printable artifact tree.

## Background
The current Output Formatting tab is obsolete. It references workstation conversations, range suggestions, highlight overrides, HTML preview, and the Source Thread Viewer. The new page starts from printable artifacts.

## Layout
Output Formatting tab should use a horizontal splitter:
- Left pane: printable artifact tree and metadata/block controls.
- Right pane: paged preview.

Artifact tree:
- Top-level items are printable artifact groups.
- Children are printable artifacts.
- Groups can be added with a `+` button.
- Groups can be renamed by double-click.
- Groups preserve expanded/collapsed state.
- Artifacts can be dragged between groups.
- Evidence blocks from the global left sidebar can be dropped onto groups or artifacts.

## Drag And Drop Rules
- Dropping an evidence block onto a group creates a new printable artifact in that group containing that evidence block.
- Dropping an evidence block onto blank tree space creates a new printable artifact in the default group.
- Dropping an evidence block onto an existing printable artifact always appends the evidence block to that artifact.
- Do not insert at drop position. Always append.
- Moving printable artifacts between groups should not affect contained evidence block order.

## Cleanup
- Remove old Output Formatting UI elements:
  - workstation conversation list
  - range boundary buttons
  - highlight override controls
  - range suggestion button
  - notes editor tied to workstation conversations
  - HTML preview/export controls
  - embedded Source Thread Viewer

## Acceptance Criteria
- Output Formatting tab no longer imports `SourceThreadView`.
- Output Formatting tab no longer calls range suggestion logic.
- Artifact groups and artifacts display from the new tables.
- Dragging an evidence block from the global sidebar onto the artifact tree creates/appends as specified.
- Selecting an artifact populates the metadata controls and preview.

## Tests
- Smoke test that Output Formatting tab initializes with the new tree.
- Drop evidence block onto group -> creates artifact.
- Drop evidence block onto existing artifact -> appends block.
- Drop same evidence block twice onto same artifact -> two ordered entries exist.
- Move artifact to another group.
