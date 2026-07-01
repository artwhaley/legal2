"""EmbeddingService — single owner of loaded model state.

No UI dependencies. Suitable for use from any thread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from message_evidence_workstation.embeddings.adapters import EmbeddingAdapter, EmbeddingAdapterInfo


class EmbeddingService:
    """Owns the loaded embedding model and dispatches index builds."""

    def __init__(self) -> None:
        self._adapter: EmbeddingAdapter | None = None
        self._adapter_info: EmbeddingAdapterInfo | None = None
        self._loaded_model_id: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self._adapter is not None and self._adapter_info is not None

    @property
    def loaded_model_id(self) -> str | None:
        return self._loaded_model_id

    @property
    def adapter_info(self) -> EmbeddingAdapterInfo | None:
        return self._adapter_info

    def load(self, adapter_key: str, model_id: str) -> EmbeddingAdapterInfo:
        """Load model from local cache only. Raises RuntimeError if not cached."""
        from message_evidence_workstation.embeddings.adapters import create_adapter

        adapter = create_adapter(adapter_key, model_id)
        info = adapter.load()
        self._set_adapter(adapter, info, model_id)
        return info

    def download(self, adapter_key: str, model_id: str) -> EmbeddingAdapterInfo:
        """Download model from HuggingFace (network required). Caches locally."""
        from message_evidence_workstation.embeddings.adapters import create_adapter

        adapter = create_adapter(adapter_key, model_id)
        info = adapter.download()
        self._set_adapter(adapter, info, model_id)
        return info

    def invalidate(self) -> None:
        self._adapter = None
        self._adapter_info = None
        self._loaded_model_id = None

    def require_loaded(self) -> tuple[EmbeddingAdapter, EmbeddingAdapterInfo]:
        if not self.is_loaded:
            raise RuntimeError(
                "Embedding model is not loaded. "
                "Use the 'Download embedding model' button in Settings "
                "to download it once."
            )
        return self._adapter, self._adapter_info  # type: ignore[return-value]

    def _set_adapter(
        self,
        adapter: EmbeddingAdapter,
        info: EmbeddingAdapterInfo,
        model_id: str,
    ) -> None:
        self._adapter = adapter
        self._adapter_info = info
        self._loaded_model_id = model_id
