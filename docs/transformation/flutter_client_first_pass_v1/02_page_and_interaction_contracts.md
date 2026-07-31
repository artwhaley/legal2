# Page and interaction contracts

## Corpus

This page contains only the functionality needed now:

- `Open EVW` file picker;
- `Close EVW`;
- absolute open path;
- clean open/error status;
- a list or dropdown of working corpora;
- current revision status, revision number, message count, estimated tokens,
  scope hash prefix, index generation, FTS status, and message-embedding
  status for the selected candidate;
- explicit selection of one usable working corpus.

Selection is by working corpus, not arbitrary historical revision. Display a
corpus's current revision. Do not implement import, filters, corpus creation,
draft editing, or publishing. A single sentence may say those will be added
incrementally; no controls are created for them.

Closing clears selection, evidence controller, all page-local results, and the
database lock after a clean checkpoint. Pages observe the state change.

## Search

Arrange three vertical zones:

1. search controls;
2. bounded-height scrollable results;
3. an expanded reusable transcript/evidence editor.

Controls:

- query field;
- `FTS5` / `Embedding` segmented mode;
- Search button;
- Cancel only while a remote embedding request is active;
- for embedding mode, a visible integer `Top results` value, default 20,
  valid 1-1000.

FTS results display total count and explicit page progress. Fetch 100 rows per
page and provide a real `Load more` action until all matches are reachable.
This is pagination, never a result cap. A new query clears old pages before
running.

Embedding results display rank and distance and state the requested top-k.
They require an already-ready local message embedding index. If absent, fail
with a direct explanation that Flutter embedding-index construction is not in
this first pass. Do not offer a fake build button.

Each message result displays sender, timestamp, a readable body excerpt, rank
information, `View in transcript`, and `Save evidence block`. Clicking the
row performs the view action. Saving uses the existing hit-centered behavior:
the hit is the one-message relevant range and up to three preceding and three
following same-thread messages become context.

The page's transcript is the full reusable evidence editor, not a screenshot
or read-only duplicate. It shares evidence state with all other pages.

## Conversation

Top/main area:

- a vertically scrollable ChatGPT-style sequence of user and assistant cards;
- a bottom question composer with Send;
- visible current phase, completed/planned windows, elapsed time, warnings,
  and Cancel during an active request.

Bottom area:

- the same reusable transcript/evidence editor, using the shared controller
  and its own scroll position.

Every question independently analyzes the selected working corpus. Do not send
prior visible turns as model context and do not imply that it does. Keep
completed turns visible in the current app session and across tab changes.

Render every server result variant:

- structured synthesis: overview, high-probability results first, a visible
  divider, lower-probability results, unclassified validated evidence,
  unverified model statements, warnings, and coverage;
- raw synthesis: complete raw answer, warnings, and complete canonical ledger;
- synthesis unavailable: explicit partial status and complete available
  canonical ledger.

Never discard lower-probability, unclassified, partial, raw, or warning-bearing
results. Never turn `complete_with_warnings` or `partial` into a failure popup.

For each verified canonical ledger range used by a result, render a compact
range item with its range ID, summary/relevance when present, endpoints,
`View in transcript`, and `Save evidence block`. Result statements with
multiple verified ranges show each range. Unclassified canonical ranges are
equally navigable and saveable. Unknown/fabricated IDs remain visible only as
warnings with no buttons.

View scrolls to the median message of the exact verified same-thread range.
Save creates one evidence block whose:

- relevant section is the complete inclusive range;
- leading context is up to three prior messages in the same source thread and
  selected revision;
- trailing context is up to three following messages under the same rules;
- core message is the lower median relevant message;
- initial highlight set contains the core message only;
- title uses the exact associated result statement when available, otherwise
  exact ledger summary, otherwise `Evidence <range_id>`;
- summary uses the exact ledger summary or relevance and may be empty.

Reject the whole save noisily if either endpoint is absent from the selected
revision, endpoints cross threads, order is invalid, or the context cannot
contain at least two messages. Never save a shortened partial range.

On successful server completion, persist only the visible user prompt and the
exact presented response using the existing `conversation` and
`conversation_turn` policy. Do not persist planning prompts, window calls,
provider responses, embeddings, or debug payloads. This packet does not
redesign persisted range history; live/current-session structured ranges are
fully interactive, while older plain-text Python history need not be loaded.

## Transcript

Use the full-height reusable transcript/evidence editor already implemented.
It must retain:

- virtualized whole-revision scrolling;
- visible evidence markup;
- sticky center-line activation;
- draggable context/relevant boundaries;
- primary message and highlights;
- title and summary editing;
- hide/show rendering;
- delete confirmation.

No second evidence editor implementation is allowed.

## Print output

Implement a narrow but real formatter against the existing printable-artifact
tables:

- list persisted groups and artifacts for the selected dataset;
- explicitly create the default group only when the user first creates an
  artifact and none exists;
- create an artifact from a selected evidence block;
- select an artifact;
- edit and save title, exhibit number, and case number;
- append another selected evidence block;
- remove an attached block;
- reorder attached blocks with explicit Move up / Move down actions;
- display a native Flutter document preview in persisted order.

The preview shows document metadata, evidence-block label/title/summary, and
all exact block messages with context/relevant visual distinction. It refreshes
after evidence persistence and artifact edits.

Do not implement PDF export, OS printing, pagination claims, page-size
controls, drag-and-drop, group editing, provenance appendices, or headers and
footers. Do not render Print or Export buttons. Call it `Document preview`, not
`Print preview`, until pagination/output exists.

