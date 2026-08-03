"""Small encrypted, content-free SQLite control plane."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import time
import uuid
import getpass
from dataclasses import replace
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from server.config import (
    CHAT_OPERATIONS,
    EmbeddingConfig,
    GlobalConfig,
    ModelProfile,
    OperationAssignment,
    OperationConfig,
    ProviderAccount,
    ServerConfig,
    default_state_dir,
    migrate_v2_config_dict,
    migrate_v3_config_dict,
)
from server.prompts import DEFAULT_PROMPTS


TABLES = {
    "control_schema_version", "config_version", "provider_account_config",
    "model_profile_config", "operation_assignment_config", "embedding_config",
    "global_config", "encrypted_secret", "provider_secret_binding", "admin_audit",
    "usage_event", "legacy_import_receipt",
}

CONTROL_SCHEMA_VERSION = 4


class ConfigurationCorruption(RuntimeError):
    pass


class SecretManager:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.key_path = state_dir / "secrets" / "master.key"
        self.key = self._resolve()
        self._fernet = Fernet(self.key)

    def _resolve(self) -> bytes:
        supplied = os.environ.get("EVW_SERVER_MASTER_KEY", "").strip()
        if supplied:
            try:
                Fernet(supplied.encode("ascii"))
            except Exception as exc:
                raise ValueError("EVW_SERVER_MASTER_KEY is not a valid Fernet key") from exc
            return supplied.encode("ascii")
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            value = self.key_path.read_bytes().strip()
            try:
                Fernet(value)
            except Exception as exc:
                raise ConfigurationCorruption("master key file is invalid") from exc
            self._secure_key_file()
            return value
        value = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(self.key_path, flags, 0o600)
        try:
            os.write(fd, value)
        finally:
            os.close(fd)
        self._secure_key_file()
        return value

    def _secure_key_file(self) -> None:
        try:
            os.chmod(self.key_path, 0o600)
            if os.name == "nt":
                user = getpass.getuser()
                completed = subprocess.run(
                    [
                        "icacls",
                        str(self.key_path),
                        "/inheritance:r",
                        "/grant:r",
                        f"{user}:(F)",
                        "SYSTEM:(F)",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.returncode != 0:
                    raise OSError("icacls rejected the master-key ACL")
        except OSError as exc:
            raise ConfigurationCorruption("unable to secure master key file") from exc

    def encrypt(self, secret: str) -> bytes:
        return self._fernet.encrypt(secret.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ConfigurationCorruption("provider secret cannot be decrypted") from exc


def _legacy_resolved_payload(raw: dict[str, Any], *, config_version: int) -> ServerConfig:
    """Convert the pre-profile resolved-operation payload used by old stores."""
    operations_raw = raw.get("operations")
    if not isinstance(operations_raw, dict):
        raise ValueError("legacy configuration operations must be an object")
    names = {
        "keyword_expansion": "keyword_expansion",
        "retrieval_terms": "analysis_planning",
        "window_scan": "window_evidence_extraction",
        "evidence_ledger_synthesis": "ledger_synthesis",
        "ledger_reduction": "ledger_compaction",
    }
    source = dict(operations_raw)
    if "ledger_reduction" not in source and "evidence_ledger_synthesis" in source:
        source["ledger_reduction"] = source["evidence_ledger_synthesis"]
    final: dict[str, OperationConfig] = {}
    for old_name, new_name in names.items():
        value = source.get(old_name)
        if not isinstance(value, dict):
            raise ValueError(f"legacy operation {old_name} is missing")
        value = dict(value)
        if "provider" in value and "provider_kind" not in value:
            value["provider_kind"] = value.pop("provider")
        if "model" in value and "model_id" not in value:
            value["model_id"] = value.pop("model")
        from server.prompts import DEFAULT_PROMPTS
        value["system_prompt"] = DEFAULT_PROMPTS[new_name]
        final[new_name] = OperationConfig.from_dict(value)
    global_raw = dict(raw.get("global_config", {}))
    global_raw.pop("window_target_input_tokens", None)
    enabled = global_raw.pop("retrieval_assistance_enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("legacy retrieval assistance flag must be Boolean")
    global_raw["retrieval_assistance_mode"] = "none"
    old_depth = global_raw.pop("ledger_reduction_max_depth", 4)
    global_raw["ledger_compaction_max_depth"] = old_depth
    global_raw.setdefault("retrieval_top_k_per_query", 100)
    global_raw.setdefault("retrieval_maximum_prompt_suggestion_messages", 40)
    global_raw.setdefault("retrieval_rrf_constant", 60)
    return ServerConfig.from_resolved_operations(
        config_version=config_version,
        host=str(raw.get("host", "127.0.0.1")),
        port=int(raw.get("port", 8710)),
        global_config=GlobalConfig(**global_raw),
        operations=final,
        embedding=EmbeddingConfig(**dict(raw.get("embedding", {}))),
    )


class ConfigStore:
    def __init__(self, state_dir: Path | None = None, *, db_path: Path | None = None):
        self.state_dir = (state_dir or default_state_dir()).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = (db_path or self.state_dir / "control.sqlite3").expanduser().resolve()
        self.secrets = SecretManager(self.state_dir)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        try:
            self._configure()
            self._migrate()
            self._check_integrity()
        except Exception:
            self.conn.rollback()
            self.conn.close()
            raise

    def _configure(self) -> None:
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.commit()

    def _migrate(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS control_schema_version (version INTEGER NOT NULL);
        INSERT INTO control_schema_version(version) SELECT 3 WHERE NOT EXISTS (SELECT 1 FROM control_schema_version);
        CREATE TABLE IF NOT EXISTS config_version (
          version_id INTEGER PRIMARY KEY AUTOINCREMENT,
          config_hash TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('draft','active','superseded')),
          created_at REAL NOT NULL,
          activated_at REAL,
          source TEXT NOT NULL DEFAULT 'admin'
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_config ON config_version(status) WHERE status='active';
        CREATE TABLE IF NOT EXISTS provider_account_config (
          version_id INTEGER NOT NULL REFERENCES config_version(version_id) ON DELETE CASCADE,
          provider_account_id TEXT NOT NULL,
          config_json TEXT NOT NULL,
          PRIMARY KEY(version_id, provider_account_id)
        );
        CREATE TABLE IF NOT EXISTS model_profile_config (
          version_id INTEGER NOT NULL REFERENCES config_version(version_id) ON DELETE CASCADE,
          model_profile_id TEXT NOT NULL,
          config_json TEXT NOT NULL,
          PRIMARY KEY(version_id, model_profile_id)
        );
        CREATE TABLE IF NOT EXISTS operation_assignment_config (
          version_id INTEGER NOT NULL REFERENCES config_version(version_id) ON DELETE CASCADE,
          operation TEXT NOT NULL,
          config_json TEXT NOT NULL,
          PRIMARY KEY(version_id, operation)
        );
        CREATE TABLE IF NOT EXISTS embedding_config (
          version_id INTEGER PRIMARY KEY REFERENCES config_version(version_id) ON DELETE CASCADE,
          config_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS global_config (
          version_id INTEGER PRIMARY KEY REFERENCES config_version(version_id) ON DELETE CASCADE,
          config_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS encrypted_secret (
          secret_id TEXT PRIMARY KEY,
          ciphertext BLOB NOT NULL,
          key_version INTEGER NOT NULL,
          provider_label TEXT NOT NULL,
          suffix TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_secret_binding (
          version_id INTEGER NOT NULL REFERENCES config_version(version_id) ON DELETE CASCADE,
          provider_account_id TEXT NOT NULL,
          secret_id TEXT NOT NULL REFERENCES encrypted_secret(secret_id),
          PRIMARY KEY(version_id, provider_account_id)
        );
        CREATE TABLE IF NOT EXISTS admin_audit (
          audit_id TEXT PRIMARY KEY,
          action TEXT NOT NULL,
          version_id INTEGER,
          created_at REAL NOT NULL,
          details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage_event (
          event_id TEXT PRIMARY KEY,
          request_id TEXT,
          created_at REAL NOT NULL,
          config_version INTEGER NOT NULL,
          product_endpoint TEXT NOT NULL,
          internal_operation TEXT,
          operation_instance TEXT,
          attempt INTEGER,
          provider_or_profile TEXT NOT NULL,
          outcome TEXT NOT NULL,
          error_code TEXT,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          usage_source TEXT NOT NULL,
          input_price_per_million REAL,
          output_price_per_million REAL,
          estimated_cost REAL,
          currency TEXT,
          latency_ms REAL,
          provider_request_id TEXT,
          embedding_item_count INTEGER NOT NULL DEFAULT 0,
          cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
          cache_write_input_tokens INTEGER NOT NULL DEFAULT 0,
          cache_miss_input_tokens INTEGER NOT NULL DEFAULT 0,
          cache_usage_reported INTEGER NOT NULL DEFAULT 0
        );
        CREATE TRIGGER IF NOT EXISTS usage_event_no_update
          BEFORE UPDATE ON usage_event
          BEGIN SELECT RAISE(ABORT, 'usage_event is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS usage_event_no_delete
          BEFORE DELETE ON usage_event
          BEGIN SELECT RAISE(ABORT, 'usage_event is append-only'); END;
        CREATE TABLE IF NOT EXISTS legacy_import_receipt (
          source_hash TEXT PRIMARY KEY,
          imported_at REAL NOT NULL,
          result TEXT NOT NULL,
          details_json TEXT NOT NULL
        );
        """)
        version_rows = self.conn.execute(
            "SELECT version FROM control_schema_version"
        ).fetchall()
        if len(version_rows) != 1:
            raise ConfigurationCorruption(
                "ambiguous control database schema version"
            )
        version = int(version_rows[0][0])
        if version == 3:
            self._migrate_v3_payloads()
            version = CONTROL_SCHEMA_VERSION
            self.conn.execute(
                "UPDATE control_schema_version SET version=?", (CONTROL_SCHEMA_VERSION,)
            )
        elif version == CONTROL_SCHEMA_VERSION:
            self._migrate_v3_payloads()
        else:
            raise ConfigurationCorruption(
                f"unsupported control database schema version {version}"
            )
        self._migrate_usage_cache_columns()
        self._migrate_obsolete_synthesis_prompts()
        self.conn.commit()

    def _migrate_usage_cache_columns(self) -> None:
        """Add content-free cache counters to existing schema-v4 stores."""
        existing = {
            str(row[1]) for row in self.conn.execute("PRAGMA table_info(usage_event)")
        }
        columns = {
            "cache_read_input_tokens": "INTEGER NOT NULL DEFAULT 0",
            "cache_write_input_tokens": "INTEGER NOT NULL DEFAULT 0",
            "cache_miss_input_tokens": "INTEGER NOT NULL DEFAULT 0",
            "cache_usage_reported": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, declaration in columns.items():
            if name not in existing:
                self.conn.execute(
                    f"ALTER TABLE usage_event ADD COLUMN {name} {declaration}"
                )

    def _migrate_v3_payloads(self) -> None:
        """Atomically migrate all schema-v3 stored payloads to schema v4."""
        rows = self.conn.execute(
            "SELECT version_id,payload_json FROM config_version ORDER BY version_id"
        ).fetchall()
        converted: list[tuple[int, ServerConfig]] = []
        for row in rows:
            version_id = int(row["version_id"])
            try:
                raw = json.loads(row["payload_json"])
                if raw.get("config_schema_version") == CONTROL_SCHEMA_VERSION:
                    continue
                migration = migrate_v2_config_dict if raw.get("config_schema_version") == 2 else migrate_v3_config_dict
                migrated = migration(
                    raw,
                    contract_prompts=DEFAULT_PROMPTS,
                )
                config = ServerConfig.from_dict(migrated, config_version=version_id)
                config.validate(require_complete=False)
            except Exception as exc:
                raise ConfigurationCorruption(
                    f"configuration version {version_id} cannot be migrated to schema v4"
                ) from exc
            converted.append((version_id, config))
        if not converted:
            return
        with self.conn:
            for version_id, config in converted:
                payload = json.dumps(
                    config.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
                )
                self.conn.execute(
                    "UPDATE config_version SET config_hash=?,payload_json=? WHERE version_id=?",
                    (self._hash(config), payload, version_id),
                )
                self._write_normalized(version_id, config)
            self.conn.execute(
                "INSERT INTO admin_audit(audit_id,action,version_id,created_at,details_json) "
                "VALUES(?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                        "config_schema_v4_migration",
                    None,
                    time.time(),
                    json.dumps(
                        {"converted_version_count": len(converted), "from_schema": 3, "to_schema": 4},
                        sort_keys=True,
                    ),
                ),
            )

    def _migrate_obsolete_synthesis_prompts(self) -> None:
        """Replace only recognized seeded contract prompts in every version.

        Operator-authored prompts remain untouched and are rejected by normal
        activation validation when they still request the obsolete contract.
        """
        legacy_seed_hashes = {
            "keyword_expansion": {
                "20623ff67e3b10be0147196a9f4b078534def6f5fbd37b7b136addd257df69d1",
            },
            "analysis_planning": {
                "0c96e296df3824eabea29bdd0853e62876fc9b90d14a0a0e0c58d2b8a40929ba",
                "c926f2858a55ac526264be9f2c17e818427a08d915ec823ca068d1b97330807d",
            },
            "window_evidence_extraction": {
                "06093b93b2ad58cc0133c7e8a9e35c533bd15aefad028ad15b6a3799e6577984",
                "2ab3d006cdfbba73e718b5c21fb5ea98516e0db266a1ee1257b53f78087c6b1a",
            },
            "ledger_compaction": {
                "869c8761712521d86bd1fc9acf624a6920d7ce7b42a700276e6912af045eb33e",
                "06d162b003fbea374b80f4746cc85fffa214957b6d76c931fa32928a078aefc1",
            },
            "ledger_synthesis": {
                "c4e708bf8e1ecda6503008a3982956816f066f20403790a116533192286a2936",
                "6c3f2b4a1f2d395373311a4b30b37767770775bac5faac8db671d02e4c1f4b7a",
            },
        }
        rows = self.conn.execute(
            "SELECT version_id,payload_json FROM config_version ORDER BY version_id"
        ).fetchall()
        migrated_ids: list[int] = []
        migrated_operations: set[str] = set()
        for row in rows:
            version_id = int(row["version_id"])
            raw = json.loads(row["payload_json"])
            assignments = raw.get("operation_assignments")
            if not isinstance(assignments, dict):
                raise ConfigurationCorruption(
                    f"configuration version {version_id} has invalid operation assignments"
                )
            migrated = json.loads(json.dumps(raw, ensure_ascii=False))
            changed = False
            for operation, recognized_seed_hashes in legacy_seed_hashes.items():
                assignment = assignments.get(operation)
                if not isinstance(assignment, dict) or not isinstance(assignment.get("system_prompt"), str):
                    raise ConfigurationCorruption(
                        f"configuration version {version_id} has an invalid {operation} assignment"
                    )
                if (
                    hashlib.sha256(assignment["system_prompt"].encode("utf-8")).hexdigest()
                    in recognized_seed_hashes
                ):
                    migrated["operation_assignments"][operation]["system_prompt"] = DEFAULT_PROMPTS[operation]
                    changed = True
                    migrated_operations.add(operation)
            if not changed:
                continue
            config = ServerConfig.from_dict(migrated, config_version=version_id)
            config.validate(require_complete=False)
            payload = json.dumps(
                config.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
            self.conn.execute(
                "UPDATE config_version SET config_hash=?,payload_json=? WHERE version_id=?",
                (self._hash(config), payload, version_id),
            )
            self._write_normalized(version_id, config)
            migrated_ids.append(version_id)
        if migrated_ids:
            self.conn.execute(
                "INSERT INTO admin_audit(audit_id,action,version_id,created_at,details_json) VALUES(?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    "prompt_contract_migration",
                    None,
                    time.time(),
                    json.dumps(
                        {
                            "migrated_version_ids": migrated_ids,
                            "migrated_operations": sorted(migrated_operations),
                            "preserved_control_schema_version": CONTROL_SCHEMA_VERSION,
                        },
                        sort_keys=True,
                    ),
                ),
            )

    def _migrate_v2_configuration(self) -> None:
        """One-way migration from per-operation providers to reusable profiles."""
        old_tables = {
            str(row[0])
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "operation_config" not in old_tables or "config_secret_binding" not in old_tables:
            raise ConfigurationCorruption("control schema v2 is missing its operation tables")
        for row in self.conn.execute(
            "SELECT version_id,payload_json FROM config_version ORDER BY version_id"
        ).fetchall():
            version_id = int(row["version_id"])
            try:
                legacy_raw = json.loads(row["payload_json"])
                if legacy_raw.get("config_schema_version") == 2:
                    migrated_raw = migrate_v2_config_dict(legacy_raw)
                    migrated = ServerConfig.from_dict(migrated_raw, config_version=version_id)
                else:
                    migrated = _legacy_resolved_payload(legacy_raw, config_version=version_id)
            except Exception as exc:
                raise ConfigurationCorruption(
                    f"configuration version {version_id} cannot be migrated"
                ) from exc
            bindings = self.conn.execute(
                "SELECT b.operation,b.secret_id,s.ciphertext "
                "FROM config_secret_binding b JOIN encrypted_secret s ON s.secret_id=b.secret_id "
                "WHERE b.version_id=?",
                (version_id,),
            ).fetchall()
            provider_secrets: dict[str, tuple[str, str]] = {}
            for binding in bindings:
                operation = str(binding["operation"])
                operation_map = {
                    "whole_corpus_answer": "window_evidence_extraction",
                    "ledger_reduction": "ledger_compaction",
                }
                mapped_operation = operation_map.get(operation, operation)
                if mapped_operation not in migrated.operation_assignments:
                    raise ConfigurationCorruption(
                        f"configuration version {version_id} has a secret for unknown operation {operation}"
                    )
                profile_id = migrated.operation_assignments[mapped_operation].model_profile_id
                provider_id = migrated.model_profiles[profile_id].provider_account_id
                plaintext = self.secrets.decrypt(bytes(binding["ciphertext"]))
                existing = provider_secrets.get(provider_id)
                if existing is not None and existing[1] != plaintext:
                    raise ConfigurationCorruption(
                        f"configuration version {version_id} has conflicting credentials "
                        f"for provider account {provider_id}"
                    )
                provider_secrets[provider_id] = (str(binding["secret_id"]), plaintext)
            for provider_id, (_, plaintext) in provider_secrets.items():
                migrated = replace(
                    migrated,
                    provider_accounts={
                        **migrated.provider_accounts,
                        provider_id: replace(
                            migrated.provider_accounts[provider_id], api_key=plaintext
                        ),
                    },
                )
            payload = migrated.to_dict()
            data = json.dumps(
                payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
            self.conn.execute(
                "UPDATE config_version SET config_hash=?,payload_json=? WHERE version_id=?",
                (self._hash(migrated), data, version_id),
            )
            self._write_normalized(version_id, migrated)
            for provider_id, (secret_id, _) in provider_secrets.items():
                self.conn.execute(
                    "INSERT INTO provider_secret_binding(version_id,provider_account_id,secret_id) "
                    "VALUES(?,?,?)",
                    (version_id, provider_id, secret_id),
                )
        self.conn.execute("DROP TABLE config_secret_binding")
        self.conn.execute("DROP TABLE operation_config")
        self.conn.execute(
            "DELETE FROM encrypted_secret WHERE secret_id NOT IN "
            "(SELECT secret_id FROM provider_secret_binding)"
        )

    def _check_integrity(self) -> None:
        versions = self.conn.execute("SELECT version FROM control_schema_version").fetchall()
        if (
            len(versions) != 1
            or int(versions[0][0]) != CONTROL_SCHEMA_VERSION
        ):
            raise ConfigurationCorruption("unsupported or ambiguous control database schema version")
        quick = self.conn.execute("PRAGMA quick_check").fetchone()[0]
        foreign = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        if quick != "ok" or foreign:
            raise ConfigurationCorruption("control database integrity check failed")

    @staticmethod
    def _hash(config: ServerConfig) -> str:
        encoded = json.dumps(config.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _write_normalized(self, version_id: int, config: ServerConfig) -> None:
        self.conn.execute("DELETE FROM provider_account_config WHERE version_id=?", (version_id,))
        self.conn.execute("DELETE FROM model_profile_config WHERE version_id=?", (version_id,))
        self.conn.execute("DELETE FROM operation_assignment_config WHERE version_id=?", (version_id,))
        self.conn.execute("DELETE FROM embedding_config WHERE version_id=?", (version_id,))
        self.conn.execute("DELETE FROM global_config WHERE version_id=?", (version_id,))
        for provider_id, value in config.provider_accounts.items():
            self.conn.execute(
                "INSERT INTO provider_account_config(version_id,provider_account_id,config_json) VALUES(?,?,?)",
                (version_id, provider_id, json.dumps(value.to_dict(), sort_keys=True, ensure_ascii=False)),
            )
        for profile_id, value in config.model_profiles.items():
            self.conn.execute(
                "INSERT INTO model_profile_config(version_id,model_profile_id,config_json) VALUES(?,?,?)",
                (version_id, profile_id, json.dumps(value.to_dict(), sort_keys=True, ensure_ascii=False)),
            )
        for operation, value in config.operation_assignments.items():
            self.conn.execute(
                "INSERT INTO operation_assignment_config(version_id,operation,config_json) VALUES(?,?,?)",
                (version_id, operation, json.dumps(value.to_dict(), sort_keys=True, ensure_ascii=False)),
            )
        self.conn.execute(
            "INSERT INTO embedding_config(version_id,config_json) VALUES(?,?)",
            (version_id, json.dumps(config.embedding.to_dict(), sort_keys=True)),
        )
        self.conn.execute(
            "INSERT INTO global_config(version_id,config_json) VALUES(?,?)",
            (version_id, json.dumps(config.global_config.to_dict(), sort_keys=True)),
        )

    def _write_config(self, config: ServerConfig, *, status: str, source: str = "admin", version_id: int | None = None) -> int:
        payload = config.to_dict()
        now = time.time()
        data = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if version_id is None:
            cursor = self.conn.execute("INSERT INTO config_version(config_hash,payload_json,status,created_at,source) VALUES(?,?,?,?,?)", (self._hash(config), data, status, now, source))
            version_id = int(cursor.lastrowid)
        else:
            self.conn.execute("UPDATE config_version SET config_hash=?,payload_json=? WHERE version_id=? AND status='draft'", (self._hash(config), data, version_id))
        self._write_normalized(version_id, config)
        return version_id

    def create_draft(self, config: ServerConfig, *, source: str = "admin") -> int:
        config.validate(require_complete=False)
        with self.conn:
            return self._write_config(config, status="draft", source=source)

    def save_draft(self, version_id: int, config: ServerConfig) -> None:
        config.validate(require_complete=False)
        with self.conn:
            row = self.conn.execute("SELECT status FROM config_version WHERE version_id=?", (version_id,)).fetchone()
            if row is None or row[0] != "draft":
                raise ValueError("only a draft version can be saved")
            self._write_config(config, status="draft", version_id=version_id)

    def save_draft_bundle(
        self,
        version_id: int,
        config: ServerConfig,
        *,
        secret_replacements: dict[str, str],
        secret_removals: set[str],
    ) -> None:
        """Atomically save one draft and all explicitly requested secret changes."""
        config.validate(require_complete=False)
        current = self.get_version(version_id)
        known_provider_ids = set(config.provider_accounts) | set(current.provider_accounts)
        unknown = (set(secret_replacements) | secret_removals) - known_provider_ids
        if unknown:
            raise ValueError(f"unknown provider accounts: {sorted(unknown)}")
        overlap = set(secret_replacements) & secret_removals
        if overlap:
            raise ValueError(
                f"cannot replace and remove the same secret: {sorted(overlap)}"
            )
        if any(not value for value in secret_replacements.values()):
            raise ValueError("replacement secrets must be nonblank")
        with self.conn:
            row = self.conn.execute(
                "SELECT status FROM config_version WHERE version_id=?", (version_id,)
            ).fetchone()
            if row is None or row[0] != "draft":
                raise ValueError("only a draft version can be saved")
            self._write_config(config, status="draft", version_id=version_id)
            for provider_account_id in secret_removals:
                self._remove_secret_binding(version_id, provider_account_id)
            for provider_account_id, value in secret_replacements.items():
                self._bind_secret(version_id, provider_account_id, value)

    def _row_config(self, row: sqlite3.Row) -> ServerConfig:
        raw = json.loads(row["payload_json"])
        config = ServerConfig.from_dict(raw, config_version=int(row["version_id"]))
        for provider_account_id in config.provider_accounts:
            binding = self.conn.execute(
                "SELECT s.ciphertext FROM provider_secret_binding b "
                "JOIN encrypted_secret s ON s.secret_id=b.secret_id "
                "WHERE b.version_id=? AND b.provider_account_id=?",
                (row["version_id"], provider_account_id),
            ).fetchone()
            if binding is not None:
                config = replace(
                    config,
                    provider_accounts={
                        **config.provider_accounts,
                        provider_account_id: replace(
                            config.provider_accounts[provider_account_id],
                            api_key=self.secrets.decrypt(bytes(binding[0])),
                        ),
                    },
                )
        return config

    def get_version(self, version_id: int) -> ServerConfig:
        row = self.conn.execute("SELECT * FROM config_version WHERE version_id=?", (version_id,)).fetchone()
        if row is None:
            raise KeyError(version_id)
        try:
            return self._row_config(row)
        except ConfigurationCorruption:
            raise
        except Exception as exc:
            raise ConfigurationCorruption("stored configuration payload is invalid") from exc

    def active(self) -> ServerConfig | None:
        row = self.conn.execute("SELECT * FROM config_version WHERE status='active'").fetchone()
        if row is None:
            return None
        return self.get_version(int(row["version_id"]))

    def draft(self) -> tuple[int, ServerConfig] | None:
        row = self.conn.execute("SELECT * FROM config_version WHERE status='draft' ORDER BY version_id DESC LIMIT 1").fetchone()
        return None if row is None else (int(row["version_id"]), self._row_config(row))

    def _bind_secret(self, version_id: int, provider_account_id: str, value: str) -> None:
        if not value:
            return
        previous = self.conn.execute(
            "SELECT secret_id FROM provider_secret_binding "
            "WHERE version_id=? AND provider_account_id=?",
            (version_id, provider_account_id),
        ).fetchone()
        secret_id = str(uuid.uuid4())
        provider = self.get_version(version_id).provider_accounts[provider_account_id]
        self.conn.execute(
            "INSERT INTO encrypted_secret(secret_id,ciphertext,key_version,provider_label,suffix) VALUES(?,?,?,?,?)",
            (secret_id, self.secrets.encrypt(value), 1, provider.name, value[-4:]),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO provider_secret_binding(version_id,provider_account_id,secret_id) VALUES(?,?,?)",
            (version_id, provider_account_id, secret_id),
        )
        if previous is not None:
            self.conn.execute(
                "DELETE FROM encrypted_secret WHERE secret_id=? AND NOT EXISTS "
                "(SELECT 1 FROM provider_secret_binding WHERE secret_id=?)",
                (str(previous[0]), str(previous[0])),
            )

    def _remove_secret_binding(self, version_id: int, provider_account_id: str) -> None:
        previous = self.conn.execute(
            "SELECT secret_id FROM provider_secret_binding "
            "WHERE version_id=? AND provider_account_id=?",
            (version_id, provider_account_id),
        ).fetchone()
        self.conn.execute(
            "DELETE FROM provider_secret_binding WHERE version_id=? AND provider_account_id=?",
            (version_id, provider_account_id),
        )
        if previous is not None:
            self.conn.execute(
                "DELETE FROM encrypted_secret WHERE secret_id=? AND NOT EXISTS "
                "(SELECT 1 FROM provider_secret_binding WHERE secret_id=?)",
                (str(previous[0]), str(previous[0])),
            )

    def set_secret(self, version_id: int, provider_account_id: str, value: str, *, remove: bool = False) -> None:
        config = self.get_version(version_id)
        if provider_account_id not in config.provider_accounts:
            raise ValueError("unknown provider account")
        with self.conn:
            row = self.conn.execute("SELECT status FROM config_version WHERE version_id=?", (version_id,)).fetchone()
            if row is None or row[0] != "draft":
                raise ValueError("secrets can only be changed on drafts")
            if remove:
                self._remove_secret_binding(version_id, provider_account_id)
            elif value:
                self._bind_secret(version_id, provider_account_id, value)

    def secret_projection(self, version_id: int) -> dict[str, dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT b.provider_account_id,s.provider_label,s.suffix "
            "FROM provider_secret_binding b JOIN encrypted_secret s ON s.secret_id=b.secret_id "
            "WHERE b.version_id=?",
            (version_id,),
        ).fetchall()
        return {str(row[0]): {"provider": str(row[1]), "configured": True, "suffix": str(row[2])} for row in rows}

    def encrypted_secret_bindings(self, version_id: int) -> dict[str, bytes]:
        rows = self.conn.execute(
            "SELECT b.provider_account_id,s.ciphertext FROM provider_secret_binding b "
            "JOIN encrypted_secret s ON s.secret_id=b.secret_id WHERE b.version_id=?",
            (version_id,),
        ).fetchall()
        bindings = {str(row[0]): bytes(row[1]) for row in rows}
        config = self.get_version(version_id)
        missing = [
            provider_id for provider_id in config.provider_accounts if provider_id not in bindings
        ]
        if missing:
            raise ConfigurationCorruption(f"active configuration has missing secret bindings: {missing}")
        return bindings

    def validate_version(self, version_id: int) -> None:
        config = self.get_version(version_id)
        config.validate(require_complete=True)
        config.validate_local_model_artifacts()

    def activate(self, version_id: int) -> ServerConfig:
        with self.conn:
            row = self.conn.execute("SELECT status FROM config_version WHERE version_id=?", (version_id,)).fetchone()
            if row is None or row[0] != "draft":
                raise ValueError("only a draft version can be activated")
            config = self.get_version(version_id)
            config.validate(require_complete=True)
            config.validate_local_model_artifacts()
            self.conn.execute("UPDATE config_version SET status='superseded' WHERE status='active'")
            self.conn.execute("UPDATE config_version SET status='active',activated_at=? WHERE version_id=?", (time.time(), version_id))
            self.conn.execute("INSERT INTO admin_audit(audit_id,action,version_id,created_at,details_json) VALUES(?,?,?,?,?)", (str(uuid.uuid4()), "activate", version_id, time.time(), "{}"))
        return config

    def rollback(self, version_id: int) -> tuple[int, ServerConfig]:
        source = self.get_version(version_id)
        draft_id = self.create_draft(source, source="rollback")
        for provider_id, provider in source.provider_accounts.items():
            secret = provider.api_key
            if secret:
                self.set_secret(draft_id, provider_id, secret)
        config = self.activate(draft_id)
        return draft_id, config

    def copy_as_draft(self, version_id: int, *, source_label: str = "admin_copy") -> int:
        source = self.get_version(version_id)
        draft_id = self.create_draft(source, source=source_label)
        for provider_id, provider in source.provider_accounts.items():
            if provider.api_key:
                self.set_secret(draft_id, provider_id, provider.api_key)
        return draft_id

    def ensure_draft(self, active_version: int | None, fallback: ServerConfig) -> tuple[int, ServerConfig]:
        """Return the current draft, creating exactly one when absent.

        ConfigurationService executes this complete method on its single
        control-store thread.  Keeping the read/create/read sequence inside
        one dispatched operation prevents concurrent admin page loads from
        interleaving duplicate draft creation.
        """
        existing = self.draft()
        if existing is not None:
            return existing
        if active_version is None:
            version_id = self.create_draft(fallback, source="admin")
        else:
            version_id = self.copy_as_draft(active_version, source_label="admin")
        created = self.draft()
        if created is None or created[0] != version_id:
            raise RuntimeError("admin draft was not created")
        return created

    def record_audit(self, action: str, *, version_id: int | None = None, details: dict[str, Any] | None = None) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO admin_audit(audit_id,action,version_id,created_at,details_json) VALUES(?,?,?,?,?)", (str(uuid.uuid4()), action, version_id, time.time(), json.dumps(details or {}, sort_keys=True)))

    def record_usage(self, **fields: Any) -> str:
        event_id = str(uuid.uuid4())
        allowed = {"request_id", "config_version", "product_endpoint", "internal_operation", "operation_instance", "attempt", "provider_or_profile", "outcome", "error_code", "input_tokens", "output_tokens", "usage_source", "input_price_per_million", "output_price_per_million", "estimated_cost", "currency", "latency_ms", "provider_request_id", "embedding_item_count", "cache_read_input_tokens", "cache_write_input_tokens", "cache_miss_input_tokens", "cache_usage_reported"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown usage fields: {sorted(unknown)}")
        values = {name: fields.get(name) for name in allowed}
        values.update({"config_version": int(values.get("config_version") or 0), "product_endpoint": str(values.get("product_endpoint") or ""), "provider_or_profile": str(values.get("provider_or_profile") or ""), "outcome": str(values.get("outcome") or ""), "usage_source": str(values.get("usage_source") or "estimated"), "input_tokens": int(values.get("input_tokens") or 0), "output_tokens": int(values.get("output_tokens") or 0), "embedding_item_count": int(values.get("embedding_item_count") or 0), "cache_read_input_tokens": int(values.get("cache_read_input_tokens") or 0), "cache_write_input_tokens": int(values.get("cache_write_input_tokens") or 0), "cache_miss_input_tokens": int(values.get("cache_miss_input_tokens") or 0), "cache_usage_reported": int(bool(values.get("cache_usage_reported")))})
        with self.conn:
            self.conn.execute("INSERT INTO usage_event(event_id,request_id,created_at,config_version,product_endpoint,internal_operation,operation_instance,attempt,provider_or_profile,outcome,error_code,input_tokens,output_tokens,usage_source,input_price_per_million,output_price_per_million,estimated_cost,currency,latency_ms,provider_request_id,embedding_item_count,cache_read_input_tokens,cache_write_input_tokens,cache_miss_input_tokens,cache_usage_reported) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (event_id, values["request_id"], time.time(), values["config_version"], values["product_endpoint"], values["internal_operation"], values["operation_instance"], values["attempt"], values["provider_or_profile"], values["outcome"], values["error_code"], values["input_tokens"], values["output_tokens"], values["usage_source"], values["input_price_per_million"], values["output_price_per_million"], values["estimated_cost"], values["currency"], values["latency_ms"], values["provider_request_id"], values["embedding_item_count"], values["cache_read_input_tokens"], values["cache_write_input_tokens"], values["cache_miss_input_tokens"], values["cache_usage_reported"]))
        return event_id

    def usage_totals(self) -> dict[str, Any]:
        row = self.conn.execute("SELECT COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),COALESCE(SUM(embedding_item_count),0),COUNT(*),COALESCE(SUM(CASE WHEN estimated_cost IS NOT NULL THEN estimated_cost ELSE 0 END),0),SUM(CASE WHEN estimated_cost IS NULL AND (input_tokens>0 OR output_tokens>0) THEN 1 ELSE 0 END),SUM(CASE WHEN outcome='failure' THEN 1 ELSE 0 END),SUM(CASE WHEN product_endpoint='/v1/embeddings' THEN 1 ELSE 0 END),COALESCE(SUM(cache_read_input_tokens),0),COALESCE(SUM(cache_write_input_tokens),0),COALESCE(SUM(cache_miss_input_tokens),0),COALESCE(SUM(cache_usage_reported),0) FROM usage_event").fetchone()
        return {
            "input_tokens": int(row[0]),
            "output_tokens": int(row[1]),
            "embedding_items": int(row[2]),
            "rows": int(row[3]),
            "known_cost": float(row[4]),
            "incomplete_cost_rows": int(row[5] or 0),
            "failed_attempts": int(row[6] or 0),
            "embedding_workloads": int(row[7] or 0),
            "cache_read_input_tokens": int(row[8]),
            "cache_write_input_tokens": int(row[9]),
            "cache_miss_input_tokens": int(row[10]),
            "cache_reported_rows": int(row[11]),
        }

    def checkpoint_status(self) -> dict[str, int]:
        row = self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        return {"busy": int(row[0]), "wal_frames": int(row[1]), "checkpointed_frames": int(row[2])}

    def version_history(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT version_id,status,created_at,activated_at,source,config_hash FROM config_version ORDER BY version_id DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def audit_history(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT audit_id,action,version_id,created_at,details_json FROM admin_audit ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()
        finally:
            self.conn.close()


def fresh_bootstrap_config() -> ServerConfig:
    from server.prompts import DEFAULT_PROMPTS
    provider = ProviderAccount(
        provider_account_id="provider-default",
        name="Primary provider",
    )
    profile = ModelProfile(
        model_profile_id="model-default",
        name="Primary chat model",
        provider_account_id=provider.provider_account_id,
    )
    assignments = {
        name: OperationAssignment(
            model_profile_id=profile.model_profile_id,
            system_prompt=DEFAULT_PROMPTS[name],
        )
        for name in CHAT_OPERATIONS
    }
    return ServerConfig(
        config_version=1,
        host="127.0.0.1",
        port=8710,
        global_config=GlobalConfig(),
        provider_accounts={provider.provider_account_id: provider},
        model_profiles={profile.model_profile_id: profile},
        operation_assignments=assignments,
        embedding=EmbeddingConfig(),
    )


def import_legacy_json(store: ConfigStore, source_path: Path) -> str | None:
    """Import the explicitly supported legacy JSON once.

    Returns ``activated``, ``incomplete``, or ``None`` when there is no source
    or this source hash was already recorded. The source is replaced only
    after a complete encrypted activation has been committed and reloaded.
    """
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        return None
    raw_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    if store.conn.execute("SELECT 1 FROM legacy_import_receipt WHERE source_hash=?", (source_hash,)).fetchone() is not None:
        return None
    raw = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("legacy server configuration must be a JSON object")
    if raw.get("imported") is True and raw.get("result") == "activated":
        return None
    old_ops = raw.get("operations")
    if not isinstance(old_ops, dict):
        raise ValueError("legacy server configuration operations must be an object")
    from server.prompts import DEFAULT_PROMPTS

    names = {
        "keyword_expansion": "keyword_expansion",
        "retrieval_terms": "analysis_planning",
        "window_scan": "window_evidence_extraction",
        "evidence_ledger_synthesis": "ledger_synthesis",
        "ledger_reduction": "ledger_compaction",
    }
    mapped: dict[str, OperationConfig] = {}
    missing: list[str] = []
    for old_name, new_name in names.items():
        old = old_ops.get(old_name)
        if old_name == "ledger_reduction" and old is None:
            old = old_ops.get("evidence_ledger_synthesis")
        if not isinstance(old, dict):
            missing.append(new_name)
            old = {}
        context = int(old.get("context_window_tokens", old.get("context_window", 0)) or 0)
        max_output = int(old.get("max_output_tokens", 0) or 0)
        max_request = int(old.get("max_request_tokens", 0) or 0)
        safety = context - max_request - max_output
        if context <= 0 or max_output <= 0 or max_request <= 0 or safety < 0:
            missing.append(new_name)
        mapped[new_name] = OperationConfig(
            provider_kind=str(old.get("provider", "openai_compatible")),
            base_url=str(old.get("base_url", "")).rstrip("/"),
            model_id=str(old.get("model_id", old.get("model", ""))),
            system_prompt=DEFAULT_PROMPTS[new_name],
            structured_output_mode="prompt_only",
            accounting_mode="serialized_payload_tiktoken",
            encoding_name="cl100k_base",
            context_window_tokens=context,
            max_output_tokens=max_output,
            safety_margin_tokens=safety if safety >= 0 else 0,
            target_input_tokens=max_request if max_request > 0 else None,
            connect_timeout_seconds=float(old.get("timeout_seconds", 10.0)),
            read_timeout_seconds=float(old.get("timeout_seconds", 600.0)),
            operation_deadline_seconds=float(old.get("timeout_seconds", 900.0)),
            temperature=float(old.get("temperature", 0.0)),
            api_key=str(old.get("api_key", "")),
        )
        if not mapped[new_name].api_key:
            missing.append(f"{new_name}.api_key")
    old_embedding = raw.get("embedding")
    if not isinstance(old_embedding, dict) or not old_embedding.get("model_name"):
        missing.append("embedding.model_name")
        old_embedding = old_embedding if isinstance(old_embedding, dict) else {}
    embedding = EmbeddingConfig(
        model_name=str(old_embedding.get("model_name", "")),
        model_revision=str(old_embedding.get("model_revision", "")),
        device=str(old_embedding.get("device", "cpu")),
        normalization=str(old_embedding.get("normalization", "unit_l2")),
        required_dimensions=int(old_embedding.get("dimensions", old_embedding.get("required_dimensions", 0)) or 0),
        internal_batch_size=int(old_embedding.get("max_batch_size", 32) or 32),
    )
    config = ServerConfig.from_resolved_operations(
        config_version=1,
        host=str(raw.get("host", "127.0.0.1")),
        port=int(raw.get("port", 8710)),
        global_config=GlobalConfig(),
        operations=mapped,
        embedding=embedding,
    )
    complete = not missing
    if complete:
        try:
            config.validate(require_complete=True)
        except ValueError as exc:
            missing.append(str(exc))
            complete = False
    with store.conn:
        version_id = store._write_config(config, status="active" if complete else "draft", source="legacy_import")
        for provider_id, provider in config.provider_accounts.items():
            if provider.api_key:
                store._bind_secret(version_id, provider_id, provider.api_key)
        store.conn.execute("INSERT INTO legacy_import_receipt(source_hash,imported_at,result,details_json) VALUES(?,?,?,?)", (source_hash, time.time(), "activated" if complete else "incomplete", json.dumps({"version_id": version_id, "missing": sorted(set(missing))}, sort_keys=True)))
        if complete:
            store.conn.execute("INSERT INTO admin_audit(audit_id,action,version_id,created_at,details_json) VALUES(?,?,?,?,?)", (str(uuid.uuid4()), "legacy_import_activate", version_id, time.time(), json.dumps({"source_hash": source_hash})))
    if complete:
        verified = store.active()
        if verified is None or verified.config_version != version_id:
            raise ConfigurationCorruption("legacy import activation could not be verified")
        receipt = {"imported": True, "source_hash": source_hash, "result": "activated", "version_id": version_id}
        temporary = source_path.with_suffix(source_path.suffix + ".receipt.tmp")
        temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        os.replace(temporary, source_path)
        return "activated"
    return "incomplete"
