"""Cross-process exclusive lock for one EVW workspace."""

from __future__ import annotations

import os
from pathlib import Path


class WorkspaceLockError(RuntimeError):
    pass


class WorkspaceFileLock:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path.resolve()
        self.lock_path = self.workspace_path.with_suffix(self.workspace_path.suffix + ".lock")
        self._handle = None

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            import msvcrt

            handle = open(self.lock_path, "a+b")
            handle.seek(0)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                handle.close()
                raise WorkspaceLockError(f"Workspace is already open: {self.workspace_path}") from exc
            self._handle = handle
            return
        import fcntl

        handle = open(self.lock_path, "a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise WorkspaceLockError(f"Workspace is already open: {self.workspace_path}") from exc
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        if os.name == "nt":
            import msvcrt

            self._handle.seek(0)
            try:
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self._handle.close()
        else:
            import fcntl

            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
        self._handle = None

    def __enter__(self) -> "WorkspaceFileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()
