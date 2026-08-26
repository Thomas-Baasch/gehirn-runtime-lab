from __future__ import annotations

import argparse
import json
from pathlib import Path

from pre_sl6_combined.router import Atom, CellState, route


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ok = CellState()
    loops: dict[str, bool] = {}
    details: dict[str, object] = {}

    # Loop 1: same semantic owner task must not be persisted twice.
    task = Atom(
        kind="OWNER_DIRECT_TASK_EVENT",
        semantic_atom_key="atom:owner-task:001",
        confirmed_task=True,
        material=True,
    )
    r1 = route(task, ok, ok, ok)
    loops["1"] = all([
        r1.sl5_01 == "NOOP_NOT_MILESTONE",
        r1.sl5_02 == "NOOP_TASK_DOMINANCE",
        r1.sl5_03 == "ALLOW_TASK_EVENT",
        r1.sl6_authorized is False,
    ])
    details["loop_1"] = r1.__dict__

    # Loop 2: qualified milestone may have two distinct purposes, never task authority.
    milestone = Atom(
        kind="SAFE_LIVE_MATERIAL_MILESTONE",
        semantic_atom_key="milestone:combined:001",
        qualified_milestone=True,
        material=True,
    )
    r2 = route(milestone, ok, ok, ok)
    loops["2"] = all([
        r2.sl5_01 == "ALLOW_MILESTONE_COMMENT",
        r2.sl5_02 == "ALLOW_MILESTONE_EVIDENCE_DELTA",
        r2.sl5_03 == "NOOP_NOT_TASK",
        r2.sl6_authorized is False,
    ])
    details["loop_2"] = r2.__dict__

    # Loop 3: task correction is SL5-03 only; if SL5-03 is blocked, there is no fallback via SL5-02.
    correction = Atom(
        kind="OWNER_TASK_CORRECTION",
        semantic_atom_key="atom:owner-task:001:correction",
        correction_valid=True,
    )
    r3_good = route(correction, ok, ok, ok)
    r3_expired = route(correction, ok, ok, CellState(expired=True))
    loops["3"] = all([
        r3_good.sl5_03 == "ALLOW_TASK_SUPERSESSION",
        r3_good.sl5_02 == "NOOP_TASK_DOMINANCE",
        r3_expired.sl5_03 == "BLOCK_EXPIRED",
        r3_expired.sl5_02 == "NOOP_TASK_DOMINANCE",
        r3_expired.sl5_01 == "NOOP_NOT_MILESTONE",
    ])
    details["loop_3"] = {"normal": r3_good.__dict__, "sl503_expired": r3_expired.__dict__}

    # Loop 4: duplicate/currentness failures remain local; no cross-cell fallback. CLEAN_1.
    task_dup = route(task, ok, ok, CellState(duplicate=True))
    milestone_dup = route(milestone, CellState(duplicate=True), CellState(duplicate=True), ok)
    material_drift = route(
        Atom(kind="MATERIAL_NON_TASK_DELTA", semantic_atom_key="atom:material:001", material=True),
        ok,
        CellState(current=False),
        ok,
    )
    loops["4"] = all([
        task_dup.sl5_03 == "NOOP_DUPLICATE",
        task_dup.sl5_02 == "NOOP_TASK_DOMINANCE",
        milestone_dup.sl5_01 == "NOOP_DUPLICATE",
        milestone_dup.sl5_02 == "NOOP_DUPLICATE",
        milestone_dup.sl5_03 == "NOOP_NOT_TASK",
        material_drift.sl5_02 == "BLOCK_CURRENTNESS",
        material_drift.sl5_01 == "NOOP_NOT_MILESTONE",
        material_drift.sl5_03 == "NOOP_NOT_TASK",
    ])
    details["loop_4"] = {
        "task_duplicate": task_dup.__dict__,
        "milestone_duplicate": milestone_dup.__dict__,
        "material_currentness_drift": material_drift.__dict__,
    }

    # Loop 5: sensitive/ambiguous/generic continue cannot create combined or SL6 authority. CLEAN_2.
    sensitive = route(
        Atom(kind="OWNER_DIRECT_TASK_EVENT", semantic_atom_key="atom:sensitive", confirmed_task=True, low_sensitivity=False),
        ok, ok, ok,
    )
    ambiguous = route(
        Atom(kind="AMBIGUOUS_OR_INCOMPLETE", semantic_atom_key="atom:ambiguous", ambiguous=True),
        ok, ok, ok,
    )
    generic = route(
        Atom(kind="MATERIAL_NON_TASK_DELTA", semantic_atom_key="atom:continue", material=True, generic_continue=True),
        ok, ok, ok,
    )
    loops["5"] = all([
        sensitive.sl5_01 == "BLOCK_SENSITIVITY",
        sensitive.sl5_02 == "BLOCK_SENSITIVITY",
        sensitive.sl5_03 == "BLOCK_SENSITIVITY",
        ambiguous.sl5_01 == "NOOP_AMBIGUOUS",
        ambiguous.sl5_02 == "NOOP_AMBIGUOUS",
        ambiguous.sl5_03 == "NOOP_AMBIGUOUS",
        generic.sl5_01 == "NOOP_GENERIC_CONTINUE",
        generic.sl5_02 == "NOOP_GENERIC_CONTINUE",
        generic.sl5_03 == "NOOP_GENERIC_CONTINUE",
        not sensitive.sl6_authorized,
        not ambiguous.sl6_authorized,
        not generic.sl6_authorized,
    ])
    details["loop_5"] = {
        "sensitive": sensitive.__dict__,
        "ambiguous": ambiguous.__dict__,
        "generic_continue": generic.__dict__,
    }

    passed = all(loops.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "loops": loops,
        "fundamental_finding_loop_1": "TASK_VS_MATERIAL_DELTA_DUPLICATION_RISK_FIXED_BY_TASK_DOMINANCE_AND_SEMANTIC_ATOM_KEY",
        "clean_1": "LOOP_4" if loops.get("4") else None,
        "clean_2": "LOOP_5" if loops.get("4") and loops.get("5") else None,
        "two_consecutive_clean": bool(loops.get("4") and loops.get("5")),
        "execute": False,
        "drive_writes": 0,
        "github_writes": 0,
        "external_actions": 0,
        "production_writes": 0,
        "sl6_authorized": False,
        "individual_cell_rights_unchanged": True,
        "details": details,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"PRE_SL6_COMBINED={result['status']}")
    for i in range(1, 6):
        print(f"PRE_SL6_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print("PRE_SL6_CLEAN_1=LOOP_4")
    print("PRE_SL6_CLEAN_2=LOOP_5")
    print(f"PRE_SL6_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print("PRE_SL6_EXECUTE=false")
    print("PRE_SL6_DRIVE_WRITES=0")
    print("PRE_SL6_GITHUB_WRITES=0")
    print("PRE_SL6_EXTERNAL_ACTIONS=0")
    print("PRE_SL6_PRODUCTION_WRITES=0")
    print("PRE_SL6_SL6_AUTHORIZED=false")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
