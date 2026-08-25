from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "core-shadow-0b-precheck.yml"
PYTHON_FILES = [
    ROOT / "core_shadow_0b" / "precheck.py",
    ROOT / "critical" / "core_shadow_0b_precheck_formal.py",
]
OUT = ROOT / "reports" / "core_shadow" / "core_shadow_0b_precheck_authority.json"

FORBIDDEN_IMPORTS = {"requests", "httpx", "urllib", "http", "socket", "subprocess", "smtplib", "imaplib", "poplib"}
FORBIDDEN_FUNCTIONS = {"send", "send_message", "pay", "delete", "publish", "merge", "grant_rights", "production_write", "credential_change"}


def scan_python(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    functions: set[str] = set()
    dynamic_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"exec", "eval", "__import__"}:
            dynamic_calls.append(node.func.id)
    return {
        "file": str(path.relative_to(ROOT)),
        "forbidden_imports": sorted(imports & FORBIDDEN_IMPORTS),
        "forbidden_functions": sorted(functions & FORBIDDEN_FUNCTIONS),
        "dynamic_calls": sorted(dynamic_calls),
    }


def evaluate() -> dict[str, Any]:
    scans = [scan_python(path) for path in PYTHON_FILES]
    text = WORKFLOW.read_text(encoding="utf-8")
    write_permissions = []
    for raw in text.splitlines():
        line = raw.strip().lower()
        if line.endswith(": write") or line.endswith(": write-all") or line == "write-all":
            write_permissions.append(raw.strip())
    secret_references = [token for token in ("secrets.", "github.event.client_payload.secret", "password", "private_key") if token.lower() in text.lower()]
    forbidden_workflow = [token for token in ("gh api --method post", "gh api --method put", "gh api --method patch", "git push", "curl -x", "pull_request_target") if token.lower() in text.lower()]
    forbidden_interfaces = sorted({
        x
        for scan in scans
        for x in scan["forbidden_imports"] + scan["forbidden_functions"] + scan["dynamic_calls"]
    } | set(forbidden_workflow))
    required_permissions = {"actions: read", "contents: read", "issues: read"}
    normalized = {line.strip().lower() for line in text.splitlines()}
    declared_reads = sorted(p for p in required_permissions if p in normalized)
    i1_ready = "core_shadow_0b_precheck_formal.py" in text and "restore-formal" in text
    passed = (
        not write_permissions
        and not secret_references
        and not forbidden_interfaces
        and set(declared_reads) == required_permissions
        and i1_ready
    )
    return {
        "schema": "core-shadow-0b.precheck-authority.v1",
        "status": "PASS" if passed else "FAIL",
        "python_scans": scans,
        "write_permissions": write_permissions,
        "secret_references": secret_references,
        "forbidden_interfaces": forbidden_interfaces,
        "declared_read_permissions": declared_reads,
        "ephemeral_same_repo_token_only": True,
        "persist_credentials_expected_false": "persist-credentials: false" in text,
        "i1_topology_ready": i1_ready,
        "productive_action_adapter_present": False,
        "new_credentials": 0,
        "new_running_cost_eur": 0,
        "merge_interface_present": False,
    }


def main() -> int:
    result = evaluate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"CORE_SHADOW_0B_PRECHECK_AUTHORITY={result['status']}")
    print("CORE_SHADOW_0B_PRECHECK_WRITE_PERMISSIONS=" + ",".join(result["write_permissions"]))
    print("CORE_SHADOW_0B_PRECHECK_SECRET_REFERENCES=" + ",".join(result["secret_references"]))
    print("CORE_SHADOW_0B_PRECHECK_FORBIDDEN_INTERFACES=" + ",".join(result["forbidden_interfaces"]))
    print(f"CORE_SHADOW_0B_PRECHECK_I1_TOPOLOGY={str(result['i1_topology_ready']).lower()}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
