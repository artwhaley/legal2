"""Explicit server-owned configuration models for Server-First V1."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping


CONFIG_SCHEMA_VERSION = 4
CHAT_OPERATIONS = (
    "keyword_expansion",
    "analysis_planning",
    "window_evidence_extraction",
    "ledger_compaction",
    "ledger_synthesis",
)
_OBSOLETE_SYNTHESIS_PROMPT_MARKERS = (
    "direct_" + "evidence",
    "useful_" + "context",
    "not_" + "responsive",
    "range_" + "dispositions",
)
ACCOUNTING_MODES = (
    "serialized_payload_tiktoken",
    "huggingface_chat_template",
    "deepseek_v4_official",
)
STRUCTURED_OUTPUT_MODES = ("json_schema", "json_object", "prompt_only")


def default_state_dir() -> Path:
    return Path(os.environ.get("EVW_SERVER_STATE_DIR", "~/.message_evidence_server")).expanduser().resolve()


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:12]}"


@dataclass(frozen=True, slots=True)
class ProviderAccount:
    provider_account_id: str
    name: str
    provider_kind: str = "openai_compatible"
    base_url: str = ""
    api_key: str = field(default="", repr=False, compare=False)

    def normalized(self) -> "ProviderAccount":
        return replace(
            self,
            provider_account_id=self.provider_account_id.strip(),
            name=self.name.strip(),
            base_url=self.base_url.strip().rstrip("/"),
        )

    def validate(self, *, require_complete: bool = True) -> None:
        value = self.normalized()
        prefix = f"Provider account {value.name or value.provider_account_id}"
        if not value.provider_account_id:
            raise ValueError("provider_account_id is required")
        if not value.name:
            raise ValueError(f"{prefix} name is required")
        if value.provider_kind != "openai_compatible":
            raise ValueError(f"{prefix} provider_kind must be openai_compatible")
        if not require_complete and not value.base_url:
            return
        if not value.base_url.startswith(("http://", "https://")):
            raise ValueError(f"{prefix} base_url must be an HTTP(S) URL")
        if value.base_url.endswith("/"):
            raise ValueError(f"{prefix} base_url must not have a trailing slash")
        if require_complete and not value.api_key:
            raise ValueError(f"{prefix} API key is not configured")

    def to_dict(self, *, include_secret: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_secret:
            data.pop("api_key", None)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ProviderAccount":
        allowed = {value.name for value in cls.__dataclass_fields__.values()}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown provider account fields: {', '.join(sorted(unknown))}")
        return cls(**raw).normalized()


@dataclass(frozen=True, slots=True)
class ModelProfile:
    model_profile_id: str
    name: str
    provider_account_id: str
    model_id: str = ""
    accounting_mode: str = "serialized_payload_tiktoken"
    encoding_name: str = "cl100k_base"
    tokenizer_name: str = ""
    tokenizer_revision: str = ""
    provider_wrapper_tokens: int = 0
    context_window_tokens: int = 0
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    supported_structured_output_modes: tuple[str, ...] = STRUCTURED_OUTPUT_MODES

    def normalized(self) -> "ModelProfile":
        return replace(
            self,
            model_profile_id=self.model_profile_id.strip(),
            name=self.name.strip(),
            provider_account_id=self.provider_account_id.strip(),
            model_id=self.model_id.strip(),
            tokenizer_name=self.tokenizer_name.strip(),
            tokenizer_revision=self.tokenizer_revision.strip(),
            encoding_name=self.encoding_name.strip(),
        )

    def validate(self, *, require_complete: bool = True) -> None:
        value = self.normalized()
        prefix = f"Model profile {value.name or value.model_profile_id}"
        if not value.model_profile_id or not value.name or not value.provider_account_id:
            raise ValueError(f"{prefix} identity and provider are required")
        if not require_complete and (not value.model_id or value.context_window_tokens <= 0):
            return
        if not value.model_id:
            raise ValueError(f"{prefix} model_id is required")
        if value.accounting_mode not in ACCOUNTING_MODES:
            raise ValueError(f"{prefix} has unsupported accounting_mode")
        if value.accounting_mode == "serialized_payload_tiktoken" and not value.encoding_name:
            raise ValueError(f"{prefix} encoding_name is required")
        if value.accounting_mode in {"huggingface_chat_template", "deepseek_v4_official"} and not value.tokenizer_name:
            raise ValueError(f"{prefix} tokenizer_name is required")
        if value.provider_wrapper_tokens < 0 or value.context_window_tokens <= 0:
            raise ValueError(f"{prefix} token settings are invalid")
        if not value.supported_structured_output_modes:
            raise ValueError(f"{prefix} must support at least one structured-output mode")
        unknown_modes = set(value.supported_structured_output_modes) - set(STRUCTURED_OUTPUT_MODES)
        if unknown_modes:
            raise ValueError(f"{prefix} has unsupported structured-output modes: {sorted(unknown_modes)}")
        for price_name in ("input_price_per_million", "output_price_per_million"):
            price = getattr(value, price_name)
            if price is not None and price < 0:
                raise ValueError(f"{prefix} {price_name} cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["supported_structured_output_modes"] = list(self.supported_structured_output_modes)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ModelProfile":
        allowed = {value.name for value in cls.__dataclass_fields__.values()}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown model profile fields: {', '.join(sorted(unknown))}")
        value = dict(raw)
        value["supported_structured_output_modes"] = tuple(
            str(item) for item in value.get("supported_structured_output_modes", STRUCTURED_OUTPUT_MODES)
        )
        return cls(**value).normalized()


@dataclass(frozen=True, slots=True)
class OperationAssignment:
    model_profile_id: str
    system_prompt: str = ""
    structured_output_mode: str = "prompt_only"
    max_output_tokens: int = 0
    safety_margin_tokens: int = 0
    target_input_tokens: int | None = None
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 600.0
    write_timeout_seconds: float = 60.0
    pool_timeout_seconds: float = 30.0
    operation_deadline_seconds: float = 900.0
    temperature: float = 0.0
    max_in_flight: int = 2
    max_queued: int = 24
    queue_wait_timeout_seconds: float = 30.0
    retryable_statuses: tuple[int, ...] = (408, 429, 500, 502, 503, 504)
    max_attempts: int = 3
    backoff_base_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    backoff_cap_seconds: float = 8.0
    backoff_jitter_seconds: float = 0.5
    circuit_threshold: int = 0
    circuit_observation_seconds: float = 60.0
    circuit_cooldown_seconds: float = 30.0

    def validate(self, operation: str, *, context_window_tokens: int, require_complete: bool = True) -> None:
        prefix = f"Operation {operation}"
        if not self.model_profile_id.strip():
            raise ValueError(f"{prefix} model_profile_id is required")
        if not require_complete and (not self.system_prompt.strip() or self.max_output_tokens <= 0):
            return
        if not self.system_prompt.strip():
            raise ValueError(f"{prefix} system_prompt is required")
        if require_complete and operation == "ledger_synthesis" and any(marker in self.system_prompt for marker in _OBSOLETE_SYNTHESIS_PROMPT_MARKERS):
            raise ValueError(f"{prefix} prompt uses an obsolete response contract; update the synthesis prompt before activation")
        if self.structured_output_mode not in STRUCTURED_OUTPUT_MODES:
            raise ValueError(f"{prefix} has unsupported structured_output_mode")
        if self.max_output_tokens <= 0:
            raise ValueError(f"{prefix} max_output_tokens must be positive")
        if self.safety_margin_tokens < 0 or self.max_output_tokens + self.safety_margin_tokens >= context_window_tokens:
            raise ValueError(f"{prefix} output and safety margin exceed context window")
        if self.target_input_tokens is not None and not 1 <= self.target_input_tokens <= context_window_tokens:
            raise ValueError(f"{prefix} target_input_tokens is outside context window")
        for name in (
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "write_timeout_seconds",
            "pool_timeout_seconds",
            "operation_deadline_seconds",
            "queue_wait_timeout_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{prefix} {name} must be positive")
        if not 0 <= self.temperature <= 2:
            raise ValueError(f"{prefix} temperature must be between 0 and 2")
        if self.max_in_flight < 1 or self.max_queued < 0 or self.max_attempts < 1:
            raise ValueError(f"{prefix} concurrency/attempt settings are invalid")
        if any(status < 400 or status > 599 for status in self.retryable_statuses):
            raise ValueError(f"{prefix} retryable_statuses contains an invalid HTTP status")
        if self.backoff_base_seconds < 0 or self.backoff_multiplier < 1 or self.backoff_cap_seconds < 0 or self.backoff_jitter_seconds < 0:
            raise ValueError(f"{prefix} backoff settings are invalid")
        if self.circuit_threshold < 0 or self.circuit_observation_seconds <= 0 or self.circuit_cooldown_seconds <= 0:
            raise ValueError(f"{prefix} circuit settings are invalid")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["retryable_statuses"] = list(self.retryable_statuses)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OperationAssignment":
        allowed = {value.name for value in cls.__dataclass_fields__.values()}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown operation assignment fields: {', '.join(sorted(unknown))}")
        value = dict(raw)
        value["retryable_statuses"] = tuple(int(item) for item in value.get("retryable_statuses", ()))
        return cls(**value)


@dataclass(frozen=True, slots=True)
class OperationConfig:
    """Complete immutable runtime configuration resolved at activation."""

    provider_kind: str = "openai_compatible"
    base_url: str = ""
    model_id: str = ""
    system_prompt: str = ""
    structured_output_mode: str = "prompt_only"
    accounting_mode: str = "serialized_payload_tiktoken"
    encoding_name: str = "cl100k_base"
    tokenizer_name: str = ""
    tokenizer_revision: str = ""
    provider_wrapper_tokens: int = 0
    context_window_tokens: int = 0
    max_output_tokens: int = 0
    safety_margin_tokens: int = 0
    target_input_tokens: int | None = None
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 600.0
    write_timeout_seconds: float = 60.0
    pool_timeout_seconds: float = 30.0
    operation_deadline_seconds: float = 900.0
    temperature: float = 0.0
    max_in_flight: int = 2
    max_queued: int = 24
    queue_wait_timeout_seconds: float = 30.0
    retryable_statuses: tuple[int, ...] = (408, 429, 500, 502, 503, 504)
    max_attempts: int = 3
    backoff_base_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    backoff_cap_seconds: float = 8.0
    backoff_jitter_seconds: float = 0.5
    circuit_threshold: int = 0
    circuit_observation_seconds: float = 60.0
    circuit_cooldown_seconds: float = 30.0
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    provider_account_id: str = ""
    provider_account_name: str = ""
    model_profile_id: str = ""
    model_profile_name: str = ""
    api_key: str = field(default="", repr=False, compare=False)

    def normalized(self) -> "OperationConfig":
        return replace(self, base_url=self.base_url.strip().rstrip("/"))

    def validate(self, operation: str, *, require_secret: bool = True) -> None:
        provider = ProviderAccount(
            self.provider_account_id or "resolved-provider",
            self.provider_account_name or "Resolved provider",
            self.provider_kind,
            self.base_url,
            self.api_key,
        )
        profile = ModelProfile(
            self.model_profile_id or "resolved-profile",
            self.model_profile_name or self.model_id or "Resolved model",
            provider.provider_account_id,
            self.model_id,
            self.accounting_mode,
            self.encoding_name,
            self.tokenizer_name,
            self.tokenizer_revision,
            self.provider_wrapper_tokens,
            self.context_window_tokens,
            self.input_price_per_million,
            self.output_price_per_million,
        )
        assignment = OperationAssignment(
            model_profile_id=profile.model_profile_id,
            system_prompt=self.system_prompt,
            structured_output_mode=self.structured_output_mode,
            max_output_tokens=self.max_output_tokens,
            safety_margin_tokens=self.safety_margin_tokens,
            target_input_tokens=self.target_input_tokens,
            connect_timeout_seconds=self.connect_timeout_seconds,
            read_timeout_seconds=self.read_timeout_seconds,
            write_timeout_seconds=self.write_timeout_seconds,
            pool_timeout_seconds=self.pool_timeout_seconds,
            operation_deadline_seconds=self.operation_deadline_seconds,
            temperature=self.temperature,
            max_in_flight=self.max_in_flight,
            max_queued=self.max_queued,
            queue_wait_timeout_seconds=self.queue_wait_timeout_seconds,
            retryable_statuses=self.retryable_statuses,
            max_attempts=self.max_attempts,
            backoff_base_seconds=self.backoff_base_seconds,
            backoff_multiplier=self.backoff_multiplier,
            backoff_cap_seconds=self.backoff_cap_seconds,
            backoff_jitter_seconds=self.backoff_jitter_seconds,
            circuit_threshold=self.circuit_threshold,
            circuit_observation_seconds=self.circuit_observation_seconds,
            circuit_cooldown_seconds=self.circuit_cooldown_seconds,
        )
        provider.validate(require_complete=require_secret)
        profile.validate(require_complete=True)
        assignment.validate(operation, context_window_tokens=profile.context_window_tokens, require_complete=True)

    def to_dict(self, *, include_secret: bool = False) -> dict[str, Any]:
        data = asdict(self)
        data["retryable_statuses"] = list(self.retryable_statuses)
        if not include_secret:
            data.pop("api_key", None)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OperationConfig":
        allowed = {value.name for value in cls.__dataclass_fields__.values()}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown operation fields: {', '.join(sorted(unknown))}")
        value = dict(raw)
        value["retryable_statuses"] = tuple(int(item) for item in value.get("retryable_statuses", ()))
        return cls(**value).normalized()


@dataclass(frozen=True, slots=True)
class GlobalConfig:
    maximum_product_request_bytes: int = 268_435_456
    maximum_conversational_corpus_tokens: int = 768_000
    maximum_embedding_items: int = 100_000
    maximum_embedding_request_bytes: int = 268_435_456
    product_max_in_flight: int = 12
    product_max_queued: int = 48
    global_queue_wait_timeout_seconds: float = 30.0
    provider_http_max_connections: int = 32
    provider_http_max_keepalive_connections: int = 16
    provider_http_keepalive_expiry_seconds: float = 30.0
    window_input_utilization_percent: float = 85.0
    maximum_concurrent_windows: int = 2
    retrieval_assistance_mode: str = "none"
    retrieval_top_k_per_query: int = 100
    retrieval_maximum_prompt_suggestion_messages: int = 40
    retrieval_rrf_constant: int = 60
    ledger_compaction_max_depth: int = 4
    stream_heartbeat_seconds: float = 10.0
    recent_event_ring_size: int = 2_000
    admin_auth_mode: str = "disabled"

    def validate(self) -> None:
        positive = ("maximum_product_request_bytes", "maximum_conversational_corpus_tokens", "maximum_embedding_items", "maximum_embedding_request_bytes", "product_max_in_flight", "provider_http_max_connections", "provider_http_max_keepalive_connections", "maximum_concurrent_windows", "retrieval_top_k_per_query", "retrieval_maximum_prompt_suggestion_messages", "retrieval_rrf_constant", "ledger_compaction_max_depth", "recent_event_ring_size")
        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f"global {name} must be positive")
        if not 1.0 <= self.window_input_utilization_percent <= 100.0:
            raise ValueError("global window_input_utilization_percent must be between 1 and 100")
        if self.product_max_queued < 0 or self.global_queue_wait_timeout_seconds <= 0 or self.provider_http_keepalive_expiry_seconds <= 0 or self.stream_heartbeat_seconds <= 0:
            raise ValueError("global queue/provider settings are invalid")
        if self.retrieval_assistance_mode not in {"none", "semantic_ranges"}:
            raise ValueError("global retrieval_assistance_mode is invalid")
        if self.retrieval_top_k_per_query > 1000:
            raise ValueError("global retrieval_top_k_per_query must be between 1 and 1000")
        if self.retrieval_maximum_prompt_suggestion_messages > 500:
            raise ValueError("global retrieval_maximum_prompt_suggestion_messages must be between 1 and 500")
        if self.retrieval_rrf_constant > 1000:
            raise ValueError("global retrieval_rrf_constant must be between 1 and 1000")
        if self.ledger_compaction_max_depth > 8:
            raise ValueError("global ledger_compaction_max_depth must be between 1 and 8")
        if self.admin_auth_mode != "disabled":
            raise ValueError("only disabled admin_auth_mode is implemented in this phase")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def migrate_v2_config_dict(
    raw: dict[str, Any],
    *,
    planning_prompt: str | None = None,
    contract_prompts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Convert the older assignment payload at the explicit migration boundary."""
    if not isinstance(raw, dict) or raw.get("config_schema_version") != 2:
        raise ValueError("stored configuration is not schema v2")
    migrated = json.loads(json.dumps(raw, ensure_ascii=False))
    global_config = migrated.get("global_config")
    if not isinstance(global_config, dict):
        raise ValueError("stored global_config must be an object")
    enabled = global_config.pop("retrieval_assistance_enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("stored retrieval assistance flag is invalid")
    global_config["retrieval_assistance_mode"] = "none"
    global_config.setdefault("retrieval_top_k_per_query", 100)
    global_config.setdefault("retrieval_maximum_prompt_suggestion_messages", 40)
    global_config.setdefault("retrieval_rrf_constant", 60)
    global_config["ledger_compaction_max_depth"] = global_config.pop("ledger_reduction_max_depth", 4)
    assignments = migrated.get("operation_assignments")
    if not isinstance(assignments, dict):
        raise ValueError("stored operation_assignments must be an object")
    planning = assignments.get("analysis_planning") or assignments.get("retrieval_terms")
    compaction = assignments.get("ledger_compaction") or assignments.get("ledger_reduction")
    required = {
        "keyword_expansion": assignments.get("keyword_expansion"),
        "analysis_planning": planning,
        "window_evidence_extraction": assignments.get("window_evidence_extraction") or assignments.get("whole_corpus_answer"),
        "ledger_compaction": compaction,
        "ledger_synthesis": assignments.get("ledger_synthesis") or assignments.get("evidence_ledger_synthesis"),
    }
    if any(not isinstance(value, dict) for value in required.values()):
        raise ValueError("stored v2 operation set is incomplete")
    migrated["operation_assignments"] = required
    if contract_prompts is not None:
        for operation in (
            "analysis_planning",
            "window_evidence_extraction",
            "ledger_compaction",
            "ledger_synthesis",
        ):
            prompt = contract_prompts.get(operation)
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f"{operation} migration prompt must be nonblank")
            required[operation] = {
                **required[operation],
                "system_prompt": prompt,
            }
    elif planning_prompt is not None:
        required["analysis_planning"] = {**required["analysis_planning"], "system_prompt": planning_prompt}
    migrated["global_config"] = global_config
    migrated["config_schema_version"] = CONFIG_SCHEMA_VERSION
    return migrated


def migrate_v3_config_dict(
    raw: dict[str, Any],
    *,
    planning_prompt: str | None = None,
    contract_prompts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Convert one stored schema-v3 payload to the schema-v4 wire shape.

    This is the only runtime migration boundary that knows the removed v3
    planning names.  Runtime loading accepts only the returned v4 shape.
    """
    if not isinstance(raw, dict):
        raise ValueError("stored configuration must be an object")
    version = raw.get("config_schema_version")
    if version == CONFIG_SCHEMA_VERSION:
        return json.loads(json.dumps(raw, ensure_ascii=False))
    if version != 3:
        raise ValueError(f"unsupported stored configuration schema {version!r}")

    migrated = json.loads(json.dumps(raw, ensure_ascii=False))
    global_config = migrated.get("global_config")
    if not isinstance(global_config, dict):
        raise ValueError("stored global_config must be an object")
    old_mode = global_config.get("retrieval_assistance_mode", "none")
    mode_map = {"disabled": "none", "terms_only": "none", "semantic_ranges": "semantic_ranges"}
    if old_mode not in mode_map:
        raise ValueError("stored retrieval assistance mode is invalid")
    global_config["retrieval_assistance_mode"] = mode_map[old_mode]
    global_config.setdefault("retrieval_top_k_per_query", 100)
    global_config.setdefault("retrieval_maximum_prompt_suggestion_messages", 40)
    global_config.setdefault("retrieval_rrf_constant", 60)
    global_config.setdefault("ledger_compaction_max_depth", 4)

    assignments = migrated.get("operation_assignments")
    if not isinstance(assignments, dict):
        raise ValueError("stored operation_assignments must be an object")
    required = {
        "keyword_expansion",
        "retrieval_terms",
        "window_evidence_extraction",
        "ledger_compaction",
        "ledger_synthesis",
    }
    missing = sorted(required - set(assignments))
    unknown = sorted(set(assignments) - required)
    if missing or unknown:
        raise ValueError(f"stored v3 operation set mismatch; missing={missing}, unknown={unknown}")
    migrated["operation_assignments"] = {
        "keyword_expansion": assignments["keyword_expansion"],
        "analysis_planning": assignments["retrieval_terms"],
        "window_evidence_extraction": assignments["window_evidence_extraction"],
        "ledger_compaction": assignments["ledger_compaction"],
        "ledger_synthesis": assignments["ledger_synthesis"],
    }
    if contract_prompts is not None:
        for operation in (
            "analysis_planning",
            "window_evidence_extraction",
            "ledger_compaction",
            "ledger_synthesis",
        ):
            prompt = contract_prompts.get(operation)
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f"{operation} migration prompt must be nonblank")
            migrated["operation_assignments"][operation] = {
                **migrated["operation_assignments"][operation],
                "system_prompt": prompt,
            }
    elif planning_prompt is not None:
        if not isinstance(planning_prompt, str) or not planning_prompt.strip():
            raise ValueError("planning_prompt must be a nonblank string")
        migrated["operation_assignments"]["analysis_planning"] = {
            **migrated["operation_assignments"]["analysis_planning"],
            "system_prompt": planning_prompt,
        }
    migrated["global_config"] = global_config
    migrated["config_schema_version"] = CONFIG_SCHEMA_VERSION
    return migrated


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    model_name: str = ""
    model_revision: str = ""
    device: str = "cpu"
    normalization: str = "unit_l2"
    required_dimensions: int = 0
    internal_batch_size: int = 32
    worker_count: int = 1
    max_queued_workloads: int = 4
    maximum_items: int = 100_000
    maximum_request_bytes: int = 268_435_456
    executor_timeout_seconds: float = 3_600.0
    progress_min_interval_ms: int = 250

    def validate(self, *, require_model: bool = True) -> None:
        if require_model and not self.model_name.strip():
            raise ValueError("embedding model_name is required")
        if self.normalization not in {"unit_l2", "none"}:
            raise ValueError("embedding normalization must be unit_l2 or none")
        if self.required_dimensions < 0 or not 1 <= self.internal_batch_size or self.worker_count < 1 or self.max_queued_workloads < 0 or self.maximum_items <= 0 or self.maximum_request_bytes <= 0 or self.executor_timeout_seconds <= 0 or self.progress_min_interval_ms < 0:
            raise ValueError("embedding settings are invalid")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ServerConfig:
    config_version: int
    host: str
    port: int
    global_config: GlobalConfig
    provider_accounts: dict[str, ProviderAccount]
    model_profiles: dict[str, ModelProfile]
    operation_assignments: dict[str, OperationAssignment]
    embedding: EmbeddingConfig

    @property
    def operations(self) -> dict[str, OperationConfig]:
        return {name: self.resolve_operation(name) for name in CHAT_OPERATIONS}

    def resolve_operation(self, operation: str) -> OperationConfig:
        assignment = self.operation_assignments[operation]
        profile = self.model_profiles[assignment.model_profile_id]
        provider = self.provider_accounts[profile.provider_account_id]
        return OperationConfig(
            provider_kind=provider.provider_kind,
            base_url=provider.base_url,
            model_id=profile.model_id,
            system_prompt=assignment.system_prompt,
            structured_output_mode=assignment.structured_output_mode,
            accounting_mode=profile.accounting_mode,
            encoding_name=profile.encoding_name,
            tokenizer_name=profile.tokenizer_name,
            tokenizer_revision=profile.tokenizer_revision,
            provider_wrapper_tokens=profile.provider_wrapper_tokens,
            context_window_tokens=profile.context_window_tokens,
            max_output_tokens=assignment.max_output_tokens,
            safety_margin_tokens=assignment.safety_margin_tokens,
            target_input_tokens=assignment.target_input_tokens,
            connect_timeout_seconds=assignment.connect_timeout_seconds,
            read_timeout_seconds=assignment.read_timeout_seconds,
            write_timeout_seconds=assignment.write_timeout_seconds,
            pool_timeout_seconds=assignment.pool_timeout_seconds,
            operation_deadline_seconds=assignment.operation_deadline_seconds,
            temperature=assignment.temperature,
            max_in_flight=assignment.max_in_flight,
            max_queued=assignment.max_queued,
            queue_wait_timeout_seconds=assignment.queue_wait_timeout_seconds,
            retryable_statuses=assignment.retryable_statuses,
            max_attempts=assignment.max_attempts,
            backoff_base_seconds=assignment.backoff_base_seconds,
            backoff_multiplier=assignment.backoff_multiplier,
            backoff_cap_seconds=assignment.backoff_cap_seconds,
            backoff_jitter_seconds=assignment.backoff_jitter_seconds,
            circuit_threshold=assignment.circuit_threshold,
            circuit_observation_seconds=assignment.circuit_observation_seconds,
            circuit_cooldown_seconds=assignment.circuit_cooldown_seconds,
            input_price_per_million=profile.input_price_per_million,
            output_price_per_million=profile.output_price_per_million,
            provider_account_id=provider.provider_account_id,
            provider_account_name=provider.name,
            model_profile_id=profile.model_profile_id,
            model_profile_name=profile.name,
            api_key=provider.api_key,
        )

    def validate(self, *, require_complete: bool = True) -> None:
        if self.config_version <= 0:
            raise ValueError("config_version must be positive")
        if not self.host or not 1 <= self.port <= 65_535:
            raise ValueError("listener host/port is invalid")
        if self.global_config.admin_auth_mode == "disabled" and self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("non-loopback bind is forbidden while admin auth is disabled")
        self.global_config.validate()
        if not self.provider_accounts:
            raise ValueError("at least one provider account is required")
        if not self.model_profiles:
            raise ValueError("at least one model profile is required")
        for key, provider in self.provider_accounts.items():
            if key != provider.provider_account_id:
                raise ValueError(f"provider account key {key} does not match its stable ID")
            provider.validate(require_complete=require_complete)
        for key, profile in self.model_profiles.items():
            if key != profile.model_profile_id:
                raise ValueError(f"model profile key {key} does not match its stable ID")
            if profile.provider_account_id not in self.provider_accounts:
                raise ValueError(f"Model profile {profile.name} references unknown provider account")
            profile.validate(require_complete=require_complete)
        missing = [name for name in CHAT_OPERATIONS if name not in self.operation_assignments]
        extra = [name for name in self.operation_assignments if name not in CHAT_OPERATIONS]
        if missing or extra:
            raise ValueError(f"operation set mismatch; missing={missing}, extra={extra}")
        for name in CHAT_OPERATIONS:
            assignment = self.operation_assignments[name]
            profile = self.model_profiles.get(assignment.model_profile_id)
            if profile is None:
                raise ValueError(f"Operation {name} references unknown model profile")
            assignment.validate(
                name,
                context_window_tokens=max(profile.context_window_tokens, 1),
                require_complete=require_complete,
            )
            if require_complete and assignment.structured_output_mode not in profile.supported_structured_output_modes:
                raise ValueError(
                    f"Operation {name} selects {assignment.structured_output_mode}, which model profile {profile.name} does not support"
                )
        self.embedding.validate(require_model=require_complete)

    def validate_local_model_artifacts(self) -> None:
        """Load and exercise every configured tokenizer without provider calls."""
        from server.token_accounting import (
            build_provider_payload,
            canonical_json,
            count_provider_payload,
        )

        for name in CHAT_OPERATIONS:
            operation = self.resolve_operation(name)
            user_object = {"task": "configuration_validation"}
            messages = [
                {"role": "system", "content": operation.system_prompt},
                {"role": "user", "content": canonical_json(user_object)},
            ]
            payload = build_provider_payload(
                operation,
                operation=name,
                messages=messages,
                user_object=user_object,
                response_schema={"type": "object", "additionalProperties": False},
            )
            try:
                count_provider_payload(payload, operation)
            except Exception as exc:
                raise ValueError(
                    f"Operation {name} cannot load or apply model profile "
                    f"{operation.model_profile_name!r} tokenizer"
                ) from exc

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, Any]:
        return {
            "config_schema_version": CONFIG_SCHEMA_VERSION,
            "config_version": self.config_version,
            "host": self.host,
            "port": self.port,
            "global_config": self.global_config.to_dict(),
            "provider_accounts": {
                key: value.to_dict(include_secret=include_secrets)
                for key, value in self.provider_accounts.items()
            },
            "model_profiles": {key: value.to_dict() for key, value in self.model_profiles.items()},
            "operation_assignments": {
                name: value.to_dict() for name, value in self.operation_assignments.items()
            },
            "embedding": self.embedding.to_dict(),
        }

    def without_secrets(self) -> "ServerConfig":
        return replace(
            self,
            provider_accounts={
                key: replace(value, api_key="") for key, value in self.provider_accounts.items()
            },
        )

    @classmethod
    def from_resolved_operations(
        cls,
        *,
        config_version: int,
        host: str,
        port: int,
        global_config: GlobalConfig,
        operations: dict[str, OperationConfig],
        embedding: EmbeddingConfig,
    ) -> "ServerConfig":
        providers: dict[str, ProviderAccount] = {}
        profiles: dict[str, ModelProfile] = {}
        assignments: dict[str, OperationAssignment] = {}
        provider_secret_values: dict[str, str] = {}
        for operation_name in CHAT_OPERATIONS:
            operation = operations[operation_name].normalized()
            provider_key = [operation.provider_kind, operation.base_url]
            provider_id = operation.provider_account_id or _stable_id("provider", provider_key)
            provider_name = operation.provider_account_name or operation.base_url or "OpenAI-compatible provider"
            existing_secret = provider_secret_values.get(provider_id)
            if existing_secret and operation.api_key and existing_secret != operation.api_key:
                raise ValueError(
                    f"operations sharing provider endpoint {operation.base_url} have different API keys"
                )
            if operation.api_key:
                provider_secret_values[provider_id] = operation.api_key
            providers[provider_id] = ProviderAccount(
                provider_id,
                provider_name,
                operation.provider_kind,
                operation.base_url,
                provider_secret_values.get(provider_id, ""),
            ).normalized()
            profile_key = [
                provider_id,
                operation.model_id,
                operation.accounting_mode,
                operation.encoding_name,
                operation.tokenizer_name,
                operation.tokenizer_revision,
                operation.provider_wrapper_tokens,
                operation.context_window_tokens,
                operation.input_price_per_million,
                operation.output_price_per_million,
            ]
            profile_id = operation.model_profile_id or _stable_id("model", profile_key)
            profile_name = operation.model_profile_name or operation.model_id or f"Model for {operation_name}"
            profiles[profile_id] = ModelProfile(
                profile_id,
                profile_name,
                provider_id,
                operation.model_id,
                operation.accounting_mode,
                operation.encoding_name,
                operation.tokenizer_name,
                operation.tokenizer_revision,
                operation.provider_wrapper_tokens,
                operation.context_window_tokens,
                operation.input_price_per_million,
                operation.output_price_per_million,
            )
            assignments[operation_name] = OperationAssignment(
                model_profile_id=profile_id,
                system_prompt=operation.system_prompt,
                structured_output_mode=operation.structured_output_mode,
                max_output_tokens=operation.max_output_tokens,
                safety_margin_tokens=operation.safety_margin_tokens,
                target_input_tokens=operation.target_input_tokens,
                connect_timeout_seconds=operation.connect_timeout_seconds,
                read_timeout_seconds=operation.read_timeout_seconds,
                write_timeout_seconds=operation.write_timeout_seconds,
                pool_timeout_seconds=operation.pool_timeout_seconds,
                operation_deadline_seconds=operation.operation_deadline_seconds,
                temperature=operation.temperature,
                max_in_flight=operation.max_in_flight,
                max_queued=operation.max_queued,
                queue_wait_timeout_seconds=operation.queue_wait_timeout_seconds,
                retryable_statuses=operation.retryable_statuses,
                max_attempts=operation.max_attempts,
                backoff_base_seconds=operation.backoff_base_seconds,
                backoff_multiplier=operation.backoff_multiplier,
                backoff_cap_seconds=operation.backoff_cap_seconds,
                backoff_jitter_seconds=operation.backoff_jitter_seconds,
                circuit_threshold=operation.circuit_threshold,
                circuit_observation_seconds=operation.circuit_observation_seconds,
                circuit_cooldown_seconds=operation.circuit_cooldown_seconds,
            )
        return cls(
            config_version,
            host,
            port,
            global_config,
            providers,
            profiles,
            assignments,
            embedding,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, config_version: int | None = None) -> "ServerConfig":
        if not isinstance(raw, dict):
            raise ValueError("server configuration must be an object")
        if raw.get("config_schema_version") != CONFIG_SCHEMA_VERSION:
            raise ValueError("runtime configuration must use schema v4")
        unknown = set(raw) - {
            "config_schema_version",
            "config_version",
            "host",
            "port",
            "global_config",
            "provider_accounts",
            "model_profiles",
            "operation_assignments",
            "embedding",
        }
        if unknown:
            raise ValueError(f"Unknown server configuration fields: {', '.join(sorted(unknown))}")
        provider_raw = raw.get("provider_accounts")
        profile_raw = raw.get("model_profiles")
        assignment_raw = raw.get("operation_assignments")
        if not isinstance(provider_raw, dict) or not isinstance(profile_raw, dict) or not isinstance(assignment_raw, dict):
            raise ValueError("provider_accounts, model_profiles, and operation_assignments must be objects")
        global_raw = dict(raw.get("global_config", {}))
        embedding_raw = raw.get("embedding", {})
        if not isinstance(global_raw, dict) or not isinstance(embedding_raw, dict):
            raise ValueError("global_config and embedding must be objects")
        legacy_window_target = global_raw.pop("window_target_input_tokens", None)
        if legacy_window_target is not None and "window_input_utilization_percent" not in global_raw:
            global_raw["window_input_utilization_percent"] = 85.0
        return cls(
            config_version=int(config_version if config_version is not None else raw.get("config_version", 0)),
            host=str(raw.get("host", "127.0.0.1")),
            port=int(raw.get("port", 8710)),
            global_config=GlobalConfig(**global_raw),
            provider_accounts={key: ProviderAccount.from_dict(value) for key, value in provider_raw.items()},
            model_profiles={key: ModelProfile.from_dict(value) for key, value in profile_raw.items()},
            operation_assignments={name: OperationAssignment.from_dict(value) for name, value in assignment_raw.items()},
            embedding=EmbeddingConfig(**embedding_raw),
        )
