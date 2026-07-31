# Mission, scope, and invariants

## Mission

Build the first intentionally useful Flutter client around the already proven
v15 EVW, local search, stateless server, and reusable transcript/evidence
editor. The finished first pass has exactly five main pages:

1. Corpus
2. Search
3. Conversation
4. Transcript
5. Print output

This is a functional migration away from the Python test client. It is not a
visual mockup and it is not permission to invent future product features.

## Binding product boundaries

- The Flutter client owns the EVW, local FTS5, local vector lookup, visible
  conversation history, evidence editing, and print-artifact organization.
- The server remains stateless and EVW-blind. It owns model selection, prompts,
  planning, embedding generation, window strategy, retries, synthesis, and
  result validation.
- The client sends only request data required by the existing public server
  contracts. It never sends the EVW file or path.
- Use the existing four server POST routes unchanged:
  `/v1/keyword-expansion`, `/v1/conversational-plan`,
  `/v1/conversational-analysis`, and `/v1/embeddings`.
- This client does not call or expose keyword expansion in V1. Do not remove
  the route or server implementation.
- Do not change server, Python client, EVW schema version, migration code,
  authentication, billing, BYOK, message import, or corpus-building behavior.
- Do not add a settings page, dashboard, provider controls, model controls, or
  prompt controls. Those remain in the server admin.

## Functional invariants

1. One process opens at most one EVW and owns exactly one `EvwDatabase`
   connection and lock.
2. A UI-selected working corpus resolves to that corpus's
   `current_revision_id`. This is session state only; do not add or write an
   “active working corpus” field.
3. Only a ready current revision can power Search, Conversation, Transcript,
   or Print output.
4. One shared `TranscriptDocumentController` owns evidence state for the
   selected revision. Every transcript surface observes that controller.
5. Transcript surfaces have independent scroll positions. Only the visible
   main page may perform center-line automatic evidence activation.
6. Every local query is explicitly scoped by working-corpus revision and index
   generation. No full-dataset search is permitted.
7. Clicking a valid result moves that page's transcript to the exact message
   or verified range. Unknown/unverified model identifiers are visible as
   warnings but never become navigation or evidence controls.
8. Every evidence write is transactional and immediately observable in every
   mounted transcript surface.
9. No valid search or conversational result is silently dropped. FTS uses
   explicit pagination; vector top-k is visible; lower-probability and
   unclassified conversational material remains visible.
10. Operations expose started, working/progress, completed, cancelled, or
    failed state. Do not silently retry or substitute a strategy.
11. Routine tests use deterministic fakes. They make no paid model calls and
    do not rebuild a real corpus's embeddings.
12. No control may imply functionality that is not implemented.

## Deliberately deferred

- importing messenger data;
- participant, source, conversation, and date filtering;
- creating/editing/publishing working-corpus definitions;
- building or clearing full-corpus embeddings in Flutter;
- keyword expansion UI;
- multi-turn model context (each question independently analyzes the selected
  working corpus);
- authentication, accounts, payments, subscriptions, and BYOK;
- PDF generation, operating-system printing, exact pagination, print margins,
  headers/footers, and provenance formatting;
- mobile platforms.

Deferred work must be described in plain text only where useful. Do not render
disabled buttons, fake forms, empty wizard steps, or placeholder cards for it.

