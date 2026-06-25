"""Chunking tests."""

from message_evidence_workstation.embeddings.chunking import (
    ChunkingConfig,
    MessageChunkSpec,
    _MessageRow,
    build_dataset_chunks,
    build_thread_chunks,
)


def test_chunking_never_splits_message_bodies() -> None:
    messages = [
        _MessageRow("m1", "t1", "a" * 800, 1),
        _MessageRow("m2", "t1", "b" * 800, 2),
        _MessageRow("m3", "t1", "short", 3),
    ]
    chunks = build_thread_chunks(messages, max_chars=900)
    assert len(chunks) == 2
    assert chunks[0].message_count == 1
    assert chunks[1].message_count >= 1
    assert "aaa" in chunks[0].body_text
    assert "bbb" not in chunks[0].body_text


def test_chunk_preserves_message_id_range() -> None:
    messages = [
        _MessageRow("m1", "t1", "hello", 1),
        _MessageRow("m2", "t1", "world", 2),
    ]
    chunks = build_thread_chunks(messages, max_chars=1200)
    assert len(chunks) == 1
    assert chunks[0].start_message_id == "m1"
    assert chunks[0].end_message_id == "m2"


def test_semantic_chunking_splits_low_similarity_adjacent_messages() -> None:
    messages = [
        _MessageRow("m1", "t1", "doctor visit", 1, "2024-01-01T09:00:00+00:00", (1.0, 0.0)),
        _MessageRow("m2", "t1", "follow up appointment", 2, "2024-01-01T09:05:00+00:00", (0.95, 0.05)),
        _MessageRow("m3", "t1", "hotel reservation", 3, "2024-01-01T09:10:00+00:00", (0.0, 1.0)),
    ]

    chunks = build_thread_chunks(
        messages,
        config=ChunkingConfig(
            max_chars=1200,
            semantic_similarity_threshold=0.75,
            session_gap_hours=24.0,
        ),
    )

    assert [chunk.start_message_id for chunk in chunks] == ["m1", "m3"]
    assert chunks[0].end_message_id == "m2"


def test_semantic_chunking_tolerates_low_similarity_sandwich_message() -> None:
    messages = [
        _MessageRow("m1", "t1", "school pickup", 1, "2024-01-01T09:00:00+00:00", (1.0, 0.0)),
        _MessageRow("m2", "t1", "brief aside", 2, "2024-01-01T09:05:00+00:00", (0.0, 1.0)),
        _MessageRow("m3", "t1", "school dropoff", 3, "2024-01-01T09:10:00+00:00", (1.0, 0.0)),
    ]

    chunks = build_thread_chunks(
        messages,
        config=ChunkingConfig(
            max_chars=1200,
            semantic_similarity_threshold=0.75,
            session_gap_hours=24.0,
        ),
    )

    assert len(chunks) == 1
    assert chunks[0].start_message_id == "m1"
    assert chunks[0].end_message_id == "m3"


def test_desired_average_chunk_length_calibrates_threshold() -> None:
    messages = []
    for index in range(100):
        cluster = index // 5
        vector = (1.0, 0.0) if cluster % 2 == 0 else (0.0, 1.0)
        messages.append(
            _MessageRow(
                f"m{index:03d}",
                "t1",
                f"message {index}",
                index,
                "2024-01-01T09:00:00+00:00",
                vector,
            )
        )

    chunks = build_dataset_chunks(
        {"t1": messages},
        config=ChunkingConfig(
            max_chars=10000,
            desired_average_chunk_messages=5,
            session_gap_hours=24.0,
        ),
    )

    assert len(chunks) == 20
    assert all(chunk.message_count == 5 for chunk in chunks)


def test_semantic_chunking_splits_on_date_change_even_when_vectors_match() -> None:
    messages = [
        _MessageRow("m1", "t1", "school pickup", 1, "2024-01-01T21:00:00+00:00", (1.0, 0.0)),
        _MessageRow("m2", "t1", "school dropoff", 2, "2024-01-02T08:00:00+00:00", (1.0, 0.0)),
    ]

    chunks = build_thread_chunks(
        messages,
        config=ChunkingConfig(
            max_chars=1200,
            semantic_similarity_threshold=0.1,
            session_gap_hours=24.0,
        ),
    )

    assert len(chunks) == 2
