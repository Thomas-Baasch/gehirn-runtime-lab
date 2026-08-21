from __future__ import annotations

import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path


def main() -> int:
    checks: dict[str, bool] = {}

    checks["memos_module_absent"] = importlib.util.find_spec("memos") is None
    try:
        metadata.distribution("MemoryOS")
    except metadata.PackageNotFoundError:
        checks["memoryos_distribution_absent"] = True
    else:
        checks["memoryos_distribution_absent"] = False

    # Product-neutral Canon/governance must import without MemoryOS installed.
    import governance.memos_composition as composition
    from governance.direct_qdrant_index import DirectQdrantIndex

    checks["product_neutral_composition_imports_without_memoryos"] = hasattr(
        composition, "CanonicalSQLiteStore"
    ) and hasattr(composition, "GovernedMemOSService")
    checks["direct_backend_available"] = DirectQdrantIndex is not None

    # Reuse the exact exchange proof. Its child processes inherit this environment,
    # so the unchanged 12/12 + 8/8 gates must pass without a MemoryOS installation.
    from critical.direct_qdrant_full_exchange_gate import main as exchange_main

    exchange_rc = exchange_main()
    summary_path = Path("reports/direct_exchange/direct_qdrant_full_exchange_summary.json")
    exchange = json.loads(summary_path.read_text(encoding="utf-8"))
    checks["unchanged_exchange_gate_passed_without_memoryos"] = (
        exchange_rc == 0
        and exchange.get("result") == "PASS"
        and exchange.get("critical") == "6/6"
        and exchange.get("remaining") == "6/6"
        and exchange.get("recovery") == "8/8"
        and exchange.get("checks", {}).get("direct_backend_injection_asserted_before_each_gate") is True
    )

    summary = {
        "schema": "externes-gehirn.direct-qdrant-no-memoryos-evidence",
        "version": "0.1.0",
        "backend": "direct qdrant-client 1.16.0",
        "environment": "MemoryOS distribution and memos import intentionally absent",
        "critical": exchange.get("critical"),
        "remaining": exchange.get("remaining"),
        "recovery": exchange.get("recovery"),
        "checks": checks,
        "passed": sum(1 for value in checks.values() if value),
        "total": len(checks),
        "result": "PASS" if all(checks.values()) else "FAIL",
        "scope_limit": "proves derived Direct-Qdrant path and product-neutral Canon/governance no longer require MemoryOS installation; separate MemOS regression job proves candidate path still works when installed",
        "stack_decision": "NOT_MADE",
    }
    out = Path("reports/direct_exchange/direct_qdrant_no_memoryos_summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
