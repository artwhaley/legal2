# Flutter state and UX contract

## Ownership

Each `_ConversationCard` owns all display state for one run:

- question;
- progress events;
- start time;
- current elapsed time while active;
- frozen terminal elapsed time;
- provisional ranges received from completed windows;
- outcome or failure;
- activity expansion state if needed for stable UI behavior.

Do not put authoritative run state inside `_WorkingConversationState`; that
widget may rebuild or become offstage. Do not move this feature into a new
state-management framework.

Only one remote conversation may be active, matching the current page and
workspace operation-lease behavior.

## Timer

Use one page-owned periodic timer for the one active card.

- Start at submission, before planning begins.
- Tick approximately once per second.
- Continue while the Conversation tab is offstage.
- Continue through planning, embeddings, provider silence, retries,
  validation, compaction, and synthesis.
- Stop and freeze on success, cancellation, or failure.
- Cancel in `dispose`.
- Never derive the live clock only from event arrival timestamps.
- Never create a timer per card, event, window, or heartbeat.

Display `MM:SS` below one hour and `H:MM:SS` at or above one hour.

## Factual stage projection

Project only events/actions that actually occurred:

1. Planning analysis
2. Preparing local retrieval
3. Submitting corpus
4. Analyzing windows
5. Validating evidence
6. Building evidence ledger
7. Compacting evidence ledger, only if triggered
8. Synthesizing answer
9. Validating synthesis
10. Saving completed answer

Do not create weighted stage percentages. Window progress is determinate only
after the server provides an exact `window_count`. A single active provider
call remains indeterminate except for elapsed time and truthful heartbeat
metadata.

## Active card layout

Render in this order:

1. Spinner, current stage, and live elapsed time.
2. Latest factual status sentence.
3. Exact window progress bar when window count is known.
4. Text showing completed/total windows and active-window count when known.
5. Preliminary evidence panel when at least one accepted range arrives.
6. Collapsible activity history.

Use this exact preliminary label:

> Preliminary evidence - final synthesis may merge, reclassify, or omit these ranges.

For each provisional range show:

- window number;
- summary, or `Description unavailable` when null;
- relevance when present;
- exact start and end message IDs.

This first pass is read-only. Do not add provisional save, edit, hide, or
evidence-block controls. Final result ranges retain their existing navigation
and save behavior.

## Activity history

Keep every received event in memory.

Presentation rules:

- Show all non-heartbeat milestones in stream order.
- Consecutive heartbeats may update one visible live heartbeat row instead of
  creating dozens of identical rows.
- This visual coalescing must not delete underlying events.
- Retries, warnings, unusable output, unavailable windows, failures, and
  cancellation are always visible and never coalesced away.
- Show each event's elapsed offset from run start.

## Concurrency and provisional ordering

Windows may complete out of index order. Do not imply otherwise.

- Activity remains in event-arrival order.
- Provisional evidence groups are appended in completion order and labeled
  with their actual window number.
- Inside a group, preserve `source_range_index` order.
- The final completed result replaces the provisional panel as the
  authoritative answer.

## Terminal presentation

### Success

Render the existing final result UI unchanged, plus a compact run summary and
a collapsed `Show activity` control.

Summary shape:

```text
Completed in 1:37 - 8/8 windows usable - 42 candidate ranges
```

Use values actually observed from events/final result. Omit a segment when its
value is genuinely unavailable; do not fill with zero guesses.

### Failure or cancellation

- Freeze elapsed time.
- Show the original failure/cancellation clearly.
- Keep completed-window, retry, warning, and provisional history available.
- Mark provisional evidence incomplete.
- Do not persist a completed conversation.

## Navigation retention

The existing `IndexedStack` is the intended mechanism. Preserve it.

Automated tests must prove that an active timer and all card state survive
switching from Conversation to every other tab and back. Do not use
`AutomaticKeepAliveClientMixin` unless tests prove the existing stack no
longer preserves state after the implementation.

Changing the selected revision continues to clear cards. Application restart
clears progress. These are intentional boundaries, not bugs.
