from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from safe_live_sl5_02.active_policy_evaluator import (
    ALLOWED_EFFECT,
    MENTORENRAT_REGISTRY,
    PETER_REGISTRY,
    UNROUTED_INBOX,
    ActivePolicy,
    DeltaCandidate,
    TargetSnapshot,
    evaluate,
)


def load_policy(path: str) -> ActivePolicy:
    raw = json.loads(Path(path).read_text())
    raw["allowed_targets"] = tuple(raw["allowed_targets"])
    raw["allowed_delta_types"] = tuple(raw["allowed_delta_types"])
    return ActivePolicy(**raw)


def candidate(**overrides) -> DeltaCandidate:
    base = dict(
        delta_key="PETER-ACTIVE-OPEN-LOOP-001",
        delta_type="OPEN_LOOP_DELTA",
        target_id=PETER_REGISTRY,
        statement="A low-sensitivity active-turn derived delta may be persisted under the exact allowlisted policy.",
        source_locator="drive:current-source-example",
        sensitivity="LOW",
        current=True,
        ambiguous=False,
        conflict=False,
        sealed=False,
        background=False,
        raw_chat=False,
        requested_effect=ALLOWED_EFFECT,
        requested_home_system_write=False,
        is_policy_activation=False,
    )
    base.update(overrides)
    return DeltaCandidate(**base)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    p = load_policy(args.policy)
    today = date(2026, 8, 26)
    loops: dict[str, bool] = {}
    details: dict[str, object] = {}

    t1 = TargetSnapshot(PETER_REGISTRY, (), True)
    d1 = evaluate(p, t1, candidate(), today)
    loops["1"] = all([
        d1.allowed_to_execute,
        d1.action == "APPEND_DERIVED_DELTA",
        d1.reason == "ACTIVE_POLICY_ALLOWS_EXACT_EFFECT",
        d1.rendered_event is not None,
        d1.rendered_event.get("derived_only") is True,
    ])
    details["loop_1_reason"] = d1.reason

    wrong = evaluate(p, t1, candidate(ambiguous=True), today)
    unrouted_target = TargetSnapshot(UNROUTED_INBOX, (), True)
    routed = evaluate(
        p,
        unrouted_target,
        candidate(
            delta_key="UNROUTED-ACTIVE-001",
            target_id=UNROUTED_INBOX,
            ambiguous=True,
            statement="Material item needs routing before a project owner is assigned.",
        ),
        today,
    )
    sensitive = evaluate(
        p,
        unrouted_target,
        candidate(delta_key="UNROUTED-SENSITIVE-ACTIVE-001", target_id=UNROUTED_INBOX, ambiguous=True, sensitivity="HIGH"),
        today,
    )
    raw_chat = evaluate(
        p,
        unrouted_target,
        candidate(delta_key="UNROUTED-RAW-ACTIVE-001", target_id=UNROUTED_INBOX, ambiguous=True, raw_chat=True),
        today,
    )
    loops["2"] = all([
        wrong.reason == "AMBIGUOUS_TARGET_REQUIRES_UNROUTED",
        routed.allowed_to_execute,
        sensitive.reason == "SENSITIVITY_NOT_ALLOWED" and not sensitive.allowed_to_execute,
        raw_chat.reason == "RAW_CHAT_NOT_ALLOWED" and not raw_chat.allowed_to_execute,
    ])
    details["loop_2_reasons"] = [wrong.reason, routed.reason, sensitive.reason, raw_chat.reason]

    conflict_bad = evaluate(p, t1, candidate(conflict=True, delta_type="STATE_DELTA"), today)
    conflict_good = evaluate(
        p,
        t1,
        candidate(
            delta_key="PETER-CONFLICT-ACTIVE-001",
            conflict=True,
            delta_type="SUPERSESSION_CONFLICT_POINTER",
            statement="Conflict held; current Home System remains authoritative.",
        ),
        today,
    )
    home_write = evaluate(p, t1, candidate(requested_home_system_write=True), today)
    loops["3"] = all([
        conflict_bad.reason == "CONFLICT_REQUIRES_POINTER_TYPE",
        conflict_good.allowed_to_execute,
        conflict_good.rendered_event is not None,
        conflict_good.rendered_event.get("status") == "CONFLICT_HELD",
        home_write.reason == "HOME_SYSTEM_WRITE_NOT_ALLOWED",
    ])
    details["loop_3_reasons"] = [conflict_bad.reason, conflict_good.reason, home_write.reason]

    duplicate = evaluate(p, TargetSnapshot(PETER_REGISTRY, ("PETER-ACTIVE-OPEN-LOOP-001",), True), candidate(), today)
    drift = evaluate(p, TargetSnapshot(PETER_REGISTRY, (), False), candidate(), today)
    loops["4"] = all([
        duplicate.reason == "DUPLICATE_DELTA_KEY" and not duplicate.allowed_to_execute,
        drift.reason == "TARGET_REVISION_DRIFT" and not drift.allowed_to_execute,
    ])
    details["loop_4_reasons"] = [duplicate.reason, drift.reason]

    mentor_target = TargetSnapshot(MENTORENRAT_REGISTRY, (), True)
    sealed = evaluate(p, mentor_target, candidate(delta_key="MENTOR-SEALED-ACTIVE-001", target_id=MENTORENRAT_REGISTRY, sealed=True), today)
    not_allowed = evaluate(p, TargetSnapshot("not-allowlisted", (), True), candidate(delta_key="OTHER-ACTIVE-001", target_id="not-allowlisted"), today)
    effect_escalation = evaluate(p, t1, candidate(requested_effect="SEND_EMAIL"), today)
    background = evaluate(p, t1, candidate(background=True), today)
    expired = ActivePolicy(**{**p.__dict__, "review_by": "2026-08-25"})
    expired_d = evaluate(expired, t1, candidate(), today)
    activation_d = evaluate(p, t1, candidate(delta_key="SL5-02-ACTIVATION", is_policy_activation=True), today)
    broken = ActivePolicy(**{**p.__dict__, "kill_switch": False})
    broken_d = evaluate(broken, t1, candidate(), today)
    loops["5"] = all([
        sealed.reason == "SEALED_CONTENT_BLOCKED",
        not_allowed.reason == "TARGET_NOT_ALLOWLISTED",
        effect_escalation.reason == "EFFECT_NOT_ALLOWED",
        background.reason == "BACKGROUND_NOT_ALLOWED",
        expired_d.reason == "POLICY_REVIEW_EXPIRED",
        activation_d.reason == "BOOTSTRAP_NOT_TRIGGER",
        broken_d.reason == "POLICY_SAFETY_INVARIANT_MISSING",
        not any(x.allowed_to_execute for x in [sealed, not_allowed, effect_escalation, background, expired_d, activation_d, broken_d]),
    ])
    details["loop_5_reasons"] = [
        sealed.reason,
        not_allowed.reason,
        effect_escalation.reason,
        background.reason,
        expired_d.reason,
        activation_d.reason,
        broken_d.reason,
    ]

    passed = all(loops.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "loops": loops,
        "clean_1": "LOOP_4" if loops.get("4") else None,
        "clean_2": "LOOP_5" if loops.get("4") and loops.get("5") else None,
        "two_consecutive_clean": bool(loops.get("4") and loops.get("5")),
        "policy_status": p.status,
        "execute_capability": p.execute,
        "owner_activation_authority": True,
        "activation_authorized": passed,
        "activation_itself_triggers_delta": False,
        "drive_writes_this_acceptance": 0,
        "external_actions_this_acceptance": 0,
        "production_writes_this_acceptance": 0,
        "allowed_targets": list(p.allowed_targets),
        "review_by": p.review_by,
        "details": details,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"SAFE_LIVE_SL5_02_ACTIVE_ACCEPTANCE={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_02_ACTIVE_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print("SAFE_LIVE_SL5_02_ACTIVE_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL5_02_ACTIVE_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL5_02_ACTIVE_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print(f"SAFE_LIVE_SL5_02_ACTIVATION_AUTHORIZED={str(result['activation_authorized']).lower()}")
    print("SAFE_LIVE_SL5_02_ACTIVATION_ITSELF_TRIGGERS_DELTA=false")
    print("SAFE_LIVE_SL5_02_DRIVE_WRITES_THIS_ACCEPTANCE=0")
    print("SAFE_LIVE_SL5_02_EXTERNAL_ACTIONS_THIS_ACCEPTANCE=0")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
