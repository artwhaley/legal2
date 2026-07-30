"""Freeze active prompts from DB as prompt-set v1."""
import json
from pathlib import Path
import sqlite3

db = Path.home() / ".message_evidence_workstation" / "workspace.db"
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row

prompts = conn.execute(
    "SELECT name, run_type, body, version FROM prompt_template WHERE is_active=1 ORDER BY run_type"
).fetchall()

print(f"Found {len(prompts)} active prompts")
prompt_set = {}
for p in prompts:
    prompt_set[p["run_type"]] = {
        "name": p["name"],
        "run_type": p["run_type"],
        "body": p["body"],
        "version": p["version"],
    }
    body_preview = p["body"][:80].replace("\n", "\\n")
    print(f"  {p['run_type']}: {body_preview}...")

out = Path("docs/transformation/phase_1_4/prompt_set_v1.json")
out.write_text(json.dumps(prompt_set, indent=2), encoding="utf-8")
print(f"\nFrozen to {out}")
conn.close()
