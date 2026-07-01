"""Embedding model adapters."""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True)
class EmbeddingAdapterInfo:
    model_name: str
    model_revision: str
    dimensions: int
    normalization_mode: str


class EmbeddingAdapter(ABC):
    @abstractmethod
    def load(self) -> EmbeddingAdapterInfo:
        raise NotImplementedError

    def download(self) -> EmbeddingAdapterInfo:
        raise NotImplementedError("This adapter does not support network download")

    @abstractmethod
    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError


class FakeEmbeddingAdapter(EmbeddingAdapter):
    def __init__(self, model_name: str = "fake-embedding", dimensions: int = 8) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._loaded = False

    def load(self) -> EmbeddingAdapterInfo:
        self._loaded = True
        return EmbeddingAdapterInfo(
            model_name=self.model_name,
            model_revision="fake-1",
            dimensions=self.dimensions,
            normalization_mode="none",
        )

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not self._loaded:
            raise RuntimeError("FakeEmbeddingAdapter.load() must be called first")
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = [digest[i % len(digest)] / 255.0 for i in range(self.dimensions)]
            vectors.append(values)
        return vectors


class SentenceTransformerAdapter(EmbeddingAdapter):
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        self._info: EmbeddingAdapterInfo | None = None

    def _build_info(self) -> EmbeddingAdapterInfo:
        sample = self._model.encode(["dimension probe"], normalize_embeddings=True)
        dimensions = int(len(sample[0]))
        self._info = EmbeddingAdapterInfo(
            model_name=self.model_name,
            model_revision=getattr(self._model, "model_version", "") or "",
            dimensions=dimensions,
            normalization_mode="l2",
        )
        return self._info

    def load(self) -> EmbeddingAdapterInfo:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; pip install sentence-transformers"
            ) from exc
        try:
            self._model = SentenceTransformer(self.model_name, local_files_only=True)
        except Exception as exc:
            raise RuntimeError(
                f"Embedding model '{self.model_name}' not found in local cache. "
                "Use the 'Download embedding model' button in Settings to download it once."
            ) from exc
        return self._build_info()

    def download(self) -> EmbeddingAdapterInfo:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; pip install sentence-transformers"
            ) from exc
        self._model = SentenceTransformer(self.model_name)
        return self._build_info()

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None or self._info is None:
            raise RuntimeError("SentenceTransformerAdapter.load() or .download() must be called first")
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]


def create_adapter(adapter_key: str, model_name: str) -> EmbeddingAdapter:
    if adapter_key == "fake":
        return FakeEmbeddingAdapter(model_name=model_name)
    if adapter_key in {"minilm", "qwen3", "embeddinggemma", "nomic"}:
        return SentenceTransformerAdapter(model_name)
    raise ValueError(f"Unknown adapter key: {adapter_key}")
