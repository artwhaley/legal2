"""Thread-owned EVW access with one writer and short-lived read transactions."""

from __future__ import annotations

import queue
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

from message_evidence_workstation.db.schema import CREATE_TABLES_SQL
from message_evidence_workstation.db.migrations import validate_v15_shape
from message_evidence_workstation.db.workspace_lock import WorkspaceFileLock
from message_evidence_workstation.domain.constants import SCHEMA_VERSION
from message_evidence_workstation.logging_ui.diagnostic_logger import DiagnosticLogger, utc_now_iso

T = TypeVar("T")


class WorkspaceStoreError(RuntimeError):
    pass


def _connect_writer(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA wal_autocheckpoint = 1000")
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        pass
    return conn


def _connect_reader(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        pass
    return conn


class WorkspaceStore:
    """The only runtime owner of an EVW write connection."""

    def __init__(self, path: Path, logger: DiagnosticLogger) -> None:
        self.path = path.resolve()
        self.logger = logger
        self._lock = WorkspaceFileLock(self.path)
        self._tasks: queue.Queue[tuple[Callable[[sqlite3.Connection], Any], threading.Event, list[Any]]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closed = False
        self._startup_error: BaseException | None = None
        self._shutdown_error: BaseException | None = None
        self._write_count = 0

    def open(self, *, create: bool = True, display_name: str | None = None) -> "WorkspaceStore":
        if self._thread is not None:
            raise WorkspaceStoreError("WorkspaceStore.open called twice")
        if not self.path.exists() and not create:
            raise WorkspaceStoreError(f"Workspace file not found: {self.path}")
        self._lock.acquire()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._writer_loop, name="evw-writer", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._startup_error is not None:
            self._lock.release()
            raise WorkspaceStoreError(str(self._startup_error)) from self._startup_error
        if display_name and not self.read(self._metadata_value, "display_name"):
            self.write(self._set_metadata, "display_name", display_name)
        return self

    def _writer_loop(self) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = _connect_writer(self.path)
            exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
            if exists is None:
                conn.executescript(CREATE_TABLES_SQL)
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
                now = utc_now_iso()
                conn.executemany(
                    "INSERT INTO workspace_state(key,value) VALUES (?,?)",
                    [("format_id", "message_evidence_workstation.evw"), ("format_version", "1"), ("created_at", now), ("updated_at", now), ("workspace_open", "0")],
                )
                conn.commit()
            else:
                version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                if version is None or int(version[0]) != SCHEMA_VERSION:
                    raise WorkspaceStoreError(
                        f"EVW schema is {version[0] if version else 'missing'}; runtime requires v{SCHEMA_VERSION}. "
                        "Run python -m message_evidence_workstation.tools.migrate_evw <file>."
                    )
                validate_v15_shape(conn)
                quick = conn.execute("PRAGMA quick_check").fetchone()
                if quick is None or str(quick[0]) != "ok":
                    raise WorkspaceStoreError(f"EVW quick_check failed: {quick[0] if quick else 'no result'}")
                foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
                if foreign:
                    raise WorkspaceStoreError(f"EVW foreign_key_check found {len(foreign)} violation(s)")
                open_marker = conn.execute("SELECT value FROM workspace_state WHERE key='workspace_open'").fetchone()
                checkpoint = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                if open_marker is not None and str(open_marker[0]) == "1":
                    self.logger.warning(
                        component="db.workspace",
                        operation="startup_recovery",
                        message="Previous EVW close was not clean; recovered committed WAL and is truncating it",
                        details={"checkpoint": tuple(checkpoint or ())},
                    )
                truncated = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if truncated is not None and int(truncated[0]) != 0:
                    raise WorkspaceStoreError(f"WAL checkpoint busy during startup: {tuple(truncated)}")
            conn.execute("UPDATE workspace_state SET value='1' WHERE key='workspace_open'")
            conn.commit()
        except BaseException as exc:
            self._startup_error = exc
        finally:
            self._ready.set()
        if self._startup_error is not None:
            if conn is not None:
                conn.close()
            return
        assert conn is not None
        try:
            while True:
                fn, done, result = self._tasks.get()
                if fn is None:  # type: ignore[comparison-overlap]
                    done.set()
                    break
                try:
                    result.append(fn(conn))
                    conn.commit()
                    self._write_count += 1
                    if self._write_count % 32 == 0:
                        conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                except BaseException as exc:
                    conn.rollback()
                    result.append(exc)
                finally:
                    done.set()
        finally:
            try:
                conn.execute("UPDATE workspace_state SET value='0' WHERE key='workspace_open'")
                conn.commit()
                checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint is not None and int(checkpoint[0]) != 0:
                    raise WorkspaceStoreError(f"WAL checkpoint busy at close: {tuple(checkpoint)}")
            except BaseException as exc:
                self._shutdown_error = exc
            finally:
                conn.close()

    def _call(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        if self._closed or self._thread is None:
            raise WorkspaceStoreError("WorkspaceStore is closed")
        done = threading.Event()
        result: list[Any] = []
        self._tasks.put((fn, done, result))
        done.wait()
        if result and isinstance(result[0], BaseException):
            raise result[0]
        return result[0] if result else None  # type: ignore[return-value]

    def write(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return self._call(lambda conn: fn(conn, *args, **kwargs))

    def read(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if self._closed or self._thread is None:
            raise WorkspaceStoreError("WorkspaceStore is closed")
        conn = _connect_reader(self.path)
        try:
            conn.execute("BEGIN")
            result = fn(conn, *args, **kwargs)
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def checkpoint(self) -> tuple[int, int, int]:
        return self.write(lambda conn: tuple(conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()))  # type: ignore[return-value]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._thread is not None:
            done = threading.Event()
            result: list[Any] = []
            self._tasks.put((None, done, result))  # type: ignore[arg-type]
            done.wait()
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                self._closed = False
                raise WorkspaceStoreError("EVW writer thread did not stop during clean close")
        self._lock.release()
        if self._shutdown_error is not None:
            raise WorkspaceStoreError(str(self._shutdown_error)) from self._shutdown_error

    @staticmethod
    def _metadata_value(conn: sqlite3.Connection, key: str) -> str:
        row = conn.execute("SELECT value FROM workspace_state WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else ""

    @staticmethod
    def _set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO workspace_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.execute("UPDATE workspace_state SET value=? WHERE key='updated_at'", (utc_now_iso(),))

    def __enter__(self) -> "WorkspaceStore":
        return self.open()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
