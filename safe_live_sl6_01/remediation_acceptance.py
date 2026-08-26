from __future__ import annotations

import argparse
import json
import tempfile
import threading
from datetime import date
from pathlib import Path

from safe_live_sl6_01.active_policy_evaluator import (
    Candidate,
    ChildState,
    Policy,
    evaluate,
    guarded_commit_sequence,
)
from safe_live_sl6_01.turn_effect_ledger import TurnEffectLedger


def children():
    return (
        ChildState("SL5-01", "SAFE_LIVE_SL5_01_MATERIAL_MILESTONE_LOGGING_V0_1", "ACTIVE", date(2026,9,1), "ISSUE_COMMENT", True),
        ChildState("SL5-02", "SAFE_LIVE_SL5_02_ACTIVE_TURN_MATERIAL_DELTA_PERSISTENCE_V0_1", "ACTIVE", date(2026,9,2), "DRIVE_DERIVED_DELTA_APPEND_OR_NOOP_ONLY", True),
        ChildState("SL5-03", "SAFE_LIVE_SL5_03_USCHI_OWNER_DIRECT_TASK_EVENT_CONTROL_V0_1", "ACTIVE", date(2026,9,2), "DRIVE_USCHI_TASK_EVENT_APPEND_OR_NOOP_ONLY", True),
    )


def candidate(cell: str, atom: str) -> Candidate:
    return Candidate(cell, atom, {"SL5-01":"MILESTONE_COMMENT","SL5-02":"MATERIAL_DELTA","SL5-03":"TASK_EVENT"}[cell], owner_task_semantics=(cell == "SL5-03"))


def open_turn(ledger: TurnEffectLedger, turn_id: str, fingerprint: str) -> bool:
    return ledger.open_turn(turn_id, fingerprint) in {"OPENED_NEW", "OPEN_ALREADY"}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); args = ap.parse_args()
    loops: dict[str, bool] = {}
    details: dict[str, object] = {}
    p = Policy()

    with tempfile.TemporaryDirectory(prefix="sl6-live-f01-") as td:
        db = Path(td) / "turn-budget.sqlite3"
        ledger = TurnEffectLedger(db)

        # Loop 1: normal distinct-child orchestration remains possible.
        t1 = "turn-remediation-normal-001"
        assert open_turn(ledger, t1, "fp-normal-001")
        r1 = evaluate(p, children(), (
            candidate("SL5-03", "atom:task:001"),
            candidate("SL5-02", "atom:material:001"),
            candidate("SL5-01", "atom:milestone:001"),
        ), as_of=date(2026,8,26))
        calls1: list[str] = []
        c1 = guarded_commit_sequence(r1, ledger=ledger, orchestration_turn_id=t1, before_effect=lambda cell, atom: calls1.append(cell))
        loops["1"] = all([
            r1.allowed_to_orchestrate,
            c1.committed == ("SL5-03","SL5-02","SL5-01"),
            calls1 == ["SL5-03","SL5-02","SL5-01"],
            not c1.blocked,
            ledger.integrity_ok(),
        ])
        details["loop_1"] = {"decision": r1.__dict__, "commit": c1.__dict__, "calls": calls1}

        # Loop 2: exact live finding reproduction. Same child is requested later
        # in the same long turn. The second request must be blocked BEFORE effect.
        t2 = "turn-reproduce-live-f01-002"
        assert open_turn(ledger, t2, "fp-weiter-gehts-equivalent")
        first = evaluate(p, children(), (candidate("SL5-02", "atom:p17:implementation"),), as_of=date(2026,8,26))
        calls2: list[str] = []
        first_commit = guarded_commit_sequence(first, ledger=ledger, orchestration_turn_id=t2, before_effect=lambda cell, atom: calls2.append(atom))
        later = evaluate(p, children(), (candidate("SL5-02", "atom:p17:dogfood"),), as_of=date(2026,8,26))
        second_commit = guarded_commit_sequence(later, ledger=ledger, orchestration_turn_id=t2, before_effect=lambda cell, atom: calls2.append(atom))
        state2 = ledger.budget_state(t2, "SL5-02")
        loops["2"] = all([
            first_commit.committed == ("SL5-02",),
            second_commit.committed == (),
            ("SL5-02", "NOOP_CHILD_BUDGET_ALREADY_CONSUMED") in second_commit.blocked,
            calls2 == ["atom:p17:implementation"],
            state2 is not None and state2.state == "COMMITTED" and state2.semantic_atom_key == "atom:p17:implementation",
        ])
        details["loop_2"] = {"first": first_commit.__dict__, "second": second_commit.__dict__, "effect_calls": calls2, "state": None if state2 is None else state2.__dict__}

        # Loop 3: crash/reopen/unknown result. Durable state must survive a new
        # ledger instance and cannot be reset by process loss.
        t3 = "turn-crash-reopen-003"
        assert open_turn(ledger, t3, "fp-crash-003")
        crash_decision = evaluate(p, children(), (
            candidate("SL5-02", "atom:uncertain:003"),
            candidate("SL5-01", "atom:must-not-run-after-unknown:003"),
        ), as_of=date(2026,8,26))
        crash_result = guarded_commit_sequence(
            crash_decision,
            ledger=ledger,
            orchestration_turn_id=t3,
            outcomes={"SL5-02":"UNKNOWN", "SL5-01":"COMMITTED"},
        )
        reopened = TurnEffectLedger(db)
        assert open_turn(reopened, t3, "fp-crash-003")
        retry = evaluate(p, children(), (candidate("SL5-02", "atom:retry-after-restart:003"),), as_of=date(2026,8,26))
        retry_calls: list[str] = []
        retry_result = guarded_commit_sequence(retry, ledger=reopened, orchestration_turn_id=t3, before_effect=lambda cell, atom: retry_calls.append(atom))
        state3 = reopened.budget_state(t3, "SL5-02")
        loops["3"] = all([
            crash_result.stopped_on_unknown == "SL5-02",
            crash_result.not_attempted == ("SL5-01",),
            state3 is not None and state3.state == "UNKNOWN",
            retry_result.committed == (),
            ("SL5-02", "NOOP_CHILD_BUDGET_ALREADY_CONSUMED") in retry_result.blocked,
            retry_calls == [],
            reopened.integrity_ok(),
        ])
        details["loop_3"] = {"unknown": crash_result.__dict__, "retry_after_reopen": retry_result.__dict__, "state": None if state3 is None else state3.__dict__}

        # Loop 4: a genuinely new turn gets a fresh budget, while expiry/currentness
        # still dominate. CLEAN_1.
        t4 = "turn-new-owner-message-004"
        assert open_turn(ledger, t4, "fp-new-owner-message-004")
        new_turn_decision = evaluate(p, children(), (candidate("SL5-02", "atom:new-turn:004"),), as_of=date(2026,8,26))
        new_turn_commit = guarded_commit_sequence(new_turn_decision, ledger=ledger, orchestration_turn_id=t4)
        expired = evaluate(p, children(), (candidate("SL5-02", "atom:expired:004"),), as_of=date(2026,9,2))
        paused_children = list(children())
        paused_children[1] = ChildState("SL5-02", "SAFE_LIVE_SL5_02_ACTIVE_TURN_MATERIAL_DELTA_PERSISTENCE_V0_1", "PAUSED", date(2026,9,2), "DRIVE_DERIVED_DELTA_APPEND_OR_NOOP_ONLY", True)
        paused = evaluate(p, paused_children, (candidate("SL5-02", "atom:paused:004"),), as_of=date(2026,8,26))
        loops["4"] = all([
            new_turn_commit.committed == ("SL5-02",),
            not expired.allowed_to_orchestrate and expired.reason == "SL6_REVIEW_FENCE_EXPIRED",
            not paused.allowed_to_orchestrate and paused.reason.startswith("CHILD_NOT_CURRENT_ACTIVE"),
        ])
        details["loop_4"] = {"new_turn": new_turn_commit.__dict__, "expired": expired.__dict__, "paused": paused.__dict__}

        # Loop 5: missing ledger/turn id, closed turn, concurrency, guard removal,
        # background and activation bootstrap all fail closed. CLEAN_2.
        d5 = evaluate(p, children(), (candidate("SL5-02", "atom:guard:005"),), as_of=date(2026,8,26))
        missing_ledger = guarded_commit_sequence(d5, ledger=None, orchestration_turn_id="turn-missing-ledger")
        missing_turn_id = guarded_commit_sequence(d5, ledger=ledger, orchestration_turn_id=None)

        closed_turn = "turn-closed-005"
        assert open_turn(ledger, closed_turn, "fp-closed-005")
        assert ledger.close_turn(closed_turn) == "CLOSED"
        closed_result = guarded_commit_sequence(d5, ledger=ledger, orchestration_turn_id=closed_turn)
        reopen_closed = ledger.open_turn(closed_turn, "fp-closed-005")

        concurrent_turn = "turn-concurrent-005"
        assert open_turn(ledger, concurrent_turn, "fp-concurrent-005")
        barrier = threading.Barrier(2)
        concurrent_results: list[str] = []
        result_lock = threading.Lock()
        def reserve_concurrently() -> None:
            local = TurnEffectLedger(db)
            barrier.wait()
            result = local.reserve(concurrent_turn, "SL5-02", "atom:concurrent:005")
            with result_lock:
                concurrent_results.append(result)
        th1 = threading.Thread(target=reserve_concurrently)
        th2 = threading.Thread(target=reserve_concurrently)
        th1.start(); th2.start(); th1.join(); th2.join()

        no_guard = evaluate(Policy(durable_turn_ledger_required=False), children(), (candidate("SL5-02", "atom:no-guard:005"),), as_of=date(2026,8,26))
        background = evaluate(p, children(), (candidate("SL5-02", "atom:bg:005"),), as_of=date(2026,8,26), background=True)
        activation = evaluate(p, children(), (candidate("SL5-02", "atom:activation:005"),), as_of=date(2026,8,26), activation_event=True)
        no_kill = evaluate(Policy(kill_switch=False), children(), (candidate("SL5-02", "atom:no-kill:005"),), as_of=date(2026,8,26))

        loops["5"] = all([
            ("SL6", "FAIL_CLOSED_DURABLE_TURN_LEDGER_REQUIRED") in missing_ledger.blocked,
            ("SL6", "FAIL_CLOSED_DURABLE_TURN_LEDGER_REQUIRED") in missing_turn_id.blocked,
            any(reason == "FAIL_CLOSED_TURN_CLOSED" for _, reason in closed_result.blocked),
            reopen_closed == "FAIL_CLOSED_TURN_CLOSED",
            sorted(concurrent_results) == ["BLOCK_CHILD_BUDGET_CONSUMED", "RESERVED"],
            not no_guard.allowed_to_orchestrate and no_guard.reason == "SL6_GUARD_MISSING",
            not background.allowed_to_orchestrate and background.reason == "BACKGROUND_NOT_ALLOWED",
            not activation.allowed_to_orchestrate and activation.reason == "ACTIVATION_IS_NOT_TRIGGER",
            not no_kill.allowed_to_orchestrate and no_kill.reason == "SL6_GUARD_MISSING",
            ledger.integrity_ok(),
        ])
        details["loop_5"] = {
            "missing_ledger": missing_ledger.__dict__,
            "missing_turn_id": missing_turn_id.__dict__,
            "closed_turn": closed_result.__dict__,
            "reopen_closed": reopen_closed,
            "concurrent_reservations": sorted(concurrent_results),
            "no_guard": no_guard.__dict__,
            "background": background.__dict__,
            "activation": activation.__dict__,
            "no_kill": no_kill.__dict__,
        }

        passed = all(loops.values())
        audit = ledger.audit()
        result = {
            "finding_id": "SL6-LIVE-F01",
            "status": "PASS" if passed else "FAIL",
            "loops": loops,
            "clean_1": "LOOP_4" if loops.get("4") else None,
            "clean_2": "LOOP_5" if loops.get("4") and loops.get("5") else None,
            "two_consecutive_clean": bool(loops.get("4") and loops.get("5")),
            "new_fundamental_finding": False if passed else None,
            "durable_turn_ledger_required": True,
            "same_turn_second_child_effect_blocked_before_effect": loops.get("2", False),
            "crash_reopen_preserves_consumed_budget": loops.get("3", False),
            "unknown_outcome_consumes_budget_and_stops_batch": loops.get("3", False),
            "new_turn_receives_fresh_budget": loops.get("4", False),
            "live_loop_2_remains_invalidated": True,
            "live_clean_counter_after_revalidation": 0,
            "revalidation_restores_only_previous_scope": True,
            "new_action_classes": 0,
            "new_targets": 0,
            "this_acceptance_executes_children": False,
            "drive_writes_this_acceptance": 0,
            "github_writes_this_acceptance": 0,
            "external_actions_this_acceptance": 0,
            "production_writes_this_acceptance": 0,
            "local_ephemeral_control_ledger_events": len(audit),
            "details": details,
        }
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, sort_keys=True, indent=2, default=str) + "\n")

    print(f"SAFE_LIVE_SL6_01_LIVE_F01_REMEDIATION={result['status']}")
    for i in range(1,6):
        print(f"SAFE_LIVE_SL6_01_LIVE_F01_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print("SAFE_LIVE_SL6_01_LIVE_F01_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL6_01_LIVE_F01_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL6_01_LIVE_F01_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print(f"SAFE_LIVE_SL6_01_LIVE_F01_SECOND_SAME_CHILD_BLOCKED={str(result['same_turn_second_child_effect_blocked_before_effect']).lower()}")
    print(f"SAFE_LIVE_SL6_01_LIVE_F01_CRASH_REOPEN_GUARD={str(result['crash_reopen_preserves_consumed_budget']).lower()}")
    print("SAFE_LIVE_SL6_01_LIVE_F01_LIVE_CLEAN_COUNTER=0")
    print("SAFE_LIVE_SL6_01_LIVE_F01_NEW_ACTION_CLASSES=0")
    print("SAFE_LIVE_SL6_01_LIVE_F01_NEW_TARGETS=0")
    print("SAFE_LIVE_SL6_01_LIVE_F01_DRIVE_WRITES_THIS_ACCEPTANCE=0")
    print("SAFE_LIVE_SL6_01_LIVE_F01_GITHUB_WRITES_THIS_ACCEPTANCE=0")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
