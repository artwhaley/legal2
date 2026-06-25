# T26 - Role-Based Model Settings and Migration

## Goal

Replace the current single-model configuration shape with role-based model settings for `Expansion`, `Research`, and `Writing`, while preserving backward compatibility with existing NIM-only settings.

## Dependencies

T25, T09, token-context-budgeting settings work.

## Implementation Notes

This ticket defines the stored configuration model that later router and provider tickets will consume. The app must remain usable for existing users with old settings files and existing `MEW_NIM_API_KEY` behavior.

Target user-facing roles:

- `Expansion model`
- `Research model`
- `Writing model`

Recommended shape:

```python
@dataclass
class ModelRoleConfig:
    provider: str
    model: str
    api_base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 4096
    timeout_seconds: float = 600.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelRoutingSettings:
    expansion: ModelRoleConfig
    research: ModelRoleConfig
    writing: ModelRoleConfig
```

Migration requirements:

- If no role-based settings exist, seed all three roles from current NIM settings.
- Preserve the current selected NIM model as the initial model for all roles.
- Preserve existing defaults for timeout, output tokens, and temperature.
- Keep `MEW_NIM_API_KEY` as an env override for NIM-backed roles.
- Add `MEW_GOOGLE_API_KEY` support now, even though Google provider behavior lands later.
- Environment variables must override stored keys.

The old `NimSettings` object can remain for compatibility during the migration window, but new feature work should prefer the role-based settings object.

Research-model task roles (confirmed): `session_summary`, `session_classification`, `coverage_audit` — used only in explicit `session_coverage` answer mode.

## Suggested Execution Plan

1. Introduce role-based settings dataclasses.
2. Add JSON load/save support with backward-compatible migration from old settings.
3. Add env override support for NIM and Google API keys.
4. Update settings tests to cover old-file migration and fresh-file defaults.

## Files / Areas Likely Touched

- `message_evidence_workstation/config/settings.py`
- `message_evidence_workstation/nim/context_limits.py`
- `message_evidence_workstation/nim/message_roles.py`
- `tests/test_ui_smoke.py`
- `tests/` settings-related tests

## Acceptance Criteria

- Existing settings files load without user intervention.
- A fresh settings file seeds all three roles to the current NIM defaults.
- `MEW_NIM_API_KEY` still overrides stored NIM keys.
- `MEW_GOOGLE_API_KEY` is supported for future Google-backed roles.
- Settings save/load round-trips preserve per-role provider/model values.

## Tests / Verification

- Unit test: old NIM-only settings migrate to the new role-based shape.
- Unit test: fresh settings create three role configs with expected defaults.
- Unit test: env vars override stored API keys.
- UI smoke test: settings load still succeeds after migration.

## Non-Goals

- No central router yet.
- No provider-specific request logic yet.
- No per-role UI controls yet.

