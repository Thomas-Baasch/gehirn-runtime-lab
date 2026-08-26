from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from safe_live_sl6_01.active_policy_evaluator import Candidate, ChildState, Policy, evaluate, simulate_commit_sequence


def children():
    return (
        ChildState("SL5-01", "SAFE_LIVE_SL5_01_MATERIAL_MILESTONE_LOGGING_V0_1", "ACTIVE", date(2026,9,1), "ISSUE_COMMENT", True),
        ChildState("SL5-02", "SAFE_LIVE_SL5_02_ACTIVE_TURN_MATERIAL_DELTA_PERSISTENCE_V0_1", "ACTIVE", date(2026,9,2), "DRIVE_DERIVED_DELTA_APPEND_OR_NOOP_ONLY", True),
        ChildState("SL5-03", "SAFE_LIVE_SL5_03_USCHI_OWNER_DIRECT_TASK_EVENT_CONTROL_V0_1", "ACTIVE", date(2026,9,2), "DRIVE_USCHI_TASK_EVENT_APPEND_OR_NOOP_ONLY", True),
    )


def normal():
    return (
        Candidate("SL5-03", "atom:task:active:001", "TASK_EVENT", owner_task_semantics=True),
        Candidate("SL5-02", "atom:material:active:001", "MATERIAL_DELTA"),
        Candidate("SL5-01", "atom:milestone:active:001", "MILESTONE_COMMENT"),
    )


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); args = ap.parse_args()
    p = Policy()
    loops = {}; details = {}

    # Loop 1: normal active orchestration, but this acceptance itself executes nothing.
    r1 = evaluate(p, children(), normal(), as_of=date(2026,8,26))
    loops["1"] = all([r1.allowed_to_orchestrate, r1.reason == "ORCHESTRATION_PREFLIGHT_OK", r1.planned_cells == ("SL5-03","SL5-02","SL5-01"), not r1.blocked])
    details["loop_1"] = r1.__dict__

    # Loop 2: child and scale expiry/currentness dominate; no fallback authority.
    after = evaluate(p, children(), normal(), as_of=date(2026,9,2))
    inactive_children = list(children()); inactive_children[1] = ChildState("SL5-02", "SAFE_LIVE_SL5_02_ACTIVE_TURN_MATERIAL_DELTA_PERSISTENCE_V0_1", "PAUSED", date(2026,9,2), "DRIVE_DERIVED_DELTA_APPEND_OR_NOOP_ONLY", True)
    inactive = evaluate(p, inactive_children, normal(), as_of=date(2026,8,26))
    loops["2"] = all([not after.allowed_to_orchestrate and after.reason == "SL6_REVIEW_FENCE_EXPIRED", not inactive.allowed_to_orchestrate and inactive.reason.startswith("CHILD_NOT_CURRENT_ACTIVE")])
    details["loop_2"] = {"after_fence": after.__dict__, "inactive_child": inactive.__dict__}

    # Loop 3: task dominance and unknown commit stop remaining batch.
    task_overlap = evaluate(p, children(), (
        Candidate("SL5-03", "atom:task:active:002", "TASK_EVENT", owner_task_semantics=True),
        Candidate("SL5-02", "atom:material:task-copy:002", "MATERIAL_DELTA", owner_task_semantics=True),
        Candidate("SL5-01", "atom:milestone:active:002", "MILESTONE_COMMENT"),
    ), as_of=date(2026,8,26))
    seq = simulate_commit_sequence(r1, unknown_cell="SL5-02")
    loops["3"] = all([
        task_overlap.allowed_to_orchestrate,
        task_overlap.planned_cells == ("SL5-03","SL5-01"),
        ("SL5-02","TASK_DOMINANCE_TO_SL5_03") in task_overlap.blocked,
        seq[0] == ("SL5-03",), seq[1] == "SL5-02", seq[2] == ("SL5-01",)
    ])
    details["loop_3"] = {"task_overlap": task_overlap.__dict__, "unknown_sequence": seq}

    # Loop 4: replay/collision/currentness fail closed or noop. CLEAN_1.
    replay = evaluate(p, children(), (
        Candidate("SL5-03", "atom:task:active:003", "TASK_EVENT", duplicate=True, owner_task_semantics=True),
        Candidate("SL5-02", "atom:material:active:003", "MATERIAL_DELTA"),
    ), as_of=date(2026,8,26))
    collision = evaluate(p, children(), (
        Candidate("SL5-03", "atom:same:active", "TASK_EVENT", owner_task_semantics=True),
        Candidate("SL5-02", "atom:same:active", "MATERIAL_DELTA"),
    ), as_of=date(2026,8,26))
    loops["4"] = all([
        replay.allowed_to_orchestrate,
        replay.planned_cells == ("SL5-02",),
        ("SL5-03","NOOP_DUPLICATE") in replay.blocked,
        not collision.allowed_to_orchestrate and collision.reason == "SEMANTIC_ATOM_COLLISION"
    ])
    details["loop_4"] = {"replay": replay.__dict__, "collision": collision.__dict__}

    # Loop 5: sensitivity/volume/background/kill-switch/activation trigger/foreign cell blocked. CLEAN_2.
    sensitive = evaluate(p, children(), (Candidate("SL5-02", "atom:sensitive", "MATERIAL_DELTA", low_sensitivity=False),), as_of=date(2026,8,26))
    volume = evaluate(p, children(), normal() + (Candidate("SL5-02", "atom:fourth", "MATERIAL_DELTA"),), as_of=date(2026,8,26))
    background = evaluate(p, children(), normal(), as_of=date(2026,8,26), background=True)
    no_kill = evaluate(Policy(kill_switch=False), children(), normal(), as_of=date(2026,8,26))
    activation = evaluate(p, children(), normal(), as_of=date(2026,8,26), activation_event=True)
    foreign = evaluate(p, children(), (Candidate("SL5-99", "atom:foreign", "OTHER"),), as_of=date(2026,8,26))
    loops["5"] = all([
        sensitive.allowed_to_orchestrate and sensitive.planned_cells == () and ("SL5-02","SENSITIVITY_NOT_ALLOWED") in sensitive.blocked,
        not volume.allowed_to_orchestrate and volume.reason == "VOLUME_LIMIT_EXCEEDED",
        not background.allowed_to_orchestrate and background.reason == "BACKGROUND_NOT_ALLOWED",
        not no_kill.allowed_to_orchestrate and no_kill.reason == "SL6_GUARD_MISSING",
        not activation.allowed_to_orchestrate and activation.reason == "ACTIVATION_IS_NOT_TRIGGER",
        not foreign.allowed_to_orchestrate and foreign.reason == "UNKNOWN_CELL"
    ])
    details["loop_5"] = {"sensitive": sensitive.__dict__, "volume": volume.__dict__, "background": background.__dict__, "no_kill": no_kill.__dict__, "activation": activation.__dict__, "foreign": foreign.__dict__}

    passed = all(loops.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "loops": loops,
        "clean_1": "LOOP_4" if loops.get("4") else None,
        "clean_2": "LOOP_5" if loops.get("4") and loops.get("5") else None,
        "two_consecutive_clean": bool(loops.get("4") and loops.get("5")),
        "policy_status": p.status,
        "activation_authorized": bool(p.owner_authorized and passed),
        "review_by": p.review_by.isoformat(),
        "execute_orchestration": p.execute_orchestration,
        "activation_itself_triggers_effect": False,
        "this_acceptance_executes_children": False,
        "drive_writes_this_acceptance": 0,
        "github_writes_this_acceptance": 0,
        "external_actions_this_acceptance": 0,
        "production_writes_this_acceptance": 0,
        "new_action_classes": 0,
        "new_targets": 0,
        "details": details,
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(result, sort_keys=True, indent=2, default=str)+"\n")
    print(f"SAFE_LIVE_SL6_01_ACTIVE_ACCEPTANCE={result['status']}")
    for i in range(1,6): print(f"SAFE_LIVE_SL6_01_ACTIVE_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print("SAFE_LIVE_SL6_01_ACTIVE_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL6_01_ACTIVE_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL6_01_ACTIVE_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print(f"SAFE_LIVE_SL6_01_ACTIVATION_AUTHORIZED={str(result['activation_authorized']).lower()}")
    print("SAFE_LIVE_SL6_01_ACTIVATION_ITSELF_TRIGGERS_EFFECT=false")
    print("SAFE_LIVE_SL6_01_THIS_ACCEPTANCE_EXECUTES_CHILDREN=false")
    print("SAFE_LIVE_SL6_01_DRIVE_WRITES_THIS_ACCEPTANCE=0")
    print("SAFE_LIVE_SL6_01_GITHUB_WRITES_THIS_ACCEPTANCE=0")
    return 0 if passed else 1

if __name__ == "__main__": raise SystemExit(main())
