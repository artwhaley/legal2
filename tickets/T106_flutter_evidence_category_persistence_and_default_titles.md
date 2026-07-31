# T106 - Flutter Evidence Category Persistence And Default Titles

## Goal

Add the explicit data operations required for safe category lifecycle management and sidebar-targeted evidence editing, and replace `Evidence at message N` with the hit message text for transcript-created blocks.

## Depends On

None.

## Current Implementation

- Schema v15 already stores dataset-scoped categories, `category.is_collapsed`, and each block's `category_id`.
- `EvwDatabase.categories()` reads only category ID and name.
- Flutter has no category-create, rename, collapse, delete, merge, or block-move operations.
- `EvwDatabase.createEvidenceBlock()` forces new blocks into `Uncategorized` and defaults to `Evidence at message ${hitOrdinal + 1}`.
- The controller's metadata and deletion methods target whichever block is currently active in the viewport.

## Files / Areas Likely Touched

- `flutter_client/lib/src/evw_models.dart`
- `flutter_client/lib/src/evw_database.dart`
- `flutter_client/lib/src/transcript_editor.dart`
- `flutter_client/test/transcript_editor_test.dart`

## Category Read And Write Contract

Implement explicit database operations to:

1. Read `is_collapsed` and the dataset-wide evidence-block count into `CategorySummary`.
2. Create a category from a non-empty trimmed name.
3. Rename a category.
4. Persist collapsed/expanded state.
5. Move one evidence block to another category.
6. Delete an empty category.
7. Merge one category into another by moving every source-category evidence block and then deleting the source category in the same transaction.

All category names must be unique within a dataset using a case-insensitive comparison. Create or rename must fail visibly on a duplicate or blank name.

`Uncategorized` is the permanent default category:

- it may be a move/merge destination;
- it cannot be renamed, deleted, or used as a merge source;
- another category cannot be created or renamed to `Uncategorized` using any case variant.

Delete and merge must operate on every evidence block in the dataset, including blocks not visible in the selected revision. A category count shown to the caller must therefore also be dataset-wide.

## Transaction And Validation Rules

Every write uses `_write()` and `_touchWorkspace()`.

- Validate that source category, destination category, revision, and evidence block belong to the expected dataset.
- Validate that a moved/deleted block is associated with the selected revision where the operation is revision-scoped.
- Reject same-source/destination merges.
- Recheck that a category is empty inside the delete transaction.
- A failed merge must leave all block category IDs and both category rows unchanged.
- Category removal must never execute `DELETE FROM evidence_block`.

## Explicit Evidence-Block Targets

Replace controller mutation methods that infer their target from `activeBlock` for sidebar operations:

- replace `deleteActiveBlock()` with `deleteBlock(evidenceBlockId)`;
- make title/summary saving receive `evidenceBlockId` explicitly;
- make category moves receive `evidenceBlockId` explicitly.

Each method must validate that the supplied block is loaded/associated, persist that exact ID, and update controller state only after the write succeeds. Viewport reconciliation must not be consulted to choose a destructive or metadata target.

Boundary, primary-message, and highlight editing may retain their existing active-transcript behavior; this ticket changes sidebar mutations only.

## Category-Aware Creation

Require transcript evidence creation to receive an explicit target `categoryId`. Callers choose `Uncategorized` only when the sidebar has no selected category or selected block. Validate the category before inserting the evidence block; do not fall back to another category after failure.

Do not change the category/title behavior for conversation-created evidence blocks in this ticket.

## Default Title Contract

When transcript `createEvidenceBlock()` has no caller-supplied title:

- store the complete trimmed `body` of the hit/core message;
- preserve internal line breaks and all non-whitespace content;
- impose no character limit and store no ellipsis;
- use the literal `No text in hit message` if the trimmed body is empty.

Caller-supplied titles remain authoritative.

## Guardrails

- No schema/version change.
- No category or block sort-order field.
- No category color or description API.
- No destructive category cascade.
- No active-viewport block inference for sidebar writes.

## Acceptance Criteria

- Category create, rename, collapse, move, empty-delete, and merge survive a fresh read.
- Duplicate and reserved category names are rejected without mutation.
- `Uncategorized` protections are enforced in the database layer, not only by disabled UI.
- Merge moves all dataset blocks, preserves revision associations, and atomically removes only the source category.
- Empty-delete fails atomically if a block appears before the transaction executes.
- Cross-dataset operations fail atomically.
- Block deletion and metadata saving persist the exact supplied block ID even when viewport active state points elsewhere.
- Transcript creation requires a valid explicit category.
- Default titles preserve complete ordinary, long, multiline, and Unicode hit-message bodies.
- A whitespace-only hit message receives exactly `No text in hit message`.

## Tests

Add focused tests for all acceptance criteria, including:

- merge coverage across two revisions of one dataset;
- failed merge rollback;
- no evidence-block deletion during category merge/removal;
- overlapping blocks where viewport activity differs from the explicit mutation target.

Run:

```powershell
cd flutter_client
flutter test test/transcript_editor_test.dart
```
