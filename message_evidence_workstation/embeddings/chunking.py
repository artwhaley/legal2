"""Message-boundary-preserving chunking for embedding indexes."""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

DEFAULT_MAX_CHARS = 1200
DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD = 0.72
DEFAULT_DESIRED_AVERAGE_CHUNK_MESSAGES = 5
DEFAULT_SESSION_GAP_HOURS = 12.0


@dataclass(slots=True)
class ChunkingConfig:
    max_chars: int = DEFAULT_MAX_CHARS
    semantic_similarity_threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD
    desired_average_chunk_messages: int = DEFAULT_DESIRED_AVERAGE_CHUNK_MESSAGES
    session_gap_hours: float = DEFAULT_SESSION_GAP_HOURS
    use_semantic_boundaries: bool = True
    split_on_date_change: bool = True

    def to_metadata(self) -> dict[str, object]:
        return {
            "strategy": "chronological_semantic",
            "max_chars": int(self.max_chars),
            "semantic_similarity_threshold": float(self.semantic_similarity_threshold),
            "desired_average_chunk_messages": int(self.desired_average_chunk_messages),
            "session_gap_hours": float(self.session_gap_hours),
            "use_semantic_boundaries": bool(self.use_semantic_boundaries),
            "split_on_date_change": bool(self.split_on_date_change),
            "overlap_policy": "none",
        }


@dataclass(slots=True)
class MessageChunkSpec:
    source_thread_id: str
    start_message_id: str
    end_message_id: str
    message_count: int
    char_count: int
    text_checksum: str
    body_text: str


@dataclass(slots=True)
class _MessageRow:
    message_id: str
    source_thread_id: str
    body: str
    sort_index: int
    timestamp: str = ""
    vector: tuple[float, ...] | None = None


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def config_from_mapping(mapping: dict | None = None, *, max_chars: int | None = None) -> ChunkingConfig:
    payload = mapping or {}
    return ChunkingConfig(
        max_chars=int(payload.get("max_chars", max_chars or DEFAULT_MAX_CHARS)),
        semantic_similarity_threshold=float(
            payload.get("semantic_similarity_threshold", DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD)
        ),
        desired_average_chunk_messages=int(
            payload.get("desired_average_chunk_messages", DEFAULT_DESIRED_AVERAGE_CHUNK_MESSAGES)
        ),
        session_gap_hours=float(payload.get("session_gap_hours", DEFAULT_SESSION_GAP_HOURS)),
        use_semantic_boundaries=bool(payload.get("use_semantic_boundaries", True)),
        split_on_date_change=bool(payload.get("split_on_date_change", True)),
    )


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 1.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm <= 0 or right_norm <= 0:
        return 1.0
    return dot / (left_norm * right_norm)


def _mean_vector(vectors: list[tuple[float, ...]]) -> tuple[float, ...] | None:
    if not vectors:
        return None
    dimensions = len(vectors[0])
    if dimensions <= 0:
        return None
    totals = [0.0] * dimensions
    count = 0
    for vector in vectors:
        if len(vector) != dimensions:
            continue
        count += 1
        for index, value in enumerate(vector):
            totals[index] += value
    if count <= 0:
        return None
    return tuple(value / count for value in totals)


def _time_or_date_boundary(
    previous: _MessageRow | None,
    current: _MessageRow,
    config: ChunkingConfig,
) -> bool:
    if previous is None:
        return False
    previous_ts = _parse_timestamp(previous.timestamp)
    current_ts = _parse_timestamp(current.timestamp)
    if previous_ts is None or current_ts is None:
        return False
    if config.split_on_date_change and previous_ts.date() != current_ts.date():
        return True
    gap_hours = (current_ts - previous_ts).total_seconds() / 3600.0
    return gap_hours > config.session_gap_hours


def _semantic_boundary(
    current_vectors: list[tuple[float, ...]],
    next_vector: tuple[float, ...] | None,
    following_vector: tuple[float, ...] | None,
    config: ChunkingConfig,
) -> bool:
    if not config.use_semantic_boundaries or next_vector is None or not current_vectors:
        return False
    strongest_existing_link = max(_cosine_similarity(vector, next_vector) for vector in current_vectors)
    if strongest_existing_link >= config.semantic_similarity_threshold:
        return False
    if following_vector is not None:
        strongest_following_link = max(_cosine_similarity(vector, following_vector) for vector in current_vectors)
        if strongest_following_link >= config.semantic_similarity_threshold:
            return False
    centroid = _mean_vector(current_vectors)
    if centroid is None:
        return False
    return _cosine_similarity(centroid, next_vector) < config.semantic_similarity_threshold


def calibrate_semantic_similarity_threshold(
    messages_by_thread: dict[str, list[_MessageRow]],
    *,
    config: ChunkingConfig,
) -> float:
    message_count = sum(1 for rows in messages_by_thread.values() for row in rows if row.body.strip())
    if message_count <= 0 or config.desired_average_chunk_messages <= 0:
        return config.semantic_similarity_threshold
    target_chunks = max(1, round(message_count / config.desired_average_chunk_messages))
    best_threshold = config.semantic_similarity_threshold
    best_delta: tuple[int, float] | None = None
    for step in range(0, 101):
        threshold = step / 100
        candidate_config = ChunkingConfig(
            max_chars=config.max_chars,
            semantic_similarity_threshold=threshold,
            desired_average_chunk_messages=config.desired_average_chunk_messages,
            session_gap_hours=config.session_gap_hours,
            use_semantic_boundaries=config.use_semantic_boundaries,
            split_on_date_change=config.split_on_date_change,
        )
        chunk_count = sum(
            len(build_thread_chunks(rows, config=candidate_config))
            for rows in messages_by_thread.values()
        )
        delta = (abs(chunk_count - target_chunks), abs(threshold - DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD))
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_threshold = threshold
    return best_threshold


def config_with_calibrated_threshold(
    messages_by_thread: dict[str, list[_MessageRow]],
    config: ChunkingConfig,
) -> ChunkingConfig:
    if not config.use_semantic_boundaries:
        return config
    threshold = calibrate_semantic_similarity_threshold(messages_by_thread, config=config)
    return ChunkingConfig(
        max_chars=config.max_chars,
        semantic_similarity_threshold=threshold,
        desired_average_chunk_messages=config.desired_average_chunk_messages,
        session_gap_hours=config.session_gap_hours,
        use_semantic_boundaries=config.use_semantic_boundaries,
        split_on_date_change=config.split_on_date_change,
    )


def _deserialize_float32_vector(blob: bytes) -> tuple[float, ...]:
    if not blob:
        return ()
    dimensions = len(blob) // 4
    if dimensions <= 0:
        return ()
    return struct.unpack(f"<{dimensions}f", blob[: dimensions * 4])


def load_message_vector_map(conn: sqlite3.Connection, dataset_id: int) -> dict[str, tuple[float, ...]]:
    from message_evidence_workstation.embeddings.sqlite_vec_backend import MESSAGE_VEC_TABLE, load_sqlite_vec

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (MESSAGE_VEC_TABLE,),
    ).fetchone()
    if row is None:
        return {}
    load_sqlite_vec(conn)
    rows = conn.execute(
        f"SELECT message_id, embedding FROM {MESSAGE_VEC_TABLE} WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchall()
    return {
        str(row["message_id"]): _deserialize_float32_vector(bytes(row["embedding"]))
        for row in rows
    }


def message_vector_count(conn: sqlite3.Connection, dataset_id: int) -> int:
    from message_evidence_workstation.embeddings.sqlite_vec_backend import MESSAGE_VEC_TABLE, load_sqlite_vec

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (MESSAGE_VEC_TABLE,),
    ).fetchone()
    if row is None:
        return 0
    load_sqlite_vec(conn)
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {MESSAGE_VEC_TABLE} WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
    )


def _load_messages_by_thread(
    conn: sqlite3.Connection,
    dataset_id: int,
    config: ChunkingConfig,
) -> dict[str, list[_MessageRow]]:
    vectors_by_message = (
        load_message_vector_map(conn, dataset_id)
        if config.use_semantic_boundaries
        else {}
    )
    thread_rows = conn.execute(
        """
        SELECT DISTINCT source_thread_id
        FROM message
        WHERE dataset_id = ?
        ORDER BY source_thread_id
        """,
        (dataset_id,),
    ).fetchall()
    messages_by_thread: dict[str, list[_MessageRow]] = {}
    for thread_row in thread_rows:
        source_thread_id = thread_row["source_thread_id"]
        message_rows = conn.execute(
            """
            SELECT message_id, source_thread_id, body_normalized, sort_index, timestamp
            FROM message
            WHERE dataset_id = ? AND source_thread_id = ?
            ORDER BY sort_index, message_id
            """,
            (dataset_id, source_thread_id),
        ).fetchall()
        messages_by_thread[source_thread_id] = [
            _MessageRow(
                message_id=row["message_id"],
                source_thread_id=row["source_thread_id"],
                body=row["body_normalized"] or "",
                sort_index=row["sort_index"],
                timestamp=row["timestamp"],
                vector=vectors_by_message.get(str(row["message_id"])),
            )
            for row in message_rows
        ]
    return messages_by_thread


def calibrated_config_for_dataset(
    conn: sqlite3.Connection,
    dataset_id: int,
    config: ChunkingConfig,
) -> ChunkingConfig:
    if not config.use_semantic_boundaries:
        return config
    return config_with_calibrated_threshold(_load_messages_by_thread(conn, dataset_id, config), config)


def build_thread_chunks(
    messages: list[_MessageRow],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    config: ChunkingConfig | None = None,
) -> list[MessageChunkSpec]:
    """Pack whole messages into chunks without splitting message bodies."""
    if not messages:
        return []
    resolved_config = config or ChunkingConfig(max_chars=max_chars)
    ordered = sorted(messages, key=lambda row: (row.sort_index, row.message_id))
    chunks: list[MessageChunkSpec] = []
    current_ids: list[str] = []
    current_parts: list[str] = []
    current_vectors: list[tuple[float, ...]] = []
    previous_message: _MessageRow | None = None

    def flush() -> None:
        if not current_ids:
            return
        body_text = "\n".join(current_parts)
        chunks.append(
            MessageChunkSpec(
                source_thread_id=ordered[0].source_thread_id,
                start_message_id=current_ids[0],
                end_message_id=current_ids[-1],
                message_count=len(current_ids),
                char_count=len(body_text),
                text_checksum=_checksum(body_text),
                body_text=body_text,
            )
        )

    for index, message in enumerate(ordered):
        piece = message.body.strip()
        if not piece:
            continue
        prospective_len = len("\n".join([*current_parts, piece])) if current_parts else len(piece)
        should_break = (
            current_parts
            and (
                prospective_len > resolved_config.max_chars
                or _time_or_date_boundary(previous_message, message, resolved_config)
                or _semantic_boundary(
                    current_vectors,
                    message.vector,
                    ordered[index + 1].vector if index + 1 < len(ordered) else None,
                    resolved_config,
                )
            )
        )
        if should_break:
            flush()
            current_ids = []
            current_parts = []
            current_vectors = []
        current_ids.append(message.message_id)
        current_parts.append(piece)
        if message.vector is not None:
            current_vectors.append(message.vector)
        previous_message = message
    flush()
    return chunks


def build_dataset_chunks(
    messages_by_thread: dict[str, list[_MessageRow]],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    config: ChunkingConfig | None = None,
) -> list[MessageChunkSpec]:
    chunks: list[MessageChunkSpec] = []
    resolved_config = config or ChunkingConfig(max_chars=max_chars)
    if resolved_config.use_semantic_boundaries:
        resolved_config = config_with_calibrated_threshold(messages_by_thread, resolved_config)
    for source_thread_id in sorted(messages_by_thread):
        thread_messages = messages_by_thread[source_thread_id]
        if not thread_messages:
            continue
        chunks.extend(build_thread_chunks(thread_messages, config=resolved_config))
    return chunks


def iter_dataset_chunks(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    config: ChunkingConfig | None = None,
) -> Iterator[MessageChunkSpec]:
    """Yield chunks one thread at a time to avoid loading the whole dataset into RAM."""
    resolved_config = config or ChunkingConfig(max_chars=max_chars)
    messages_by_thread = _load_messages_by_thread(conn, dataset_id, resolved_config)
    if resolved_config.use_semantic_boundaries:
        resolved_config = config_with_calibrated_threshold(messages_by_thread, resolved_config)
    for source_thread_id in sorted(messages_by_thread):
        yield from build_thread_chunks(messages_by_thread[source_thread_id], config=resolved_config)


def count_dataset_chunks(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    config: ChunkingConfig | None = None,
) -> int:
    return sum(1 for _ in iter_dataset_chunks(conn, dataset_id, max_chars=max_chars, config=config))
