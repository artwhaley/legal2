"""Baseline EVW inspection."""
import sqlite3
from pathlib import Path

db = Path.home() / ".message_evidence_workstation" / "workspace.db"
print(f"db: {db} size: {db.stat().st_size} exists: {db.exists()}")

conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

print("\n=== SCHEMA VERSION ===")
try:
    c = conn.execute("SELECT value FROM workspace_state WHERE key='schema_version'")
    r = c.fetchone()
    print(f"  schema_version = {r[0]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== ALL TABLES ===")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
for t in tables:
    print(f"  {t[0]}")

print("\n=== TABLE ROW COUNTS ===")
for t in tables:
    try:
        c = conn.execute(f'SELECT COUNT(*) FROM "{t[0]}"')
        print(f"  {t[0]}: {c.fetchone()[0]}")
    except Exception as e:
        print(f"  {t[0]}: ERROR - {e}")

print("\n=== DATASETS ===")
try:
    cols = [d[0] for d in conn.execute("PRAGMA table_info(dataset)").fetchall()]
    print(f"  columns: {cols}")
    c = conn.execute("SELECT * FROM dataset")
    for r in c.fetchall():
        print(f"  {dict(zip(cols, r))}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== PROMPT_TEMPLATE ===")
try:
    prompts = conn.execute("SELECT prompt_id, name, version, updated_at FROM prompt_template ORDER BY prompt_id").fetchall()
    print(f"  count: {len(prompts)}")
    for p in prompts:
        print(f"    id={p[0]} name={p[1]} v={p[2]} updated={p[3]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== MODEL_RUN ===")
try:
    print(f"  count: {conn.execute('SELECT COUNT(*) FROM model_run').fetchone()[0]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== PROCESS_LOG ===")
try:
    print(f"  count: {conn.execute('SELECT COUNT(*) FROM process_log').fetchone()[0]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== EMBEDDING INDEX METADATA ===")
try:
    cols = [d[0] for d in conn.execute("PRAGMA table_info(embedding_index_metadata)").fetchall()]
    print(f"  columns: {cols}")
    c = conn.execute("SELECT * FROM embedding_index_metadata ORDER BY embedding_index_id DESC LIMIT 4")
    for r in c.fetchall():
        print(f"  {dict(zip(cols, r))}")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== WAL/SHM ===")
for suffix in [".evw-wal", ".evw-shm"]:
    p = db.with_name(db.stem + suffix)
    if p.exists():
        print(f"  {p.name}: {p.stat().st_size} bytes")

conn.close()
