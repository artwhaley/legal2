# Message Evidence Workstation

Python desktop MVP for legal message evidence review: load normalized message data, search (FTS, keyword expansion, embeddings), curate workstation conversations in categories, conversational NIM search, and HTML output preview.

## Requirements

- Python 3.11+
- NVIDIA NIM API key for LLM features (keyword expansion, conversational planner/synthesis, range suggestion)
- Optional: local embedding model via `sentence-transformers` for vector search

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -e ".[dev]"
```

Configure NIM in the app under **Setup / Settings**, or set `MEW_NIM_API_KEY` in the environment.

## Run

```bash
python -m message_evidence_workstation.app
```

Reload dataset from configured default path:

```bash
python -m message_evidence_workstation.app --reload-dataset
```

## Test dataset layout

```
my_dataset/
  dataset.json
  source_threads.jsonl
  messages.jsonl
```

Sample fixture: `tests/fixtures/sample_dataset/`

## Test

```bash
pytest
```

## Documentation

- MVP spec: `00_source_spec/message_evidence_workstation_mvp_spec.md`
- Build plan: `01_build_plan.md`
- Ticket index: `02_ticket_index.md`
- Manual smoke checklist: `docs/smoke_test_checklist.md`
- Known limitations: `docs/known_limitations.md`

## Terminology

- **SourceThread** — raw platform thread (may span years)
- **Message** — one normalized message
- **WorkstationConversation** — curated topic/exhibit-sized passage
- **Category** — user bucket containing workstation conversations
- **Hit** — message that triggered retrieval
