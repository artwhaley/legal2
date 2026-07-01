"""sqlite-vec backend: load, tables, search."""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from message_evidence_workstation.logging_ui.process_log import ProcessLogger, utc_now_iso

MESSAGE_VEC_TABLE = "message_embedding_vec"
CHUNK_VEC_TABLE = "chunk_embedding_vec"

CHUNK_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS message_chunk (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    source_thread_id TEXT NOT NULL,
    start_message_id TEXT NOT NULL,
    end_message_id TEXT NOT NULL,
    message_count INTEGER NOT NULL,
    char_count INTEGER NOT NULL,
    text_checksum TEXT NOT NULL,
    body_text TEXT NOT NULL,
    FOREIGN KEY (dataset_id) REFERENCES dataset(dataset_id)
);

CREATE INDEX IF NOT EXISTS idx_message_chunk_dataset
    ON message_chunk(dataset_id, source_thread_id);
"""


@dataclass(slots=True)
class SqliteVecValidationResult:
    success: bool
    message: str
    details: dict[str, Any]


@dataclass(slots=True)
class VectorSearchHit:
    message_id: str
    source_thread_id: str
    distance: float
    rank: int
    chunk_id: int | None = None
    start_message_id: str | None = None
    end_message_id: str | None = None


def _import_sqlite_vec():
    try:
        import sqlite_vec  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("sqlite-vec Python package is not installed") from exc
    return sqlite_vec


def load_sqlite_vec(conn: sqlite3.Connection, extension_path: str | None = None) -> str:
    sqlite_vec = _import_sqlite_vec()
    if extension_path:
        sqlite_vec.load(conn, extension_path)
        return extension_path
    sqlite_vec.load(conn)
    return "auto"


def sqlite_vec_version() -> str:
    sqlite_vec = _import_sqlite_vec()
    if hasattr(sqlite_vec, "version"):
        return str(sqlite_vec.version())
    return ""


def ensure_chunk_metadata_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(CHUNK_METADATA_DDL)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _table_dimensions(conn: sqlite3.Connection, table_name: str) -> int | None:
    if not _table_exists(conn, table_name):
        return None
    row = conn.execute(f"SELECT sql FROM sqlite_master WHERE name = ?", (table_name,)).fetchone()
    if row is None or not row[0]:
        return None
    sql = row[0]
    marker = "FLOAT["
    start = sql.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = sql.find("]", start)
    if end < 0:
        return None
    try:
        return int(sql[start:end])
    except ValueError:
        return None


def _table_sql(conn: sqlite3.Connection, table_name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = ?",
        (table_name,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _vec_table_has_model_partition(conn: sqlite3.Connection, table_name: str) -> bool:
    sql = _table_sql(conn, table_name).lower()
    return "model_name" in sql and "partition key" in sql


def count_message_vectors(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    model_name: str | None = None,
) -> int:
    if not _table_exists(conn, MESSAGE_VEC_TABLE):
        return 0
    load_sqlite_vec(conn)
    if model_name and _vec_table_has_model_partition(conn, MESSAGE_VEC_TABLE):
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM {MESSAGE_VEC_TABLE} WHERE dataset_id = ? AND model_name = ?",
                (dataset_id, model_name),
            ).fetchone()[0]
        )
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {MESSAGE_VEC_TABLE} WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
    )


def count_chunk_vectors(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    model_name: str | None = None,
) -> int:
    if not _table_exists(conn, CHUNK_VEC_TABLE):
        return 0
    load_sqlite_vec(conn)
    if model_name and _vec_table_has_model_partition(conn, CHUNK_VEC_TABLE):
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM {CHUNK_VEC_TABLE} WHERE dataset_id = ? AND model_name = ?",
                (dataset_id, model_name),
            ).fetchone()[0]
        )
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {CHUNK_VEC_TABLE} WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
    )


def _metadata_model_name(
    conn: sqlite3.Connection,
    dataset_id: int,
    granularity: str,
) -> str:
    row = conn.execute(
        """
        SELECT model_name
        FROM embedding_index_metadata
        WHERE dataset_id = ? AND granularity = ?
        ORDER BY embedding_index_id DESC
        LIMIT 1
        """,
        (dataset_id, granularity),
    ).fetchone()
    return str(row["model_name"]) if row and row["model_name"] else "legacy"


def migrate_legacy_vec_tables_to_partitions(conn: sqlite3.Connection, logger: Any) -> None:
    """Rebuild pre-v11 vec tables with model_name partition keys."""
    needs_message_migration = _table_exists(conn, MESSAGE_VEC_TABLE) and not _vec_table_has_model_partition(
        conn, MESSAGE_VEC_TABLE
    )
    needs_chunk_migration = _table_exists(conn, CHUNK_VEC_TABLE) and not _vec_table_has_model_partition(
        conn, CHUNK_VEC_TABLE
    )
    if not needs_message_migration and not needs_chunk_migration:
        return

    load_sqlite_vec(conn)
    if needs_message_migration:
        dimensions = _table_dimensions(conn, MESSAGE_VEC_TABLE)
        if dimensions is None:
            conn.execute(f"DROP TABLE IF EXISTS {MESSAGE_VEC_TABLE}")
        else:
            rows = conn.execute(
                f"""
                SELECT message_id, dataset_id, source_thread_id, embedding
                FROM {MESSAGE_VEC_TABLE}
                """
            ).fetchall()
            by_dataset: dict[int, list[tuple]] = {}
            for row in rows:
                by_dataset.setdefault(int(row["dataset_id"]), []).append(row)
            conn.execute(f"DROP TABLE IF EXISTS {MESSAGE_VEC_TABLE}")
            ensure_message_vec_table(conn, dimensions)
            for dataset_id, dataset_rows in by_dataset.items():
                model_name = _metadata_model_name(conn, dataset_id, "message")
                payload = [
                    (
                        list(_deserialize_float32_vector(bytes(row["embedding"]))),
                        str(row["message_id"]),
                        dataset_id,
                        str(row["source_thread_id"]),
                    )
                    for row in dataset_rows
                ]
                if payload:
                    insert_message_vectors(conn, payload, model_name=model_name)
            logger.info(
                component="embeddings.sqlite_vec_backend",
                operation="migrate_message_vec_partitions",
                message="Migrated message embedding vec table to model partitions",
                details={"row_count": len(rows), "dimensions": dimensions},
            )

    if needs_chunk_migration:
        dimensions = _table_dimensions(conn, CHUNK_VEC_TABLE)
        if dimensions is None:
            conn.execute(f"DROP TABLE IF EXISTS {CHUNK_VEC_TABLE}")
        else:
            rows = conn.execute(
                f"""
                SELECT chunk_id, dataset_id, source_thread_id, embedding
                FROM {CHUNK_VEC_TABLE}
                """
            ).fetchall()
            by_dataset = {}
            for row in rows:
                by_dataset.setdefault(int(row["dataset_id"]), []).append(row)
            conn.execute(f"DROP TABLE IF EXISTS {CHUNK_VEC_TABLE}")
            ensure_chunk_vec_table(conn, dimensions)
            for dataset_id, dataset_rows in by_dataset.items():
                model_name = _metadata_model_name(conn, dataset_id, "chunk")
                payload = [
                    (
                        list(_deserialize_float32_vector(bytes(row["embedding"]))),
                        int(row["chunk_id"]),
                        dataset_id,
                        str(row["source_thread_id"]),
                    )
                    for row in dataset_rows
                ]
                if payload:
                    insert_chunk_vectors(conn, payload, model_name=model_name)
            logger.info(
                component="embeddings.sqlite_vec_backend",
                operation="migrate_chunk_vec_partitions",
                message="Migrated chunk embedding vec table to model partitions",
                details={"row_count": len(rows), "dimensions": dimensions},
            )
    conn.commit()


def _deserialize_float32_vector(blob: bytes) -> tuple[float, ...]:
    import struct

    if not blob:
        return ()
    dimensions = len(blob) // 4
    if dimensions <= 0:
        return ()
    return struct.unpack(f"<{dimensions}f", blob[: dimensions * 4])


def ensure_message_vec_table(conn: sqlite3.Connection, dimensions: int) -> None:
    existing = _table_dimensions(conn, MESSAGE_VEC_TABLE)
    if existing is not None and existing != dimensions:
        conn.execute(f"DROP TABLE IF EXISTS {MESSAGE_VEC_TABLE}")
    if not _table_exists(conn, MESSAGE_VEC_TABLE):
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE {MESSAGE_VEC_TABLE} USING vec0(
                embedding FLOAT[{dimensions}],
                model_name text partition key,
                +message_id TEXT,
                +dataset_id INTEGER,
                +source_thread_id TEXT
            )
            """
        )
    conn.commit()


def ensure_chunk_vec_table(conn: sqlite3.Connection, dimensions: int) -> None:
    existing = _table_dimensions(conn, CHUNK_VEC_TABLE)
    if existing is not None and existing != dimensions:
        conn.execute(f"DROP TABLE IF EXISTS {CHUNK_VEC_TABLE}")
    if not _table_exists(conn, CHUNK_VEC_TABLE):
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE {CHUNK_VEC_TABLE} USING vec0(
                embedding FLOAT[{dimensions}],
                model_name text partition key,
                +chunk_id INTEGER,
                +dataset_id INTEGER,
                +source_thread_id TEXT
            )
            """
        )
    conn.commit()


def clear_message_vectors(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    model_name: str | None = None,
) -> None:
    if not _table_exists(conn, MESSAGE_VEC_TABLE):
        return
    if model_name and _vec_table_has_model_partition(conn, MESSAGE_VEC_TABLE):
        conn.execute(
            f"DELETE FROM {MESSAGE_VEC_TABLE} WHERE dataset_id = ? AND model_name = ?",
            (dataset_id, model_name),
        )
    else:
        conn.execute(f"DELETE FROM {MESSAGE_VEC_TABLE} WHERE dataset_id = ?", (dataset_id,))
    conn.commit()


def clear_chunk_vectors(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    model_name: str | None = None,
) -> None:
    ensure_chunk_metadata_schema(conn)
    if _table_exists(conn, CHUNK_VEC_TABLE):
        if model_name and _vec_table_has_model_partition(conn, CHUNK_VEC_TABLE):
            conn.execute(
                f"DELETE FROM {CHUNK_VEC_TABLE} WHERE dataset_id = ? AND model_name = ?",
                (dataset_id, model_name),
            )
        else:
            conn.execute(f"DELETE FROM {CHUNK_VEC_TABLE} WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM message_chunk WHERE dataset_id = ?", (dataset_id,))
    conn.commit()


def insert_message_vectors(
    conn: sqlite3.Connection,
    rows: list[tuple[list[float], str, int, str]],
    *,
    model_name: str,
) -> None:
    sqlite_vec = _import_sqlite_vec()
    has_partition = _vec_table_has_model_partition(conn, MESSAGE_VEC_TABLE)
    if has_partition:
        conn.executemany(
            f"""
            INSERT INTO {MESSAGE_VEC_TABLE} (
                embedding, model_name, message_id, dataset_id, source_thread_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    sqlite_vec.serialize_float32(vector),
                    model_name,
                    message_id,
                    dataset_id,
                    source_thread_id,
                )
                for vector, message_id, dataset_id, source_thread_id in rows
            ],
        )
        return
    conn.executemany(
        f"""
        INSERT INTO {MESSAGE_VEC_TABLE} (
            embedding, message_id, dataset_id, source_thread_id
        ) VALUES (?, ?, ?, ?)
        """,
        [
            (sqlite_vec.serialize_float32(vector), message_id, dataset_id, source_thread_id)
            for vector, message_id, dataset_id, source_thread_id in rows
        ],
    )


def insert_chunk_vectors(
    conn: sqlite3.Connection,
    rows: list[tuple[list[float], int, int, str]],
    *,
    model_name: str,
) -> None:
    sqlite_vec = _import_sqlite_vec()
    has_partition = _vec_table_has_model_partition(conn, CHUNK_VEC_TABLE)
    if has_partition:
        conn.executemany(
            f"""
            INSERT INTO {CHUNK_VEC_TABLE} (
                embedding, model_name, chunk_id, dataset_id, source_thread_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    sqlite_vec.serialize_float32(vector),
                    model_name,
                    chunk_id,
                    dataset_id,
                    source_thread_id,
                )
                for vector, chunk_id, dataset_id, source_thread_id in rows
            ],
        )
        return
    conn.executemany(
        f"""
        INSERT INTO {CHUNK_VEC_TABLE} (
            embedding, chunk_id, dataset_id, source_thread_id
        ) VALUES (?, ?, ?, ?)
        """,
        [
            (sqlite_vec.serialize_float32(vector), chunk_id, dataset_id, source_thread_id)
            for vector, chunk_id, dataset_id, source_thread_id in rows
        ],
    )


def vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def search_message_vectors(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    query_vector: list[float],
    model_name: str,
    top_k: int = 20,
) -> list[VectorSearchHit]:
    if not _table_exists(conn, MESSAGE_VEC_TABLE):
        raise RuntimeError("Message embedding index table is missing")
    load_sqlite_vec(conn)
    sqlite_vec = _import_sqlite_vec()
    started = time.perf_counter()
    # vec0 auxiliary columns cannot appear in KNN WHERE; oversample then filter.
    oversample = max(top_k * 10, 50)
    partition_clause = " AND model_name = ?" if _vec_table_has_model_partition(conn, MESSAGE_VEC_TABLE) else ""
    params: list[Any] = [sqlite_vec.serialize_float32(query_vector), oversample]
    if partition_clause:
        params.append(model_name)
    rows = conn.execute(
        f"""
        SELECT message_id, source_thread_id, distance, dataset_id
        FROM {MESSAGE_VEC_TABLE}
        WHERE embedding MATCH ?
          AND k = ?{partition_clause}
        ORDER BY distance
        """,
        tuple(params),
    ).fetchall()
    rows = [row for row in rows if int(row["dataset_id"]) == dataset_id][:top_k]
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    hits = [
        VectorSearchHit(
            message_id=row["message_id"],
            source_thread_id=row["source_thread_id"],
            distance=float(row["distance"]),
            rank=index + 1,
        )
        for index, row in enumerate(rows)
    ]
    logger.info(
        component="embeddings.sqlite_vec_backend",
        operation="message_vector_query",
        message="Message vector search completed",
        details={
            "dataset_id": dataset_id,
            "model_name": model_name,
            "dimensions": len(query_vector),
            "query_vector_norm": vector_norm(query_vector),
            "top_k_requested": top_k,
            "top_k_returned": len(hits),
            "distances": [hit.distance for hit in hits[:10]],
            "message_ids": [hit.message_id for hit in hits[:10]],
            "elapsed_ms": elapsed_ms,
        },
        dataset_id=dataset_id,
    )
    return hits


def search_chunk_vectors(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int,
    query_vector: list[float],
    model_name: str,
    top_k: int = 20,
) -> list[VectorSearchHit]:
    if not _table_exists(conn, CHUNK_VEC_TABLE):
        raise RuntimeError("Chunk embedding index table is missing")
    load_sqlite_vec(conn)
    sqlite_vec = _import_sqlite_vec()
    started = time.perf_counter()
    oversample = max(top_k * 10, 50)
    partition_clause = " AND model_name = ?" if _vec_table_has_model_partition(conn, CHUNK_VEC_TABLE) else ""
    params: list[Any] = [sqlite_vec.serialize_float32(query_vector), oversample]
    if partition_clause:
        params.append(model_name)
    rows = conn.execute(
        f"""
        SELECT chunk_id, source_thread_id, distance, dataset_id
        FROM {CHUNK_VEC_TABLE}
        WHERE embedding MATCH ?
          AND k = ?{partition_clause}
        ORDER BY distance
        """,
        tuple(params),
    ).fetchall()
    rows = [row for row in rows if int(row["dataset_id"]) == dataset_id][:top_k]
    chunk_meta: dict[int, tuple[str, str]] = {}
    if rows:
        placeholders = ",".join("?" for _ in rows)
        meta_rows = conn.execute(
            f"""
            SELECT chunk_id, start_message_id, end_message_id
            FROM message_chunk
            WHERE chunk_id IN ({placeholders})
            """,
            [int(row["chunk_id"]) for row in rows],
        ).fetchall()
        chunk_meta = {
            int(meta["chunk_id"]): (meta["start_message_id"], meta["end_message_id"])
            for meta in meta_rows
        }
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    hits: list[VectorSearchHit] = []
    for index, row in enumerate(rows):
        chunk_id = int(row["chunk_id"])
        start_id, end_id = chunk_meta.get(chunk_id, (row["source_thread_id"], row["source_thread_id"]))
        hits.append(
            VectorSearchHit(
                message_id=start_id,
                source_thread_id=row["source_thread_id"],
                distance=float(row["distance"]),
                rank=index + 1,
                chunk_id=chunk_id,
                start_message_id=start_id,
                end_message_id=end_id,
            )
        )
    logger.info(
        component="embeddings.sqlite_vec_backend",
        operation="chunk_vector_query",
        message="Chunk vector search completed",
        details={
            "dataset_id": dataset_id,
            "model_name": model_name,
            "dimensions": len(query_vector),
            "query_vector_norm": vector_norm(query_vector),
            "top_k_requested": top_k,
            "top_k_returned": len(hits),
            "distances": [hit.distance for hit in hits[:10]],
            "chunk_ids": [hit.chunk_id for hit in hits[:10]],
            "elapsed_ms": elapsed_ms,
        },
        dataset_id=dataset_id,
    )
    return hits


def validate_sqlite_vec(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dimensions: int = 4,
    extension_path: str | None = None,
) -> SqliteVecValidationResult:
    details: dict[str, Any] = {
        "dimensions": dimensions,
        "extension_path": extension_path,
        "sqlite_version": sqlite3.sqlite_version,
    }
    logger.info(
        component="embeddings.sqlite_vec_backend",
        operation="validate_start",
        message="Starting sqlite-vec validation",
        details=details,
    )
    try:
        path = load_sqlite_vec(conn, extension_path)
        details["extension_path"] = path
        details["sqlite_vec_version"] = sqlite_vec_version()

        conn.execute("DROP TABLE IF EXISTS vec_validation_smoke")
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE vec_validation_smoke USING vec0(
                sample_id INTEGER PRIMARY KEY,
                embedding FLOAT[{dimensions}]
            )
            """
        )
        sqlite_vec = _import_sqlite_vec()
        vector = [0.1, 0.2, 0.3, 0.4][:dimensions]
        conn.execute(
            "INSERT INTO vec_validation_smoke(sample_id, embedding) VALUES (?, ?)",
            (1, sqlite_vec.serialize_float32(vector)),
        )
        row = conn.execute(
            """
            SELECT sample_id, distance
            FROM vec_validation_smoke
            WHERE embedding MATCH ?
              AND k = 1
            ORDER BY distance
            """,
            (sqlite_vec.serialize_float32(vector),),
        ).fetchone()
        if row is None or int(row[0]) != 1:
            raise RuntimeError(f"Unexpected nearest-neighbor result: {row}")
        details["nearest_neighbor_id"] = int(row[0])
        details["nearest_neighbor_distance"] = float(row[1])
        conn.execute("DROP TABLE IF EXISTS vec_validation_smoke")
        conn.commit()

        result = SqliteVecValidationResult(
            success=True,
            message="sqlite-vec validation succeeded",
            details=details,
        )
        logger.info(
            component="embeddings.sqlite_vec_backend",
            operation="validate_success",
            message=result.message,
            details=result.details,
        )
        return result
    except Exception as exc:
        conn.rollback()
        result = SqliteVecValidationResult(
            success=False,
            message=f"sqlite-vec validation failed: {exc}",
            details={**details, "error": str(exc)},
        )
        logger.error(
            component="embeddings.sqlite_vec_backend",
            operation="validate_failed",
            message=result.message,
            details=result.details,
            exc=exc,
        )
        return result


def record_validation_status(
    conn: sqlite3.Connection,
    logger: ProcessLogger,
    *,
    dataset_id: int | None,
    result: SqliteVecValidationResult,
) -> None:
    conn.execute(
        """
        INSERT INTO embedding_index_metadata (
            dataset_id, granularity, backend, model_name, created_at, status, last_error,
            sqlite_vec_version, extension_path
        ) VALUES (?, 'validation', 'sqlite_vec', '', ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            utc_now_iso(),
            "ready" if result.success else "failed",
            "" if result.success else result.message,
            str(result.details.get("sqlite_vec_version", "")),
            str(result.details.get("extension_path", "")),
        ),
    )
    conn.commit()
    logger.info(
        component="embeddings.sqlite_vec_backend",
        operation="validation_status_recorded",
        message="Recorded sqlite-vec validation status",
        details={"success": result.success},
        dataset_id=dataset_id,
    )
