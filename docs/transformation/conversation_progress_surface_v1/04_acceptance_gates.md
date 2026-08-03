# Acceptance gates

## Gate A - Server exactness

- `ProvisionalWindowRange` is strict.
- `window_completed` contains every accepted range and no rejected range.
- Accepted count equals list length.
- Validated normalization and authoritative thread identity are emitted.
- Empty and partial windows remain representable.
- Strict Python mirror agrees with Pydantic.

## Gate B - Zero additional model work

Using deterministic fake providers, prove the same request performs the same:

- planning calls;
- embedding calls;
- extraction calls;
- compaction calls, when applicable;
- synthesis calls.

No prompt or provider request body changes. The new event changes network
output only after extraction validation.

## Gate C - Flutter exactness

- Dart rejects old, missing, malformed, or extra-field event shapes.
- Dart accepts populated and empty provisional range lists.
- No provisional range is silently dropped.
- Out-of-order window completion is represented honestly.

## Gate D - Live observability

- Elapsed time advances through at least ten simulated seconds with no server
  event.
- Current stage follows real actions/events.
- Window progress uses exact counts.
- Latest heartbeat updates active-window state.
- Retry, warning, unavailable-window, failure, and cancellation remain visible.
- Provisional evidence appears immediately on `window_completed`.

## Gate E - Session retention

During an active fake request:

1. Enter Conversation and start the request.
2. Switch to Corpus, Search, Transcript, and Print output.
3. Advance fake time and stream more events while Conversation is offstage.
4. Return to Conversation.

Prove:

- the same card instance/state remains;
- elapsed time advanced;
- all events and provisional ranges remain;
- the request was neither cancelled nor duplicated.

Repeat after success, failure, and cancellation. Application restart is not a
retention requirement. Revision change must still clear cards.

## Gate F - Persistence integrity

- Successful persistence contains only the existing completed conversation
  fields.
- No activity, heartbeat, retry, timer, or provisional payload is written.
- Failed/cancelled runs write no completed conversation.
- No EVW schema or migration changes exist in the diff.

## Gate G - Full regression

Run with the repository's configured environments:

```text
focused Python server contract/orchestration tests
complete Python automated suite, excluding only documented existing markers
dart format on touched Dart files
flutter analyze
flutter test
flutter build windows --release
git diff --check
```

Do not use system Python when the repository virtual environment is available.
Record exact executable paths and commands.

## Gate H - Cost and external-state proof

- Automated tests use deterministic fakes only.
- External provider-call count is zero.
- No real embedding rebuild occurs.
- No server/admin configuration is activated or changed.
- No real EVW is mutated by tests.
