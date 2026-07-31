# T108 - Flutter Transcript Sidebar Layout And Safe Deletion

## Goal

Place evidence management on the left and make the sidebar the only evidence-block deletion surface. A viewport-active block is never a deletion target.

## Depends On

T107.

## Files / Areas Likely Touched

- `flutter_client/lib/src/transcript_editor.dart`
- `flutter_client/test/transcript_editor_test.dart`

## Wide Layout

At the existing wide breakpoint, place the evidence sidebar before the transcript with the existing gutter. T110 will replace the initial fixed width with a persisted resizable width.

Do not change transcript rendering, scrolling, annotations, or boundary interactions. Preserve the existing narrow responsive layout until T110 adds its safe small-window behavior.

## Sidebar Actions

Place these controls beneath the sidebar content:

- `New block at center`
- `Delete selected block`

`New block at center` retains center-ordinal creation and uses T107's explicit creation category.

`Delete selected block`:

- is disabled unless a block row was explicitly selected in the sidebar;
- captures that selected block's immutable ID and title before opening confirmation;
- confirms the exact block title;
- calls `deleteBlock(capturedId)`;
- remains bound to that captured ID even if viewport activity changes while the dialog is open.

Category selection, viewport activation, transcript clicks, scroll position, search navigation, and conversation navigation must never enable or retarget this button.

## Right-Click Deletion

Right-clicking an evidence-block row may open a sidebar context menu containing `Delete block...`.

- The right-clicked row itself is the immutable target; it does not rely on prior selection or viewport activity.
- Capture the row's ID/title before showing the menu and confirmation.
- Use the same confirmation and explicit-ID deletion path as the button.
- Right-clicking a category or empty sidebar space must not expose block deletion.

There must be no evidence-block delete action outside the sidebar.

## Remove The Existing Top Toolbar

Remove the toolbar surface and do not relocate:

- `Reveal active block`
- `Reload evidence`
- message count
- evidence-block count

## Remove The Specified Copy

Delete these blocks and their unused spacing:

- the paragraph beginning `The visible block nearest the center markers becomes editable.`;
- `Select a block to edit its title, summary, boundaries, primary message, and highlights.`

Add no replacement instructions.

## Remove Unsafe/Duplicate Deletion Paths

- Remove the old metadata-section delete control.
- Remove any call site using `deleteActiveBlock()`.
- Search the Flutter client for evidence-block deletion controls and prove only the sidebar button and block-row context menu remain.

## Guardrails

- No keyboard shortcuts or Delete-key binding.
- No swipe-to-delete or drag-to-delete.
- No viewport-based destructive action.
- Keep the existing confirmation dialog and visible failure reporting.
- No new toolbar, metrics, help copy, or fallback controls.

## Acceptance Criteria

- Wide layout places evidence sidebar left of transcript.
- New and Delete are beneath the sidebar.
- Delete remains disabled for category-only selection and viewport-only activity.
- Selecting block A, scrolling until block B becomes active, and pressing Delete still targets block A.
- Opening deletion for A and forcing a deep jump before confirmation still targets A.
- Right-click deletion targets the clicked block even when another block is selected/active.
- Overlapping evidence blocks cannot change a captured deletion target.
- No delete action exists outside the two sidebar entry points.
- Reveal, Reload, counts, and specified explanatory copy are absent.

## Tests

Add widget tests for all safety cases above, deletion cancel/confirm, and absence of removed UI. Run:

```powershell
cd flutter_client
flutter test test/transcript_editor_test.dart
```
