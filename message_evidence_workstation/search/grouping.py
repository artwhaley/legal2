"""Group nearby search hits into candidate workstation conversations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.result_models import GroupedSearchResult, SearchHit

if TYPE_CHECKING:
    from message_evidence_workstation.logging_ui.process_log import ProcessLogger

MESSAGE_DISTANCE_THRESHOLD = 5
TIME_DISTANCE_MINUTES = 30


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _within_time_window(left: str, right: str) -> bool:
    left_dt = _parse_ts(left)
    right_dt = _parse_ts(right)
    if left_dt is None or right_dt is None:
        return False
    delta = abs((left_dt - right_dt).total_seconds()) / 60.0
    return delta <= TIME_DISTANCE_MINUTES


def _position_for_hit(hit: SearchHit) -> int | None:
    if hit.thread_ordinal is not None:
        return hit.thread_ordinal
    if hit.sort_index is not None:
        return hit.sort_index
    return None


def _should_group(left: SearchHit, right: SearchHit) -> bool:
    if left.source_thread_id != right.source_thread_id:
        return False
    left_idx = _position_for_hit(left)
    right_idx = _position_for_hit(right)
    if left_idx is not None and right_idx is not None:
        if abs(left_idx - right_idx) <= MESSAGE_DISTANCE_THRESHOLD:
            return True
    if left.timestamp and right.timestamp and _within_time_window(left.timestamp, right.timestamp):
        return True
    return False


def group_hits(
    hits: list[SearchHit],
    *,
    logger: ProcessLogger | None = None,
    dataset_id: int | None = None,
) -> list[GroupedSearchResult]:
    ordered = fuse_hits(hits)
    groups: list[list[SearchHit]] = []
    for hit in ordered:
        placed = False
        for group in groups:
            if any(_should_group(existing, hit) for existing in group):
                group.append(hit)
                placed = True
                if logger is not None:
                    logger.info(
                        component="search.grouping",
                        operation="group_merge_hit",
                        message="Merged hit into existing candidate group",
                        details={
                            "message_id": hit.message_id,
                            "source_thread_id": hit.source_thread_id,
                            "group_size": len(group),
                            "reason": "same_thread_within_distance_or_time",
                        },
                        dataset_id=dataset_id,
                    )
                break
        if not placed:
            groups.append([hit])
            if logger is not None:
                logger.info(
                    component="search.grouping",
                    operation="group_new",
                    message="Started new candidate group",
                    details={
                        "message_id": hit.message_id,
                        "source_thread_id": hit.source_thread_id,
                    },
                    dataset_id=dataset_id,
                )

    results: list[GroupedSearchResult] = []
    for group in groups:
        primary = group[0]
        title_source = primary.snippet or primary.body or primary.message_id
        results.append(
            GroupedSearchResult(
                group_id=str(uuid4()),
                source_thread_id=primary.source_thread_id,
                primary_hit_message_id=primary.message_id,
                hits=group,
                title=title_source[:80],
                snippet=title_source[:160],
                retrieval_methods={
                    hit.retrieval_method for hit in group
                } | {method for hit in group for method in hit.extra_methods},
            )
        )
    return results
