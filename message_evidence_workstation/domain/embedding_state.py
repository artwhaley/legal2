"""Shared embedding readiness and progress state for UI gating."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EmbeddingState:
    message_ready: bool = False
    chunk_ready: bool = False
    message_progress: int = 0
    message_total: int = 0
    chunk_progress: int = 0
    chunk_total: int = 0
    building: bool = False

    @property
    def message_incomplete(self) -> bool:
        if self.message_total <= 0:
            return not self.message_ready
        return self.message_progress < self.message_total

    @property
    def chunk_incomplete(self) -> bool:
        if self.chunk_total <= 0:
            return not self.chunk_ready
        return self.chunk_progress < self.chunk_total
