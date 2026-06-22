"""Inspect workspace DB state."""
from pathlib import Path
import sqlite3

db = Path.home() / ".message_evidence_workstation" / "workspace.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
print("db", db, "bytes", db.stat().st_size)
for row in conn.execute("SELECT dataset_id, name, message_count FROM dataset ORDER BY dataset_id"):
    print("dataset", dict(row))
print("messages", conn.execute("SELECT COUNT(*) FROM message").fetchone()[0])
for row in conn.execute(
    """
    SELECT granularity, status, model_name, message_count, chunk_count, last_error
    FROM embedding_index_metadata
    ORDER BY embedding_index_id DESC
    LIMIT 8
    """
):
    print("meta", dict(row))
vec = conn.execute(
    "SELECT name FROM sqlite_master WHERE name='message_embedding_vec'"
).fetchone()
print("vec table", vec)
if vec:
    print("vec rows", conn.execute("SELECT COUNT(*) FROM message_embedding_vec").fetchone()[0])
