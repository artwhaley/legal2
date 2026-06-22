"""Chunking tests."""

from message_evidence_workstation.embeddings.chunking import MessageChunkSpec, _MessageRow, build_thread_chunks


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
