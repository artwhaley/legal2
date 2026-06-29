"""Provider-neutral model routing types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModelProvider(str, Enum):
    NIM = "nim"
    GOOGLE = "google"


class ModelTaskRole(str, Enum):
    """Stable internal task roles for LLM calls."""

    SEARCH_EXPANSION = "search_expansion"
    FULL_CONTEXT_SEARCH = "full_context_search"
    WINDOWED_CONTEXT_SEARCH = "windowed_context_search"
    WINDOWED_RESULT_MERGE = "windowed_result_merge"
    FULL_CONTEXT_ANSWER = "full_context_answer"
    CONVERSATIONAL_CANDIDATE = "conversational_candidate"
    MODEL_TEST = "model_test"
    MODEL_LIST = "model_list"


class UserFacingModelRole(str, Enum):
    """User-configurable model roles in settings."""

    EXPANSION = "expansion"
    RESEARCH = "research"
    WRITING = "writing"


@dataclass(slots=True)
class ModelInfo:
    id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelChatResult:
    content: str
    provider: ModelProvider
    model: str
    task_role: ModelTaskRole
    raw_response: dict[str, Any]
    latency_ms: int
    usage: ModelUsage | None = None
    message_layout: str = "provider_default"
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None


@dataclass(slots=True)
class ModelTestResult:
    success: bool
    provider: str
    model: str
    latency_ms: int | None = None
    response_preview: str = ""
    error_type: str | None = None
    error_message: str | None = None
    method: str = ""
    path: str = ""
    url: str = ""
    status_code: int | None = None
    response_body: str | None = None
