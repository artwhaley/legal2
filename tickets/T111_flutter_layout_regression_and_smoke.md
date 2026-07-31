# T111 - Flutter Layout Regression And Smoke

## Goal

Prove the transcript/category/deletion, Conversation Send/Stop, and persisted resizing changes work together on a real schema-v15 workspace.

## Depends On

T106, T107, T108, T109, T110.

## Automated Verification

```powershell
cd flutter_client
flutter analyze
flutter test
```

Do not suppress analyzer failures or weaken assertions.

## Required Regression Coverage

- Category create, select, collapse, rename, empty-delete, merge, and persistence.
- Merge preserves every dataset evidence block and all revision associations.
- Category-selected, block-selected, and no-selection creation rules.
- Hit-message default titles stored in full; two-line sidebar presentation; full title editing.
- Explicit sidebar selection is unaffected by viewport activity, overlap, deep jumps, Search navigation, or Conversation navigation.
- Delete button targets only the selected sidebar block; right-click targets only the clicked block.
- No evidence-block delete surface exists outside the sidebar.
- Left sidebar, New/Delete placement, and all requested UI removals.
- Conversation description/Ready-card removal and Send -> Stop -> Stopping -> Send transitions.
- All five resizable work areas, persistence keys, minimums, small-window fallback, and shared transcript-sidebar size.
- Existing transcript virtualization, evidence annotation/editing, search, conversation, and print tests remain green.

## Manual Real-EVW Smoke

Use a disposable copy of a real schema-v15 EVW and record every result.

1. Open a ready revision and confirm the evidence sidebar is left of the transcript with the requested chrome removed.
2. Create two categories, rename one, collapse one, reopen the EVW, and confirm both name and collapse state persisted.
3. Create blocks using category-selected, block-selected, and no-selection states; confirm category placement and hit-message titles.
4. Edit a title to a long multiline value; reopen and confirm the complete value persisted.
5. Drag blocks between categories and confirm persistence after reopen.
6. Merge a populated category into another and confirm every block remains present in all associated revisions; confirm only the source category disappeared.
7. Create and delete an empty category. Confirm populated-category Delete is unavailable and `Uncategorized` is protected.
8. Select block A in the sidebar, scroll/jump until block B is viewport-active, then use Delete selected block. Cancel once; repeat and confirm only A is deleted.
9. With A selected and B active, right-click B and delete it; confirm B is the target.
10. Repeat deletion targeting with overlapping blocks and confirm the captured target never changes.
11. Submit a Conversation request; confirm Send becomes Stop, click it once, confirm Stopping is disabled, then confirm return to Send after closure.
12. Complete another request and confirm inline Working and completed output still render.
13. Resize every listed vertical and horizontal split, change tabs, close/reopen the EVW, and restart the app; confirm sizes persist.
14. Drag every split to both extremes and shrink the window; confirm every pane and divider remains visible/reachable at its safe minimum or stacked fallback.

## Guardrails

- No additional design changes during smoke fixes.
- No keyboard shortcuts.
- A failed persistence or safety assertion is a defect to fix in its owning ticket, not a limitation to waive.
- Never perform destructive smoke steps against the only copy of a production/legal evidence workspace.

## Acceptance Criteria

- `flutter analyze` passes.
- Full Flutter tests pass.
- Every manual step passes on a disposable real EVW.
- No evidence was lost during category lifecycle or deletion testing.
- No unrequested UI, fallback, shortcut, or explanatory copy was added.
