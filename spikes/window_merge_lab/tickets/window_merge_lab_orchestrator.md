# Window Merge Lab - Ticket Orchestrator

## Source Spec
[../SPEC.md](../SPEC.md)

## Execution Order

Run tickets sequentially unless a ticket explicitly says otherwise.

| Order | Ticket | Summary |
|------:|--------|---------|
| 1 | [WML01](WML01_scaffold_and_data_export.md) | Scaffold the spike package and export saved scan-window model runs |
| 2 | [WML02](WML02_data_loader_and_compaction.md) | Load, parse, compact, and validate scan-window inputs |
| 3 | [WML03](WML03_prompt_and_strategy_core.md) | Implement prompt builders and non-GUI strategy harness |
| 4 | [WML04](WML04_gui_shell_and_input_browser.md) | Build the PySide6 GUI shell, settings panel, and source-window browser |
| 5 | [WML05](WML05_gui_strategy_execution.md) | Wire dry-run/run buttons, background execution, outputs, and logs |
| 6 | [WML06](WML06_evaluation_and_comparison.md) | Add evaluator views, metrics, and strategy comparison outputs |
| 7 | [WML07](WML07_spike_hardening_and_handoff.md) | Polish docs, smoke tests, and recommendation handoff |
| 8 | [WML08](WML08_synthesis_budget_planner_orchestrator.md) | Continuation stack: synthesis budget planner with full and compact direct modes |
| 9 | [LEDGER](LEDGER.md) | Continuation stack: unified evidence-ledger synthesis with full/compact profiles and deterministic validation |

## Global Guardrails

- This is a spike under `spikes/window_merge_lab/`.
- Do not modify production app behavior.
- Do not modify database schema.
- Do not write app tables.
- Do not import or instantiate production UI widgets.
- Do not rerun scan-window calls unless the user explicitly asks.
- Use the six saved scan model runs `165-170` as the core input.
- LLM synthesis is the product goal. Deterministic logic is support/evaluation machinery only.
- Write experiment outputs only under `spikes/window_merge_lab/outputs/`.

## Acceptance Bar

The stack is complete when a user can launch:

```powershell
python spikes\window_merge_lab\merge_lab_app.py
```

Then load saved scan windows, select a merge strategy, inspect the prompt, dry-run or run the strategy, and view raw response, parsed JSON, readable output, metrics, and evaluation in the GUI.
