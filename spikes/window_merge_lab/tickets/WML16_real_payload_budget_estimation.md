# WML16 - Real Payload Budget Estimation

## Goal

Fix budget planning so it estimates actual serialized prompt payloads, not raw source window objects.

## Depends On

- WML15

## Phase Inversion

Estimating actual serialized tokens requires building candidate messages first.
But building messages requires knowing which profile (full/compact) to use.
Break the circular dependency with a provisional-build step:

1. Build ledger records
2. Build candidate `full` messages using a **provisional** plan (default `answer_format="detailed"`, profile can be set to `"full"` at this stage since we're testing the full payload)
3. Estimate actual serialized input tokens for `full` by serializing the candidate messages and counting tokens
4. Estimate expected `full` output tokens (using per-range constants, e.g. `1500 + range_count * 190`)
5. If `full` fits (both input and output within budget), choose it
6. Otherwise build candidate `compact` messages using a provisional compact plan (`answer_format="brief"`)
7. Estimate actual serialized input tokens for `compact`
8. Choose `compact`

The planner should return:

- selected profile
- built messages for the selected profile (reuse them — do not build again)
- estimated serialized input tokens for the selected profile
- estimated output tokens for the selected profile
- comparable estimates for both profiles
- reason compact was selected when applicable

## Estimation Method

Use `len(json.dumps(messages, ensure_ascii=False)) // 3.5` for serialized token
estimation (same as existing `estimate_json_tokens`). The existing per-constant
output estimates (`estimate_full_direct_output_tokens`, `estimate_compact_direct_output_tokens`)
remain as the output-side budget check.

## Planner Mode Naming

The current budget planner uses mode strings `"full_direct_synthesis"` and
`"compact_direct_synthesis"`. Align these to the LEDGER convention during this
refactor:

| Old value | New value |
|---|---|
| `mode: "full_direct_synthesis"` | `mode: "full"` |
| `mode: "compact_direct_synthesis"` | `mode: "compact"` |
| `prompt_profile: "full_direct_synthesis"` | `prompt_profile: "full"` |
| `prompt_profile: "compact_direct_synthesis"` | `prompt_profile: "compact"` |
| `answer_format: "detailed"` | unchanged |
| `answer_format: "brief"` | unchanged |

Update `SynthesisBudgetPlan.mode` type hint from
`Literal["full_direct_synthesis", "compact_direct_synthesis"]` to
`Literal["full", "compact"]`.

Also update `SynthesisBudgetPlan.prompt_profile` type to `Literal["full", "compact"]`.
The calling code in strategies and GUI reads `plan.mode` for display and metrics
— those references will automatically pick up the new strings.

## Rules

- Full is preferred when it fits
- Compact is selected otherwise
- No synthesis-time refusal mode in this stack
- Planning should target `evidence_ledger_synthesis`
- Existing legacy strategies may keep old planner behavior unless the implementation chooses to reuse the improved planner

## Guardrails

- Do not estimate off raw windows when the final payload is materially different
- Do not hide the planner decision from metrics
- Keep estimation constants easy to tune

## Acceptance Criteria

- Planner builds candidate messages before deciding
- Planner records actual serialized prompt estimates
- Full is selected when full fits
- Compact is selected when full does not fit
- Metrics show both selected profile and why compact was chosen
- Tests cover full-fit and compact-selected cases

