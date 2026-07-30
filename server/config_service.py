"""Lifespan-owned immutable configuration snapshots."""

from __future__ import annotations

import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from server.config import ServerConfig
from server.config_store import ConfigStore, ConfigurationCorruption, fresh_bootstrap_config, import_legacy_json


class ConfigurationRequired(RuntimeError):
    pass


class ConfigurationService:
    def __init__(self, state_dir: Path | None = None, *, store: ConfigStore | None = None):
        self.store = store or ConfigStore(state_dir)
        self._lock = threading.RLock()
        self._snapshot: ServerConfig | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evw-control-store")
        self.started = False

    @property
    def bootstrap_mode(self) -> bool:
        return self._snapshot is None

    def startup(self) -> None:
        with self._lock:
            if self.started:
                return
            if self.store.active() is None:
                legacy = self.store.state_dir / "server.json"
                import_legacy_json(self.store, legacy)
            active = self.store.active()
            if active is None:
                if self.store.draft() is None:
                    self.store.create_draft(fresh_bootstrap_config(), source="bootstrap")
                self._snapshot = None
            else:
                try:
                    active.validate(require_complete=True)
                    active.validate_local_model_artifacts()
                except Exception as exc:
                    raise ConfigurationCorruption("active configuration failed validation") from exc
                self._snapshot = active.without_secrets()
            self.started = True

    def snapshot(self) -> ServerConfig:
        with self._lock:
            if not self.started:
                raise RuntimeError("configuration service is not started")
            if self._snapshot is None:
                raise ConfigurationRequired("CONFIGURATION_REQUIRED")
            return self._snapshot

    def maybe_snapshot(self) -> ServerConfig | None:
        with self._lock:
            return self._snapshot

    def activate(self, version_id: int) -> ServerConfig:
        with self._lock:
            if not self.started:
                raise RuntimeError("configuration service is not started")
            candidate = self.store.activate(version_id)
            candidate.validate(require_complete=True)
            candidate.validate_local_model_artifacts()
            self._snapshot = candidate.without_secrets()
            return candidate

    def candidate(self, version_id: int) -> ServerConfig:
        candidate = self.store.get_version(version_id)
        candidate.validate(require_complete=True)
        candidate.validate_local_model_artifacts()
        return candidate

    async def store_call(self, method_name: str, *args, **kwargs):
        """Run one ordered control-store operation outside the event loop."""
        loop = asyncio.get_running_loop()
        method = getattr(self.store, method_name)
        return await loop.run_in_executor(
            self._executor, lambda: method(*args, **kwargs)
        )

    async def activate_prepared(self, version_id: int) -> ServerConfig:
        candidate = await self.store_call("activate", version_id)
        candidate.validate(require_complete=True)
        candidate.validate_local_model_artifacts()
        self.publish_activated(candidate)
        return self.snapshot()

    def publish_activated(self, candidate: ServerConfig) -> None:
        """Publish a fully prepared active configuration to new requests."""
        with self._lock:
            self._snapshot = candidate.without_secrets()

    async def close_async(self) -> None:
        with self._lock:
            should_close = self.started
            self.started = False
        if should_close:
            await self.store_call("close")
        self._executor.shutdown(wait=True, cancel_futures=True)

    def close(self) -> None:
        with self._lock:
            if self.started:
                self.store.close()
                self.started = False
