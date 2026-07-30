"""Server-rendered loopback administration for every server-owned decision."""

from __future__ import annotations

import json
import hashlib
import secrets
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from server.config import (
    CHAT_OPERATIONS,
    ModelProfile,
    OperationAssignment,
    ProviderAccount,
    ServerConfig,
)
from server.config_service import ConfigurationService
from server.contracts import (
    AnalysisPlanningOutput,
    KeywordExpansionOutput,
    LedgerCompactionOutput,
    LedgerSynthesisOutput,
    SCHEMA_REGISTRY,
    WindowEvidenceEnvelope,
)
from server.embeddings import EmbeddingService
from server.model_runtime import ModelOutputInvalid, parse_model_output
from server.observability import EventSink
from server.provider import ProviderError
from server.token_accounting import (
    build_provider_payload,
    canonical_json,
    count_provider_payload,
    estimate_cost,
)


OUTPUT_MODELS = {
    "keyword_expansion": KeywordExpansionOutput,
    "analysis_planning": AnalysisPlanningOutput,
    "window_evidence_extraction": WindowEvidenceEnvelope,
    "ledger_compaction": LedgerCompactionOutput,
    "ledger_synthesis": LedgerSynthesisOutput,
}


def _field(
    label: str,
    help_text: str,
    *,
    kind: str = "text",
    options: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "label": label,
        "help": help_text,
        "kind": kind,
        "options": options,
    }


OPERATION_GUIDE = {
    "keyword_expansion": {
        "title": "Keyword expansion",
        "step": "Independent search tool",
        "summary": "Turns a user's short search phrase into a strict list of related search terms.",
        "when": "Runs only when the client explicitly requests keyword expansion. The client uses the returned terms for local FTS5 search; the server never sees or searches the EVW.",
    },
    "analysis_planning": {
        "title": "Conversational analysis planning",
        "step": "Conversation · step 1",
        "summary": "Operationalizes the user's question into a frozen analysis plan and ordered retrieval queries.",
        "when": "Runs for every conversational analysis request. The client executes the returned plan and sends the unchanged analysis context back for validation.",
    },
    "window_evidence_extraction": {
        "title": "Window evidence extraction",
        "step": "Conversation - extraction",
        "summary": "Examines one server-planned message window and returns exact evidence ranges.",
        "when": "Runs once for every planned window. Every assigned message is scanned, and retrieval suggestions are advisory only.",
    },
    "ledger_compaction": {
        "title": "Evidence-ledger compaction",
        "step": "Conversation - budget fallback",
        "summary": "Compresses an oversized evidence ledger into validated higher-level summaries without changing its source-range identity.",
        "when": "Runs only after an exact synthesis preflight shows the complete ledger cannot fit. Every trigger is visible in stream progress and activity.",
    },
    "ledger_synthesis": {
        "title": "Evidence-ledger synthesis",
        "step": "Conversation - final step",
        "summary": "Produces the final conversational answer from the validated evidence ledger and coverage report.",
        "when": "Runs once at the end of every conversation, after extraction and any required compaction. It is responsible for the answer shown to the user.",
    },
}


GLOBAL_FIELD_GROUPS = (
    {
        "title": "Request safety limits",
        "summary": "Hard ceilings checked before expensive work begins. Requests over these limits fail visibly; data is never silently truncated.",
        "fields": (
            "maximum_product_request_bytes",
            "maximum_conversational_corpus_tokens",
            "maximum_embedding_items",
            "maximum_embedding_request_bytes",
        ),
    },
    {
        "title": "Whole-server traffic",
        "summary": "Bounds all product requests together so a burst cannot consume unlimited server memory or work slots.",
        "fields": (
            "product_max_in_flight",
            "product_max_queued",
            "global_queue_wait_timeout_seconds",
        ),
    },
    {
        "title": "Provider connection pool",
        "summary": "Controls reusable outbound HTTP connections shared by model operations.",
        "fields": (
            "provider_http_max_connections",
            "provider_http_max_keepalive_connections",
            "provider_http_keepalive_expiry_seconds",
        ),
    },
    {
        "title": "Conversational orchestration",
        "summary": "Controls execution after the dedicated window-size decision shown above.",
        "fields": (
            "maximum_concurrent_windows",
            "retrieval_assistance_mode",
            "retrieval_top_k_per_query",
            "retrieval_maximum_prompt_suggestion_messages",
            "retrieval_rrf_constant",
            "ledger_compaction_max_depth",
            "stream_heartbeat_seconds",
        ),
    },
    {
        "title": "Administration and visibility",
        "summary": "Controls the in-memory event display and the current admin security mode.",
        "fields": ("recent_event_ring_size", "admin_auth_mode"),
    },
)


EMBEDDING_FIELD_GROUPS = (
    {
        "title": "Model identity",
        "summary": "Defines the one vector space used by message and query embeddings. Changing it requires rebuilding stored client vectors.",
        "fields": (
            "model_name",
            "model_revision",
            "device",
            "normalization",
            "required_dimensions",
        ),
    },
    {
        "title": "Execution",
        "summary": "Controls how the server splits a client workload and how much local embedding work can run at once.",
        "fields": (
            "internal_batch_size",
            "worker_count",
            "max_queued_workloads",
            "executor_timeout_seconds",
            "progress_min_interval_ms",
        ),
    },
    {
        "title": "Per-request ceilings",
        "summary": "Rejects unreasonable embedding requests before model execution. Accepted requests are still internally batched by the server.",
        "fields": ("maximum_items", "maximum_request_bytes"),
    },
)


MODEL_PROFILE_FIELD_GROUPS = (
    {
        "title": "Model identity",
        "fields": (
            "name",
            "model_id",
            "accounting_mode",
        ),
    },
    {
        "title": "Context and token accounting",
        "fields": (
            "encoding_name",
            "tokenizer_name",
            "tokenizer_revision",
            "provider_wrapper_tokens",
            "context_window_tokens",
        ),
    },
    {
        "title": "Capabilities and accounting",
        "fields": (
            "supported_structured_output_modes",
            "input_price_per_million",
            "output_price_per_million",
        ),
    },
)


OPERATION_ASSIGNMENT_FIELD_GROUPS = (
    {
        "title": "Output and sampling",
        "fields": (
            "structured_output_mode",
            "temperature",
            "max_output_tokens",
            "safety_margin_tokens",
            "target_input_tokens",
        ),
    },
    {
        "title": "Timeouts",
        "fields": (
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "write_timeout_seconds",
            "pool_timeout_seconds",
            "operation_deadline_seconds",
        ),
    },
    {
        "title": "Concurrency and explicit retry policy",
        "fields": (
            "max_in_flight",
            "max_queued",
            "queue_wait_timeout_seconds",
            "retryable_statuses",
            "max_attempts",
            "backoff_base_seconds",
            "backoff_multiplier",
            "backoff_cap_seconds",
            "backoff_jitter_seconds",
        ),
    },
    {
        "title": "Circuit breaker",
        "fields": (
            "circuit_threshold",
            "circuit_observation_seconds",
            "circuit_cooldown_seconds",
        ),
    },
)


FIELD_GUIDE = {
    "host": _field(
        "Listen address",
        "Network interface used by this server process. With admin authentication disabled, validation permits only localhost addresses. A change takes effect after process restart.",
    ),
    "port": _field(
        "Listen port",
        "TCP port used by the admin page and all product endpoints. A change takes effect after process restart.",
        kind="int",
    ),
    "global_config.maximum_product_request_bytes": _field(
        "Maximum product request size",
        "Absolute HTTP body ceiling, in bytes, for public product requests. Oversized requests are rejected before their full body is buffered.",
        kind="int",
    ),
    "global_config.maximum_conversational_corpus_tokens": _field(
        "Maximum conversational corpus",
        "Maximum content tokens the server will accept in one conversational working corpus. This is an intentional product/cost ceiling, separate from any model's context window.",
        kind="int",
    ),
    "global_config.maximum_embedding_items": _field(
        "Maximum embedding items",
        "Server-wide ceiling on texts in one embedding request. This does not define provider batch size; accepted items are split into internal batches below.",
        kind="int",
    ),
    "global_config.maximum_embedding_request_bytes": _field(
        "Maximum embedding request size",
        "Server-wide byte ceiling for one embedding request. The smaller of this and the embedding-specific byte ceiling is enforced.",
        kind="int",
    ),
    "global_config.product_max_in_flight": _field(
        "Concurrent product requests",
        "Maximum number of public API requests admitted to active processing across conversational, keyword, and embedding endpoints.",
        kind="int",
    ),
    "global_config.product_max_queued": _field(
        "Queued product requests",
        "Maximum number of additional public requests allowed to wait for a global work slot. Once full, new work fails visibly as server busy.",
        kind="int",
    ),
    "global_config.global_queue_wait_timeout_seconds": _field(
        "Global queue wait timeout",
        "How long an admitted public request may wait for a global work slot before failing with a queue timeout.",
        kind="float",
    ),
    "global_config.provider_http_max_connections": _field(
        "Maximum provider connections",
        "Maximum total outbound HTTP connections available for model-provider calls.",
        kind="int",
    ),
    "global_config.provider_http_max_keepalive_connections": _field(
        "Reusable provider connections",
        "Maximum idle outbound connections retained for reuse. Reuse avoids a new connection handshake for every model call.",
        kind="int",
    ),
    "global_config.provider_http_keepalive_expiry_seconds": _field(
        "Provider keepalive expiry",
        "How long an idle reusable provider connection remains in the pool.",
        kind="float",
    ),
    "global_config.window_input_utilization_percent": _field(
        "Window context utilization",
        "Percentage of the window-extraction operation's usable input capacity available to each planned window. The usable capacity is the smaller of its optional target input ceiling and context window minus reserved output and safety margin. The server chooses the fewest windows that fit this percentage, then deterministically balances their exact serialized payload sizes.",
        kind="float",
    ),
    "global_config.maximum_concurrent_windows": _field(
        "Concurrent window calls",
        "Maximum evidence-extraction windows processed at the same time for one conversational request.",
        kind="int",
    ),
    "global_config.retrieval_assistance_mode": _field(
        "Local retrieval mode",
        "Choose no local semantic lookup or semantic advisory message ranges. Retrieval never filters corpus or exhaustive windows.",
        kind="select",
        options=("none", "semantic_ranges"),
    ),
    "global_config.retrieval_top_k_per_query": _field(
        "Retrieval top K per query",
        "Maximum exact local message hits accepted for each extracted query.",
        kind="int",
    ),
    "global_config.retrieval_maximum_prompt_suggestion_messages": _field(
        "Maximum prompt suggestions",
        "Explicit advisory hint limit; it never limits evidence or corpus scanning.",
        kind="int",
    ),
    "global_config.retrieval_rrf_constant": _field(
        "RRF constant",
        "Reciprocal-rank-fusion constant used for deterministic candidate ordering.",
        kind="int",
    ),
    "global_config.ledger_compaction_max_depth": _field(
        "Maximum ledger compaction levels",
        "Maximum hierarchical compaction rounds after exact synthesis preflight overflows.",
        kind="int",
    ),
    "global_config.stream_heartbeat_seconds": _field(
        "Stream heartbeat interval",
        "Maximum quiet time, in seconds, before a long conversational request emits a heartbeat. This keeps the client and production HTTP proxies informed while a provider call is still running.",
        kind="float",
    ),
    "global_config.recent_event_ring_size": _field(
        "Recent events retained",
        "Maximum redacted process events kept in server memory for the live dashboard. This is operational history, not user evidence.",
        kind="int",
    ),
    "global_config.admin_auth_mode": _field(
        "Admin authentication",
        "Authentication is deliberately not implemented in this phase. While disabled, the server refuses a non-loopback listen address.",
        kind="readonly",
    ),
    "embedding.model_name": _field(
        "Embedding model",
        "Sentence-transformers model used to encode both working-corpus messages and individual search queries into the same vector space.",
    ),
    "embedding.model_revision": _field(
        "Pinned model revision",
        "Optional exact model revision. Leave blank to use the configured model's default revision. In production this should remain stable.",
    ),
    "embedding.device": _field(
        "Compute device",
        "Device passed to the local embedding model, such as cpu, cuda, or mps. It must exist on the server host.",
    ),
    "embedding.normalization": _field(
        "Vector normalization",
        "unit_l2 returns unit-length vectors suitable for cosine-style local lookup. none returns the model's raw vectors.",
        kind="choice",
        options=("unit_l2", "none"),
    ),
    "embedding.required_dimensions": _field(
        "Required vector dimensions",
        "Expected vector length. Zero accepts the loaded model's native size; a positive value makes activation fail if the model does not match.",
        kind="int",
    ),
    "embedding.internal_batch_size": _field(
        "Texts per model batch",
        "Number of accepted texts sent through one local model encode call. Clients do not choose this.",
        kind="int",
    ),
    "embedding.worker_count": _field(
        "Embedding workers",
        "Number of independent model replicas and embedding workloads that may execute concurrently. Higher values increase memory use.",
        kind="int",
    ),
    "embedding.max_queued_workloads": _field(
        "Queued embedding workloads",
        "Number of complete embedding requests allowed to wait behind active embedding workers.",
        kind="int",
    ),
    "embedding.maximum_items": _field(
        "Embedding items per request",
        "Embedding-runtime ceiling on texts in one accepted request. The smaller of this and the global embedding-item ceiling is enforced.",
        kind="int",
    ),
    "embedding.maximum_request_bytes": _field(
        "Embedding bytes per request",
        "Embedding-runtime byte ceiling. The smaller of this and the global embedding-byte ceiling is enforced.",
        kind="int",
    ),
    "embedding.executor_timeout_seconds": _field(
        "Model batch timeout",
        "Maximum time allowed for one internal model encode call. It is not a timeout for the complete multi-batch workload.",
        kind="float",
    ),
    "embedding.progress_min_interval_ms": _field(
        "Minimum progress interval",
        "Shortest interval between progress events when batches complete quickly. Final completion is always emitted.",
        kind="int",
    ),
    "operations.provider_kind": _field(
        "Provider protocol",
        "Transport contract used for this call. This server currently implements the OpenAI-compatible chat-completions protocol only.",
        kind="readonly",
    ),
    "operations.base_url": _field(
        "Provider base URL",
        "Base API URL without a trailing slash. The server appends /chat/completions for this operation.",
    ),
    "operations.model_id": _field(
        "Model",
        "Exact provider model identifier used for this operation. Each stage can use a different model.",
    ),
    "operations.system_prompt": _field(
        "Complete system prompt",
        "Exact system message sent for this operation. There is no hidden fallback prompt.",
    ),
    "operations.structured_output_mode": _field(
        "Structured-output mode",
        "json_schema sends the exact strict schema to supporting providers; json_object requests a JSON object; prompt_only relies on the prompt. Returned data is strictly validated in every mode.",
        kind="choice",
        options=("json_schema", "json_object", "prompt_only"),
    ),
    "operations.accounting_mode": _field(
        "Input token accounting",
        "How the server counts input before making this call. serialized_payload_tiktoken tokenizes the complete OpenAI-compatible JSON payload. huggingface_chat_template applies the configured model repository's official Jinja chat template. deepseek_v4_official applies DeepSeek's published V4 message encoding because V4 intentionally has no Jinja template.",
        kind="choice",
        options=(
            "serialized_payload_tiktoken",
            "huggingface_chat_template",
            "deepseek_v4_official",
        ),
    ),
    "operations.encoding_name": _field(
        "Tiktoken encoding",
        "Encoding used when input accounting is serialized_payload_tiktoken. It counts the complete JSON provider payload.",
    ),
    "operations.tokenizer_name": _field(
        "Hugging Face tokenizer",
        "Exact official model repository used for local tokenization when accounting is huggingface_chat_template. Its files must already be cached on the server; runtime requests never download code or tokenizer data.",
    ),
    "operations.tokenizer_revision": _field(
        "Tokenizer revision",
        "Optional pinned tokenizer revision used for Hugging Face chat-template accounting.",
    ),
    "operations.provider_wrapper_tokens": _field(
        "Provider wrapper tokens",
        "Explicit fixed allowance for provider framing that is not produced by the official local chat template. Keep zero unless comparison with provider-reported usage proves a stable difference.",
        kind="int",
    ),
    "operations.context_window_tokens": _field(
        "Model context window",
        "Total model capacity shared by serialized input, reserved output, and safety margin. The server refuses calls that do not fit.",
        kind="int",
    ),
    "operations.max_output_tokens": _field(
        "Reserved output tokens",
        "Maximum output sent to the provider and reserved during preflight budgeting.",
        kind="int",
    ),
    "operations.safety_margin_tokens": _field(
        "Context safety margin",
        "Additional context capacity deliberately left unused to absorb tokenizer or provider-framing uncertainty.",
        kind="int",
    ),
    "operations.target_input_tokens": _field(
        "Target input ceiling",
        "Optional stricter ceiling for the complete serialized input. Leave blank to use only context window minus output and safety reservations.",
        kind="nullable_int",
    ),
    "operations.connect_timeout_seconds": _field(
        "Connect timeout",
        "Maximum time to establish the provider network connection for one attempt.",
        kind="float",
    ),
    "operations.read_timeout_seconds": _field(
        "Read timeout",
        "Maximum period waiting for provider response data during one attempt.",
        kind="float",
    ),
    "operations.write_timeout_seconds": _field(
        "Write timeout",
        "Maximum period allowed to send the request body to the provider during one attempt.",
        kind="float",
    ),
    "operations.pool_timeout_seconds": _field(
        "Connection-pool timeout",
        "Maximum time one attempt waits for an outbound provider connection from the shared HTTP pool.",
        kind="float",
    ),
    "operations.operation_deadline_seconds": _field(
        "Complete operation deadline",
        "Wall-clock deadline for this internal operation, including queue wait, configured attempts, and backoff.",
        kind="float",
    ),
    "operations.temperature": _field(
        "Temperature",
        "Provider sampling temperature. Zero is the most deterministic setting for evidence extraction and structured answers.",
        kind="float",
    ),
    "operations.max_in_flight": _field(
        "Concurrent calls",
        "Maximum active provider calls for this specific operation across all users.",
        kind="int",
    ),
    "operations.max_queued": _field(
        "Queued calls",
        "Maximum additional calls for this operation allowed to wait for a slot.",
        kind="int",
    ),
    "operations.queue_wait_timeout_seconds": _field(
        "Operation queue timeout",
        "How long this operation may wait for its own concurrency slot before failing visibly.",
        kind="float",
    ),
    "operations.retryable_statuses": _field(
        "Retryable HTTP statuses",
        "Comma-separated provider HTTP statuses eligible for an explicit retry, such as 429,503. Empty means no status-based retries.",
        kind="int_list",
    ),
    "operations.max_attempts": _field(
        "Maximum attempts",
        "Total attempts including the first call. Set to 1 to disable retries.",
        kind="int",
    ),
    "operations.backoff_base_seconds": _field(
        "Initial retry delay",
        "Base delay before a configured retry.",
        kind="float",
    ),
    "operations.backoff_multiplier": _field(
        "Retry delay multiplier",
        "Multiplier applied to the delay after each failed retryable attempt.",
        kind="float",
    ),
    "operations.backoff_cap_seconds": _field(
        "Maximum retry delay",
        "Upper bound on calculated retry backoff.",
        kind="float",
    ),
    "operations.backoff_jitter_seconds": _field(
        "Retry jitter",
        "Maximum random delay added to retry backoff. Zero keeps retry timing deterministic.",
        kind="float",
    ),
    "operations.circuit_threshold": _field(
        "Failures before opening circuit",
        "Number of qualifying failures inside the observation period that opens this operation's circuit. Zero disables the circuit breaker.",
        kind="int",
    ),
    "operations.circuit_observation_seconds": _field(
        "Circuit observation period",
        "Rolling period in which failures count toward the circuit threshold.",
        kind="float",
    ),
    "operations.circuit_cooldown_seconds": _field(
        "Circuit cooldown",
        "How long new calls fail immediately after the circuit opens, before a recovery attempt is allowed.",
        kind="float",
    ),
    "operations.input_price_per_million": _field(
        "Input price per million tokens",
        "USD price used only for accounting. Leave blank when unknown; affected usage rows will be marked as cost-incomplete.",
        kind="nullable_float",
    ),
    "operations.output_price_per_million": _field(
        "Output price per million tokens",
        "USD price used only for accounting. Leave blank when unknown; affected usage rows will be marked as cost-incomplete.",
        kind="nullable_float",
    ),
}

FIELD_GUIDE.update(
    {
        "provider_accounts.name": _field(
            "Account name",
            "Human-readable name for this provider account. Renaming it does not change operation assignments.",
        ),
        "provider_accounts.provider_kind": FIELD_GUIDE["operations.provider_kind"],
        "provider_accounts.base_url": FIELD_GUIDE["operations.base_url"],
        "model_profiles.name": _field(
            "Profile name",
            "Human-readable reusable model setup shown in operation dropdowns. The stable internal ID does not change when this name changes.",
        ),
        "model_profiles.model_id": FIELD_GUIDE["operations.model_id"],
        "model_profiles.accounting_mode": FIELD_GUIDE["operations.accounting_mode"],
        "model_profiles.encoding_name": FIELD_GUIDE["operations.encoding_name"],
        "model_profiles.tokenizer_name": FIELD_GUIDE["operations.tokenizer_name"],
        "model_profiles.tokenizer_revision": FIELD_GUIDE["operations.tokenizer_revision"],
        "model_profiles.provider_wrapper_tokens": FIELD_GUIDE["operations.provider_wrapper_tokens"],
        "model_profiles.context_window_tokens": FIELD_GUIDE["operations.context_window_tokens"],
        "model_profiles.input_price_per_million": FIELD_GUIDE["operations.input_price_per_million"],
        "model_profiles.output_price_per_million": FIELD_GUIDE["operations.output_price_per_million"],
        "model_profiles.supported_structured_output_modes": _field(
            "Supported output modes",
            "Comma-separated modes this provider/model setup is known to accept. Operation validation fails if an assignment selects a mode not listed here.",
            kind="string_list",
        ),
    }
)
for _assignment_field in OperationAssignment.__dataclass_fields__:
    if _assignment_field == "model_profile_id":
        continue
    _legacy_key = f"operations.{_assignment_field}"
    if _legacy_key in FIELD_GUIDE:
        FIELD_GUIDE[f"operation_assignments.{_assignment_field}"] = FIELD_GUIDE[_legacy_key]


def _sample_message(message_id: str, text: str) -> dict[str, str]:
    return {
        "message_id": message_id,
        "thread_id": "synthetic-thread",
        "timestamp": "2026-01-01T00:00:00Z",
        "sender": "Synthetic Sender",
        "text": text,
    }


def sample_user_object(operation: str) -> dict[str, Any]:
    first = _sample_message("synthetic-message-1", "The school meeting is Tuesday.")
    second = _sample_message("synthetic-message-2", "I can attend the meeting.")
    coverage = [{
        "window_id": "w000001",
        "first_message_id": first["message_id"],
        "last_message_id": second["message_id"],
        "message_count": 2,
        "evidence_range_count": 1,
        "uncertainties": [],
    }]
    record = {
        "range_id": "r000001",
        "window_id": "w000001",
        "source_range_index": 0,
        "thread_id": "synthetic-thread",
        "start_message_id": first["message_id"],
        "end_message_id": second["message_id"],
        "summary": "A school meeting was scheduled and acknowledged.",
        "relevance": "Directly answers when the meeting was discussed.",
        "messages": [first, second],
        "normalizations": [],
        "uncertainties": [],
    }
    analysis_plan = {
        "analysis_question": "Identify passages responsive to the user's question.",
        "answer_objective": "Present responsive results with supporting ranges.",
        "concepts": [{"label": "responsive passage", "definition": "A passage that materially answers the question.", "manifestations": ["direct discussion"]}],
        "inclusion_criteria": ["The passage materially answers the question."],
        "exclusion_criteria": ["The passage is merely adjacent."],
        "answer_requirements": ["State results and cite accepted ranges."],
        "interpretive_assumptions": [],
    }
    metadata = [{key: record[key] for key in ("range_id", "window_id", "source_range_index", "thread_id", "start_message_id", "end_message_id", "summary", "relevance", "normalizations")}]
    if operation == "keyword_expansion":
        return {"task": operation, "query": "school meeting schedule"}
    if operation == "analysis_planning":
        return {"task": operation, "question": "When was the school meeting discussed?"}
    if operation == "window_evidence_extraction":
        return {"task": operation, "question": "When was the school meeting discussed?", "analysis_plan": analysis_plan, "retrieval_queries": [{"query_id": "q0001", "text": "school meeting"}], "suggestion_ranges": [], "window_id": "w000001", "messages": [first, second]}
    if operation == "ledger_compaction":
        return {"task": operation, "question": "When was the school meeting discussed?", "analysis_plan": analysis_plan, "level": 1, "group_id": "g01-000001", "coverage_report": coverage, "records_or_summaries": [record]}
    if operation == "ledger_synthesis":
        return {"task": operation, "question": "When was the school meeting discussed?", "analysis_plan": analysis_plan, "evidence_validation_summary": {"planned_window_count": 1, "usable_window_count": 1, "unavailable_window_count": 0, "unavailable_windows": [], "status": "complete", "accepted_range_count": 1, "rejected_range_count": 0, "normalized_range_count": 0, "rejected_ranges": [], "warnings": []}, "coverage_report": coverage, "ledger_metadata": metadata, "records_or_highest_level_summaries": [record]}
    raise ValueError(f"unknown operation {operation}")


ADMIN_PAGES = {
    "dashboard": "/admin/",
    "providers": "/admin/providers",
    "models": "/admin/models",
    "operations": "/admin/operations",
    "server": "/admin/server",
    "activity": "/admin/activity",
    "debug": "/admin/debug",
}


class AdminController:
    def __init__(self, app: FastAPI, service: ConfigurationService, events: EventSink):
        self.app = app
        self.service = service
        self.events = events
        self.csrf_tokens: set[str] = set()
        self.environment = Environment(
            loader=FileSystemLoader(str(Path(__file__).with_name("templates"))),
            autoescape=select_autoescape(["html", "xml"]),
        )

    async def _draft(self) -> tuple[int, ServerConfig]:
        active = self.service.maybe_snapshot()
        from server.config_store import fresh_bootstrap_config

        return await self.service.store_call(
            "ensure_draft",
            None if active is None else active.config_version,
            fresh_bootstrap_config(),
        )

    async def context(
        self,
        *,
        page_name: str = "dashboard",
        message: str = "",
        error: str = "",
        test_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if page_name not in ADMIN_PAGES:
            raise ValueError("unknown admin page")
        token = secrets.token_urlsafe(24)
        self.csrf_tokens.add(token)
        draft_id, draft = await self._draft()
        active = self.service.maybe_snapshot()
        runtime = getattr(self.app.state, "current_runtime", None)
        resilience = runtime.resilience if runtime else None
        runtime_status = {
            "configuration": "required" if active is None else "active",
            "active_version": active.config_version if active else None,
            "listener_current": getattr(self.app.state, "listener_current", None),
            "listener_configured": f"{active.host}:{active.port}" if active else None,
            "listener_restart_required": bool(
                active
                and getattr(self.app.state, "listener_current", None)
                != f"{active.host}:{active.port}"
            ),
            "embedding_reconfiguring": bool(
                getattr(self.app.state, "embedding_reconfiguring", False)
            ),
            "embedding": runtime.embedding.status() if runtime else None,
            "operations": {
                name: {
                    "provider": active.operations[name].provider_account_name,
                    "model": active.operations[name].model_profile_name,
                    "provider_model_id": active.operations[name].model_id,
                    **(
                        resilience.state(name)
                        if resilience
                        else {"circuit": "not_loaded", "in_flight": 0, "queued": 0}
                    ),
                }
                for name in CHAT_OPERATIONS
            }
            if active
            else {},
        }
        previews: dict[str, dict[str, Any]] = {}
        resolved_summaries: dict[str, dict[str, Any]] = {}
        for name in CHAT_OPERATIONS:
            operation = draft.operations[name]
            usable_input = min(
                operation.target_input_tokens
                if operation.target_input_tokens is not None
                else operation.context_window_tokens,
                max(
                    0,
                    operation.context_window_tokens
                    - operation.max_output_tokens
                    - operation.safety_margin_tokens,
                ),
            )
            resolved_summaries[name] = {
                "provider_name": operation.provider_account_name,
                "profile_name": operation.model_profile_name,
                "model_id": operation.model_id,
                "accounting_mode": operation.accounting_mode,
                "context_window_tokens": operation.context_window_tokens,
                "max_output_tokens": operation.max_output_tokens,
                "safety_margin_tokens": operation.safety_margin_tokens,
                "effective_input_tokens": usable_input,
            }
            user = sample_user_object(name)
            wire = [
                {"role": "system", "content": operation.system_prompt},
                {"role": "user", "content": canonical_json(user)},
            ]
            try:
                previews[name] = build_provider_payload(
                    operation,
                    operation=name,
                    messages=wire,
                    user_object=user,
                    response_schema=SCHEMA_REGISTRY[name]["model_output"],
                )
                if "Authorization" in previews[name]:
                    raise RuntimeError("provider preview unexpectedly contains authorization")
            except Exception as exc:
                previews[name] = {"preview_error": str(exc)}
        window_operation = draft.operations["window_evidence_extraction"]
        window_hard_input = resolved_summaries[
            "window_evidence_extraction"
        ]["effective_input_tokens"]
        window_utilization = draft.global_config.window_input_utilization_percent
        window_planning = {
            "provider_name": window_operation.provider_account_name,
            "profile_name": window_operation.model_profile_name,
            "model_id": window_operation.model_id,
            "context_window_tokens": window_operation.context_window_tokens,
            "max_output_tokens": window_operation.max_output_tokens,
            "safety_margin_tokens": window_operation.safety_margin_tokens,
            "operation_input_ceiling": window_operation.target_input_tokens,
            "hard_input_tokens": window_hard_input,
            "utilization_percent": window_utilization,
            "target_input_tokens": int(
                window_hard_input * window_utilization / 100.0
            ),
        }
        return {
            "page_name": page_name,
            "admin_pages": ADMIN_PAGES,
            "csrf_token": token,
            "message": message,
            "error": error,
            "test_output": test_output,
            "bootstrap": active is None,
            "active_version": active.config_version if active else None,
            "draft_id": draft_id,
            "config": draft.to_dict(),
            "secret_projection": await self.service.store_call(
                "secret_projection", draft_id
            ),
            "schemas": SCHEMA_REGISTRY,
            "previews": previews,
            "resolved_summaries": resolved_summaries,
            "window_planning": window_planning,
            "events": self.events.snapshot(),
            "metrics": self.events.dashboard_metrics(),
            "runtime_status": runtime_status,
            "usage": await self.service.store_call("usage_totals"),
            "checkpoint": await self.service.store_call("checkpoint_status"),
            "versions": await self.service.store_call("version_history"),
            "audits": await self.service.store_call("audit_history", 100),
            "operations": CHAT_OPERATIONS,
            "operation_guide": OPERATION_GUIDE,
            "model_profile_field_groups": MODEL_PROFILE_FIELD_GROUPS,
            "operation_assignment_field_groups": OPERATION_ASSIGNMENT_FIELD_GROUPS,
            "global_field_groups": GLOBAL_FIELD_GROUPS,
            "embedding_field_groups": EMBEDDING_FIELD_GROUPS,
            "field_guide": FIELD_GUIDE,
            "debug_status": self.app.state.debug_capture.status(),
            "debug_tail": self.app.state.debug_capture.tail(),
        }

    async def page(
        self,
        *,
        page_name: str = "dashboard",
        message: str = "",
        error: str = "",
        test_output: dict[str, Any] | None = None,
    ) -> HTMLResponse:
        context = await self.context(
            page_name=page_name,
            message=message,
            error=error,
            test_output=test_output,
        )
        return HTMLResponse(self.environment.get_template("admin.html").render(**context))

    def check_csrf(self, token: str) -> None:
        if not token or token not in self.csrf_tokens:
            raise ValueError("invalid admin session token")
        self.csrf_tokens.remove(token)


def _coerce_form_value(old: Any, raw: str, *, kind: str | None = None) -> Any:
    if kind == "nullable_int":
        return None if raw.strip().lower() in {"", "none", "null"} else int(raw)
    if kind == "nullable_float":
        return None if raw.strip().lower() in {"", "none", "null"} else float(raw)
    if old is None:
        return None if raw.strip().lower() in {"", "none", "null"} else float(raw)
    if isinstance(old, bool):
        return raw.lower() in {"1", "true", "yes", "on"}
    if isinstance(old, int):
        return int(raw)
    if isinstance(old, float):
        return float(raw)
    if isinstance(old, list):
        if kind == "string_list":
            return [item.strip() for item in raw.split(",") if item.strip()]
        return [int(item.strip()) for item in raw.split(",") if item.strip()]
    return raw


def register_admin(app: FastAPI, service: ConfigurationService, events: EventSink) -> AdminController:
    controller = AdminController(app, service, events)

    @app.get("/admin/", response_class=HTMLResponse, include_in_schema=False)
    async def admin_page(request: Request) -> HTMLResponse:
        return await controller.page(page_name="dashboard")

    @app.get("/admin/providers", response_class=HTMLResponse, include_in_schema=False)
    async def admin_providers(request: Request) -> HTMLResponse:
        return await controller.page(page_name="providers")

    @app.get("/admin/models", response_class=HTMLResponse, include_in_schema=False)
    async def admin_models(request: Request) -> HTMLResponse:
        return await controller.page(page_name="models")

    @app.get("/admin/operations", response_class=HTMLResponse, include_in_schema=False)
    async def admin_operations(request: Request) -> HTMLResponse:
        return await controller.page(page_name="operations")

    @app.get("/admin/server", response_class=HTMLResponse, include_in_schema=False)
    async def admin_server(request: Request) -> HTMLResponse:
        return await controller.page(page_name="server")

    @app.get("/admin/activity", response_class=HTMLResponse, include_in_schema=False)
    async def admin_activity(request: Request) -> HTMLResponse:
        return await controller.page(page_name="activity")

    @app.get("/admin/debug", response_class=HTMLResponse, include_in_schema=False)
    async def admin_debug(request: Request) -> HTMLResponse:
        return await controller.page(page_name="debug")

    @app.get("/admin/debug/session/{session_id}", include_in_schema=False)
    async def admin_debug_session(session_id: str) -> FileResponse:
        path = app.state.debug_capture.session_path(session_id)
        return FileResponse(
            path,
            media_type="application/x-ndjson",
            filename=path.name,
        )

    @app.post("/admin/action", response_class=HTMLResponse, include_in_schema=False)
    async def admin_action(request: Request) -> HTMLResponse:
        form = await request.form()
        action = str(form.get("action", ""))
        version_id = int(form["version_id"]) if form.get("version_id") else None
        return_page = str(form.get("return_page", "dashboard"))
        if return_page not in ADMIN_PAGES:
            return_page = "dashboard"
        try:
            controller.check_csrf(str(form.get("csrf_token", "")))
            if action == "start_debug_capture":
                session = await app.state.debug_capture.start()
                await service.store_call(
                    "record_audit",
                    "start_debug_capture",
                    version_id=service.snapshot().config_version,
                    details={
                        "capture_session_id": session.session_id,
                        "scope": "all_local_development_traffic",
                    },
                )
                events.emit("debug_capture_started")
                return await controller.page(
                    page_name="debug",
                    message=(
                        f"Debug capture {session.session_id} started. "
                        "Requests accepted from now on will be captured."
                    ),
                )
            if action == "stop_debug_capture":
                session = await app.state.debug_capture.stop()
                await service.store_call(
                    "record_audit",
                    "stop_debug_capture",
                    version_id=service.snapshot().config_version,
                    details={"capture_session_id": session.session_id},
                )
                events.emit("debug_capture_stopped")
                return await controller.page(
                    page_name="debug",
                    message=(
                        f"Debug capture {session.session_id} stopped. "
                        "Already-bound requests will finish their trace."
                    ),
                )
            if action == "clear_debug_captures":
                removed = await app.state.debug_capture.clear()
                await service.store_call(
                    "record_audit",
                    "clear_debug_captures",
                    version_id=service.snapshot().config_version,
                    details={"files_removed": removed},
                )
                events.emit("debug_captures_cleared")
                return await controller.page(
                    page_name="debug",
                    message=f"Deleted {removed} temporary debug capture file(s).",
                )
            if action == "validate":
                if version_id is None:
                    raise ValueError("version_id is required")
                await service.store_call("validate_version", version_id)
                await service.store_call("record_audit", "validate", version_id=version_id)
                events.emit("config_validate", config_version=version_id)
                return await controller.page(
                    page_name=return_page,
                    message="Draft is valid; no provider or embedding call was made.",
                )
            if action == "activate":
                if version_id is None:
                    raise ValueError("version_id is required")
                activated = await app.state.activate_runtime(version_id)
                events.emit("config_activate", config_version=activated.config_version)
                return await controller.page(
                    page_name=return_page,
                    message=f"Configuration {activated.config_version} activated.",
                )
            if action == "save_server":
                if version_id is None:
                    raise ValueError("version_id is required")
                current = await service.store_call("get_version", version_id)
                raw = current.to_dict()
                raw["host"] = str(form.get("host", raw["host"]))
                raw["port"] = int(form.get("port", raw["port"]))
                for section in ("global_config", "embedding"):
                    values = dict(raw[section])
                    for field_name, old in tuple(values.items()):
                        key = f"{section}.{field_name}"
                        if key in form:
                            kind = FIELD_GUIDE[key]["kind"]
                            values[field_name] = _coerce_form_value(
                                old, str(form[key]), kind=kind
                            )
                    raw[section] = values
                updated = ServerConfig.from_dict(raw, config_version=version_id)
                await service.store_call("save_draft", version_id, updated)
                await service.store_call("record_audit", "save", version_id=version_id)
                events.emit("config_save", config_version=version_id)
                return await controller.page(
                    page_name="server",
                    message="Server and embedding settings saved to the draft. Active runtime is unchanged.",
                )
            if action == "add_provider":
                if version_id is None:
                    raise ValueError("version_id is required")
                current = await service.store_call("get_version", version_id)
                provider_id = f"provider-{uuid.uuid4().hex[:12]}"
                provider = ProviderAccount(provider_id, "New provider account")
                updated = replace(
                    current,
                    provider_accounts={**current.provider_accounts, provider_id: provider},
                )
                await service.store_call("save_draft", version_id, updated)
                await service.store_call(
                    "record_audit", "add_provider", version_id=version_id, details={"provider_account_id": provider_id}
                )
                return await controller.page(
                    page_name="providers",
                    message="Provider account added to the draft. Complete its endpoint and credential before activation.",
                )
            if action == "save_provider":
                if version_id is None:
                    raise ValueError("version_id is required")
                provider_id = str(form.get("provider_account_id", ""))
                current = await service.store_call("get_version", version_id)
                provider = current.provider_accounts.get(provider_id)
                if provider is None:
                    raise ValueError("provider account does not exist")
                provider = replace(
                    provider,
                    name=str(form.get("provider_accounts.name", provider.name)),
                    base_url=str(form.get("provider_accounts.base_url", provider.base_url)),
                ).normalized()
                updated = replace(
                    current,
                    provider_accounts={**current.provider_accounts, provider_id: provider},
                )
                replacement = str(form.get("secret", ""))
                remove_secret = str(form.get("remove_secret", "")) == "on"
                if remove_secret and str(form.get("confirm_remove", "")) != "REMOVE":
                    raise ValueError("type REMOVE to confirm credential removal")
                await service.store_call(
                    "save_draft_bundle",
                    version_id,
                    updated,
                    secret_replacements={provider_id: replacement} if replacement else {},
                    secret_removals={provider_id} if remove_secret else set(),
                )
                await service.store_call(
                    "record_audit", "save_provider", version_id=version_id, details={"provider_account_id": provider_id}
                )
                return await controller.page(
                    page_name="providers",
                    message=f"Provider account {provider.name} saved to the draft.",
                )
            if action == "delete_provider":
                if version_id is None:
                    raise ValueError("version_id is required")
                provider_id = str(form.get("provider_account_id", ""))
                current = await service.store_call("get_version", version_id)
                provider = current.provider_accounts.get(provider_id)
                if provider is None:
                    raise ValueError("provider account does not exist")
                references = [
                    profile.name
                    for profile in current.model_profiles.values()
                    if profile.provider_account_id == provider_id
                ]
                if references:
                    raise ValueError(
                        f"cannot delete provider account; referenced by model profiles: {', '.join(references)}"
                    )
                updated = replace(
                    current,
                    provider_accounts={
                        key: value
                        for key, value in current.provider_accounts.items()
                        if key != provider_id
                    },
                )
                await service.store_call(
                    "save_draft_bundle",
                    version_id,
                    updated,
                    secret_replacements={},
                    secret_removals={provider_id},
                )
                await service.store_call(
                    "record_audit", "delete_provider", version_id=version_id, details={"provider_account_id": provider_id}
                )
                return await controller.page(
                    page_name="providers",
                    message=f"Provider account {provider.name} deleted from the draft.",
                )
            if action in {"add_profile", "clone_profile"}:
                if version_id is None:
                    raise ValueError("version_id is required")
                current = await service.store_call("get_version", version_id)
                profile_id = f"model-{uuid.uuid4().hex[:12]}"
                if action == "clone_profile":
                    source_id = str(form.get("model_profile_id", ""))
                    source = current.model_profiles.get(source_id)
                    if source is None:
                        raise ValueError("model profile to clone does not exist")
                    profile = replace(
                        source,
                        model_profile_id=profile_id,
                        name=f"{source.name} copy",
                    )
                else:
                    if not current.provider_accounts:
                        raise ValueError("create a provider account before creating a model profile")
                    profile = ModelProfile(
                        model_profile_id=profile_id,
                        name="New model profile",
                        provider_account_id=next(iter(current.provider_accounts)),
                    )
                updated = replace(
                    current,
                    model_profiles={**current.model_profiles, profile_id: profile},
                )
                await service.store_call("save_draft", version_id, updated)
                await service.store_call(
                    "record_audit", action, version_id=version_id, details={"model_profile_id": profile_id}
                )
                return await controller.page(
                    page_name="models",
                    message=f"Model profile {profile.name} added to the draft.",
                )
            if action == "save_profile":
                if version_id is None:
                    raise ValueError("version_id is required")
                profile_id = str(form.get("model_profile_id", ""))
                current = await service.store_call("get_version", version_id)
                raw = current.to_dict()
                values = dict(raw["model_profiles"].get(profile_id, {}))
                if not values:
                    raise ValueError("model profile does not exist")
                values["provider_account_id"] = str(
                    form.get("provider_account_id", values["provider_account_id"])
                )
                for field_name, old in tuple(values.items()):
                    key = f"model_profiles.{field_name}"
                    if key in form and key in FIELD_GUIDE:
                        values[field_name] = _coerce_form_value(
                            old, str(form[key]), kind=FIELD_GUIDE[key]["kind"]
                        )
                raw["model_profiles"][profile_id] = values
                updated = ServerConfig.from_dict(raw, config_version=version_id)
                await service.store_call("save_draft", version_id, updated)
                await service.store_call(
                    "record_audit", "save_profile", version_id=version_id, details={"model_profile_id": profile_id}
                )
                return await controller.page(
                    page_name="models",
                    message=f"Model profile {values['name']} saved to the draft.",
                )
            if action == "delete_profile":
                if version_id is None:
                    raise ValueError("version_id is required")
                profile_id = str(form.get("model_profile_id", ""))
                current = await service.store_call("get_version", version_id)
                profile = current.model_profiles.get(profile_id)
                if profile is None:
                    raise ValueError("model profile does not exist")
                references = [
                    OPERATION_GUIDE[name]["title"]
                    for name, assignment in current.operation_assignments.items()
                    if assignment.model_profile_id == profile_id
                ]
                if references:
                    raise ValueError(
                        f"cannot delete model profile; assigned to operations: {', '.join(references)}"
                    )
                updated = replace(
                    current,
                    model_profiles={
                        key: value
                        for key, value in current.model_profiles.items()
                        if key != profile_id
                    },
                )
                await service.store_call("save_draft", version_id, updated)
                await service.store_call(
                    "record_audit", "delete_profile", version_id=version_id, details={"model_profile_id": profile_id}
                )
                return await controller.page(
                    page_name="models",
                    message=f"Model profile {profile.name} deleted from the draft.",
                )
            if action == "save_operations":
                if version_id is None:
                    raise ValueError("version_id is required")
                current = await service.store_call("get_version", version_id)
                raw = current.to_dict()
                for operation in CHAT_OPERATIONS:
                    values = dict(raw["operation_assignments"][operation])
                    profile_key = f"operation_assignments.{operation}.model_profile_id"
                    if profile_key in form:
                        values["model_profile_id"] = str(form[profile_key])
                    for field_name, old in tuple(values.items()):
                        key = f"operation_assignments.{operation}.{field_name}"
                        guide_key = f"operation_assignments.{field_name}"
                        if key in form and guide_key in FIELD_GUIDE:
                            values[field_name] = _coerce_form_value(
                                old, str(form[key]), kind=FIELD_GUIDE[guide_key]["kind"]
                            )
                    raw["operation_assignments"][operation] = values
                updated = ServerConfig.from_dict(raw, config_version=version_id)
                await service.store_call("save_draft", version_id, updated)
                await service.store_call("record_audit", "save_operations", version_id=version_id)
                events.emit("config_save", config_version=version_id)
                return await controller.page(
                    page_name="operations",
                    message="Operation routing, prompts, and execution policies saved to the draft.",
                )
            if action == "test":
                if version_id is None:
                    raise ValueError("version_id is required")
                operation_name = str(form.get("operation", ""))
                if operation_name not in CHAT_OPERATIONS:
                    raise ValueError("operation is required")
                draft = await service.store_call("get_version", version_id)
                operation = draft.operations[operation_name]
                operation.validate(operation_name, require_secret=True)
                user = sample_user_object(operation_name)
                schema = SCHEMA_REGISTRY[operation_name]["model_output"]
                wire = [
                    {"role": "system", "content": operation.system_prompt},
                    {"role": "user", "content": canonical_json(user)},
                ]
                payload = build_provider_payload(operation, operation=operation_name, messages=wire, user_object=user, response_schema=schema)
                accounting = count_provider_payload(payload, operation)
                if not accounting.fits:
                    raise ValueError("synthetic operation test does not fit the draft budget")
                provider = getattr(app.state, "provider", None)
                if provider is None:
                    raise RuntimeError("provider transport is not started")
                started = time.perf_counter()
                try:
                    result = await provider.chat(operation_name, operation, messages=wire, user_object=user, response_schema=schema, api_key=operation.api_key)
                except ProviderError as exc:
                    latency_ms = (time.perf_counter() - started) * 1000
                    cost = estimate_cost(operation, accounting.input_tokens, 0)
                    await service.store_call("record_usage", request_id=None, config_version=version_id, product_endpoint="/admin/test", internal_operation=operation_name, attempt=1, provider_or_profile=operation.model_id, outcome="failure", error_code=exc.code, input_tokens=accounting.input_tokens, output_tokens=0, usage_source="estimated", input_price_per_million=operation.input_price_per_million, output_price_per_million=operation.output_price_per_million, estimated_cost=cost, currency="USD", latency_ms=latency_ms, provider_request_id=exc.provider_request_id)
                    await service.store_call("record_audit", "test_failed", version_id=version_id, details={"operation": operation_name, "error_code": exc.code})
                    events.emit("config_test_failed", config_version=version_id, internal_operation=operation_name, error_code=exc.code, latency_ms=latency_ms, severity="ERROR")
                    return await controller.page(
                        page_name="activity",
                        error=str(exc),
                        test_output={
                            "operation": operation_name,
                            "schema_valid": False,
                            "accounted_input_tokens": accounting.input_tokens,
                            "provider_input_tokens": None,
                            "provider_output_tokens": None,
                            "usage_source": "estimated",
                            "latency_ms": latency_ms,
                            "estimated_cost": cost,
                            "raw_output": None,
                            "parsed_output": None,
                            "error_code": exc.code,
                        },
                    )
                try:
                    parsed = parse_model_output(result.content, OUTPUT_MODELS[operation_name])
                except ModelOutputInvalid as exc:
                    cost = estimate_cost(operation, result.input_tokens, result.output_tokens)
                    await service.store_call("record_usage", request_id=None, config_version=version_id, product_endpoint="/admin/test", internal_operation=operation_name, attempt=1, provider_or_profile=operation.model_id, outcome="failure", error_code=exc.code, input_tokens=result.input_tokens, output_tokens=result.output_tokens, usage_source=result.usage_source, input_price_per_million=operation.input_price_per_million, output_price_per_million=operation.output_price_per_million, estimated_cost=cost, currency="USD", latency_ms=result.latency_ms, provider_request_id=result.provider_request_id)
                    await service.store_call("record_audit", "test_failed", version_id=version_id, details={"operation": operation_name, "error_code": exc.code})
                    events.emit("config_test_failed", config_version=version_id, internal_operation=operation_name, error_code=exc.code, latency_ms=result.latency_ms, severity="ERROR")
                    return await controller.page(
                        page_name="activity",
                        error=str(exc),
                        test_output={
                            "operation": operation_name,
                            "schema_valid": False,
                            "accounted_input_tokens": accounting.input_tokens,
                            "provider_input_tokens": result.input_tokens,
                            "provider_output_tokens": result.output_tokens,
                            "usage_source": result.usage_source,
                            "latency_ms": result.latency_ms,
                            "estimated_cost": cost,
                            "raw_output": result.content,
                            "parsed_output": None,
                            "error_code": exc.code,
                        },
                    )
                cost = estimate_cost(operation, result.input_tokens, result.output_tokens)
                await service.store_call("record_usage", request_id=None, config_version=version_id, product_endpoint="/admin/test", internal_operation=operation_name, attempt=1, provider_or_profile=operation.model_id, outcome="success", input_tokens=result.input_tokens, output_tokens=result.output_tokens, usage_source=result.usage_source, input_price_per_million=operation.input_price_per_million, output_price_per_million=operation.output_price_per_million, estimated_cost=cost, currency="USD", latency_ms=result.latency_ms, provider_request_id=result.provider_request_id)
                await service.store_call("record_audit", "test", version_id=version_id, details={"operation": operation_name})
                events.emit("config_test", config_version=version_id, internal_operation=operation_name, latency_ms=result.latency_ms)
                return await controller.page(
                    page_name="activity",
                    message=f"Strict test passed for {operation_name}.",
                    test_output={
                        "operation": operation_name,
                        "schema_valid": True,
                        "accounted_input_tokens": accounting.input_tokens,
                        "provider_input_tokens": result.input_tokens,
                        "provider_output_tokens": result.output_tokens,
                        "usage_source": result.usage_source,
                        "latency_ms": result.latency_ms,
                        "estimated_cost": cost,
                        "raw_output": result.content,
                        "parsed_output": parsed.model_dump(),
                    },
                )
            if action == "test_embedding":
                if version_id is None:
                    raise ValueError("version_id is required")
                draft = await service.store_call("get_version", version_id)
                draft.embedding.validate(require_model=True)
                candidate = app.state.embedding_factory(draft.embedding)
                try:
                    profile = await candidate.prepare()
                    vectors = await candidate.encode(["synthetic embedding test"])
                    if len(vectors) != 1 or len(vectors[0]) != profile.dimensions or any(not isinstance(value, float) for value in vectors[0]):
                        raise RuntimeError("embedding test returned invalid dimensions or values")
                finally:
                    await candidate.close_async()
                await service.store_call("record_audit", "test_embedding", version_id=version_id)
                events.emit("embedding_config_test", config_version=version_id, model=draft.embedding.model_name)
                return await controller.page(
                    page_name="server",
                    message=f"Embedding test passed: {profile.profile_id}, {profile.dimensions} dimensions.",
                )
            if action == "rollback":
                source_version = int(form.get("source_version", "0"))
                if source_version <= 0:
                    raise ValueError("rollback source version is required")
                draft_id = await service.store_call("copy_as_draft", source_version, source_label="rollback")
                activated = await app.state.activate_runtime(draft_id)
                await service.store_call("record_audit", "rollback", version_id=activated.config_version, details={"source_version": source_version})
                events.emit("config_rollback", config_version=activated.config_version)
                return await controller.page(
                    page_name="activity",
                    message=f"Version {source_version} rolled forward as active version {activated.config_version}.",
                )
            if action == "reset_circuit":
                operation_name = str(form.get("operation", ""))
                runtime = getattr(app.state, "current_runtime", None)
                if runtime is None or operation_name not in CHAT_OPERATIONS:
                    raise ValueError("active operation is required")
                runtime.resilience.reset_circuit(operation_name)
                await service.store_call("record_audit", "reset_circuit", version_id=runtime.config.config_version, details={"operation": operation_name})
                events.emit("circuit_reset", config_version=runtime.config.config_version, internal_operation=operation_name)
                return await controller.page(
                    page_name="activity",
                    message=f"Circuit reset for {operation_name}.",
                )
            raise ValueError(f"unsupported admin action {action}")
        except Exception as exc:
            events.emit("admin_action_failed", internal_operation=action or None, error_code=getattr(exc, "code", exc.__class__.__name__), severity="ERROR")
            return await controller.page(page_name=return_page, error=str(exc))

    @app.get("/admin/events", include_in_schema=False)
    async def admin_events() -> dict[str, Any]:
        runtime = getattr(app.state, "current_runtime", None)
        active = service.maybe_snapshot()
        resilience = runtime.resilience if runtime else None
        redacted = active.to_dict() if active is not None else None
        runtime_shape = None
        if redacted is not None:
            runtime_shape = dict(redacted)
            runtime_shape.pop("config_version", None)
            runtime_shape["global_config"] = dict(runtime_shape["global_config"])
            runtime_shape["global_config"].pop("retrieval_assistance_mode", None)
        debug_status = app.state.debug_capture.status()
        return {
            "events": events.snapshot(),
            "metrics": events.dashboard_metrics(),
            "usage": await service.store_call("usage_totals"),
            "embedding": runtime.embedding.status() if runtime else None,
            "operations": {
                name: {
                    "model": active.operations[name].model_id,
                    **(
                        resilience.state(name)
                        if resilience
                        else {"circuit": "not_loaded", "in_flight": 0, "queued": 0}
                    ),
                }
                for name in CHAT_OPERATIONS
            }
            if active
            else {},
            "active_config_version": active.config_version if active else None,
            "retrieval_assistance_mode": (
                active.global_config.retrieval_assistance_mode if active else None
            ),
            "configuration_fingerprint": (
                hashlib.sha256(canonical_json(redacted).encode("utf-8")).hexdigest()
                if redacted is not None else None
            ),
            "mode_independent_configuration_fingerprint": (
                hashlib.sha256(canonical_json(runtime_shape).encode("utf-8")).hexdigest()
                if runtime_shape is not None else None
            ),
            "debug_status": debug_status,
            "debug_capture": debug_status,
        }

    return controller
