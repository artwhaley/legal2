# Target Architecture and Ownership

## Processes

### Python model server

The FastAPI server is stateless and EVW-blind. It owns provider credentials,
provider SDKs, model selection, prompt-set v2, model calls, embedding model
execution, output parsing, and response validation. It accepts all required
text and stable local IDs in request bodies and returns typed results.

The server must not:

- import `sqlite3`, EVW repositories, client settings, or client UI modules;
- accept filesystem/EVW paths;
- open, mutate, cache, copy, or back up an EVW;
- persist transcripts, prompts, responses, embeddings, or conversations;
- retry, switch provider/model, truncate valid input, or fall back locally.

### Python desktop client

The existing PySide client is the reference writable client for this closeout.
It owns the EVW lock/lifecycle, canonical import, working-corpus definitions,
membership, scoped local indexes, FTS5/spellfix queries, sqlite-vec KNN queries,
transcript/window construction, evidence/artifact writes, and visible
conversation persistence.

It calls the server for only:

- keyword expansion;
- exhaustive retrieval terms;
- message, chunk, and query embeddings;
- whole-transcript answers;
- exhaustive window scans;
- evidence-ledger synthesis.

### Flutter Windows client

Flutter opens a v14 EVW read-only. In this phase it provides a real corpus and
transcript viewer and the compatibility probe. It performs no writes and no
server calls. Its purpose is to prove that the local data contract is usable
without Python before the full Flutter feature client is built.

## One obvious workflow

```text
import canonical messages
  -> create/preview search-corpus definition
  -> reject visibly if over 768,000 tokens
  -> materialize membership
  -> build scoped FTS5 and spellfix generation
  -> activate corpus atomically
  -> optionally build scoped message/chunk vectors through server embeddings
  -> run all searches against resolved active scope
```

Changing canonical message/thread/timestamp content increments the dataset
content revision, marks every affected working corpus stale, clears active
scope, and blocks all search until a new complete generation is activated.

## Supported conversational architecture

There is one conversational path:

- whole transcript when the active, date-narrowed corpus fits the server model
  budget;
- otherwise deterministic exhaustive windows;
- each window is scanned once;
- window evidence is assembled into the deterministic evidence ledger;
- the server synthesizes the ledger once;
- the client validates returned IDs against the active scope and persists only
  the prompt, presented answer, visible citations, mode, and scope provenance.

Delete the old generic planner/tool-runner/synthesis path and the bounded legacy
window-merge path. They are not fallback routes.

## Failure behavior

- No active ready corpus: every search control is disabled with one visible
  reason.
- Stale corpus/index: search refuses to run.
- Server down: FTS5/spellfix remain available; keyword expansion,
  conversational work, embedding calculation, and embedding search fail
  visibly. Nothing falls back.
- Missing embedding index: only embedding modes are disabled; lexical and
  conversational exhaustive paths remain explicit and usable.
- Database lock/checkpoint/integrity failure: stop the operation and preserve
  all files.

## Deliberate removals

Remove these production concepts from the Python client:

- `ModelRouter`, provider classes, NIM/Google clients, provider retries, local
  prompt registry, model-run persistence, and role-model settings;
- `EVW_TEST_ALLOW_LOCAL_MODEL_BACKEND` and every `gateway is None` branch;
- local sentence-transformer loading and local query/message/chunk embedding;
- optional/no-corpus vector partition keys;
- dataset-only search/transcript/window signatures;
- hidden provider/model widgets and compatibility settings migration;
- old conversational planner, tool runner, synthesis, and bounded window merge;
- runtime v12/v13 schema mutation.

Provider implementation code moves into `server/`; it is not imported from the
desktop-client package. Tests move with the code or are replaced.
