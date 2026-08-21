from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


OUT = Path("reports/direct_exchange")
OUT.mkdir(parents=True, exist_ok=True)


def run_gate(module_name: str, source_report: str, target_report: str, *, recovery: bool = False) -> dict:
    bootstrap = [
        "from governance.direct_qdrant_index import DirectQdrantIndex",
        "import governance.memos_composition as mc",
        "mc.PartitionedMemOSIndex = DirectQdrantIndex",
    ]
    if recovery:
        bootstrap += [
            "import governance.memos_recovery as mr",
            "mr.RecoverablePartitionedMemOSIndex = DirectQdrantIndex",
        ]
    bootstrap += [
        f"import {module_name} as gate",
        "raise SystemExit(gate.main())",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    subprocess.run([sys.executable, "-c", ";".join(bootstrap)], check=True, env=env)
    src = Path(source_report)
    dst = OUT / target_report
    shutil.copy2(src, dst)
    return json.loads(dst.read_text(encoding="utf-8"))


def main() -> int:
    critical = run_gate(
        "critical.governance_memos_composed_gate",
        "reports/composed/governance_memos_critical.json",
        "direct_qdrant_critical.json",
    )
    remaining = run_gate(
        "critical.governance_memos_remaining_gate",
        "reports/composed/governance_memos_remaining.json",
        "direct_qdrant_remaining.json",
    )
    recovery = run_gate(
        "critical.governance_memos_recovery_gate",
        "reports/composed/governance_memos_recovery.json",
        "direct_qdrant_recovery.json",
        recovery=True,
    )

    checks = {
        "direct_gt04_gt05_gt06_gt08_gt09_gt12": critical.get("result") == "PASS" and critical.get("passed") == 6,
        "direct_gt01_gt02_gt03_gt07_gt10_gt11": remaining.get("result") == "PASS" and remaining.get("passed") == 6,
        "direct_recovery_fault_injection": recovery.get("result") == "PASS" and recovery.get("passed") == 8,
    }
    summary = {
        "schema": "externes-gehirn.direct-qdrant-full-exchange-evidence",
        "version": "0.1.0",
        "backend": "direct qdrant-client 1.16.0",
        "test_truth_reuse": "unchanged existing composed Golden Test and recovery gate modules; only derived-index class injected before module import",
        "critical": f"{critical.get('passed')}/{critical.get('total')}",
        "remaining": f"{remaining.get('passed')}/{remaining.get('total')}",
        "recovery": f"{recovery.get('passed')}/{recovery.get('total')}",
        "checks": checks,
        "passed": sum(1 for value in checks.values() if value),
        "total": len(checks),
        "result": "PASS" if all(checks.values()) else "FAIL",
        "scope_limit": "functional/recovery exchange proof for derived retrieval backend only; MemoryOS package removal and production semantic-quality benchmark remain separate",
        "stack_decision": "NOT_MADE",
    }
    (OUT / "direct_qdrant_full_exchange_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
