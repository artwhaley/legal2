# T40 - Printable Artifact Domain And Repositories

## Goal
Add domain dataclasses and repository functions for printable artifact groups, artifacts, ordered artifact blocks, and preview context loading.

## Scope
Add domain models:
- `PrintableArtifactGroup`
- `PrintableArtifact`
- `PrintableArtifactEvidenceBlock`
- `PrintableArtifactContext`
- `PrintableArtifactBlockContext`

Repository functions:
- `ensure_default_printable_artifact_group(conn, logger, dataset_id)`
- `list_printable_artifact_groups(conn, dataset_id)`
- `create_printable_artifact_group(conn, logger, dataset_id, name)`
- `rename_printable_artifact_group(conn, logger, group_id, name)`
- `set_printable_artifact_group_collapsed(conn, logger, group_id, is_collapsed)`
- `create_printable_artifact_from_evidence_block(conn, logger, dataset_id, group_id, evidence_block_id)`
- `append_evidence_block_to_printable_artifact(conn, logger, printable_artifact_id, evidence_block_id)`
- `move_printable_artifact_to_group(conn, logger, printable_artifact_id, group_id, sort_order=None)`
- `update_printable_artifact_metadata(conn, logger, printable_artifact_id, title, exhibit_number, case_number)`
- `reorder_printable_artifact_blocks(conn, logger, printable_artifact_id, ordered_join_ids)`
- `remove_printable_artifact_block(conn, logger, printable_artifact_evidence_block_id)`
- `load_printable_artifact_context(conn, printable_artifact_id)`

## Behavior
- Creating an artifact from an evidence block should default `title` from the evidence block title.
- Appending a block to an artifact always places it after existing blocks.
- Reordering blocks updates `sort_order` and should be immediately visible in subsequent context loads.
- Removing a block from an artifact does not delete the evidence block.
- Moving an artifact between groups does not alter its contained block list.

## Acceptance Criteria
- All repository functions log meaningful operations where existing repository patterns do.
- Loading context returns artifact metadata, included evidence blocks in `sort_order`, each block's source thread/messages, and dataset/thread/source metadata needed for preview/provenance.
- Empty artifact groups are supported.

## Tests
- Create default group.
- Create artifact from evidence block.
- Append two evidence blocks and verify order.
- Append the same evidence block twice and verify both entries remain.
- Reorder blocks and verify persisted order.
- Remove one artifact block and verify source evidence block remains.
- Move artifact between groups.
