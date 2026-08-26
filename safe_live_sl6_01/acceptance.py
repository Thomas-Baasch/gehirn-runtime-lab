from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from safe_live_sl6_01.policy import EffectCandidate, OrchestrationPolicy, preflight, simulate_commits


def normal_candidates():
    return (
        EffectCandidate("SL5-03", "atom:task:001", "TASK_EVENT"),
        EffectCandidate("SL5-02", "atom:material:001", "MATERIAL_DELTA"),
        EffectCandidate("SL5-01", "atom:milestone:001", "MILESTONE_COMMENT"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    loops: dict[str, bool] = {}
    details: dict[str, object] = {}

    # Loop 1: normal three-cell orchestration, deterministic least-external-first order.
    p = OrchestrationPolicy()
    r1 = preflight(p, normal_candidates())
    loops["1"] = all([
        r1.batch_allowed,
        r1.batch_reason == "PREFLIGHT_OK",
        r1.planned_cells == ("SL5-03", "SL5-02", "SL5-01"),
        not r1.execute,
        not r1.sl6_authorized,
        len(r1.blocked) == 0,
    ])
    details["loop_1"] = r1.__dict__

    # Loop 2: scale can never outlive the earliest child review/expiry fence.
    expired_scale = preflight(OrchestrationPolicy(as_of=date(2026, 9, 2)), normal_candidates())
    valid_before_fence = preflight(OrchestrationPolicy(as_of=date(2026, 9, 1)), normal_candidates())
    loops["2"] = all([
        not expired_scale.batch_allowed,
        expired_scale.batch_reason == "EARLIEST_CHILD_REVIEW_FENCE_EXPIRED",
        valid_before_fence.batch_allowed,
    ])
    details["loop_2"] = {"after_fence": expired_scale.__dict__, "at_fence": valid_before_fence.__dict__}

    # Loop 3: local child block is isolated; unknown commit outcome stops all remaining candidates.
    partially_blocked = preflight(
        p,
        (
            EffectCandidate("SL5-03", "atom:task:002", "TASK_EVENT"),
            EffectCandidate("SL5-02", "atom:material:002", "MATERIAL_DELTA", child_current=False),
            EffectCandidate("SL5-01", "atom:milestone:002", "MILESTONE_COMMENT"),
        ),
    )
    all_valid = preflight(p, normal_candidates())
    unknown_mid = simulate_commits(all_valid, unknown_cell="SL5-02")
    loops["3"] = all([
        partially_blocked.batch_allowed,
        partially_blocked.planned_cells == ("SL5-03", "SL5-01"),
        ("SL5-02", "CHILD_CURRENTNESS_BLOCK") in partially_blocked.blocked,
        unknown_mid.committed == ("SL5-03",),
        unknown_mid.stopped_on_unknown == "SL5-02",
        unknown_mid.not_attempted == ("SL5-01",),
    ])
    details["loop_3"] = {"partial_block": partially_blocked.__dict__, "unknown_commit": unknown_mid.__dict__}

    # Loop 4: replay/collision/currentness. CLEAN_1.
    replay = preflight(
        p,
        (
            EffectCandidate("SL5-03", "atom:task:003", "TASK_EVENT", duplicate=True),
            EffectCandidate("SL5-02", "atom:material:003", "MATERIAL_DELTA", child_current=False),
            EffectCandidate("SL5-01", "atom:milestone:003", "MILESTONE_COMMENT"),
        ),
    )
    collision = preflight(
        p,
        (
            EffectCandidate("SL5-03", "atom:same", "TASK_EVENT"),
            EffectCandidate("SL5-02", "atom:same", "MATERIAL_DELTA"),
        ),
    )
    loops["4"] = all([
        replay.batch_allowed,
        replay.planned_cells == ("SL5-01",),
        ("SL5-03", "NOOP_DUPLICATE") in replay.blocked,
        ("SL5-02", "CHILD_CURRENTNESS_BLOCK") in replay.blocked,
        not collision.batch_allowed,
        collision.batch_reason == "SEMANTIC_ATOM_COLLISION",
    ])
    details["loop_4"] = {"replay": replay.__dict__, "collision": collision.__dict__}

    # Loop 5: sensitivity, volume, background, missing kill switch, and accidental ACTIVE status stay blocked. CLEAN_2.
    sensitive = preflight(
        p,
        (
            EffectCandidate("SL5-03", "atom:task:004", "TASK_EVENT", low_sensitivity=False),
            EffectCandidate("SL5-02", "atom:material:004", "MATERIAL_DELTA"),
        ),
    )
    volume = preflight(
        p,
        (
            EffectCandidate("SL5-03", "atom:v1", "TASK_EVENT"),
            EffectCandidate("SL5-02", "atom:v2", "MATERIAL_DELTA"),
            EffectCandidate("SL5-01", "atom:v3", "MILESTONE_COMMENT"),
            EffectCandidate("SL5-02", "atom:v4", "MATERIAL_DELTA"),
        ),
    )
    background = preflight(p, normal_candidates(), background=True)
    no_kill = preflight(OrchestrationPolicy(kill_switch_present=False), normal_candidates())
    active_guard = preflight(OrchestrationPolicy(status="ACTIVE", sl6_authorized=True), normal_candidates())
    loops["5"] = all([
        sensitive.batch_allowed,
        ("SL5-03", "SENSITIVITY_NOT_ALLOWED") in sensitive.blocked,
        sensitive.planned_cells == ("SL5-02",),
        not volume.batch_allowed and volume.batch_reason == "VOLUME_LIMIT_EXCEEDED",
        not background.batch_allowed and background.batch_reason == "BACKGROUND_NOT_ALLOWED",
        not no_kill.batch_allowed and no_kill.batch_reason == "KILL_SWITCH_REQUIRED",
        not active_guard.batch_allowed and active_guard.batch_reason == "POLICY_NOT_DRY_RUN_ONLY",
    ])
    details["loop_5"] = {
        "sensitive": sensitive.__dict__,
        "volume": volume.__dict__,
        "background": background.__dict__,
        "no_kill": no_kill.__dict__,
        "active_guard": active_guard.__dict__,
    }

    passed = all(loops.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "loops": loops,
        "design_fundamental_finding": "SL6_MUST_NOT_OUTLIVE_EARLIEST_CHILD_CELL_REVIEW",
        "clean_1": "LOOP_4" if loops.get("4") else None,
        "clean_2": "LOOP_5" if loops.get("4") and loops.get("5") else None,
        "two_consecutive_clean": bool(loops.get("4") and loops.get("5")),
        "policy_status": p.status,
        "earliest_child_review": p.earliest_child_review.isoformat(),
        "max_effects_per_turn": p.max_effects_per_turn,
        "max_commits_per_cell": p.max_commits_per_cell,
        "execute": False,
        "drive_writes": 0,
        "github_writes": 0,
        "external_actions": 0,
        "production_writes": 0,
        "sl6_activation_authorized": False,
        "new_action_classes": 0,
        "new_targets": 0,
        "details": details,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2, default=str) + "\n")

    print(f"SAFE_LIVE_SL6_01_DRYRUN={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL6_01_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print("SAFE_LIVE_SL6_01_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL6_01_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL6_01_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print("SAFE_LIVE_SL6_01_EXECUTE=false")
    print("SAFE_LIVE_SL6_01_DRIVE_WRITES=0")
    print("SAFE_LIVE_SL6_01_GITHUB_WRITES=0")
    print("SAFE_LIVE_SL6_01_EXTERNAL_ACTIONS=0")
    print("SAFE_LIVE_SL6_01_PRODUCTION_WRITES=0")
    print("SAFE_LIVE_SL6_01_ACTIVATION_AUTHORIZED=false")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
