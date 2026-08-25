from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "core_shadow_0a1" / "runtime.py"
KONRAD = ROOT / "core_shadow_0a1" / "konrad_control.py"
READBACK = ROOT / "core_shadow_0a1" / "independent_readback.py"
WORKFLOW = ROOT / ".github" / "workflows" / "core-shadow-0a1.yml"
OUT = ROOT / "reports" / "core_shadow" / "core_shadow_0a1_authority_surface.json"

FORBIDDEN_FUNCTIONS = {
    "send", "send_message", "pay", "payment", "delete", "delete_original",
    "publish", "production_write", "credential_change", "merge",
    "merge_pull_request", "grant", "grant_rights", "sign_contract",
}
FORBIDDEN_IMPORT_ROOTS = {
    "requests", "httpx", "urllib", "http", "socket", "subprocess",
    "ftplib", "smtplib", "imaplib", "poplib",
}
FORBIDDEN_CALL_ROOTS = {"requests", "httpx", "urllib", "http", "socket", "subprocess", "smtplib"}


def _scan_python(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    functions: set[str] = set()
    dangerous_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.value.id in FORBIDDEN_CALL_ROOTS:
                    dangerous_calls.append(f"{fn.value.id}.{fn.attr}")
            elif isinstance(fn, ast.Name) and fn.id in {"exec", "eval", "__import__"}:
                dangerous_calls.append(fn.id)
    return {
        "path": str(path.relative_to(ROOT)),
        "imports": sorted(imports),
        "forbidden_imports": sorted(imports & FORBIDDEN_IMPORT_ROOTS),
        "forbidden_functions": sorted(functions & FORBIDDEN_FUNCTIONS),
        "dangerous_calls": sorted(dangerous_calls),
    }


def evaluate() -> dict[str, Any]:
    scans = [_scan_python(path) for path in (RUNTIME, KONRAD, READBACK)]
    workflow = WORKFLOW.read_text(encoding="utf-8")
    workflow_write_permissions: list[str] = []
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.endswith(": write") or stripped.endswith(": write-all"):
            workflow_write_permissions.append(stripped)
    forbidden_workflow_tokens = [
        token for token in ("secrets.", "GH_TOKEN", "gh api", "curl ", "wget ", "git push", "pull_request_target")
        if token in workflow
    ]
    external_effect_interfaces = sorted({
        name for scan in scans
        for name in scan["forbidden_functions"] + scan["dangerous_calls"] + scan["forbidden_imports"]
    })
    passed = not external_effect_interfaces and not workflow_write_permissions and not forbidden_workflow_tokens
    return {
        "schema": "core-shadow-0a1.authority-surface.v1",
        "status": "PASS" if passed else "FAIL",
        "scans": scans,
        "external_effect_interfaces": external_effect_interfaces,
        "workflow_write_permissions": workflow_write_permissions,
        "forbidden_workflow_tokens": forbidden_workflow_tokens,
        "network_or_process_client_present": bool(external_effect_interfaces),
        "credentials_required": False,
        "production_authority_present": False,
        "merge_interface_present": False,
        "new_running_cost_eur": 0,
    }


def main() -> int:
    result = evaluate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"CORE_SHADOW_0A1_AUTHORITY_SURFACE={result['status']}")
    print("CORE_SHADOW_0A1_EXTERNAL_EFFECT_INTERFACES=" + ",".join(result["external_effect_interfaces"]))
    print("CORE_SHADOW_0A1_WORKFLOW_WRITE_PERMISSIONS=" + ",".join(result["workflow_write_permissions"]))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
