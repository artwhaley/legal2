"""Embedding model registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmbeddingModelSpec:
    model_id: str
    label: str
    adapter_key: str


EMBEDDING_MODELS: tuple[EmbeddingModelSpec, ...] = (
    EmbeddingModelSpec(
        model_id="Qwen/Qwen3-Embedding-0.6B",
        label="Qwen3 Embedding 0.6B",
        adapter_key="qwen3",
    ),
    EmbeddingModelSpec(
        model_id="google/embeddinggemma-300m",
        label="EmbeddingGemma 300M",
        adapter_key="embeddinggemma",
    ),
    EmbeddingModelSpec(
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        label="all-MiniLM-L6-v2",
        adapter_key="minilm",
    ),
    EmbeddingModelSpec(
        model_id="nomic-ai/nomic-embed-text-v1",
        label="Nomic Embed Text v1",
        adapter_key="nomic",
    ),
)


def get_model_spec(model_id: str) -> EmbeddingModelSpec | None:
    for spec in EMBEDDING_MODELS:
        if spec.model_id == model_id:
            return spec
    return None
