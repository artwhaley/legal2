"""Windowed transcript data access for virtualized UI."""

from __future__ import annotations

import sqlite3
from typing import Protocol

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.models import EvidenceBlock, Message
from message_evidence_workstation.ui.transcript_display import build_sender_participant_map


class TranscriptDataSource(Protocol):
    def message_count(self, thread_id: str) -> int: ...

    def fetch_messages(self, thread_id: str, start_index: int, count: int) -> list[Message]: ...

    def fetch_evidence_blocks(self, thread_id: str) -> list[EvidenceBlock]: ...

    def fetch_block_highlights(self, block_ids: list[int]) -> dict[int, frozenset[str]]: ...

    def fetch_participant_map(self, thread_id: str) -> dict[str, int]: ...

    def message_index_for_id(self, thread_id: str, message_id: str) -> int | None: ...

    def ordered_message_ids(self, thread_id: str) -> list[str]: ...


class InMemoryTranscriptDataSource:
    """In-memory data source for tests and small legacy loads."""

    def __init__(
        self,
        messages_by_thread: dict[str, list[Message]] | None = None,
        blocks_by_thread: dict[str, list[EvidenceBlock]] | None = None,
    ) -> None:
        self._messages_by_thread = messages_by_thread or {}
        self._blocks_by_thread = blocks_by_thread or {}

    def set_thread(self, thread_id: str, messages: list[Message], blocks: list[EvidenceBlock] | None = None) -> None:
        self._messages_by_thread[thread_id] = list(messages)
        if blocks is not None:
            self._blocks_by_thread[thread_id] = list(blocks)

    def message_count(self, thread_id: str) -> int:
        return len(self._messages_by_thread.get(thread_id, []))

    def fetch_messages(self, thread_id: str, start_index: int, count: int) -> list[Message]:
        if count <= 0:
            return []
        messages = self._messages_by_thread.get(thread_id, [])
        start = max(0, start_index)
        end = min(len(messages), start + count)
        if start >= end:
            return []
        return messages[start:end]

    def fetch_evidence_blocks(self, thread_id: str) -> list[EvidenceBlock]:
        return list(self._blocks_by_thread.get(thread_id, []))

    def fetch_block_highlights(self, block_ids: list[int]) -> dict[int, frozenset[str]]:
        del block_ids
        return {}

    def fetch_participant_map(self, thread_id: str) -> dict[str, int]:
        return build_sender_participant_map(self._messages_by_thread.get(thread_id, []))

    def message_index_for_id(self, thread_id: str, message_id: str) -> int | None:
        ordered = self.ordered_message_ids(thread_id)
        try:
            return ordered.index(message_id)
        except ValueError:
            return None

    def ordered_message_ids(self, thread_id: str) -> list[str]:
        return [message.message_id for message in self._messages_by_thread.get(thread_id, [])]


class SqlTranscriptDataSource:
    """SQLite-backed transcript paging."""

    def __init__(self, conn: sqlite3.Connection, dataset_id: int) -> None:
        self._conn = conn
        self._dataset_id = dataset_id

    def message_count(self, thread_id: str) -> int:
        return repositories.thread_message_count(self._conn, self._dataset_id, thread_id)

    def fetch_messages(self, thread_id: str, start_index: int, count: int) -> list[Message]:
        if count <= 0:
            return []
        return repositories.fetch_messages_for_slot_range(
            self._conn,
            self._dataset_id,
            thread_id,
            start_index,
            start_index + count,
        )

    def fetch_evidence_blocks(self, thread_id: str) -> list[EvidenceBlock]:
        return evidence_blocks.list_evidence_blocks(
            self._conn,
            self._dataset_id,
            source_thread_id=thread_id,
        )

    def fetch_block_highlights(self, block_ids: list[int]) -> dict[int, frozenset[str]]:
        return evidence_blocks.fetch_highlights_for_blocks(self._conn, block_ids)

    def fetch_participant_map(self, thread_id: str) -> dict[str, int]:
        return repositories.fetch_thread_participant_map(self._conn, self._dataset_id, thread_id)

    def message_index_for_id(self, thread_id: str, message_id: str) -> int | None:
        return repositories.message_index_in_thread(
            self._conn,
            self._dataset_id,
            thread_id,
            message_id,
        )

    def ordered_message_ids(self, thread_id: str) -> list[str]:
        return repositories.fetch_message_ids_for_thread(self._conn, self._dataset_id, thread_id)
