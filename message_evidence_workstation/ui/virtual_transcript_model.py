"""Bounded SQL-backed model for the virtual transcript widget."""

from __future__ import annotations

import sqlite3
from collections import OrderedDict
from dataclasses import dataclass, replace

from message_evidence_workstation.db import evidence_blocks, repositories
from message_evidence_workstation.domain.models import EvidenceBlock, Message
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.ui.transcript_data_source import (
    InMemoryTranscriptDataSource,
    SqlTranscriptDataSource,
    TranscriptDataSource,
)

MAX_MESSAGE_CACHE = 512


@dataclass(slots=True)
class VirtualEvidenceOverlay:
    evidence_block_id: int
    context_start_slot: int
    relevant_start_slot: int
    relevant_end_slot: int
    context_end_slot: int
    core_hit_message_id: str
    highlighted_message_ids: frozenset[str]
    is_active: bool = False


class VirtualTranscriptModel:
    """Virtual transcript state with bounded message hydration."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        logger: ProcessLogger,
        *,
        dataset_id: int | None = None,
        data_source: TranscriptDataSource | None = None,
    ) -> None:
        self.conn = conn
        self.logger = logger
        self.dataset_id = dataset_id
        self._data_source = data_source
        self.source_thread_id: str | None = None
        self.message_count = 0
        self._message_cache: OrderedDict[int, Message] = OrderedDict()
        self._evidence_blocks: list[EvidenceBlock] = []
        self._overlays: list[VirtualEvidenceOverlay] = []
        self.active_evidence_block_id: int | None = None
        self.fetch_count = 0

    def set_dataset(self, dataset_id: int | None) -> None:
        self.dataset_id = dataset_id
        self._data_source = (
            SqlTranscriptDataSource(self.conn, dataset_id) if dataset_id is not None else None
        )
        self.clear_thread()

    def clear_thread(self) -> None:
        self.source_thread_id = None
        self.message_count = 0
        self._message_cache.clear()
        self._evidence_blocks = []
        self._overlays = []
        self.active_evidence_block_id = None

    def load_thread(self, source_thread_id: str) -> None:
        if self.dataset_id is None or self._data_source is None:
            self.clear_thread()
            return
        self.source_thread_id = source_thread_id
        self._message_cache.clear()
        self.message_count = self._data_source.message_count(source_thread_id)
        self.load_evidence_blocks()
        if self._evidence_blocks and self.active_evidence_block_id is None:
            self.set_active_evidence_block(self._evidence_blocks[0].evidence_block_id)
        self.logger.info(
            component="ui.virtual_transcript_model",
            operation="thread_loaded",
            message="Virtual transcript thread metadata loaded",
            details={
                "dataset_id": self.dataset_id,
                "source_thread_id": source_thread_id,
                "message_count": self.message_count,
            },
            dataset_id=self.dataset_id,
        )

    def messages_for_range(self, start_ordinal: int, end_ordinal: int) -> list[Message]:
        if self._data_source is None or self.source_thread_id is None:
            return []
        start = max(0, start_ordinal)
        end = min(self.message_count, end_ordinal)
        if end <= start:
            return []

        missing: list[int] = [
            ordinal
            for ordinal in range(start, end)
            if ordinal not in self._message_cache
        ]
        if missing:
            batch_start = missing[0]
            batch_end = missing[-1] + 1
            fetched = self._data_source.fetch_messages(
                self.source_thread_id,
                batch_start,
                batch_end - batch_start,
            )
            self.fetch_count += 1
            for message in fetched:
                if message.thread_ordinal is not None:
                    self._remember_message(int(message.thread_ordinal), message)

        return [self._message_cache[ordinal] for ordinal in range(start, end) if ordinal in self._message_cache]

    def cached_message_count(self) -> int:
        return len(self._message_cache)

    def message_at(self, ordinal: int) -> Message | None:
        messages = self.messages_for_range(ordinal, ordinal + 1)
        return messages[0] if messages else None

    def ordinal_for_message_id(self, message_id: str) -> int | None:
        if self.dataset_id is None or self.source_thread_id is None:
            return None
        for ordinal, message in self._message_cache.items():
            if message.message_id == message_id:
                return ordinal
        if self._data_source is not None:
            return self._data_source.message_index_for_id(self.source_thread_id, message_id)
        return repositories.message_ordinal(
            self.conn,
            self.dataset_id,
            self.source_thread_id,
            message_id,
        )

    def message_id_for_ordinal(self, ordinal: int) -> str | None:
        if ordinal < 0 or ordinal >= self.message_count:
            return None
        cached = self._message_cache.get(ordinal)
        if cached is not None:
            return cached.message_id
        if self._data_source is not None and self.source_thread_id is not None:
            fetched = self._data_source.fetch_messages(self.source_thread_id, ordinal, 1)
            if fetched:
                self._remember_message(ordinal, fetched[0])
                return fetched[0].message_id
        if self.dataset_id is None or self.source_thread_id is None:
            return None
        row = self.conn.execute(
            """
            SELECT message_id
            FROM message
            WHERE dataset_id = ? AND source_thread_id = ? AND thread_ordinal = ?
            """,
            (self.dataset_id, self.source_thread_id, ordinal),
        ).fetchone()
        if row is None:
            return None
        return str(row["message_id"])

    def load_evidence_blocks(self) -> list[EvidenceBlock]:
        if self._data_source is None or self.source_thread_id is None:
            self._evidence_blocks = []
            self._overlays = []
            return []
        self._evidence_blocks = self._data_source.fetch_evidence_blocks(self.source_thread_id)
        highlight_map = self._data_source.fetch_block_highlights(
            [block.evidence_block_id for block in self._evidence_blocks]
        )
        self._overlays = [
            VirtualEvidenceOverlay(
                evidence_block_id=block.evidence_block_id,
                context_start_slot=block.context_start_slot,
                relevant_start_slot=block.relevant_start_slot,
                relevant_end_slot=block.relevant_end_slot,
                context_end_slot=block.context_end_slot,
                core_hit_message_id=block.core_hit_message_id,
                highlighted_message_ids=highlight_map.get(
                    block.evidence_block_id,
                    block.highlighted_message_ids,
                ),
                is_active=block.evidence_block_id == self.active_evidence_block_id,
            )
            for block in self._evidence_blocks
        ]
        return list(self._evidence_blocks)

    def append_or_update_evidence_block(self, block: EvidenceBlock) -> None:
        replaced = False
        for index, existing in enumerate(self._evidence_blocks):
            if existing.evidence_block_id == block.evidence_block_id:
                self._evidence_blocks[index] = block
                replaced = True
                break
        if not replaced:
            self._evidence_blocks.append(block)
        overlay = VirtualEvidenceOverlay(
            evidence_block_id=block.evidence_block_id,
            context_start_slot=block.context_start_slot,
            relevant_start_slot=block.relevant_start_slot,
            relevant_end_slot=block.relevant_end_slot,
            context_end_slot=block.context_end_slot,
            core_hit_message_id=block.core_hit_message_id,
            highlighted_message_ids=frozenset(block.highlighted_message_ids),
            is_active=True,
        )
        overlay_replaced = False
        self._overlays = [
            replace(item, is_active=False)
            for item in self._overlays
        ]
        for index, existing in enumerate(self._overlays):
            if existing.evidence_block_id == overlay.evidence_block_id:
                self._overlays[index] = overlay
                overlay_replaced = True
                break
        if not overlay_replaced:
            self._overlays.append(overlay)
        self.active_evidence_block_id = block.evidence_block_id

    def set_active_evidence_block(self, evidence_block_id: int | None) -> None:
        self.active_evidence_block_id = evidence_block_id
        self._overlays = [
            replace(overlay, is_active=overlay.evidence_block_id == evidence_block_id)
            for overlay in self._overlays
        ]

    def active_overlay(self) -> VirtualEvidenceOverlay | None:
        for overlay in self._overlays:
            if overlay.is_active:
                return overlay
        return None

    def overlay_for_block(self, evidence_block_id: int) -> VirtualEvidenceOverlay | None:
        for overlay in self._overlays:
            if overlay.evidence_block_id == evidence_block_id:
                return overlay
        return None

    def update_active_overlay_slots(
        self,
        *,
        context_start: int,
        relevant_start: int,
        relevant_end: int,
        context_end: int,
    ) -> None:
        overlay = self.active_overlay()
        if overlay is None:
            return
        updated = replace(
            overlay,
            context_start_slot=context_start,
            relevant_start_slot=relevant_start,
            relevant_end_slot=relevant_end,
            context_end_slot=context_end,
        )
        self._overlays = [
            updated if item.evidence_block_id == updated.evidence_block_id else item
            for item in self._overlays
        ]

    def update_active_overlay_hit(self, message_id: str) -> None:
        overlay = self.active_overlay()
        if overlay is None:
            return
        updated = replace(overlay, core_hit_message_id=message_id)
        self._overlays = [
            updated if item.evidence_block_id == updated.evidence_block_id else item
            for item in self._overlays
        ]

    def toggle_active_overlay_highlight(self, message_id: str) -> None:
        overlay = self.active_overlay()
        if overlay is None:
            return
        highlights = set(overlay.highlighted_message_ids)
        if message_id in highlights:
            highlights.remove(message_id)
        else:
            highlights.add(message_id)
        updated = replace(overlay, highlighted_message_ids=frozenset(highlights))
        self._overlays = [
            updated if item.evidence_block_id == updated.evidence_block_id else item
            for item in self._overlays
        ]

    def _remember_message(self, ordinal: int, message: Message) -> None:
        self._message_cache[ordinal] = message
        self._message_cache.move_to_end(ordinal)
        while len(self._message_cache) > MAX_MESSAGE_CACHE:
            self._message_cache.popitem(last=False)


def in_memory_model(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    messages_by_thread: dict[str, list[Message]],
    blocks_by_thread: dict[str, list[EvidenceBlock]] | None = None,
) -> VirtualTranscriptModel:
    data_source = InMemoryTranscriptDataSource(messages_by_thread, blocks_by_thread)
    return VirtualTranscriptModel(
        conn,
        logger,
        dataset_id=dataset_id,
        data_source=data_source,
    )
