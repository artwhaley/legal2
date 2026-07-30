"""Verify the final Server-First V1 package ownership boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRODUCT_POST_ROUTES = {
    "/v1/keyword-expansion",
    "/v1/conversational-plan",
    "/v1/conversational-analysis",
    "/v1/embeddings",
}
V3_RUNTIME_RESIDUE = {
    "/v1/conversational-retrieval-plan",
    "retrieval_terms",
    "retrieval_plan_id",
    "terms_only",
    "retrieval_assistance_accepted",
    "no_relevant_evidence",
}


def imports_under(directory: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path in directory.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend((path, alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((path, node.module))
    return found


def main() -> int:
    failures: list[str] = []
    app_path = ROOT / "server" / "app.py"
    app_tree = ast.parse(app_path.read_text(encoding="utf-8-sig"), filename=str(app_path))
    post_routes = {
        node.args[0].value
        for node in ast.walk(app_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "post"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    if post_routes != PRODUCT_POST_ROUTES:
        failures.append(f"product POST route inventory mismatch: {sorted(post_routes)}")
    for path, module in imports_under(ROOT / "server"):
        if module.startswith("message_evidence_workstation") or module.startswith("server.gui") or module.startswith("server.routing"):
            failures.append(f"server import forbidden: {path.relative_to(ROOT)} -> {module}")
    for path, module in imports_under(ROOT / "message_evidence_workstation"):
        if module.startswith("message_evidence_workstation.llm") or module.startswith("message_evidence_workstation.nim") or module.startswith("server"):
            failures.append(f"client server/model import forbidden: {path.relative_to(ROOT)} -> {module}")
    for path in (ROOT / "server").rglob("*.py"):
        text = path.read_text(encoding="utf-8-sig")
        if "PySide" in text or "PyQt" in text:
            failures.append(f"Qt import forbidden in server: {path.relative_to(ROOT)}")
    runtime_files = [
        *(ROOT / "server").glob("*.py"),
        ROOT / "message_evidence_workstation" / "client_api" / "contracts.py",
        ROOT / "message_evidence_workstation" / "client_api" / "gateway.py",
        ROOT / "message_evidence_workstation" / "services" / "client_workflows.py",
    ]
    for path in runtime_files:
        if path.name in {"config.py", "config_store.py"}:
            continue
        text = path.read_text(encoding="utf-8-sig")
        for residue in sorted(V3_RUNTIME_RESIDUE):
            if residue in text:
                failures.append(f"v3 runtime residue: {path.relative_to(ROOT)} contains {residue!r}")
    if failures:
        print("\n".join(failures))
        return 1
    print("package boundaries: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
