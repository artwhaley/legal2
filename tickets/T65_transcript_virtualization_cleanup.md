# T65 - Transcript Virtualization Cleanup

## Goal
Finish the transcript virtualization pass by removing full-thread escape hatches and replacing whole-thread UI notifications with bounded visible-window updates.

## Background
The transcript surface is partially virtualized, but a few helpers still load entire threads or emit signals across every slot in a large thread.

**Spec reference:** `05_large_dataset_performance_patch_spec.md` Sections 9, 10

## Depends On
- T64

## Scope
- Remove or rewrite transcript helpers that build a virtualized model and then also load the full thread
- Replace `_emit_all_separator_changes` with bounded range notifications
- Replace any whole-window/whole-thread message update blasts with loaded-window or visible-range updates
- Ensure evidence block selection, highlight toggles, and focus flows continue to work with bounded loaded windows
- Keep transcript sessions/chunks as optional metadata only; do not require transcript segmentation for scrolling

## Guardrails
- Do not break evidence block create/edit/save flows
- Do not reintroduce `list_messages_for_thread` into transcript display paths
- Keep memory bounded while scrolling

## Non-Goals
- New transcript sectioning UX
- Search pipeline changes

## Acceptance Criteria
- Transcript display paths do not load full threads
- Selecting or editing evidence blocks in a large thread does not emit one signal per slot
- Deep scroll remains responsive with loaded-window updates only

## Tests
- Update transcript model/widget tests
- Add or extend scale smoke for deep scroll/focus behavior
- `python -m pytest -q`

