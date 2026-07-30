"""Inspect prompt templates and model routing call sites."""
import sqlite3
from pathlib import Path

db = Path.home() / ".message_evidence_workstation" / "workspace.db"
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

print("=== PROMPT_TEMPLATE (columns) ===")
cols = [d[0] for d in conn.execute("PRAGMA table_info(prompt_template)").fetchall()]
print(f"  columns: {cols}")

print("\n=== PROMPT_TEMPLATE (all rows) ===")
c = conn.execute("SELECT * FROM prompt_template")
for r in c.fetchall():
    d = dict(r)
    body = d.get('body', '') or ''
    body_preview = body[:100].replace('\n', '\\n')
    print(f"  {d.get('name')} v{d.get('version','?')} body={body_preview}...")
    if 'prompt_id' in d:
        print(f"    prompt_id={d['prompt_id']}")

print("\n=== SCHEMA_VERSION ===")
c = conn.execute("SELECT * FROM schema_version")
for r in c.fetchall():
    print(f"  {dict(r)}")

conn.close()
