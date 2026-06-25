# T31 - Role-Based Model Settings UI

## Goal

Expose per-role provider/model configuration in Setup / Settings so users can independently configure Expansion, Research, and Writing models.

## Dependencies

T26, T28, T30.

## Implementation Notes

The settings UI needs to stay usable while adding much more configuration power. The important user-facing idea is simple: three roles, each with a provider and model, plus provider-specific keys.

Required controls:

- `Expansion model` provider selector
- `Expansion model` model selector or manual entry
- `Research model` provider selector
- `Research model` model selector or manual entry
- `Writing model` provider selector
- `Writing model` model selector or manual entry
- grouped API key fields for NIM and Google
- per-role model test buttons

Recommended convenience behavior:

- a control to copy one role's provider/model to the others or "use same model for all roles"
- preserve current single-model default feeling for users who do not want to think about roles
- manual entry fallback when provider listing is unavailable or incomplete

The settings page should continue to expose provider-specific diagnostics such as model test results and model-list refresh where appropriate.

## Suggested Execution Plan

1. Add role-based UI controls bound to the new settings shape.
2. Add provider-specific key fields and env-override messaging.
3. Add per-role model test actions wired through the router.
4. Add convenience behavior for same-model setup.
5. Update settings smoke tests.

## Files / Areas Likely Touched

- `message_evidence_workstation/ui/settings_tab.py`
- `message_evidence_workstation/config/settings.py`
- `tests/test_ui_smoke.py`
- related settings tests

## Acceptance Criteria

- User can independently configure provider/model for expansion, research, and writing.
- User can store Google and NIM credentials in settings, with env overrides still winning.
- User can test each role's configured model from the settings UI.
- Existing users who do nothing still see sane defaults and a working app.

## Tests / Verification

- UI smoke test: settings page renders role-based controls.
- UI smoke test: saving and reloading settings preserves per-role provider/model values.
- UI smoke test: per-role model test action routes through the configured provider.
- Regression test: old settings still load and populate the new controls.

## Non-Goals

- No subscription or usage-reporting UI.
- No advanced provider-specific tuning panel beyond core role settings.

