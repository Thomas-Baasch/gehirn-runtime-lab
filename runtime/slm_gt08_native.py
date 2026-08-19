from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from superlocalmemory.learning.cross_project import CrossProjectAggregator


def insert_memory(db: Path, profile: str, content: str, created_at: str) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO memories(profile_id, content, project_name, created_at) VALUES (?, ?, ?, ?)",
            (profile, content, profile, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def read_target_language(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT profile_id, key, value, confidence, evidence_count, contradictions, first_seen, last_seen "
            "FROM transferable_patterns WHERE profile_id = ? AND key = ? ORDER BY id",
            ("target", "language"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def main() -> int:
    now = datetime.now(UTC).isoformat()
    with tempfile.TemporaryDirectory(prefix="eg-slm-gt08-") as td:
        db = Path(td) / "slm.db"
        agg = CrossProjectAggregator(db)

        # Establish a current target preference from a first source profile.
        insert_memory(db, "source_python", "python service", now)
        insert_memory(db, "source_python", "python api", now)
        first_output = agg.aggregate(["source_python"], "target")
        first_rows = read_target_language(db)

        # Introduce a contradictory current source without declaring a correction.
        insert_memory(db, "source_rust", "rust service", now)
        insert_memory(db, "source_rust", "rust api", now)
        insert_memory(db, "source_rust", "rust worker", now)
        second_output = agg.aggregate(["source_rust"], "target")
        final_rows = read_target_language(db)

        first_value = first_rows[0]["value"] if first_rows else None
        final_value = final_rows[0]["value"] if final_rows else None
        contradictions = []
        if final_rows:
            try:
                contradictions = json.loads(final_rows[0].get("contradictions") or "[]")
            except Exception:
                contradictions = [str(final_rows[0].get("contradictions"))]

        winner_selected = final_value is not None and final_value != first_value
        single_current_row = len(final_rows) == 1
        contradiction_detected = bool(contradictions)

        # Contract GT-08 requires coexistence as CONFLICTING with no silent/current winner.
        # Detection metadata does not rescue the test if the native store still replaces the current value.
        contract_pass = contradiction_detected and not winner_selected and not single_current_row

        report = {
            "schema": "externes-gehirn.cross-project-runtime-evidence.v0.1",
            "candidate": "SuperLocalMemory",
            "version": "4.0.8",
            "release_commit": "a5438ee6028c9bd7ca30959a3d61d133c24592ed",
            "golden_test": "GT-08",
            "control": "NATIVE_CROSS_PROJECT_AGGREGATOR_NEGATIVE_CONTROL",
            "input": {
                "first_source": ["python service", "python api"],
                "contradictory_source": ["rust service", "rust api", "rust worker"],
                "target_profile": "target",
                "explicit_correction": False,
            },
            "native_outputs": {
                "first_aggregate": first_output,
                "second_aggregate": second_output,
                "first_target_rows": first_rows,
                "final_target_rows": final_rows,
            },
            "observations": {
                "first_value": first_value,
                "final_value": final_value,
                "contradiction_detected": contradiction_detected,
                "contradictions": contradictions,
                "winner_selected_and_current_value_changed": winner_selected,
                "final_current_row_count": len(final_rows),
                "old_current_value_preserved_as_separate_current_conflicting_record": not single_current_row,
            },
            "target_project_scope": "native profile_id=target",
            "epistemic_status_before": "NOT_NATIVELY_REPRESENTED_BY_THIS_SURFACE",
            "epistemic_status_after": "NOT_NATIVELY_REPRESENTED_BY_THIS_SURFACE",
            "provenance_history": {
                "native_contradiction_metadata_retained": contradiction_detected,
                "separate_old_current_record_retained": not single_current_row,
            },
            "policy_access_decision": "NOT_APPLICABLE_TO_GT08_NATIVE_AGGREGATOR_CONTROL",
            "result": "PASS" if contract_pass else "FAIL",
            "critical_fail": not contract_pass,
            "reason": (
                "Native aggregator kept conflicting states without selecting a current winner."
                if contract_pass
                else "Native aggregator detected contradiction but selected/upserted a current winner instead of preserving both current claims as CONFLICTING."
            ),
        }

        out = Path("reports/critical/slm_gt08_native.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
