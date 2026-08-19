from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from superlocalmemory.storage.correction_cases import (
    CorrectionActor,
    CorrectionAuthorizationError,
    CorrectionCaseStore,
)
from superlocalmemory.storage.migrations import M042_correction_case_ledger as m042


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eg-slm-gt06-") as td:
        db = Path(td) / "memory.db"
        with sqlite3.connect(db) as conn:
            m042.apply(conn)
            assert m042.verify(conn)
            conn.execute(
                "CREATE TABLE atomic_facts ("
                "fact_id TEXT PRIMARY KEY, profile_id TEXT, scope TEXT, content TEXT)"
            )
            conn.execute(
                "INSERT INTO atomic_facts VALUES "
                "('price-old', 'wzw', 'project', '490 Euro'), "
                "('price-new', 'wzw', 'project', '510 Euro')"
            )
            conn.execute(
                "CREATE TABLE fact_temporal_validity ("
                "fact_id TEXT PRIMARY KEY, profile_id TEXT, valid_from TEXT, valid_until TEXT, "
                "system_created_at TEXT, system_expired_at TEXT, invalidated_by TEXT, "
                "invalidation_reason TEXT)"
            )
            conn.execute(
                "INSERT INTO fact_temporal_validity VALUES "
                "('price-old', 'wzw', '2026-08-01T00:00:00+00:00', NULL, "
                "'2026-08-01T00:00:00+00:00', NULL, NULL, NULL)"
            )
            conn.commit()

        trusted = CorrectionActor(
            actor_id="reviewer-1", actor_kind="human", trust_tier="operator_verified"
        )
        untrusted = CorrectionActor(
            actor_id="agent-unverified", actor_kind="agent", trust_tier="unverified"
        )
        store = CorrectionCaseStore(
            db,
            is_profile_active=lambda profile_id: profile_id == "wzw",
            is_actor_trusted=lambda actor: actor.actor_id == "reviewer-1",
        )

        proposed = store.propose(
            case_id="gt06-price-correction",
            profile_id="wzw",
            scope="project",
            predecessor_fact_id="price-old",
            successor_fact_id="price-new",
            reason_code="user_corrected_price",
            actor=trusted,
            idempotency_key="gt06-propose-1",
        )

        untrusted_blocked = False
        try:
            store.apply(
                proposed.case_id,
                expected_version=0,
                actor=untrusted,
                operation_id="gt06-untrusted-apply",
            )
        except CorrectionAuthorizationError:
            untrusted_blocked = True

        after_untrusted = store.get_case(proposed.case_id)

        applied = store.apply(
            proposed.case_id,
            expected_version=0,
            actor=trusted,
            operation_id="gt06-trusted-apply",
        )

        with sqlite3.connect(db) as conn:
            old_fact = conn.execute(
                "SELECT fact_id, profile_id, scope, content FROM atomic_facts WHERE fact_id='price-old'"
            ).fetchone()
            new_fact = conn.execute(
                "SELECT fact_id, profile_id, scope, content FROM atomic_facts WHERE fact_id='price-new'"
            ).fetchone()
            temporal = conn.execute(
                "SELECT valid_from, valid_until, system_created_at, system_expired_at, "
                "invalidated_by, invalidation_reason FROM fact_temporal_validity "
                "WHERE fact_id='price-old'"
            ).fetchone()
            case_row = conn.execute(
                "SELECT case_id, profile_id, scope, predecessor_fact_id, successor_fact_id, "
                "reason_code, status, version, proposed_by_actor_id, proposed_by_actor_kind, "
                "proposed_by_trust_tier, reviewed_by_actor_id, reviewed_at, applied_at, "
                "system_effective_at FROM correction_cases WHERE case_id=?",
                (proposed.case_id,),
            ).fetchone()
            events = conn.execute(
                "SELECT event_type, operation_id, actor_id, actor_kind, actor_trust_tier, "
                "expected_version, resulting_version, system_occurred_at "
                "FROM correction_events WHERE case_id=? ORDER BY rowid",
                (proposed.case_id,),
            ).fetchall()

        old_retained = old_fact == ("price-old", "wzw", "project", "490 Euro")
        new_retained = new_fact == ("price-new", "wzw", "project", "510 Euro")
        old_superseded = bool(
            temporal
            and temporal[3] is not None
            and temporal[4] == "price-new"
            and temporal[5] == "user_corrected_price"
        )
        correction_first_class = bool(
            case_row
            and case_row[2] == "project"
            and case_row[3] == "price-old"
            and case_row[4] == "price-new"
            and case_row[5] == "user_corrected_price"
            and case_row[6] == "applied"
        )
        provenance_retained = bool(
            case_row
            and case_row[8] == "reviewer-1"
            and case_row[10] == "operator_verified"
            and case_row[11] == "reviewer-1"
            and case_row[12] is not None
            and case_row[13] is not None
            and len(events) == 2
            and events[0][0] == "proposed"
            and events[1][0] == "applied"
        )
        untrusted_no_effect = (
            untrusted_blocked
            and after_untrusted.status == "proposed"
            and after_untrusted.version == 0
        )

        contract_pass = all(
            [
                correction_first_class,
                old_retained,
                new_retained,
                old_superseded,
                provenance_retained,
                untrusted_no_effect,
            ]
        )

        report = {
            "schema": "externes-gehirn.cross-project-runtime-evidence.v0.1",
            "candidate": "SuperLocalMemory",
            "version": "4.0.8",
            "release_commit": "a5438ee6028c9bd7ca30959a3d61d133c24592ed",
            "golden_test": "GT-06",
            "control": "NATIVE_REVIEW_GATED_CORRECTION_CASE_AND_TEMPORAL_HISTORY",
            "input": {
                "project": "wzw",
                "old_claim": "490 Euro",
                "correction": "510 Euro",
                "authorized_reviewer": "reviewer-1",
            },
            "native_semantic_mapping": {
                "knowledge_type_CORRECTION": "CorrectionCase with predecessor_fact_id/successor_fact_id and applied lifecycle",
                "old_epistemic_status_SUPERSEDED": "predecessor fact temporal record has system_expired_at and invalidated_by=successor",
                "provenance": "correction case + append-only correction_events with actor/trust/time/version",
                "history": "predecessor fact content remains stored after correction",
            },
            "observations": {
                "correction_first_class": correction_first_class,
                "untrusted_apply_blocked": untrusted_blocked,
                "untrusted_attempt_left_case_proposed": untrusted_no_effect,
                "trusted_apply_status": applied.status,
                "trusted_apply_version": applied.version,
                "old_fact_retained": old_retained,
                "new_fact_retained": new_retained,
                "old_fact_superseded_by_new": old_superseded,
                "provenance_and_events_retained": provenance_retained,
                "temporal_record": temporal,
                "correction_case": case_row,
                "correction_events": events,
            },
            "scope_note": "This probe validates GT-06 correction lifecycle semantics on SLM's native correction/history surface. It does not by itself prove all mandatory router fields or the full GT-01..GT-12 block.",
            "result": "PASS" if contract_pass else "FAIL",
            "critical_fail": not contract_pass,
            "reason": (
                "Native review-gated correction linked old and new claims, superseded the predecessor only after trusted review, retained old content, and retained correction provenance/history."
                if contract_pass
                else "One or more required GT-06 correction/history/authority properties were not preserved natively."
            ),
        }

        out = Path("reports/critical/slm_gt06_correction.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
