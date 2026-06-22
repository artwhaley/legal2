"""Search grouping tests."""

from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.grouping import group_hits
from message_evidence_workstation.search.result_models import SearchHit


def _hit(
    message_id: str,
    *,
    thread: str = "thread_001",
    match_type: str = "exact",
    timestamp: str = "2024-01-01T10:00:00+00:00",
) -> SearchHit:
    return SearchHit(
        message_id=message_id,
        source_thread_id=thread,
        match_type=match_type,
        retrieval_method="fts_exact",
        query_text="q",
        timestamp=timestamp,
    )


def test_deduplicate_exact_over_partial() -> None:
    hits = fuse_hits(
        [_hit("msg_001", match_type="exact")],
        [_hit("msg_001", match_type="partial")],
    )
    assert len(hits) == 1
    assert hits[0].match_type == "exact"


def test_group_by_message_distance() -> None:
    sort_index = {"msg_a": 1, "msg_b": 3, "msg_c": 20}
    groups = group_hits(
        [
            _hit("msg_a", timestamp="2024-01-01T10:00:00+00:00"),
            _hit("msg_b", timestamp="2024-01-01T10:01:00+00:00"),
            _hit("msg_c", timestamp="2024-02-01T10:00:00+00:00"),
        ],
        sort_index_by_message=sort_index,
    )
    assert len(groups) == 2
    assert {hit.message_id for hit in groups[0].hits} == {"msg_a", "msg_b"}


def test_group_by_time_distance() -> None:
    sort_index = {"msg_a": 1, "msg_b": 100}
    groups = group_hits(
        [
            _hit("msg_a", timestamp="2024-01-01T10:00:00+00:00"),
            _hit("msg_b", timestamp="2024-01-01T10:20:00+00:00"),
        ],
        sort_index_by_message=sort_index,
    )
    assert len(groups) == 1
    assert len(groups[0].hits) == 2
