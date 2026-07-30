"""Shared domain constants."""

SCHEMA_VERSION = 15

NORMALIZED_FORMAT_VERSION = 1

IMPORT_VALIDITY_LOADING = "loading"
IMPORT_VALIDITY_READY = "ready"
IMPORT_VALIDITY_FAILED = "failed"
IMPORT_VALIDITY_STALE = "stale"

WORKSPACE_KEY_DATASET_IMPORT_VALIDITY = "dataset_import_validity"
WORKSPACE_KEY_DATASET_IMPORT_ERROR = "dataset_import_error"

DEFAULT_PRINTABLE_ARTIFACT_GROUP_NAME = "Default"

WORKSPACE_FORMAT_ID = "message_evidence_workstation.evw"
WORKSPACE_FORMAT_VERSION = 1

UNCATEGORIZED_CATEGORY_NAME = "Uncategorized"

SEVERITY_DEBUG = "debug"
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

CONVERSATION_STATUS_CANDIDATE = "candidate"
CONVERSATION_STATUS_ACCEPTED = "accepted"
CONVERSATION_STATUS_REJECTED = "rejected"
CONVERSATION_STATUS_EXPORT_READY = "export_ready"

CREATED_BY_MANUAL = "manual"
CREATED_BY_SIMPLE_SEARCH = "simple_search"
CREATED_BY_CONVERSATIONAL_SEARCH = "conversational_search"
CREATED_BY_CONVERSATIONAL_ANSWER = "conversational_answer"
CREATED_BY_TRANSCRIPT_EDITOR = "transcript_editor"

BOUNDARY_CONTEXT_START = "context_start"
BOUNDARY_CONTEXT_END = "context_end"
BOUNDARY_RELEVANT_START = "relevant_start"
BOUNDARY_RELEVANT_END = "relevant_end"

RETRIEVAL_MANUAL = "manual"

HIGHLIGHT_NONE = "none"
HIGHLIGHT_HIT = "hit"
HIGHLIGHT_RELEVANT = "relevant"
HIGHLIGHT_CONTEXT = "context"

# Working corpus status lifecycle: draft → indexing → ready
#                                       indexing → failed
#                               ready → stale → indexing → ready
WORKING_CORPUS_STATUS_DRAFT = "draft"
WORKING_CORPUS_STATUS_BUILDING = "building"
WORKING_CORPUS_STATUS_READY = "ready"
WORKING_CORPUS_STATUS_STALE = "stale"
WORKING_CORPUS_STATUS_FAILED = "failed"

WORKING_CORPUS_SELECTION_ALL = "all"
WORKING_CORPUS_SELECTION_SELECTED = "selected"

WORKING_CORPUS_TOKEN_LIMIT = 768_000
WORKING_CORPUS_DEFAULT_NAME = "Full Corpus"
