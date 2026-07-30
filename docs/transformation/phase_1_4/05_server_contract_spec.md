# Server Extraction Specification

## Service boundary

Create a separately runnable stateless FastAPI service under `server/` with a `python -m server` entrypoint. Bind to loopback by default.

The server owns:

- provider SDKs and credentials;
- model selection and limits;
- frozen prompt-set v1;
- prompt construction;
- model output parsing;
- answer-range validation and repair;
- evidence-ledger validation/assembly;
- keyword expansion;
- retrieval-term generation;
- embedding generation.

The client owns:

- EVW access and lifecycle;
- full-corpus/working-corpus selection;
- FTS5, spellfix, chunks, and vector lookup;
- date scopes that narrow the active working corpus;
- transcript serialization and window planning;
- progress and visible failure state;
- evidence/artifact persistence;
- visible conversation persistence.

The server never opens an EVW and never chooses the working-corpus membership.

## Endpoints

Implement typed contracts for:

```text
GET  /v1/health
GET  /v1/capabilities
POST /v1/keyword-expansion
POST /v1/retrieval-terms
POST /v1/embeddings
POST /v1/answers/whole-transcript
POST /v1/answers/window-scan
POST /v1/answers/window-merge
POST /v1/answers/evidence-ledger-synthesis
```

Every request includes a client request ID. Answer requests include stable local message/range IDs and working-corpus identity/generation as non-persistent metadata. The server validates supplied IDs and response structure but does not query the client database.

Embedding requests preserve input order and return exactly one vector per input, plus model name, revision, dimensions, normalization, and request metadata. Batch size is at most 32.

Oversized requests fail explicitly. Nothing is silently truncated.

Errors use a stable code/message/details envelope. No automatic retry, provider switch, or model switch is permitted.

## Prompt behavior

Freeze these active roles as server prompt-set v1:

- keyword expansion;
- exhaustive retrieval terms;
- whole-transcript answer;
- exhaustive window scan;
- exhaustive window merge;
- evidence-ledger synthesis.

Use the exact active workspace prompt bodies captured before prompt tables are removed. Do not use code defaults if they differ.

## Server exclusions

Do not implement authentication, Clerk, Stripe, subscriptions, account databases, payment, BYOK, cloud deployment, or server-side EVW persistence in these phases.

Server logs may contain operation metadata, timing, model/provider identifiers, error types, and usage metadata. They must not contain request bodies, transcript text, prompts, or responses.
