from types import SimpleNamespace

from server.conversation_unified import _fuse_candidates, _suggestion_ranges
from server.evidence_ledger import WindowLedgerInput


def _context(hits):
    return SimpleNamespace(
        retrieval_queries=[SimpleNamespace(query_id="q0001", text="first"), SimpleNamespace(query_id="q0002", text="second")],
        hits=[SimpleNamespace(**hit) for hit in hits],
    )


def _snapshot(maximum=10):
    return SimpleNamespace(global_config=SimpleNamespace(
        retrieval_rrf_constant=60,
        retrieval_maximum_prompt_suggestion_messages=maximum,
    ))


def test_fusion_uses_rrf_then_distance_then_corpus_ordinal_then_message_id():
    context = _context([
        {"query_id": "q0001", "message_id": "m1", "rank": 1, "distance": 0.2},
        {"query_id": "q0002", "message_id": "m1", "rank": 1, "distance": 0.2},
        {"query_id": "q0001", "message_id": "m2", "rank": 2, "distance": 0.4},
        {"query_id": "q0002", "message_id": "m2", "rank": 2, "distance": 0.4},
        {"query_id": "q0001", "message_id": "m3", "rank": 3, "distance": 0.1},
    ])
    messages = [
        {"message_id": "m3"},
        {"message_id": "m2"},
        {"message_id": "m1"},
    ]

    selected, candidates, counts = _fuse_candidates(messages, context, _snapshot(maximum=2))

    assert selected == ["m1", "m2"]
    assert counts == {"raw_hit_count": 5, "unique_candidate_message_count": 3}
    assert candidates["m1"]["query_ids"] == {"q0001", "q0002"}


def test_suggestion_ranges_merge_only_directly_adjacent_selected_messages():
    context = _context([
        {"query_id": "q0001", "message_id": "m1", "rank": 1, "distance": 0.1},
        {"query_id": "q0002", "message_id": "m2", "rank": 1, "distance": 0.1},
        {"query_id": "q0001", "message_id": "m4", "rank": 2, "distance": 0.2},
    ])
    selected, candidates, _ = _fuse_candidates(
        [{"message_id": f"m{i}"} for i in range(1, 5)], context, _snapshot()
    )
    windows = [WindowLedgerInput("w000001", tuple(
        {"message_id": f"m{i}", "thread_id": "thread", "timestamp": str(i), "sender": "s", "text": "x"}
        for i in range(1, 5)
    ))]

    ranges = _suggestion_ranges(
        windows,
        selected,
        candidates,
        [{"query_id": "q0001", "text": "first"}, {"query_id": "q0002", "text": "second"}],
    )

    assert ranges["w000001"] == [
        {
            "thread_id": "thread",
            "start_message_id": "m1",
            "end_message_id": "m2",
            "hit_message_ids": ["m1", "m2"],
            "matched_query_ids": ["q0001", "q0002"],
        },
        {
            "thread_id": "thread",
            "start_message_id": "m4",
            "end_message_id": "m4",
            "hit_message_ids": ["m4"],
            "matched_query_ids": ["q0001"],
        },
    ]
