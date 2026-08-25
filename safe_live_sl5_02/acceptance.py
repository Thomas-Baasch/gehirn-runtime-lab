from __future__ import annotations

import argparse
import json
from pathlib import Path

from safe_live_sl5_02.policy import (
    ALLOWED_EFFECT,
    MENTORENRAT_REGISTRY,
    PETER_REGISTRY,
    UNROUTED_INBOX,
    DeltaCandidate,
    Policy,
    TargetSnapshot,
    evaluate,
)


def candidate(**overrides) -> DeltaCandidate:
    base = dict(
        delta_key="PETER-OPEN-LOOP-001",
        delta_type="OPEN_LOOP_DELTA",
        target_id=PETER_REGISTRY,
        statement="Next safe build step remains source-grounded and derived-only.",
        source_locator="drive:example-current-source",
        sensitivity="LOW",
        current=True,
        ambiguous=False,
        conflict=False,
        sealed=False,
        background=False,
        raw_chat=False,
        requested_effect=ALLOWED_EFFECT,
        requested_home_system_write=False,
    )
    base.update(overrides)
    return DeltaCandidate(**base)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    p = Policy()
    loops: dict[str, bool] = {}
    details: dict[str, object] = {}

    # Loop 1: normal unambiguous PETER delta -> prepare only, never execute.
    t1 = TargetSnapshot(PETER_REGISTRY, (), True)
    d1 = evaluate(p, t1, candidate())
    loops["1"] = all([
        d1.allowed_to_prepare,
        not d1.allowed_to_execute,
        d1.action == "PREPARE_APPEND_DRY_RUN_ONLY",
        d1.reason == "PREPARED_DRY_RUN_ONLY",
        d1.rendered_event is not None,
        d1.rendered_event.get("derived_only") is True,
    ])
    details["loop_1_reason"] = d1.reason

    # Loop 2: ambiguity must go to unrouted; sensitive/raw-chat must stop.
    wrong = evaluate(p, t1, candidate(ambiguous=True))
    unrouted_target = TargetSnapshot(UNROUTED_INBOX, (), True)
    routed = evaluate(
        p,
        unrouted_target,
        candidate(
            delta_key="UNROUTED-001",
            target_id=UNROUTED_INBOX,
            ambiguous=True,
            statement="Material item needs project routing before ownership is assigned.",
        ),
    )
    sensitive = evaluate(
        p,
        unrouted_target,
        candidate(
            delta_key="UNROUTED-SENSITIVE-001",
            target_id=UNROUTED_INBOX,
            ambiguous=True,
            sensitivity="HIGH",
        ),
    )
    raw_chat = evaluate(
        p,
        unrouted_target,
        candidate(
            delta_key="UNROUTED-RAW-001",
            target_id=UNROUTED_INBOX,
            ambiguous=True,
            raw_chat=True,
        ),
    )
    loops["2"] = all([
        wrong.reason == "AMBIGUOUS_TARGET_REQUIRES_UNROUTED",
        not wrong.allowed_to_execute,
        routed.allowed_to_prepare and not routed.allowed_to_execute,
        sensitive.reason == "SENSITIVITY_NOT_ALLOWED" and not sensitive.allowed_to_prepare,
        raw_chat.reason == "RAW_CHAT_NOT_ALLOWED" and not raw_chat.allowed_to_prepare,
    ])
    details["loop_2_reasons"] = [wrong.reason, routed.reason, sensitive.reason, raw_chat.reason]

    # Loop 3: conflicts become explicit pointer deltas; home-system write is blocked.
    conflict_bad = evaluate(p, t1, candidate(conflict=True, delta_type="STATE_DELTA"))
    conflict_good = evaluate(
        p,
        t1,
        candidate(
            delta_key="PETER-CONFLICT-001",
            conflict=True,
            delta_type="SUPERSESSION_CONFLICT_POINTER",
            statement="Conflict held; current Home System remains authoritative.",
        ),
    )
    home_write = evaluate(p, t1, candidate(requested_home_system_write=True))
    loops["3"] = all([
        conflict_bad.reason == "CONFLICT_REQUIRES_POINTER_TYPE",
        conflict_good.allowed_to_prepare and not conflict_good.allowed_to_execute,
        conflict_good.rendered_event is not None,
        conflict_good.rendered_event.get("status") == "CONFLICT_HELD",
        home_write.reason == "HOME_SYSTEM_WRITE_NOT_ALLOWED",
    ])
    details["loop_3_reasons"] = [conflict_bad.reason, conflict_good.reason, home_write.reason]

    # Loop 4: crash/replay/concurrency safety via key idempotency and revision currentness.
    duplicate_target = TargetSnapshot(PETER_REGISTRY, ("PETER-OPEN-LOOP-001",), True)
    duplicate = evaluate(p, duplicate_target, candidate())
    drift_target = TargetSnapshot(PETER_REGISTRY, (), False)
    drift = evaluate(p, drift_target, candidate())
    loops["4"] = all([
        duplicate.action == "NOOP",
        duplicate.reason == "DUPLICATE_DELTA_KEY",
        not duplicate.allowed_to_execute,
        drift.reason == "TARGET_REVISION_DRIFT",
        not drift.allowed_to_prepare,
    ])
    details["loop_4_reasons"] = [duplicate.reason, drift.reason]

    # Loop 5: sealed/project isolation/authority escalation/background all fail closed.
    mentor_target = TargetSnapshot(MENTORENRAT_REGISTRY, (), True)
    sealed = evaluate(
        p,
        mentor_target,
        candidate(
            delta_key="MENTOR-SEALED-001",
            target_id=MENTORENRAT_REGISTRY,
            sealed=True,
        ),
    )
    wrong_target = TargetSnapshot("not-allowlisted", (), True)
    not_allowed = evaluate(
        p,
        wrong_target,
        candidate(delta_key="OTHER-001", target_id="not-allowlisted"),
    )
    effect_escalation = evaluate(p, t1, candidate(requested_effect="SEND_EMAIL"))
    background = evaluate(p, t1, candidate(background=True))
    active_policy = Policy(status="ACTIVE")
    activation_guard = evaluate(active_policy, t1, candidate())
    loops["5"] = all([
        sealed.reason == "SEALED_CONTENT_BLOCKED",
        not_allowed.reason == "TARGET_NOT_ALLOWLISTED",
        effect_escalation.reason == "EFFECT_NOT_ALLOWED",
        background.reason == "BACKGROUND_NOT_ALLOWED",
        activation_guard.reason == "POLICY_NOT_DRY_RUN_ONLY",
        not any(x.allowed_to_execute for x in [sealed, not_allowed, effect_escalation, background, activation_guard]),
    ])
    details["loop_5_reasons"] = [
        sealed.reason,
        not_allowed.reason,
        effect_escalation.reason,
        background.reason,
        activation_guard.reason,
    ]

    passed = all(loops.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "loops": loops,
        "clean_1": "LOOP_4" if loops.get("4") else None,
        "clean_2": "LOOP_5" if loops.get("4") and loops.get("5") else None,
        "two_consecutive_clean": bool(loops.get("4") and loops.get("5")),
        "policy_status": p.status,
        "execute": False,
        "drive_writes": 0,
        "external_actions": 0,
        "production_writes": 0,
        "activation_authorized": False,
        "allowed_targets": list(p.allowed_targets),
        "details": details,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"SAFE_LIVE_SL5_02_DRYRUN={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_02_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print("SAFE_LIVE_SL5_02_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL5_02_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL5_02_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print("SAFE_LIVE_SL5_02_EXECUTE=false")
    print("SAFE_LIVE_SL5_02_DRIVE_WRITES=0")
    print("SAFE_LIVE_SL5_02_EXTERNAL_ACTIONS=0")
    print("SAFE_LIVE_SL5_02_PRODUCTION_WRITES=0")
    print("SAFE_LIVE_SL5_02_ACTIVATION_AUTHORIZED=false")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
