# Window Merge Lab Spike Spec

## Purpose
Build a nondestructive GUI spike for experimenting with merge strategies for exhaustive-window conversational search.

The spike reuses saved scan-window outputs from the failed large-dataset query:

`Show me all the times we talked about school`

The goal is to test LLM merge strategies without rerunning expensive scan-window calls and without touching production UI behavior.

## Product Principle
The conversational interface is an LLM synthesis product.

Deterministic code in this spike is only support machinery for:

- loading saved scan outputs
- compacting payloads
- estimating sizes
- validating message IDs
- comparing strategy outputs
- avoiding wasted API calls

The important strategies must produce LLM synthesis and analysis. Do not frame deterministic aggregation as the product answer.

## GUI Requirement
This spike must be a small GUI app, not only a terminal script.

The user should be able to launch the lab, choose a strategy, adjust settings, click buttons, and inspect prompts/results/errors in text panes.

The GUI does not need production styling. It should be practical and clear.

Recommended launch command:

```powershell
python spikes\window_merge_lab\merge_lab_app.py
```

Recommended toolkit:

- PySide6, because it is already available in the main app.

The GUI must not import or instantiate production app widgets.

## GUI Layout
Create:

`spikes/window_merge_lab/merge_lab_app.py`

Main window sections:

### Settings Panel
Fields:

- Workspace `.evw` path
- Input JSON path
- Output directory
- Strategy selector
- Provider selector: `settings`, `nim`, `google`
- Model override
- Max output tokens
- Timeout seconds
- Dry run checkbox
- Include raw scan text checkbox

Buttons:

- Load From `.evw`
- Load Input JSON
- Save Input JSON
- Build Prompt
- Run Strategy
- Parse Last Result
- Evaluate Outputs
- Open Output Folder
- Clear Log

### Source Windows Panel
Display:

- table/list of the six scan windows
- model run id
- window id
- estimated tokens
- answer range count
- parse status
- latency
- error status

Selecting a window should show:

- raw scan response
- parsed scan JSON
- compact ranges

### Strategy Panel
Display:

- selected strategy
- expected call count
- prompt character count
- estimated token count
- actual call count
- elapsed time
- parse status
- error status

### Prompt / Payload Pane
Text boxes/tabs:

- prompt preview
- exact JSON payload sent to the model
- compact input data

### Result Pane
Text boxes/tabs:

- raw model response
- parsed JSON
- readable Markdown result
- evaluation report
- error traceback/log

### Activity Log
A scrolling text area with timestamped events:

- loaded inputs
- built prompt
- started call
- completed call
- parse success/failure
- output paths
- errors

## Directory Layout
Use:

```text
spikes/window_merge_lab/
  SPEC.md
  README.md
  merge_lab_app.py
  merge_lab.py
  db_export.py
  data_loader.py
  strategies.py
  prompts.py
  evaluator.py
  inputs/
    school_scan_windows.json
    school_scan_windows_compact.json
  outputs/
    .gitkeep
```

`merge_lab.py` may provide CLI access, but the GUI is required.

## Data Export
`db_export.py` reads from:

`C:\Users\artwh\.message_evidence_workstation\workspace.evw`

Export model runs:

`165, 166, 167, 168, 169, 170`

For each scan window, save:

- `model_run_id`
- `run_type`
- `provider`
- `model`
- `created_at`
- `latency_ms`
- original user query
- `window_id`
- `session_id`
- `source_thread_id`
- `estimated_tokens`
- `message_ids`
- parsed model response
- raw response text
- raw request payload where useful

The export must be read-only against the `.evw`.

## Strategies
The GUI must expose these strategy options:

### One-Shot Compact LLM Merge
One LLM call over all six compact scan outputs.

Use:

- window summaries
- compact answer ranges
- source window ids
- source message ids

Do not include full transcripts.

### Hierarchical Balanced LLM Merge
Three LLM calls:

1. merge windows 1-3
2. merge windows 4-6
3. merge those two partial syntheses

Hard requirement: exactly bounded calls. Do not recurse indefinitely.

### Rolling Synthesis
Sequential update:

1. start with window 1
2. merge window 2 into current synthesis
3. continue through window 6

Each intermediate state must remain compact.

### Evidence Table Then Synthesis
Two-phase LLM strategy:

1. normalize scan outputs into an evidence table
2. synthesize final answer from that table

### Deterministic Baseline / Control
No LLM call. This exists only as a comparison/control view:

- raw range count
- dedupe count
- chronological-ish ordering
- source-window coverage

Do not present it as the target product behavior.

## Output Files
Every strategy run writes:

```text
outputs/{timestamp}_{strategy}/
  prompt_payload.json
  prompt_preview.md
  result_raw.txt
  result_parsed.json
  result_readable.md
  metrics.json
  evaluation.md
```

The GUI should show the output folder path after each run.

## Evaluation
`evaluator.py` should report:

- parse success
- answer range count
- invalid message IDs
- duplicate-looking ranges
- source windows represented
- likely dropped windows
- output length
- call count
- latency
- provider/model
- whether all six scan windows influenced the answer

Manual quality checklist:

- Does it feel like the model reviewed all windows?
- Does it synthesize rather than merely list?
- Does it preserve dates and concrete evidence?
- Does it avoid hallucinated IDs?
- Does it avoid losing smaller but important clusters?
- Are answer ranges useful for transcript navigation?

## Safety
The spike must not:

- modify production app code
- modify database schema
- write app tables
- start the production app
- import production UI widgets
- require search/conversational tabs

It may:

- reuse non-UI parsing/model-call helpers
- read the `.evw`
- write under `spikes/window_merge_lab/outputs/`
- read recovered files under `recovered_outputs/`

## Success Criteria
The spike is successful when the user can:

1. Launch a GUI app.
2. Load the six saved scan windows.
3. Select a merge strategy.
4. Inspect the generated prompt/payload before calling the model.
5. Run or dry-run the strategy.
6. See raw response, parsed JSON, readable result, and evaluation.
7. Compare strategies without rerunning the scan windows.

