# Window Merge Lab

GUI spike for testing LLM merge strategies against saved exhaustive-window scan outputs.

## Launch

```powershell
python spikes\window_merge_lab\merge_lab_app.py
```

Or use the CLI:

```powershell
# List strategies
python spikes\window_merge_lab\merge_lab.py --list-strategies

# Dry-run a strategy (no API calls)
python spikes\window_merge_lab\merge_lab.py --strategy one_shot_compact --dry-run

# Run with a provider
python spikes\window_merge_lab\merge_lab.py --strategy hierarchical_balanced --provider settings
```

## Workflow

1. **Load data**: Click "Load Input JSON" to load the exported scan windows from `inputs/school_scan_windows.json`, or click "Load From .evw" to re-export from the workspace database directly.
2. **Select strategy**: Choose from five merge strategies in the dropdown.
3. **Inspect source windows**: Click rows in the source-window table to view raw responses, parsed JSON, and compact ranges.
4. **Build prompt**: Click "Build Prompt" to generate the LLM prompt without calling the model.
5. **Run strategy**: Click "Run Strategy" with "Dry run" checked to test without API calls, or uncheck to call the selected provider.
6. **Evaluate**: Click "Evaluate Outputs" to see quality metrics and coverage analysis.
7. **Compare**: Output files are written under `outputs/{timestamp}_{strategy}/` for cross-strategy comparison.

## Strategies

| Strategy | Calls | Description |
|----------|-------|-------------|
| `one_shot_compact` | 1 | Single LLM call over all six compact window findings |
| `hierarchical_balanced` | 3 | Merge windows 1-3, merge 4-6, then merge the two partial syntheses |
| `rolling_synthesis` | 6 | Sequential update: start with window 1, merge window 2 onward |
| `evidence_table_then_synthesis` | 1 | Normalize window findings into an evidence table, then synthesize |
| `deterministic_baseline` | 0 | No LLM call: concatenate, deduplicate, count (control only) |

## Safety

- This spike is intentionally isolated from the production UI.
- It does not modify production app code, database schema, or app tables.
- It does not import or instantiate production UI widgets.
- It only reads the `.evw` workspace database (read-only queries).
- All output files are written under `spikes/window_merge_lab/outputs/`.

## Directory Layout

```
spikes/window_merge_lab/
  README.md
  SPEC.md
  merge_lab_app.py          # PySide6 GUI
  merge_lab.py              # CLI entry point
  db_export.py              # Read-only workspace exporter
  data_loader.py            # Input loading, parsing, compaction, validation
  strategies.py             # Merge strategy implementations
  prompts.py                # Prompt builders for each strategy
  evaluator.py              # Evaluation and comparison
  inputs/
    school_scan_windows.json          # Full export (6 windows)
    school_scan_windows_compact.json  # Compact strategy-friendly records
  outputs/
    {timestamp}_{strategy}/
      prompt_payload.json
      prompt_preview.md
      result_raw.txt
      result_parsed.json
      result_readable.md
      metrics.json
      evaluation.md
```

## Known Limitations

- The GUI does not stream partial responses.
- API errors are captured but not automatically retried.
- Provider selection uses the same `ModelRoleConfig` pattern as the production app but does not expose full settings UI.
- The spike uses saved model runs 165-170 from the "Show me all the times we talked about school" query only.
