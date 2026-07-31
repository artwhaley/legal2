# T109 - Flutter Conversation Chrome Cleanup And Send/Stop Control

## Goal

Remove the Conversation description and global Ready/Processing card while keeping cancellation immediately available by changing the composer button from Send to Stop during an active request.

## Depends On

T108 because Conversation embeds the shared transcript editor.

## Files / Areas Likely Touched

- `flutter_client/lib/src/conversation_page.dart`
- `flutter_client/lib/src/workstation_widgets.dart`
- relevant Flutter widget tests

## Remove Unrequested Chrome

1. Remove this description from loaded and no-workspace Conversation states:

   `Ask a scoped question, inspect live processing state, and review every cited range against the transcript.`

2. Allow `WorkstationPage` to omit its description without rendering an empty widget or spacing. Other pages keep their descriptions.
3. Remove `_ConversationStatus`, its Ready/Processing card, elapsed display, progress text, Cancel button, and associated spacing.
4. Remove state used only by the deleted status card.

## Send / Stop State Machine

Use the existing composer action location as the single request control:

- idle: label `Send`, send icon, submits the question;
- request active: label `Stop`, stop icon, calls the existing request cancellation exactly once;
- stop requested but request not closed: label `Stopping...`, disabled;
- request completed, failed, or cancelled: return to idle `Send` in `finally`.

The question field stays disabled while a request is active. A second request cannot start until the current request closes.

Stopping must preserve the existing visible cancellation notice/error handling. Do not silently remove a working/result card or report cancellation as successful before the gateway request actually closes.

## Behavior To Preserve

- The active answer card continues to show inline `Working...`.
- Completed answers, failures, validation errors, and notices remain visible.
- Conversation execution, server contracts, evidence navigation, range saving, and the embedded transcript are unchanged.

## Guardrails

- No global readiness/status replacement.
- No keyboard shortcut for Send or Stop beyond existing text-field submission behavior.
- No new progress header, elapsed display, metrics, or explanatory copy.
- No changes to answer/evidence result rendering.
- Do not remove working-corpus validation.

## Acceptance Criteria

- Scoped-question description and Ready/Processing card are absent.
- Other pages retain their descriptions.
- Composer button is Send only when idle.
- During an active request the same button becomes Stop and is enabled.
- One Stop click requests cancellation once and changes the button to disabled Stopping.
- After closure, the button returns to Send for completed, failed, and cancelled requests.
- Inline Working, completed output, failures, and cancellation notice remain visible.
- Rapid repeated clicks cannot send twice or cancel twice.

## Tests

Add/update widget tests for every button state and transition, including delayed cancellation closure and failure after a stop request. Run:

```powershell
cd flutter_client
flutter test
```
