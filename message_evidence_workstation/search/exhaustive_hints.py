"""Planner-driven retrieval hints for exhaustive window scans."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from message_evidence_workstation.config.settings import load_settings
from message_evidence_workstation.embeddings.adapters import EmbeddingAdapter, create_adapter
from message_evidence_workstation.embeddings.index_jobs import get_ready_index
from message_evidence_workstation.llm.router import ModelRouter
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.nim.model_runs import run_nim_chat
from message_evidence_workstation.nim.prompts import RUN_TYPE_EXHAUSTIVE_SCAN_RETRIEVAL_TERMS
from message_evidence_workstation.search.embedding_search import (
    search_chunk_embeddings,
    search_message_embeddings,
)
from message_evidence_workstation.search.fts import search_keyword_terms
from message_evidence_workstation.search.tool_runner import ToolRunnerDeps
from message_evidence_workstation.search.window_planner import TranscriptWindow


@dataclass(frozen=True, slots=True)
class ExhaustiveHintItem:
    source: Literal["fts5", "message_embedding", "chunk_embedding"]
    term: str
    source_thread_id: str
    hit_message_id: str
    start_message_id: str
    end_message_id: str


@dataclass(frozen=True, slots=True)
class ExhaustiveHintBlock:
    source_thread_id: str
    start_message_id: str
    end_message_id: str
    hit_message_ids: tuple[str, ...]
    terms: tuple[str, ...]
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExhaustiveHintCollection:
    planner_terms: tuple[str, ...]
    all_blocks: tuple[ExhaustiveHintBlock, ...]
    window_blocks_by_id: dict[str, tuple[ExhaustiveHintBlock, ...]]


def _clean_planner_terms(raw_terms: list[object], *, max_terms: int = 5) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        if not isinstance(raw, str):
            raise ValueError("planner term is not a string")
        term = raw.strip()
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(term)
        if len(cleaned) >= max_terms:
            break
    return cleaned


def parse_exhaustive_scan_retrieval_terms(content: str, *, max_terms: int = 5) -> list[str]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"planner returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("planner payload is not an object")
    terms = payload.get("terms")
    if not isinstance(terms, list):
        raise ValueError("planner payload is missing a terms array")
    return _clean_planner_terms(terms, max_terms=max_terms)


def _load_embedding_adapter_for_hints(
    deps: ToolRunnerDeps | None,
) -> tuple[EmbeddingAdapter, str] | None:
    if deps is not None and deps.embedding_adapter is not None and deps.embedding_model_name:
        return deps.embedding_adapter, deps.embedding_model_name
    settings = load_settings()
    model_name = settings.embedding_model
    if not model_name:
        return None
    from message_evidence_workstation.embeddings.model_registry import get_model_spec

    spec = get_model_spec(model_name)
    if spec is None:
        return None
    adapter = create_adapter(spec.adapter_key, spec.model_id)
    adapter.load()
    return adapter, spec.model_id


def _thread_message_ids(
    conn: sqlite3.Connection,
    dataset_id: int,
    source_thread_ids: set[str],
) -> dict[str, list[str]]:
    if not source_thread_ids:
        return {}
    placeholders = ",".join("?" for _ in source_thread_ids)
    rows = conn.execute(
        f"""
        SELECT source_thread_id, message_id
        FROM message
        WHERE dataset_id = ?
          AND source_thread_id IN ({placeholders})
        ORDER BY source_thread_id, timestamp, sort_index, message_id
        """,
        (dataset_id, *sorted(source_thread_ids)),
    ).fetchall()
    thread_ids: dict[str, list[str]] = {}
    for row in rows:
        source_thread_id = str(row["source_thread_id"])
        thread_ids.setdefault(source_thread_id, []).append(str(row["message_id"]))
    return thread_ids


def _dedupe_hint_items(items: list[ExhaustiveHintItem]) -> list[ExhaustiveHintItem]:
    deduped: list[ExhaustiveHintItem] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for item in items:
        key = (
            item.source_thread_id,
            item.start_message_id,
            item.end_message_id,
            item.hit_message_id,
            item.source,
            item.term.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _merge_contiguous_hint_items(
    items: list[ExhaustiveHintItem],
    *,
    thread_message_ids: dict[str, list[str]],
) -> list[ExhaustiveHintBlock]:
    thread_positions = {
        source_thread_id: {message_id: index for index, message_id in enumerate(message_ids)}
        for source_thread_id, message_ids in thread_message_ids.items()
    }

    sortable: list[tuple[int, int, ExhaustiveHintItem]] = []
    for item in items:
        positions = thread_positions.get(item.source_thread_id)
        if positions is None:
            continue
        start_pos = positions.get(item.start_message_id)
        end_pos = positions.get(item.end_message_id)
        hit_pos = positions.get(item.hit_message_id)
        if start_pos is None or end_pos is None or hit_pos is None:
            continue
        sortable.append((min(start_pos, end_pos), max(start_pos, end_pos), item))
    sortable.sort(key=lambda entry: (entry[2].source_thread_id, entry[0], entry[1], entry[2].hit_message_id))

    blocks: list[ExhaustiveHintBlock] = []
    current_thread = ""
    current_start = ""
    current_end = ""
    current_start_pos = -1
    current_end_pos = -1
    current_hit_ids: list[str] = []
    current_terms: list[str] = []
    current_sources: list[str] = []

    def flush() -> None:
        if not current_thread:
            return
        blocks.append(
            ExhaustiveHintBlock(
                source_thread_id=current_thread,
                start_message_id=current_start,
                end_message_id=current_end,
                hit_message_ids=tuple(dict.fromkeys(current_hit_ids)),
                terms=tuple(dict.fromkeys(current_terms)),
                sources=tuple(dict.fromkeys(current_sources)),
            )
        )

    for start_pos, end_pos, item in sortable:
        if not current_thread:
            current_thread = item.source_thread_id
            current_start = item.start_message_id
            current_end = item.end_message_id
            current_start_pos = start_pos
            current_end_pos = end_pos
            current_hit_ids = [item.hit_message_id]
            current_terms = [item.term]
            current_sources = [item.source]
            continue

        if item.source_thread_id == current_thread and start_pos <= current_end_pos + 1:
            if start_pos < current_start_pos:
                current_start_pos = start_pos
                current_start = item.start_message_id
            if end_pos > current_end_pos:
                current_end_pos = end_pos
                current_end = item.end_message_id
            current_hit_ids.append(item.hit_message_id)
            current_terms.append(item.term)
            current_sources.append(item.source)
            continue

        flush()
        current_thread = item.source_thread_id
        current_start = item.start_message_id
        current_end = item.end_message_id
        current_start_pos = start_pos
        current_end_pos = end_pos
        current_hit_ids = [item.hit_message_id]
        current_terms = [item.term]
        current_sources = [item.source]

    flush()
    return blocks


def _assign_blocks_to_windows(
    blocks: list[ExhaustiveHintBlock],
    *,
    planned_windows: list[TranscriptWindow],
    thread_message_ids: dict[str, list[str]],
) -> dict[str, tuple[ExhaustiveHintBlock, ...]]:
    thread_positions = {
        source_thread_id: {message_id: index for index, message_id in enumerate(message_ids)}
        for source_thread_id, message_ids in thread_message_ids.items()
    }
    assigned: dict[str, list[ExhaustiveHintBlock]] = {window.window_id: [] for window in planned_windows}
    for block in blocks:
        positions = thread_positions.get(block.source_thread_id)
        if positions is None:
            continue
        block_start = positions.get(block.start_message_id)
        block_end = positions.get(block.end_message_id)
        if block_start is None or block_end is None:
            continue
        low = min(block_start, block_end)
        high = max(block_start, block_end)
        ordered_ids = thread_message_ids[block.source_thread_id]
        for window in planned_windows:
            if window.source_thread_id != block.source_thread_id:
                continue
            window_start = positions.get(window.message_ids[0])
            window_end = positions.get(window.message_ids[-1])
            if window_start is None or window_end is None:
                continue
            intersect_start = max(low, min(window_start, window_end))
            intersect_end = min(high, max(window_start, window_end))
            if intersect_start > intersect_end:
                continue
            clipped_hit_ids = [
                message_id
                for message_id in block.hit_message_ids
                if intersect_start <= positions.get(message_id, -1) <= intersect_end
            ]
            assigned[window.window_id].append(
                ExhaustiveHintBlock(
                    source_thread_id=block.source_thread_id,
                    start_message_id=ordered_ids[intersect_start],
                    end_message_id=ordered_ids[intersect_end],
                    hit_message_ids=tuple(clipped_hit_ids),
                    terms=block.terms,
                    sources=block.sources,
                )
            )
    return {window_id: tuple(blocks) for window_id, blocks in assigned.items()}


def _fts_hint_items(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    terms: list[str],
) -> tuple[list[ExhaustiveHintItem], dict[str, int]]:
    items: list[ExhaustiveHintItem] = []
    counts: dict[str, int] = {}
    for term in terms:
        page = search_keyword_terms(conn, logger, dataset_id, [term], limit=None)
        hits = page["hits"]
        counts[term] = len(hits)
        for hit in hits:
            items.append(
                ExhaustiveHintItem(
                    source="fts5",
                    term=term,
                    source_thread_id=hit.source_thread_id,
                    hit_message_id=hit.message_id,
                    start_message_id=hit.message_id,
                    end_message_id=hit.message_id,
                )
            )
    return items, counts


def _message_embedding_hint_items(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    terms: list[str],
    adapter: EmbeddingAdapter,
    model_name: str,
) -> tuple[list[ExhaustiveHintItem], dict[str, int]]:
    items: list[ExhaustiveHintItem] = []
    counts: dict[str, int] = {}
    for term in terms:
        hits = search_message_embeddings(
            conn,
            logger,
            dataset_id=dataset_id,
            query=term,
            model_name=model_name,
            adapter=adapter,
            selectivity="broad",
        )
        counts[term] = len(hits)
        for hit in hits:
            items.append(
                ExhaustiveHintItem(
                    source="message_embedding",
                    term=term,
                    source_thread_id=hit.source_thread_id,
                    hit_message_id=hit.message_id,
                    start_message_id=hit.message_id,
                    end_message_id=hit.message_id,
                )
            )
    return items, counts


def _chunk_embedding_hint_items(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    terms: list[str],
    adapter: EmbeddingAdapter,
    model_name: str,
) -> tuple[list[ExhaustiveHintItem], dict[str, int]]:
    items: list[ExhaustiveHintItem] = []
    counts: dict[str, int] = {}
    for term in terms:
        hits = search_chunk_embeddings(
            conn,
            logger,
            dataset_id=dataset_id,
            query=term,
            model_name=model_name,
            adapter=adapter,
            selectivity="broad",
        )
        counts[term] = len(hits)
        if not hits:
            continue
        chunk_ids = [int(hit.chunk_id) for hit in hits if hit.chunk_id is not None]
        if not chunk_ids:
            continue
        chunk_rows = conn.execute(
            f"""
            SELECT chunk_id, source_thread_id, start_message_id, end_message_id
            FROM message_chunk
            WHERE chunk_id IN ({",".join("?" for _ in chunk_ids)})
            """,
            chunk_ids,
        ).fetchall()
        chunk_map = {int(row["chunk_id"]): row for row in chunk_rows}
        for hit in hits:
            if hit.chunk_id is None:
                continue
            row = chunk_map.get(int(hit.chunk_id))
            if row is None:
                continue
            items.append(
                ExhaustiveHintItem(
                    source="chunk_embedding",
                    term=term,
                    source_thread_id=str(row["source_thread_id"]),
                    hit_message_id=hit.message_id,
                    start_message_id=str(row["start_message_id"]),
                    end_message_id=str(row["end_message_id"]),
                )
            )
    return items, counts


def _source_counts(blocks: tuple[ExhaustiveHintBlock, ...]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for block in blocks:
        for source in block.sources:
            counts[source] += 1
    return dict(counts)


def collect_exhaustive_window_hints(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    router: ModelRouter,
    *,
    dataset_id: int,
    user_query: str,
    planned_windows: list[TranscriptWindow],
    deps: ToolRunnerDeps | None = None,
) -> ExhaustiveHintCollection:
    logger.info(
        component="search.exhaustive_hints",
        operation="exhaustive_scan_hint_planner_started",
        message="Starting exhaustive scan retrieval-term planner",
        details={"dataset_id": dataset_id},
        dataset_id=dataset_id,
    )
    try:
        planner = run_nim_chat(
            conn,
            logger,
            router,
            run_type=RUN_TYPE_EXHAUSTIVE_SCAN_RETRIEVAL_TERMS,
            user_content=user_query,
            dataset_id=dataset_id,
        )
        terms = parse_exhaustive_scan_retrieval_terms(planner.content)
    except Exception as exc:
        logger.error(
            component="search.exhaustive_hints",
            operation="exhaustive_scan_hint_planner_failed",
            message="Exhaustive scan retrieval-term planner failed; running without hints",
            details={"query": user_query},
            exc=exc,
            dataset_id=dataset_id,
        )
        return ExhaustiveHintCollection(planner_terms=(), all_blocks=(), window_blocks_by_id={})

    if not terms:
        logger.warning(
            component="search.exhaustive_hints",
            operation="exhaustive_scan_hint_planner_no_terms",
            message="Exhaustive scan retrieval-term planner returned no usable terms; running without hints",
            details={"query": user_query},
            dataset_id=dataset_id,
        )
        return ExhaustiveHintCollection(planner_terms=(), all_blocks=(), window_blocks_by_id={})

    logger.info(
        component="search.exhaustive_hints",
        operation="exhaustive_scan_hint_planner_completed",
        message="Exhaustive scan retrieval-term planner completed",
        details={"terms": terms},
        dataset_id=dataset_id,
    )
    logger.info(
        component="search.exhaustive_hints",
        operation="exhaustive_scan_hint_retrieval_started",
        message="Starting exhaustive scan retrieval hints",
        details={"terms": terms},
        dataset_id=dataset_id,
    )

    source_thread_ids = {window.source_thread_id for window in planned_windows}
    ordered_ids = _thread_message_ids(conn, dataset_id, source_thread_ids)

    all_items: list[ExhaustiveHintItem] = []
    fts_items, fts_counts = _fts_hint_items(conn, logger, dataset_id=dataset_id, terms=terms)
    all_items.extend(fts_items)
    logger.info(
        component="search.exhaustive_hints",
        operation="exhaustive_scan_hint_retrieval_channel_completed",
        message="Collected FTS5 exhaustive scan hints",
        details={
            "source": "fts5",
            "term_hit_counts": fts_counts,
            "hint_item_count": len(fts_items),
            "message_ids": [item.hit_message_id for item in fts_items[:200]],
        },
        dataset_id=dataset_id,
    )

    settings = load_settings()
    model_name = settings.embedding_model
    message_ready = bool(model_name) and get_ready_index(conn, dataset_id, "message", model_name) is not None
    chunk_ready = bool(model_name) and get_ready_index(conn, dataset_id, "chunk", model_name) is not None
    adapter_bundle: tuple[EmbeddingAdapter, str] | None = None
    if message_ready or chunk_ready:
        adapter_bundle = _load_embedding_adapter_for_hints(deps)

    if message_ready and adapter_bundle is not None:
        adapter, resolved_model_name = adapter_bundle
        message_items, message_counts = _message_embedding_hint_items(
            conn,
            logger,
            dataset_id=dataset_id,
            terms=terms,
            adapter=adapter,
            model_name=resolved_model_name,
        )
        all_items.extend(message_items)
        logger.info(
            component="search.exhaustive_hints",
            operation="exhaustive_scan_hint_retrieval_channel_completed",
            message="Collected message-embedding exhaustive scan hints",
            details={
                "source": "message_embedding",
                "term_hit_counts": message_counts,
                "hint_item_count": len(message_items),
                "message_ids": [item.hit_message_id for item in message_items[:200]],
            },
            dataset_id=dataset_id,
        )
    else:
        logger.info(
            component="search.exhaustive_hints",
            operation="exhaustive_scan_hint_retrieval_channel_unavailable",
            message="Message embedding hints unavailable for exhaustive scan",
            details={"source": "message_embedding", "model_name": model_name or "", "status": "not_ready"},
            dataset_id=dataset_id,
        )

    if chunk_ready and adapter_bundle is not None:
        adapter, resolved_model_name = adapter_bundle
        chunk_items, chunk_counts = _chunk_embedding_hint_items(
            conn,
            logger,
            dataset_id=dataset_id,
            terms=terms,
            adapter=adapter,
            model_name=resolved_model_name,
        )
        all_items.extend(chunk_items)
        logger.info(
            component="search.exhaustive_hints",
            operation="exhaustive_scan_hint_retrieval_channel_completed",
            message="Collected chunk-embedding exhaustive scan hints",
            details={
                "source": "chunk_embedding",
                "term_hit_counts": chunk_counts,
                "hint_item_count": len(chunk_items),
                "ranges": [
                    f"{item.start_message_id}..{item.end_message_id}"
                    for item in chunk_items[:200]
                ],
            },
            dataset_id=dataset_id,
        )
    else:
        logger.info(
            component="search.exhaustive_hints",
            operation="exhaustive_scan_hint_retrieval_channel_unavailable",
            message="Chunk embedding hints unavailable for exhaustive scan",
            details={"source": "chunk_embedding", "model_name": model_name or "", "status": "not_ready"},
            dataset_id=dataset_id,
        )

    deduped_items = _dedupe_hint_items(all_items)
    blocks = _merge_contiguous_hint_items(deduped_items, thread_message_ids=ordered_ids)
    assigned = _assign_blocks_to_windows(blocks, planned_windows=planned_windows, thread_message_ids=ordered_ids)
    logger.info(
        component="search.exhaustive_hints",
        operation="exhaustive_scan_hint_blocks_built",
        message="Built exhaustive scan hint blocks",
        details={
            "planner_terms": terms,
            "raw_hint_item_count": len(all_items),
            "deduped_hint_item_count": len(deduped_items),
            "hint_block_count": len(blocks),
        },
        dataset_id=dataset_id,
    )
    logger.info(
        component="search.exhaustive_hints",
        operation="exhaustive_scan_hint_blocks_assigned",
        message="Assigned exhaustive scan hint blocks to planned windows",
        details={
            "window_hint_counts": {
                window_id: {
                    "block_count": len(window_blocks),
                    "source_counts": _source_counts(window_blocks),
                }
                for window_id, window_blocks in assigned.items()
            }
        },
        dataset_id=dataset_id,
    )
    return ExhaustiveHintCollection(
        planner_terms=tuple(terms),
        all_blocks=tuple(blocks),
        window_blocks_by_id=assigned,
    )
