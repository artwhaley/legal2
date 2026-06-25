"""Model provider protocol."""

from __future__ import annotations

from typing import Protocol

from message_evidence_workstation.llm.types import ModelChatResult, ModelInfo, ModelTaskRole


class ModelProviderClient(Protocol):
    def list_models(self) -> list[ModelInfo]:
        ...

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: float,
        task_role: ModelTaskRole,
    ) -> ModelChatResult:
        ...
