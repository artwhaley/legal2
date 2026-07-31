# T107 - Flutter Evidence Category Sidebar

## Goal

Turn the flat evidence list into a persisted category tree with explicit sidebar selection, category-aware creation, drag-to-category behavior, and safe category rename/delete/merge controls.

## Depends On

T106.

## Files / Areas Likely Touched

- `flutter_client/lib/src/transcript_editor.dart`
- `flutter_client/test/transcript_editor_test.dart`

## Sidebar Structure

- Keep the existing `Evidence blocks` panel and selected-block metadata editor.
- Add one compact `New category` control in the panel header.
- Render every dataset category, including empty categories and `Uncategorized`.
- Render the revision's evidence blocks under their category.
- Persist every category expansion/collapse toggle.
- Keep existing database ordering for categories and blocks.

Creating a category uses a name dialog with Create and Cancel. Blank, duplicate, or reserved names show the existing failure UI and create nothing. After success, the new category is expanded and becomes the selected creation category.

## Explicit Sidebar Selection

Maintain sidebar selection separately from the transcript's viewport-driven active block.

- Clicking a category selects that category as the creation target and clears any sidebar block selection.
- Clicking a block selects that immutable block ID, selects its category as the creation target, and may reveal/activate it in the transcript as it does now.
- Viewport scrolling, deep jumps, overlapping ranges, search-result navigation, and conversation-result navigation must never change sidebar selection.
- The sidebar title/summary editor reads and writes the explicitly selected sidebar block, not whichever block the viewport later marks active.
- Creating a block selects the new block and its category.

Creation rules:

- selected category -> create there;
- selected sidebar block -> create in that block's category;
- no sidebar selection -> create in `Uncategorized`.

## Drag Between Categories

- Give every block row a visible mouse drag affordance.
- Make every category header a drop target, including empty categories.
- A same-category drop performs no write.
- A successful move writes once, keeps the block selected, and selects/expands the destination category.
- A failed move surfaces the original error and reloads/keeps the persisted source category.

No block ordering is added.

## Category Lifecycle UI

Give non-protected category headers an explicit menu with:

- `Rename category`
- `Delete category`
- `Merge into...`

Rules:

- Rename uses a dialog showing the current full name and an explicit Save action.
- Delete is available only for a category whose dataset-wide block count is zero. It requires confirmation naming the category.
- Merge requires choosing a different destination category and confirming both category names and the dataset-wide number of blocks that will move.
- Merge calls one T106 transaction; the UI must not move rows optimistically before it succeeds.
- After merge, select/expand the destination. A selected moved block remains selected.
- `Uncategorized` has no rename, delete, or merge-as-source actions, but remains a valid destination.

Do not offer a destructive deletion path for a populated category. The supported removal path is merge.

## Evidence Titles

- Display each stored title with `maxLines: 2` and `TextOverflow.ellipsis`.
- Show the full stored title in the selected-block editor.
- Keep explicit Save for title and summary.
- Do not truncate, rewrite, or cap saved titles.

## Guardrails

- No keyboard shortcuts.
- No category color, description, or reorder UI.
- No category drag/reorder.
- No block reorder or drag-to-delete.
- No automatic save while typing.
- No new instructional paragraphs.
- Do not hydrate all hit-message bodies to render the tree; use stored titles.

## Acceptance Criteria

- Categories render, create, select, collapse, rename, empty-delete, and merge as specified.
- Category state survives controller reload and EVW reopen.
- Explicit sidebar block selection survives viewport changes and big/deep scrolls.
- Metadata edits always affect the selected sidebar block.
- Category/block/no-selection creation rules are deterministic.
- Dragging persists, and failures leave UI/database consistent.
- Populated categories cannot be directly deleted.
- Merge preserves every evidence block and removes only the source category.
- Block titles occupy at most two list lines while the full title remains editable.

## Tests

Add widget/data tests for all acceptance criteria, including right after viewport-driven active-block handoff and with overlapping blocks.

Run:

```powershell
cd flutter_client
flutter test test/transcript_editor_test.dart
```
