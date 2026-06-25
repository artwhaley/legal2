# T39 - Printable Artifact Schema

## Goal
Add first-class persistence for printable artifact groups, printable artifacts, and ordered evidence blocks inside each artifact.

## Background
A printable artifact is a print package/exhibit. It can contain one or more evidence blocks, in user-controlled order. A single evidence block can appear in multiple printable artifacts. Dragging the same evidence block again creates or appends another artifact entry; do not enforce uniqueness.

## Schema
Add `printable_artifact_group`:

```sql
printable_artifact_group (
    printable_artifact_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_collapsed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
)
```

Add `printable_artifact`:

```sql
printable_artifact (
    printable_artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    exhibit_number TEXT NOT NULL DEFAULT '',
    case_number TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id),
    FOREIGN KEY (group_id) REFERENCES printable_artifact_group(printable_artifact_group_id)
)
```

Add `printable_artifact_evidence_block`:

```sql
printable_artifact_evidence_block (
    printable_artifact_evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    printable_artifact_id INTEGER NOT NULL,
    evidence_block_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (printable_artifact_id) REFERENCES printable_artifact(printable_artifact_id),
    FOREIGN KEY (evidence_block_id) REFERENCES evidence_block(evidence_block_id)
)
```

## Rules
- Do not add a uniqueness constraint on `evidence_block_id`.
- Do not add a uniqueness constraint on `(printable_artifact_id, evidence_block_id)`.
- `exhibit_number` and `case_number` are plain text fields. No validation.
- Create one default group per dataset, similar to Uncategorized, so the UI always has a drop target.

## Acceptance Criteria
- Existing EVW files migrate forward cleanly.
- Fresh workspaces create the new tables.
- Re-running migrations is idempotent.
- Multiple artifacts can reference the same evidence block.
- One artifact can contain multiple evidence blocks.
- The same evidence block can be appended twice to one artifact if the user does it.

## Tests
- Schema smoke test includes all three new tables.
- Migration test opens an existing/minimal workspace and confirms tables exist.
- Repository-level test inserts multiple artifact rows pointing at the same evidence block.
- Repository-level test inserts multiple ordered block entries in one artifact.
