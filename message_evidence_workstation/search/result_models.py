"""Search result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SearchHit:
    message_id: str
    source_thread_id: str
    match_type: str
    retrieval_method: str
    query_text: str
    matched_term: str = ""
    score: float | None = None
    rank: int | None = None
    distance: float | None = None
    sender_display: str = ""
    timestamp: str = ""
    body: str = ""
    snippet: str = ""
    chunk_id: int | None = None
    extra_methods: set[str] = field(default_factory=set)


@dataclass(slots=True)
class GroupedSearchResult:
    group_id: str
    source_thread_id: str
    primary_hit_message_id: str
    hits: list[SearchHit] = field(default_factory=list)
    title: str = ""
    snippet: str = ""
    retrieval_methods: set[str] = field(default_factory=set)
    relevant_start_message_id: str = ""
    relevant_end_message_id: str = ""
    leading_context_start_message_id: str = ""
    trailing_context_end_message_id: str = ""
    summary: str = ""

    def to_drag_payload(self) -> dict[str, Any]:
        payload = {
            "group_id": self.group_id,
            "source_thread_id": self.source_thread_id,
            "primary_hit_message_id": self.primary_hit_message_id,
            "query_text": self.hits[0].query_text if self.hits else "",
            "title": self.title,
            "snippet": self.snippet,
            "summary": self.summary,
            "hits": [
                {
                    "message_id": hit.message_id,
                    "retrieval_method": hit.retrieval_method,
                    "match_type": hit.match_type,
                    "query_text": hit.query_text,
                    "matched_term": hit.matched_term,
                    "score": hit.score,
                    "rank": hit.rank,
                    "distance": hit.distance,
                }
                for hit in self.hits
            ],
        }
        if self.relevant_start_message_id and self.relevant_end_message_id:
            payload["answer_range"] = {
                "hit_message_id": self.primary_hit_message_id,
                "start_message_id": self.relevant_start_message_id,
                "end_message_id": self.relevant_end_message_id,
                "leading_context_start_message_id": self.leading_context_start_message_id,
                "trailing_context_end_message_id": self.trailing_context_end_message_id,
            }
        return payload

    @classmethod
    def from_drag_payload(cls, payload: dict[str, Any]) -> GroupedSearchResult:
        hits = [
            SearchHit(
                message_id=item["message_id"],
                source_thread_id=payload["source_thread_id"],
                match_type=item.get("match_type", "exact"),
                retrieval_method=item.get("retrieval_method", "fts_exact"),
                query_text=item.get("query_text", ""),
                matched_term=item.get("matched_term", ""),
                score=item.get("score"),
                rank=item.get("rank"),
                distance=item.get("distance"),
            )
            for item in payload.get("hits", [])
        ]
        methods = {hit.retrieval_method for hit in hits}
        return cls(
            group_id=payload.get("group_id", ""),
            source_thread_id=payload["source_thread_id"],
            primary_hit_message_id=payload["primary_hit_message_id"],
            hits=hits,
            title=payload.get("title", ""),
            snippet=payload.get("snippet", ""),
            summary=payload.get("summary", ""),
            retrieval_methods=methods,
            relevant_start_message_id=(payload.get("answer_range") or {}).get("start_message_id", ""),
            relevant_end_message_id=(payload.get("answer_range") or {}).get("end_message_id", ""),
            leading_context_start_message_id=(payload.get("answer_range") or {}).get(
                "leading_context_start_message_id",
                "",
            ),
            trailing_context_end_message_id=(payload.get("answer_range") or {}).get(
                "trailing_context_end_message_id",
                "",
            ),
        )
