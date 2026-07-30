"""Deterministic provider/model fixtures that exercise real server orchestration."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any

import httpx

from server.config import CHAT_OPERATIONS, EmbeddingConfig, GlobalConfig, OperationConfig, ServerConfig
from server.config_service import ConfigurationService
from server.embeddings import EmbeddingService
from server.prompts import DEFAULT_PROMPTS
from server.provider import AsyncProvider


class FakeEmbeddingModel:
    def __init__(self, *, dimensions: int = 3, weight: float = 1.0, fail_after: int | None = None, delay: float = 0.0):
        self.dimensions = dimensions
        self.weight = weight
        self.fail_after = fail_after
        self.delay = delay
        self.calls = 0
        self.artifact_fingerprint_material = {"weight": weight, "dimensions": dimensions}

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimensions

    def encode(self, texts, normalize_embeddings):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("synthetic embedding failure")
        vector = [self.weight] + [0.0] * (self.dimensions - 1)
        return [list(vector) for _ in texts]


def server_config(*, context_window_tokens: int = 20_000, max_output_tokens: int = 1_000, global_config: GlobalConfig | None = None, embedding: EmbeddingConfig | None = None, operation_changes: dict[str, Any] | None = None) -> ServerConfig:
    operation_changes = operation_changes or {}
    operations = {}
    for name in CHAT_OPERATIONS:
        values = {
            "base_url": "https://provider.example/v1",
            "model_id": f"test-{name}",
            "system_prompt": DEFAULT_PROMPTS[name],
            "structured_output_mode": "json_schema",
            "context_window_tokens": context_window_tokens,
            "max_output_tokens": max_output_tokens,
            "safety_margin_tokens": 100,
            "retryable_statuses": (429, 500, 502, 503, 504),
            "max_attempts": 1,
            "input_price_per_million": 1.0,
            "output_price_per_million": 2.0,
            "api_key": "synthetic-secret-1234",
        }
        values.update(operation_changes)
        operations[name] = OperationConfig(**values)
    return ServerConfig.from_resolved_operations(
        config_version=1,
        host="127.0.0.1",
        port=8710,
        global_config=global_config or GlobalConfig(),
        operations=operations,
        embedding=embedding or EmbeddingConfig(model_name="fake", required_dimensions=3),
    )


def configured_service(tmp_path, config: ServerConfig | None = None) -> tuple[ConfigurationService, ServerConfig]:
    service = ConfigurationService(tmp_path)
    service.startup()
    draft = service.store.draft()[0]
    selected = config or server_config()
    service.store.save_draft(draft, selected)
    for provider_id in selected.provider_accounts:
        service.store.set_secret(draft, provider_id, "synthetic-secret-1234")
    service.activate(draft)
    return service, selected


def with_resolved_operations(
    config: ServerConfig, operations: dict[str, OperationConfig]
) -> ServerConfig:
    """Rebuild test configuration after altering resolved operation values."""
    return ServerConfig.from_resolved_operations(
        config_version=config.config_version,
        host=config.host,
        port=config.port,
        global_config=config.global_config,
        operations=operations,
        embedding=config.embedding,
    )


def output_for_user(user: dict[str, Any]) -> dict[str, Any]:
    task = user["task"]
    if task == "keyword_expansion":
        return {"terms": ["school", "meeting"]}
    if task == "analysis_planning":
        return {
            "analysis_question": "Identify passages that answer the user's question.",
            "answer_objective": "Present responsive exchanges with dates and supporting ranges.",
            "concepts": [{"label": "responsive exchange", "definition": "A passage that materially bears on the requested subject.", "manifestations": ["direct discussion"]}],
            "inclusion_criteria": ["The passage materially answers the requested question."],
            "exclusion_criteria": [],
            "retrieval_queries": ["question response", "material answer"],
            "answer_requirements": ["Cite supporting ranges."],
            "interpretive_assumptions": [],
        }
    if task == "window_evidence_extraction":
        messages = user["messages"]
        return {
            "window_id": user["window_id"],
            "evidence_ranges": [{
                "thread_id": messages[0]["thread_id"],
                "start_message_id": messages[0]["message_id"],
                "end_message_id": messages[-1]["message_id"],
                "summary": "The window contains evidence.",
                "relevance": "The passage bears on the question.",
            }],
            "uncertainties": [],
        }
    if task == "ledger_compaction":
        ids: list[str] = []
        for item in user["records_or_summaries"]:
            ids.extend(item["covered_range_ids"] if "covered_range_ids" in item else [item["range_id"]])
        return {
            "group_id": user["group_id"],
            "summary": "All supplied evidence is preserved in this group.",
            "covered_range_ids": ids,
            "uncertainties": [],
        }
    if task == "ledger_synthesis":
        ids = [item["range_id"] for item in user["ledger_metadata"]]
        return {
            "overview": "The ledger supports the answer.",
            "results": [{"probability": "high_probability", "statement": "The ledger supports the answer.", "range_ids": ids, "uncertainty": None}] if ids else [],
            "uncertainties": [],
        }
    raise AssertionError(f"unexpected task {task}")


def fake_provider(*, mutate=None, status_by_task: dict[str, int] | None = None, calls: list[dict[str, Any]] | None = None) -> AsyncProvider:
    status_by_task = status_by_task or {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        user = json.loads(payload["messages"][1]["content"])
        if calls is not None:
            calls.append({"user": user, "payload": payload, "authorization": request.headers.get("authorization")})
        status = status_by_task.get(user["task"], 200)
        if status != 200:
            return httpx.Response(status, text="safe synthetic provider failure")
        output = output_for_user(user)
        if mutate is not None:
            output = mutate(user, output)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}], "usage": {"prompt_tokens": 101, "completion_tokens": 23}},
            headers={"x-request-id": "synthetic-provider-request"},
        )

    return AsyncProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def fake_embedding_service(config: ServerConfig, model: FakeEmbeddingModel | None = None) -> EmbeddingService:
    return EmbeddingService(config.embedding, model=model or FakeEmbeddingModel(dimensions=config.embedding.required_dimensions or 3))
