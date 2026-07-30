"""Explicit, temporary, server-side capture of exact development traffic."""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


_SESSION_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CaptureSession:
    session_id: str
    path: Path
    started_at: str
    subject_account_id: str | None


class DebugCaptureManager:
    """Own capture state and one ordered JSONL writer.

    Product requests bind to the active session at ingress. Stopping capture
    prevents new bindings; requests already bound continue through their
    terminal response so a captured trace is internally coherent.
    """

    def __init__(
        self,
        state_dir: Path,
        *,
        failure_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.directory = state_dir / "debug-captures"
        self.failure_callback = failure_callback
        self.active: CaptureSession | None = None
        self.bindings: dict[str, str] = {}
        self.sessions: dict[str, CaptureSession] = {}
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None
        self._failure: str | None = None

    async def startup(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._load_existing()
        self._writer_task = asyncio.create_task(
            self._writer(), name="server-debug-capture-writer"
        )

    async def close(self) -> None:
        if self._writer_task is None:
            return
        if self.active is not None:
            await self.stop()
        await self._queue.join()
        self._queue.put_nowait(None)
        await self._writer_task
        self._writer_task = None

    def _load_existing(self) -> None:
        for path in self.directory.glob("*.jsonl"):
            session_id = path.stem
            if not _SESSION_ID.fullmatch(session_id):
                continue
            started = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat().replace("+00:00", "Z")
            self.sessions[session_id] = CaptureSession(
                session_id, path, started, None
            )

    async def start(self, *, subject_account_id: str | None = None) -> CaptureSession:
        if self.active is not None:
            raise ValueError("debug capture is already active")
        if self._failure is not None:
            raise RuntimeError(
                f"debug capture writer failed; clear captures before restarting it: {self._failure}"
            )
        now = datetime.now(timezone.utc)
        session_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
        path = self.directory / f"{session_id}.jsonl"
        await asyncio.to_thread(self._create_file_exclusive, path)
        session = CaptureSession(
            session_id,
            path,
            now.isoformat().replace("+00:00", "Z"),
            subject_account_id,
        )
        self.sessions[session_id] = session
        self.active = session
        self._enqueue(
            session_id,
            "capture_started",
            request_id=None,
            data={"subject_account_id": subject_account_id},
        )
        return session

    async def stop(self) -> CaptureSession:
        session = self.active
        if session is None:
            raise ValueError("debug capture is not active")
        self._enqueue(
            session.session_id,
            "capture_stopped",
            request_id=None,
            data={"bound_requests_remaining": self.bound_request_count(session.session_id)},
        )
        self.active = None
        await self._queue.join()
        return session

    async def clear(self) -> int:
        if self.active is not None:
            raise ValueError("stop debug capture before clearing files")
        if self.bindings:
            raise ValueError("captured requests are still running; wait for them to finish")
        await self._queue.join()
        paths = list(self.directory.glob("*.jsonl"))
        for path in paths:
            await asyncio.to_thread(path.unlink)
        self.sessions.clear()
        self._failure = None
        return len(paths)

    def bind_request(
        self, request_id: str, *, account_id: str | None
    ) -> str | None:
        session = self.active
        if session is None:
            return None
        if (
            session.subject_account_id is not None
            and account_id != session.subject_account_id
        ):
            return None
        self.bindings[request_id] = session.session_id
        return session.session_id

    def release_request(self, request_id: str) -> None:
        self.bindings.pop(request_id, None)

    def record_for_request(
        self, request_id: str, kind: str, data: dict[str, Any]
    ) -> None:
        session_id = self.bindings.get(request_id)
        if session_id is not None:
            self._enqueue(session_id, kind, request_id=request_id, data=data)

    def record_session(
        self,
        session_id: str | None,
        kind: str,
        *,
        request_id: str | None,
        data: dict[str, Any],
    ) -> None:
        if session_id is not None:
            self._enqueue(session_id, kind, request_id=request_id, data=data)

    def _enqueue(
        self,
        session_id: str,
        kind: str,
        *,
        request_id: str | None,
        data: dict[str, Any],
    ) -> None:
        if self._failure is not None:
            return
        self._queue.put_nowait(
            (
                session_id,
                {
                    "timestamp": _utc_now(),
                    "session_id": session_id,
                    "kind": kind,
                    "request_id": request_id,
                    "data": data,
                },
            )
        )

    async def _writer(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                session_id, record = item
                session = self.sessions.get(session_id)
                if session is None:
                    raise RuntimeError(f"unknown capture session {session_id}")
                line = json.dumps(
                    record, ensure_ascii=False, separators=(",", ":"), default=str
                ) + "\n"
                await asyncio.to_thread(self._append, session.path, line)
            except Exception as exc:
                self._failure = str(exc)
                self.active = None
                if self.failure_callback is not None:
                    self.failure_callback(self._failure)
            finally:
                self._queue.task_done()

    @staticmethod
    def _create_file_exclusive(path: Path) -> None:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)

    @staticmethod
    def _append(path: Path, line: str) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()

    def bound_request_count(self, session_id: str) -> int:
        return sum(1 for value in self.bindings.values() if value == session_id)

    def status(self) -> dict[str, Any]:
        active = self.active
        files = []
        for session in sorted(
            self.sessions.values(), key=lambda value: value.started_at, reverse=True
        ):
            try:
                size = session.path.stat().st_size
            except FileNotFoundError:
                size = 0
            files.append(
                {
                    "session_id": session.session_id,
                    "path": str(session.path),
                    "started_at": session.started_at,
                    "subject_account_id": session.subject_account_id,
                    "bytes": size,
                    "bound_requests": self.bound_request_count(session.session_id),
                }
            )
        return {
            "active": active is not None,
            "active_session_id": active.session_id if active else None,
            "active_started_at": active.started_at if active else None,
            "subject_account_id": active.subject_account_id if active else None,
            "bound_requests": (
                self.bound_request_count(active.session_id) if active else 0
            ),
            "pending_records": self._queue.qsize(),
            "writer_failure": self._failure,
            "sessions": files,
        }

    def session_path(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid capture session ID")
        session = self.sessions.get(session_id)
        if session is None or not session.path.is_file():
            raise FileNotFoundError("capture session does not exist")
        return session.path

    def tail(self, session_id: str | None = None, *, maximum_bytes: int = 1_000_000) -> str:
        if not self.sessions:
            return ""
        if session_id is None:
            session = max(self.sessions.values(), key=lambda value: value.started_at)
        else:
            session = self.sessions.get(session_id)
            if session is None:
                raise FileNotFoundError("capture session does not exist")
        path = session.path
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > maximum_bytes:
                handle.seek(size - maximum_bytes)
                handle.readline()
                prefix = (
                    f"[Viewer shows the final {maximum_bytes:,} bytes. "
                    "Use the complete-session link for the entire JSONL file.]\n"
                )
            else:
                prefix = ""
            return prefix + handle.read().decode("utf-8", errors="replace")
