"""Run the fixed, read-only question-planned-analysis investigation.

The runner deliberately has no retry loop and no model/provider fallback.  The
server remains the owner of prompts, model assignments, ranking, windowing, and
ledger synthesis; this process only freezes EVW inputs, performs the permitted
    local vector lookup, submits diagnostic semantic arms, and writes reviewable
artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import html.parser
import json
import os
import re
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


QUESTION = "Show me fights about school."
DEFAULT_SMALL_REVISION_ID = 3
GOLD_RANGES = (
    ("2023-03-28", "julie_kramer", "decipher_message_1:3572", "decipher_message_1:3516"),
    ("2023-11-13", "julie_kramer", "decipher_message_1:986", "decipher_message_1:972"),
    ("2024-06-26", "julie_kramer", "decipher_export_19:583", "decipher_export_19:603"),
    ("2024-07-10", "julie_kramer", "decipher_export_19:788", "decipher_export_19:793"),
    ("2025-07-16", "julie_kramer", "decipher_export_19:3370", "decipher_export_19:3397"),
    ("2025-08-04", "julie_kramer", "decipher_export_19:3451", "decipher_export_19:3456"),
    ("2026-07-01", "julie_kramer", "decipher_export_5:131", "decipher_export_5:142"),
)
SESSION_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")


class ExperimentError(RuntimeError):
    """A visible, non-retryable investigation failure."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"cannot read JSON artifact {path}: {exc}") from exc


class HttpClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, payload: Any | None = None) -> tuple[int, dict[str, str], bytes]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as exc:
            content = exc.read().decode("utf-8", errors="replace")
            raise ExperimentError(f"{method} {path} failed with HTTP {exc.code}: {content[:1000]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ExperimentError(f"{method} {path} could not complete: {exc}") from exc

    def json(self, method: str, path: str, payload: Any | None = None) -> dict[str, Any]:
        status, _, body = self.request(method, path, payload)
        if status < 200 or status >= 300:
            raise ExperimentError(f"{method} {path} returned HTTP {status}")
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ExperimentError(f"{method} {path} returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ExperimentError(f"{method} {path} returned a non-object JSON value")
        return value

    def ndjson(self, path: str, payload: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
        status, _, body = self.request("POST", path, payload)
        try:
            events = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ExperimentError(f"POST {path} returned invalid NDJSON") from exc
        if not events or any(not isinstance(event, dict) for event in events):
            raise ExperimentError(f"POST {path} returned no valid events")
        return status, events


class _FormParser(html.parser.HTMLParser):
    def __init__(self, form_id: str | None):
        super().__init__(convert_charrefs=True)
        self.form_id = form_id
        self.in_form = False
        self.done = False
        self.select_name: str | None = None
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and not self.in_form and not self.done:
            if self.form_id is None or attributes.get("id") == self.form_id:
                self.in_form = True
            return
        if not self.in_form:
            return
        if tag == "input" and attributes.get("name"):
            input_type = attributes.get("type", "text").lower()
            if input_type not in {"submit", "button", "checkbox", "radio"}:
                self.values[str(attributes["name"])] = html.unescape(attributes.get("value") or "")
        elif tag == "select" and attributes.get("name"):
            self.select_name = str(attributes["name"])
        elif tag == "option" and self.select_name and "selected" in attributes:
            self.values[self.select_name] = html.unescape(attributes.get("value") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self.select_name = None
        elif tag == "form" and self.in_form:
            self.in_form = False
            self.done = True


def _extract_form(html_text: str, form_id: str | None) -> dict[str, str]:
    parser = _FormParser(form_id)
    parser.feed(html_text)
    if not parser.values:
        raise ExperimentError(f"admin form {form_id or '<first>'} was not found")
    return parser.values


def _csrf_and_version(html_text: str) -> tuple[str, str]:
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html_text)
    version = re.search(r'name="version_id" value="([^"]+)"', html_text)
    if csrf is None or version is None:
        raise ExperimentError("admin page did not expose a CSRF token and draft version")
    return html.unescape(csrf.group(1)), html.unescape(version.group(1))


def _admin_post(client: HttpClient, html_text: str, action: str, return_page: str) -> None:
    csrf, version = _csrf_and_version(html_text)
    data = urllib.parse.urlencode(
        {
            "csrf_token": csrf,
            "version_id": version,
            "return_page": return_page,
            "action": action,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        client.base_url + "/admin/action",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise ExperimentError(f"POST /admin/action ({action}) failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ExperimentError(f"POST /admin/action ({action}) could not complete: {exc}") from exc


def _ensure_debug_capture(client: HttpClient) -> str:
    projection = client.json("GET", "/admin/events")
    debug = projection.get("debug_status")
    if not isinstance(debug, dict):
        raise ExperimentError("/admin/events does not expose debug status")
    if debug.get("active"):
        raise ExperimentError("debug capture is already active; stop it before starting a fresh investigation")
    page_status, _, page_body = client.request("GET", "/admin/debug")
    if page_status != 200:
        raise ExperimentError(f"GET /admin/debug returned HTTP {page_status}")
    _admin_post(client, page_body.decode("utf-8"), "start_debug_capture", "debug")
    current = client.json("GET", "/admin/events")
    status = current.get("debug_status") or {}
    if not status.get("active") or status.get("writer_failure"):
        raise ExperimentError("debug capture did not become active with a healthy writer")
    session_id = status.get("active_session_id")
    if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
        raise ExperimentError("debug capture returned an invalid session ID")
    return session_id


def _require_capture(client: HttpClient) -> dict[str, Any]:
    projection = client.json("GET", "/admin/events")
    status = projection.get("debug_status") or {}
    if not status.get("active"):
        raise ExperimentError("debug capture is not active; refusing a network phase")
    if status.get("writer_failure"):
        raise ExperimentError("debug capture writer is not healthy")
    if status.get("pending_records", 0):
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.1)
            projection = client.json("GET", "/admin/events")
            status = projection.get("debug_status") or {}
            if not status.get("active"):
                raise ExperimentError("debug capture stopped while waiting for its writer to drain")
            if status.get("writer_failure"):
                raise ExperimentError("debug capture writer failed while draining pending records")
            if not status.get("pending_records", 0):
                return projection
        raise ExperimentError("debug capture writer did not drain pending records within 5 seconds")
    return projection


def _activate_mode(client: HttpClient, mode: str) -> dict[str, Any]:
    if mode not in {"none", "semantic_ranges"}:
        raise ExperimentError(f"unsupported investigation mode {mode}")
    page_status, _, page_body = client.request("GET", "/admin/server")
    if page_status != 200:
        raise ExperimentError(f"GET /admin/server returned HTTP {page_status}")
    page = page_body.decode("utf-8")
    fields = _extract_form(page, "server-editor")
    field_name = "global_config.retrieval_assistance_mode"
    if field_name not in fields:
        raise ExperimentError("server admin form does not expose retrieval assistance mode")
    fields[field_name] = mode
    fields["action"] = "save_server"
    fields["return_page"] = "server"
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        client.base_url + "/admin/action",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise ExperimentError(f"saving {mode} configuration failed with HTTP {exc.code}") from exc
    page_status, _, page_body = client.request("GET", "/admin/server")
    if page_status != 200:
        raise ExperimentError("could not reload server admin page after saving configuration")
    _admin_post(client, page_body.decode("utf-8"), "validate", "server")
    page_status, _, page_body = client.request("GET", "/admin/server")
    if page_status != 200:
        raise ExperimentError("could not reload server admin page after validation")
    _admin_post(client, page_body.decode("utf-8"), "activate", "server")
    projection = client.json("GET", "/admin/events")
    if projection.get("retrieval_assistance_mode") != mode:
        raise ExperimentError(f"active configuration did not become {mode}")
    return projection


class ReadOnlyCorpus:
    def __init__(self, path: Path, revision_id: int):
        self.path = path.resolve()
        if not self.path.is_file():
            raise ExperimentError(f"EVW does not exist: {self.path}")
        try:
            self.connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            self.connection.row_factory = sqlite3.Row
            schema = self.connection.execute("SELECT version FROM schema_version").fetchone()
            if schema is None or int(schema[0]) != 15:
                raise ExperimentError("selected EVW is not schema v15")
            revision = self.connection.execute(
                "SELECT * FROM working_corpus_revision WHERE working_corpus_revision_id=?",
                (revision_id,),
            ).fetchone()
            if revision is None:
                raise ExperimentError(f"working-corpus revision {revision_id} does not exist")
            index = self.connection.execute(
                "SELECT * FROM working_corpus_revision_index WHERE working_corpus_revision_id=? ORDER BY index_generation DESC LIMIT 1",
                (revision_id,),
            ).fetchone()
            if revision[13] != "ready" or index is None or index[4] != "ready" or index[7] != "ready":
                raise ExperimentError(
                    f"revision {revision_id} is not ready for message embeddings: revision={revision[13]!r}, index={None if index is None else index[4]!r}, message_embedding={None if index is None else index[7]!r}"
                )
            cache = self.connection.execute("SELECT dimensions, normalization FROM embedding_cache_state WHERE cache_id=1").fetchone()
            if cache is None:
                raise ExperimentError("EVW has no embedding cache geometry")
            self.revision_id = revision_id
            self.index_generation = int(index[2])
            self.embedding_dimensions = int(cache[0])
            self.embedding_normalization = str(cache[1])
            self.messages = [
                dict(row)
                for row in self.connection.execute(
                    "SELECT m.message_id, m.source_thread_id AS thread_id, m.timestamp, m.sender_display AS sender, m.body AS text, r.ordinal, r.embedding_input_hash FROM working_corpus_revision_message r JOIN message m ON m.message_id=r.message_id WHERE r.working_corpus_revision_id=? ORDER BY r.ordinal",
                    (revision_id,),
                )
            ]
            if not self.messages:
                raise ExperimentError("selected working-corpus revision has no messages")
            self.by_id = {row["message_id"]: row for row in self.messages}
            if len(self.by_id) != len(self.messages):
                raise ExperimentError("selected working-corpus revision has duplicate message IDs")
        except sqlite3.Error as exc:
            raise ExperimentError(f"could not read EVW read-only: {exc}") from exc

    def close(self) -> None:
        self.connection.close()

    def verify_small_revision(self, revision_id: int) -> int:
        row = self.connection.execute(
            "SELECT r.status, i.status, i.message_embedding_status, COUNT(m.message_id) FROM working_corpus_revision r JOIN working_corpus_revision_index i ON i.working_corpus_revision_id=r.working_corpus_revision_id LEFT JOIN working_corpus_revision_message m ON m.working_corpus_revision_id=r.working_corpus_revision_id WHERE r.working_corpus_revision_id=? GROUP BY r.status, i.status, i.message_embedding_status",
            (revision_id,),
        ).fetchone()
        if row is None or row[0] != "ready" or row[1] != "ready" or row[2] != "ready":
            raise ExperimentError(f"small revision {revision_id} is missing or not ready")
        return int(row[3])

    def resolve_gold(self) -> list[dict[str, Any]]:
        resolved = []
        for event_date, thread_id, start_id, end_id in GOLD_RANGES:
            start = self.by_id.get(start_id)
            end = self.by_id.get(end_id)
            if start is None or end is None:
                raise ExperimentError(f"provisional gold endpoint is absent: {start_id} or {end_id}")
            if start["thread_id"] != thread_id or end["thread_id"] != thread_id:
                raise ExperimentError(f"provisional gold endpoint has the wrong thread: {start_id}/{end_id}")
            if int(start["ordinal"]) > int(end["ordinal"]):
                raise ExperimentError(f"provisional gold range is reversed in canonical order: {start_id}..{end_id}")
            resolved.append(
                {
                    "event_date": event_date,
                    "thread_id": thread_id,
                    "start_message_id": start_id,
                    "end_message_id": end_id,
                    "start_ordinal": int(start["ordinal"]),
                    "end_ordinal": int(end["ordinal"]),
                }
            )
        return resolved

    def vector_rows(self) -> Iterable[sqlite3.Row]:
        return self.connection.execute(
            "SELECT r.message_id, r.ordinal, r.embedding_input_hash, a.vector FROM working_corpus_revision_message r JOIN embedding_artifact a ON a.input_hash=r.embedding_input_hash WHERE r.working_corpus_revision_id=? ORDER BY r.ordinal",
            (self.revision_id,),
        )


def _unpack_vector(value: bytes, dimensions: int) -> tuple[float, ...]:
    if len(value) != dimensions * 4:
        raise ExperimentError("EVW embedding artifact geometry does not match embedding cache")
    return struct.unpack(f"<{dimensions}f", value)


def _distance(left: tuple[float, ...], right: tuple[float, ...], normalization: str) -> float:
    if normalization == "unit_l2":
        return max(0.0, 1.0 - sum(a * b for a, b in zip(left, right)))
    return sum((a - b) ** 2 for a, b in zip(left, right))


def _resolve_query_vectors(events: list[dict[str, Any]], query_ids: set[str]) -> dict[str, tuple[float, ...]]:
    vectors: dict[str, tuple[float, ...]] = {}
    for event in events:
        if event.get("event") != "vector_batch":
            continue
        for item in event.get("data", {}).get("items", []):
            message_id = item.get("message_id")
            if message_id in query_ids:
                if message_id in vectors:
                    raise ExperimentError(f"query embedding was returned twice: {message_id}")
                vectors[message_id] = tuple(float(value) for value in item["vector"])
    if vectors.keys() != query_ids:
        raise ExperimentError("query embedding workload did not return exactly the frozen query set")
    return vectors


def _local_candidates(corpus: ReadOnlyCorpus, plan: dict[str, Any], embedding_events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    query_ids = {query["query_id"] for query in plan["retrieval_queries"]}
    query_vectors = _resolve_query_vectors(embedding_events, query_ids)
    rows = []
    for row in corpus.vector_rows():
        rows.append((row["message_id"], int(row["ordinal"]), _unpack_vector(row["vector"], corpus.embedding_dimensions)))
    result: dict[str, list[dict[str, Any]]] = {}
    top_k = int(plan["search_policy"]["top_k_per_query"])
    for query in plan["retrieval_queries"]:
        query_vector = query_vectors[query["query_id"]]
        ordered = sorted(
            (
                (message_id, ordinal, _distance(query_vector, vector, corpus.embedding_normalization))
                for message_id, ordinal, vector in rows
            ),
            key=lambda item: (item[2], item[1], item[0]),
        )[:top_k]
        result[query["query_id"]] = [
            {"query_id": query["query_id"], "message_id": message_id, "rank": index, "distance": distance}
            for index, (message_id, _, distance) in enumerate(ordered, start=1)
        ]
    return result


def _raw_gold_overlap(candidates: dict[str, list[dict[str, Any]]], corpus: ReadOnlyCorpus, gold: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in gold:
        ranks: dict[str, int] = {}
        messages: dict[str, list[str]] = {}
        for query_id, values in candidates.items():
            for hit in values:
                row = corpus.by_id[hit["message_id"]]
                if row["thread_id"] == item["thread_id"] and item["start_ordinal"] <= int(row["ordinal"]) <= item["end_ordinal"]:
                    ranks[query_id] = min(ranks.get(query_id, hit["rank"]), hit["rank"])
                    messages.setdefault(query_id, []).append(hit["message_id"])
        output.append({**item, "best_raw_rank_by_query": ranks, "retrieved_by_query": messages, "retrieved": bool(ranks)})
    return output


def _flatten_candidates(candidates: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [hit for values in candidates.values() for hit in values]


def _selected_ids(candidates: dict[str, list[dict[str, Any]]], corpus: ReadOnlyCorpus, maximum: int, rrf_constant: int) -> list[str]:
    ordinal = {row["message_id"]: int(row["ordinal"]) for row in corpus.messages}
    aggregate: dict[str, dict[str, Any]] = {}
    for query_id, values in candidates.items():
        for hit in values:
            item = aggregate.setdefault(hit["message_id"], {"score": 0.0, "best_distance": float("inf"), "query_ids": []})
            item["score"] += 1.0 / (rrf_constant + int(hit["rank"]))
            item["best_distance"] = min(item["best_distance"], float(hit["distance"]))
            item["query_ids"].append(query_id)
    ordered = sorted(aggregate, key=lambda message_id: (-aggregate[message_id]["score"], aggregate[message_id]["best_distance"], ordinal[message_id], message_id))
    return ordered[:maximum]


def _gold_overlap_ids(selected_ids: list[str], corpus: ReadOnlyCorpus, gold: list[dict[str, Any]]) -> set[int]:
    overlaps: set[int] = set()
    for index, item in enumerate(gold):
        for message_id in selected_ids:
            row = corpus.by_id[message_id]
            if row["thread_id"] == item["thread_id"] and item["start_ordinal"] <= int(row["ordinal"]) <= item["end_ordinal"]:
                overlaps.add(index)
    return overlaps


def _analysis_context(plan: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "analysis_plan_id": plan["analysis_plan_id"],
        "plan_config_version": plan["config_version"],
        "compatibility_fingerprint": plan["compatibility_fingerprint"],
        "analysis_plan": plan["analysis_plan"],
        "retrieval_queries": plan["retrieval_queries"],
        "embedding": plan["embedding"],
        "search_policy": plan["search_policy"],
        "hits": hits,
    }


def _wire_corpus(corpus: ReadOnlyCorpus) -> list[dict[str, str]]:
    return [
        {
            "message_id": row["message_id"],
            "thread_id": row["thread_id"],
            "timestamp": row["timestamp"],
            "sender": row["sender"],
            "text": row["text"],
        }
        for row in corpus.messages
    ]


def _request_metadata(corpus: ReadOnlyCorpus, analysis_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": QUESTION,
        "scope_id": f"retrieval-investigation-revision-{corpus.revision_id}",
        "working_corpus_revision_id": corpus.revision_id,
        "message_count": len(corpus.messages),
        "analysis_context": analysis_context,
        "working_corpus_messages_omitted_from_artifact": True,
    }


def _event_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _arm_metrics(events: list[dict[str, Any]], gold: list[dict[str, Any]], corpus: ReadOnlyCorpus, selected_ids: list[str]) -> dict[str, Any]:
    if [event.get("sequence") for event in events] != list(range(1, len(events) + 1)):
        raise ExperimentError("arm stream sequence is not monotonic and exact")
    terminal = events[-1]
    result = terminal.get("result") if terminal.get("event") == "completed" else None
    final_ranges = []
    if result is not None:
        final_ranges = result.get("evidence_ledger", [])
    final_gold: set[int] = set()
    for index, item in enumerate(gold):
        for record in final_ranges:
            start = corpus.by_id.get(record.get("start_message_id"))
            end = corpus.by_id.get(record.get("end_message_id"))
            if start and end and start["thread_id"] == item["thread_id"] and end["thread_id"] == item["thread_id"] and int(start["ordinal"]) <= item["end_ordinal"] and int(end["ordinal"]) >= item["start_ordinal"]:
                final_gold.add(index)
                break
    diagnostics = result.get("retrieval_diagnostics", {}) if result else {}
    processing = result.get("ledger_processing", {}) if result else {}
    plan_event = next((event.get("data", {}) for event in events if event.get("event") == "window_plan_created"), {})
    attempts = sum(1 for event in events if event.get("event") in {"retry_wait", "queued"})
    started = [_event_timestamp(event["timestamp"]) for event in events if event.get("event") == "window_started"]
    completed = [_event_timestamp(event["timestamp"]) for event in events if event.get("event") == "window_completed"]
    return {
        "terminal_event": terminal.get("event"),
        "partial": terminal.get("event") != "completed" or (result or {}).get("completion_status") != "complete",
        "strategy": result.get("strategy") if result else None,
        "coverage": result.get("coverage") if result else None,
        "final_range_inventory": final_ranges,
        "provisional_gold_recall": {"found": sorted(final_gold), "count": len(final_gold), "total": len(gold)},
        "selected_suggestion_message_ids": selected_ids,
        "final_ranges_overlapping_suggestions": diagnostics.get("answer_relevant_ranges_overlapping_suggestions"),
        "final_ranges_outside_suggestions": diagnostics.get("answer_relevant_ranges_outside_suggestions"),
        "answer_ranges_overlapping_suggestions": diagnostics.get("answer_relevant_ranges_overlapping_suggestions"),
        "answer_ranges_outside_suggestions": diagnostics.get("answer_relevant_ranges_outside_suggestions"),
        "suggestions_without_final_evidence": diagnostics.get("suggestions_without_final_evidence"),
        "usage": result.get("usage") if result else None,
        "ledger_processing": processing,
        "window_plan_hash": plan_event.get("window_plan_hash"),
        "window_count": plan_event.get("window_count"),
        "window_durations_ms": [max(0.0, (end - start) * 1000) for start, end in zip(started, completed)],
        "provider_retry_or_queue_events": attempts,
    }


def _artifact_hashes(output_dir: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "manifest.json" and not path.name.startswith("."):
            hashes[path.name] = _sha256_bytes(path.read_bytes())
    return hashes


def _write_manifest(output_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["artifact_hashes"] = _artifact_hashes(output_dir)
    _atomic_json(output_dir / "manifest.json", manifest)


def _load_manifest(path: Path) -> tuple[Path, dict[str, Any]]:
    manifest = _read_json(path)
    if not isinstance(manifest, dict) or manifest.get("runner") != "QPA1-800":
        raise ExperimentError("manifest is not a QPA1-800 investigation manifest")
    output_dir = path.resolve().parent
    for name, expected in manifest.get("artifact_hashes", {}).items():
        artifact = output_dir / name
        if not artifact.is_file() or _sha256_bytes(artifact.read_bytes()) != expected:
            raise ExperimentError(f"artifact hash mismatch or missing artifact: {name}")
    return output_dir, manifest


def _prepare(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ExperimentError(f"output directory is not empty: {output_dir}")
    if args.question != QUESTION:
        raise ExperimentError("the investigation question is fixed by packet 09")
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus = ReadOnlyCorpus(Path(args.evw), args.working_corpus_revision_id)
    session_id = None
    client = HttpClient(args.server_url)
    try:
        small_count = corpus.verify_small_revision(DEFAULT_SMALL_REVISION_ID)
        session_id = _ensure_debug_capture(client)
        semantic_projection = _activate_mode(client, "semantic_ranges")
        _require_capture(client)
        plan = client.json(
            "POST",
            "/v1/conversational-plan",
            {"request_id": str(uuid.uuid4()), "question": QUESTION},
        )
        _require_capture(client)
        embedding_payload = {
            "request_id": str(uuid.uuid4()),
            "items": [{"message_id": query["query_id"], "text": query["text"]} for query in plan["retrieval_queries"]],
        }
        embedding_status, embedding_events = client.ndjson("/v1/embeddings", embedding_payload)
        if embedding_status != 200 or embedding_events[-1].get("event") != "completed":
            raise ExperimentError("query embedding workload did not complete")
        _require_capture(client)
        candidates = _local_candidates(corpus, plan, embedding_events)
        gold = corpus.resolve_gold()
        raw_overlap = _raw_gold_overlap(candidates, corpus, gold)
        metadata = {
            "runner": "QPA1-800",
            "prepared_at": _utc_now(),
            "evw": str(corpus.path),
            "working_corpus_revision_id": corpus.revision_id,
            "working_corpus_message_count": len(corpus.messages),
            "small_revision_id": DEFAULT_SMALL_REVISION_ID,
            "small_revision_message_count": small_count,
            "question": QUESTION,
            "server_url": args.server_url,
            "capture_session_id": session_id,
            "capture_started_projection": semantic_projection,
            "analysis_plan_id": plan.get("analysis_plan_id"),
        }
        _atomic_json(output_dir / "provisional-gold.json", gold)
        _atomic_json(output_dir / "analysis-plan.json", plan)
        accepted = next(event["data"] for event in embedding_events if event.get("event") == "accepted")
        vector_hashes = {
            item["message_id"]: _sha256_bytes(json.dumps(item["vector"], separators=(",", ":")).encode("utf-8"))
            for event in embedding_events if event.get("event") == "vector_batch"
            for item in event.get("data", {}).get("items", [])
        }
        _atomic_json(output_dir / "query-embedding-metadata.json", {"accepted": accepted, "completed": embedding_events[-1].get("result"), "query_vector_sha256": vector_hashes})
        _atomic_json(output_dir / "raw-candidates.json", {"search_policy": plan["search_policy"], "queries": candidates})
        _atomic_json(output_dir / "raw-gold-overlap.json", raw_overlap)
        manifest = {
            **metadata,
            "plan_identity": {key: plan[key] for key in ("analysis_plan_id", "config_version", "compatibility_fingerprint", "analysis_plan", "retrieval_queries", "embedding", "search_policy")},
            "arms": {},
            "capture": {"started_by_runner": True, "session_id": session_id, "stopped": False},
        }
        _write_manifest(output_dir, manifest)
    finally:
        corpus.close()


def _run_arm(args: argparse.Namespace) -> None:
    output_dir, manifest = _load_manifest(Path(args.manifest))
    if args.question != manifest["question"]:
        raise ExperimentError("arm question does not match the frozen manifest")
    client = HttpClient(manifest["server_url"])
    _require_capture(client)
    plan = _read_json(output_dir / "analysis-plan.json")
    corpus = ReadOnlyCorpus(Path(manifest["evw"]), int(manifest["working_corpus_revision_id"]))
    try:
        candidates = _read_json(output_dir / "raw-candidates.json")["retrieval_queries"]
        gold = _read_json(output_dir / "provisional-gold.json")
        if args.arm == "full-semantic":
            mode = "semantic_ranges"
            hits = _flatten_candidates(candidates)
            stem = "full-semantic"
        elif args.arm == "censored-semantic":
            mode = "semantic_ranges"
            raw_overlap = _read_json(output_dir / "raw-gold-overlap.json")
            if not any(item.get("retrieved") for item in raw_overlap):
                raise ExperimentError("censored-semantic is not eligible: the frozen raw pool overlaps no provisional positive")
            positive_ids = {
                hit["message_id"]
                for values in candidates.values()
                for hit in values
                if any(
                    corpus.by_id[hit["message_id"]]["thread_id"] == item["thread_id"]
                    and item["start_ordinal"] <= int(corpus.by_id[hit["message_id"]]["ordinal"]) <= item["end_ordinal"]
                    for item in gold
                )
            }
            censored: dict[str, list[dict[str, Any]]] = {}
            for query_id, values in candidates.items():
                remaining = [hit for hit in values if hit["message_id"] not in positive_ids]
                censored[query_id] = [{**hit, "rank": rank} for rank, hit in enumerate(remaining, start=1)]
            _atomic_json(output_dir / "censored-candidates.json", {"removed_positive_message_ids": sorted(positive_ids), "queries": censored})
            hits = _flatten_candidates(censored)
            stem = "censored-semantic"
        else:
            raise ExperimentError(f"unknown arm {args.arm}")
        projection = _activate_mode(client, mode)
        _require_capture(client)
        analysis_context = _analysis_context(plan, hits)
        request = {
            "request_id": str(uuid.uuid4()),
            "question": QUESTION,
            "working_corpus": {"scope_id": f"retrieval-investigation-revision-{corpus.revision_id}", "messages": _wire_corpus(corpus)},
            "analysis_context": analysis_context,
        }
        request_metadata = _request_metadata(corpus, analysis_context)
        _atomic_json(output_dir / f"{stem}-request.json", request_metadata)
        started = time.perf_counter()
        status, events = client.ndjson("/v1/conversational-analysis", request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if status != 200:
            raise ExperimentError(f"{args.arm} analysis returned HTTP {status}")
        candidate_map = {
            query_id: [dict(hit) for hit in hits if hit["query_id"] == query_id]
            for query_id in candidates
        }
        selected = _selected_ids(
            candidate_map,
            corpus,
            int(plan["search_policy"]["maximum_prompt_suggestion_messages"]),
            int(plan["search_policy"]["rrf_constant"]),
        )
        if args.arm == "censored-semantic" and _gold_overlap_ids(selected, corpus, gold):
            raise ExperimentError("censored-semantic selected a provisional-positive message")
        metrics = _arm_metrics(events, gold, corpus, selected)
        metrics["wall_time_ms"] = elapsed_ms
        metrics["mode_projection"] = {
            "active_config_version": projection.get("active_config_version"),
            "retrieval_assistance_mode": projection.get("retrieval_assistance_mode"),
            "mode_independent_configuration_fingerprint": projection.get("mode_independent_configuration_fingerprint"),
            "configuration_fingerprint": projection.get("configuration_fingerprint"),
        }
        result_artifact = {"events": events, "metrics": metrics}
        _atomic_json(output_dir / f"{stem}-result.json", result_artifact)
        if args.arm == "full-semantic":
            _atomic_json(output_dir / "full-selected-suggestions.json", {"message_ids": selected, "provisional_positive_overlap": sorted(_gold_overlap_ids(selected, corpus, gold))})
        elif args.arm == "censored-semantic":
            _atomic_json(output_dir / "censored-selected-suggestions.json", {"message_ids": selected, "provisional_positive_overlap": []})
        manifest["arms"][args.arm] = {"mode": mode, "request_artifact": f"{stem}-request.json", "result_artifact": f"{stem}-result.json", "metrics": metrics}
        _write_manifest(output_dir, manifest)
    finally:
        corpus.close()


def _comparison(manifest: dict[str, Any]) -> dict[str, Any]:
    arms = manifest.get("arms", {})
    reasons = []
    if "full-semantic" not in arms:
        reasons.append("full-semantic arm is required")
    plan_identity = manifest.get("plan_identity", {})
    for arm_name, arm in arms.items():
        metrics = arm.get("metrics", {})
        if metrics.get("partial"):
            reasons.append(f"{arm_name} returned a partial or failed result")
        if metrics.get("window_plan_hash") is None:
            reasons.append(f"{arm_name} did not expose a window-plan hash")
    fingerprints = {arm.get("metrics", {}).get("mode_projection", {}).get("mode_independent_configuration_fingerprint") for arm in arms.values()}
    if len(fingerprints - {None}) > 1:
        reasons.append("arm configurations differ beyond retrieval-assistance mode")
    hashes = {arm.get("metrics", {}).get("window_plan_hash") for arm in arms.values() if arm.get("metrics", {}).get("window_plan_hash")}
    if len(hashes) > 1:
        reasons.append("window-plan hashes differ across arms")
    return {
        "valid_apples_to_apples_quality_comparison": not reasons,
        "reasons": reasons,
        "question": manifest.get("question"),
        "analysis_plan_id": plan_identity.get("analysis_plan_id"),
        "compatibility_fingerprint": plan_identity.get("compatibility_fingerprint"),
        "embedding": plan_identity.get("embedding"),
        "arms": {name: {"strategy": value.get("metrics", {}).get("strategy"), "recall": value.get("metrics", {}).get("provisional_gold_recall"), "outside_suggestion_ranges": value.get("metrics", {}).get("final_ranges_outside_suggestions"), "ledger_processing": value.get("metrics", {}).get("ledger_processing"), "window_plan_hash": value.get("metrics", {}).get("window_plan_hash")} for name, value in arms.items()},
    }


def _comparison_markdown(comparison: dict[str, Any], manifest: dict[str, Any]) -> str:
    display_names = {
        "full-semantic": "semantic_ranges",
        "censored-semantic": "semantic_ranges_censored",
    }
    queries = manifest.get("plan_identity", {}).get("retrieval_queries", [])
    lines = [
        "# Retrieval hint investigation",
        "",
        "Diagnostic comparison; this is not a statistical benchmark.",
        "",
        f"- Question: `{manifest.get('question')}`",
        f"- Frozen retrieval queries: `{', '.join(str(query.get('text', '')) for query in queries)}`",
        f"- Apples-to-apples validity: **{comparison['valid_apples_to_apples_quality_comparison']}**",
    ]
    if comparison["reasons"]:
        lines.extend(["- Validity reasons:", *[f"  - {reason}" for reason in comparison["reasons"]]])
    lines.extend(["", "| Arm | Strategy | Gold recall | Outside-suggestion final ranges | Window hash |", "|---|---|---:|---:|---|"])
    for name, value in comparison["arms"].items():
        recall = value.get("recall") or {}
        lines.append(f"| {display_names.get(name, name)} | {value.get('strategy')} | {recall.get('count', 0)}/{recall.get('total', 0)} | {value.get('outside_suggestion_ranges')} | `{value.get('window_plan_hash')}` |")
    lines.extend(["", "## Exact returned results", ""])
    for name, arm in manifest.get("arms", {}).items():
        artifact = (
            _read_json(Path(manifest["output_dir"]) / arm["result_artifact"])
            if manifest.get("output_dir")
            else None
        )
        lines.append(f"### {display_names.get(name, name)}")
        if not artifact:
            lines.extend(["", "Result artifact is unavailable.", ""])
            continue
        events = artifact.get("events", [])
        terminal = events[-1] if events else {}
        if terminal.get("event") != "completed":
            lines.extend(
                [
                    "",
                    "The arm failed without a synthesized answer.",
                    "",
                    "````json",
                    json.dumps(terminal.get("error", terminal), indent=2, ensure_ascii=False),
                    "````",
                    "",
                ]
            )
            continue
        result = terminal["result"]
        lines.extend(
            [
                "",
                "#### Synthesized overview",
                "",
                "````text",
                str(result.get("overview") or result.get("raw_answer") or ""),
                "````",
                "",
                "#### Structured overview",
                "",
                "````text",
                str(result.get("overview") or ""),
                "````",
                "",
                "#### Complete returned evidence ledger",
                "",
                "````json",
                json.dumps(result["evidence_ledger"], indent=2, ensure_ascii=False),
                "````",
                "",
                "#### Diagnostics, processing, coverage, and usage",
                "",
                "````json",
                json.dumps(
                    {
                        "strategy": result["strategy"],
                        "uncertainties": result["uncertainties"],
                        "coverage": result["coverage"],
                        "retrieval_diagnostics": result["retrieval_diagnostics"],
                        "ledger_processing": result["ledger_processing"],
                        "usage": result["usage"],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                "````",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _report(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest).resolve()
    output_dir, manifest = _load_manifest(manifest_path)
    manifest["output_dir"] = str(output_dir)
    comparison = _comparison(manifest)
    _atomic_json(output_dir / "comparison.json", comparison)
    _atomic_text(output_dir / "comparison.md", _comparison_markdown(comparison, manifest))
    client = HttpClient(manifest["server_url"])
    capture_status = client.json("GET", "/admin/events")
    if (capture_status.get("debug_status") or {}).get("active"):
        _require_capture(client)
        page_status, _, page_body = client.request("GET", "/admin/debug")
        if page_status != 200:
            raise ExperimentError("could not open debug admin page while stopping capture")
        _admin_post(client, page_body.decode("utf-8"), "stop_debug_capture", "debug")
    final_projection = client.json("GET", "/admin/events")
    manifest["capture"]["stopped"] = not (final_projection.get("debug_status") or {}).get("active", False)
    manifest["capture"]["final_debug_status"] = final_projection.get("debug_status")
    manifest["comparison_artifacts"] = ["comparison.json", "comparison.md"]
    _write_manifest(output_dir, manifest)
    print(json.dumps(comparison, indent=2, ensure_ascii=False))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--evw", required=True)
    prepare.add_argument("--working-corpus-revision-id", required=True, type=int)
    prepare.add_argument("--server-url", required=True)
    prepare.add_argument("--question", required=True)
    prepare.add_argument("--output-dir", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--manifest", required=True)
    run.add_argument("--arm", choices=("full-semantic", "censored-semantic"), required=True)
    run.set_defaults(question=QUESTION)
    report = subparsers.add_parser("report")
    report.add_argument("--manifest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            _prepare(args)
        elif args.command == "run":
            _run_arm(args)
        elif args.command == "report":
            _report(args)
        else:
            raise ExperimentError(f"unknown command {args.command}")
        return 0
    except ExperimentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
