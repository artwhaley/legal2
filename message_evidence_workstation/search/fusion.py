"""Search hit fusion and de-duplication."""

from __future__ import annotations

from message_evidence_workstation.search.result_models import SearchHit

MATCH_PRIORITY = {
    "exact": 0,
    "partial": 1,
    "keyword": 2,
    "fuzzy": 3,
    "message_embedding": 4,
    "chunk_embedding": 5,
}


def fuse_hits(*hit_lists: list[SearchHit]) -> list[SearchHit]:
    by_message: dict[str, SearchHit] = {}
    for hits in hit_lists:
        for hit in hits:
            existing = by_message.get(hit.message_id)
            if existing is None:
                hit.extra_methods.add(hit.retrieval_method)
                by_message[hit.message_id] = hit
                continue
            existing.extra_methods.add(hit.retrieval_method)
            existing.extra_methods.update(hit.extra_methods)
            existing_priority = MATCH_PRIORITY.get(existing.match_type, 99)
            new_priority = MATCH_PRIORITY.get(hit.match_type, 99)
            if new_priority < existing_priority:
                hit.extra_methods.update(existing.extra_methods)
                hit.extra_methods.add(hit.retrieval_method)
                by_message[hit.message_id] = hit
            else:
                existing.extra_methods.add(hit.retrieval_method)
                existing.extra_methods.update(hit.extra_methods)
    fused = list(by_message.values())
    fused.sort(
        key=lambda hit: (
            MATCH_PRIORITY.get(hit.match_type, 99),
            hit.rank if hit.rank is not None else 9999,
            hit.message_id,
        )
    )
    return fused
