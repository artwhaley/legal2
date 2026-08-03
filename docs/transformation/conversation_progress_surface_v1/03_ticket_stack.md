# Ticket stack

Execute in dependency order. Complete focused tests and update
`execution_log.md` before starting a dependent ticket.

## CSP1-000 - Baseline and contract inventory

Read the full packet and all named source/test files. Record:

- branch, commit, and complete dirty-worktree status;
- Python environment used by the repository;
- Flutter and Dart versions;
- focused server contract/orchestration baseline;
- complete Flutter test/analyze baseline;
- Windows release-build baseline if presently possible;
- exact current `window_completed` server, Python mirror, and Dart contracts;
- current `IndexedStack` state-retention behavior.

Do not modify source in this ticket. Preserve unrelated user changes and
generated logs.

Acceptance: `execution_log.md` contains a factual baseline and no source file
was changed by CSP1-000.

## CSP1-100 - Extend the server event contract

Implement `ProvisionalWindowRange` and extend `WindowCompletedData` exactly as
specified in `01_server_event_contract.md`.

Update strict server contract tests for:

- valid populated and empty events;
- missing and extra fields;
- accepted count/list mismatch;
- duplicate source indexes;
- invalid nullable text;
- invalid normalization;
- validation-status invariants.

Acceptance: focused Pydantic contract tests pass without weakening strictness.

## CSP1-200 - Emit validated ranges without changing model work

Populate the extended `window_completed` event from
`ValidatedWindowEvidence` in `server/conversation_unified.py`.

Add orchestration tests proving:

- valid siblings are emitted when another model range is fabricated;
- fabricated/rejected ranges are absent;
- reversed endpoints use normalized values;
- missing descriptions remain null rather than invented text;
- empty evidence emits an empty list;
- multi-window completion emits each window's own ranges;
- provider invocation count and operation sequence are unchanged;
- final ledger and synthesis behavior are unchanged.

Acceptance: no prompt snapshot, provider payload, usage count, or final result
changes except consequences of the new progress fields.

## CSP1-300 - Update strict client contract mirrors

Update:

- Dart `window_completed` validation;
- deterministic fake event fixtures;
- the one temporary Python API-contract mirror branch.

Both mirrors enforce the same exact fields and invariants as Pydantic. Do not
add permissive optional support for old event shapes. This project controls
one server and one future product client; move the exact contract together.

Acceptance: malformed event matrices fail in Python and Dart, and real-shaped
events pass.

## CSP1-400 - Add card-owned session run state and live timer

Extend the existing conversation card/page state minimally. Implement one
page-owned periodic timer and terminal elapsed freezing.

Requirements:

- state remains owned above rebuildable working widgets;
- timer advances without incoming events;
- timer advances while offstage in another tab;
- timer stops exactly once on every terminal path;
- dispose cannot leave a timer or callback alive;
- revision changes retain the current intentional card-clear behavior;
- tab changes never clear or cancel state.

Acceptance: deterministic widget tests cover success, failure, cancellation,
event silence, tab switching, and disposal.

## CSP1-500 - Project exact progress and provisional evidence

Parse the extended event into the card's in-memory display state. Implement
the active-card layout from `02_flutter_state_and_ux.md`.

Requirements:

- exact factual stage mapping;
- exact determinate window progress only when counts exist;
- active-window count from heartbeat data;
- provisional groups in completion order, source ranges in source order;
- all ranges displayed with no arbitrary cap;
- null summary shown as `Description unavailable`;
- no provisional evidence interaction or persistence;
- all failures/retries/warnings remain visible.

Acceptance: one-window, multi-window, out-of-order, empty-evidence, retry, and
partial-window widget/workflow tests pass.

## CSP1-600 - Terminal run summary and retained activity

On terminal state, keep the full card and activity in memory while making the
final answer primary.

Requirements:

- success replaces provisional presentation with existing final result UI;
- compact summary uses actual elapsed/window/range data;
- full activity is collapsed but available;
- failure/cancellation keeps incomplete provisional history visible;
- switching tabs after any terminal state retains everything;
- no progress fields are added to EVW writes;
- failed/cancelled runs still do not create completed history.

Acceptance: persistence-spy tests and widget tests prove the boundary.

## CSP1-700 - Focused regression and residue cleanup

Run all focused and complete automated suites. Inspect the implementation for:

- duplicate timers or run-state stores;
- model-authored progress text;
- fake percentages;
- provisional-range truncation;
- progress persistence;
- prompt/provider/config changes;
- Python GUI/workflow changes;
- navigation-state regression;
- stale callbacks after disposal;
- mojibake introduced or touched in visible status strings.

Remove obsolete unused progress widgets only when the new implementation makes
them unreachable and tests cover the replacement. Do not perform unrelated UI
cleanup.

## CSP1-800 - Build and manual smoke preparation

Run formatting, static analysis, complete tests, and Windows release build.
Prepare lean manual checks for:

- a 100K single-window run;
- a large multi-window run;
- a retry;
- cancellation;
- terminal provider failure;
- switching through all tabs during and after each state.

Automated gates make no external model calls. Do not start a live server or
spend provider tokens merely to satisfy this ticket.

## CSP1-900 - Closeout

Create `closeout_report.md` containing:

- ticket status;
- changed files and purpose;
- exact commands, results, and test totals;
- event contract before/after;
- provider-call-count invariance proof;
- EVW persistence invariance proof;
- tab/session retention proof;
- timer lifecycle proof;
- Windows build result;
- residue-scan result;
- any genuine unresolved deficiency;
- concise human manual-test instructions.

Do not claim completion while a required gate is failing. Clean disposable
test artifacts and stop any process started by validation.
