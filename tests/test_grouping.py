"""Search grouping tests."""

from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.grouping import group_hits
from message_evidence_workstation.search.result_models import SearchHit
from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.logging_ui.process_log import ProcessLogger


def _hit(
    message_id: str,
    *,
    thread: str = "thread_001",
    match_type: str = "exact",
    timestamp: str = "2024-01-01T10:00:00+00:00",
    thread_ordinal: int | None = None,
) -> SearchHit:
    return SearchHit(
        message_id=message_id,
        source_thread_id=thread,
        match_type=match_type,
        retrieval_method="fts_exact",
        query_text="q",
        timestamp=timestamp,
        thread_ordinal=thread_ordinal,
    )


def test_deduplicate_exact_over_partial() -> None:
    hits = fuse_hits(
        [_hit("msg_001", match_type="exact")],
        [_hit("msg_001", match_type="partial")],
    )
    assert len(hits) == 1
    assert hits[0].match_type == "exact"


def test_group_by_message_distance() -> None:
    groups = group_hits(
        [
            _hit("msg_a", timestamp="2024-01-01T10:00:00+00:00", thread_ordinal=1),
            _hit("msg_b", timestamp="2024-01-01T10:01:00+00:00", thread_ordinal=3),
            _hit("msg_c", timestamp="2024-02-01T10:00:00+00:00", thread_ordinal=20),
        ],
    )
    assert len(groups) == 2
    assert {hit.message_id for hit in groups[0].hits} == {"msg_a", "msg_b"}


def test_group_by_time_distance() -> None:
    groups = group_hits(
        [
            _hit("msg_a", timestamp="2024-01-01T10:00:00+00:00", thread_ordinal=1),
            _hit("msg_b", timestamp="2024-01-01T10:20:00+00:00", thread_ordinal=100),
        ],
    )
    assert len(groups) == 1
    assert len(groups[0].hits) == 2


def test_grouping_logs_summary_not_per_hit(tmp_path) -> None:
    conn = connect(tmp_path / "grouping.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    hits = [
        _hit(
            f"msg_{index:03d}",
            timestamp=f"2024-01-01T10:{index:02d}:00+00:00",
            thread_ordinal=index * 10,
        )
        for index in range(20)
    ]

    group_hits(hits, logger=logger)

    rows = conn.execute(
        """
        SELECT operation
        FROM process_log
        WHERE component = 'search.grouping'
        ORDER BY process_log_id
        """
    ).fetchall()
    assert [row["operation"] for row in rows] == ["grouping_started", "grouping_completed"]
