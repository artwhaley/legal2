"""Explicit simple-search retrieval modes."""

from __future__ import annotations

from typing import Literal

SearchMode = Literal["fts5", "expanded_keyword", "message_embedding", "chunk_embedding"]

SEARCH_MODE_LABELS: dict[SearchMode, str] = {
    "fts5": "FTS5",
    "expanded_keyword": "Expanded keyword",
    "message_embedding": "Message embedding",
    "chunk_embedding": "Chunk embedding",
}
