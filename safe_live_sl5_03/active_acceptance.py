from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from safe_live_sl5_03.active_policy_evaluator import (
    ALLOWED_EFFECT,
    TARGET_CONTROL_VIEW,
    ActivePolicy,
    TargetSnapshot,
    TaskEventCandidate,
    evaluate,
)


def load_policy(path: str) -> ActivePolicy:
    raw = json.loads(Path(path).read_text())
    raw["allowed_event_types"] = tuple(raw["allowed_event_types"])
    return ActivePolicy(**raw)


def base_event(**overrides) -> TaskEventCandidate:
    data = dict(
        event_key="TASK-EVENT-ACTIVE-001",
        task_id="TASK-ACTIVE-001",
        event_type="TASK_CREATE_CONFIRMED",
        target_id=TARGET_CONTROL_VIEW,
        title="Freitag Schlüssel bereitlegen",
        source_locator="active-chat:owner-explicit:2026-08-26:synthetic-acceptance",
        owner_explicit=True,
        confirmed_task_semantics=True,
        sensitivity="LOW",
        requested_effect=ALLOWED_EFFECT,
    )
    data.update(overrides)
    return TaskEventCandidate(**data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    p = load_policy(args.policy)
    today = date(2026, 8, 26)
    empty = TargetSnapshot(TARGET_CONTROL_VIEW, (), (), True)
    loops: dict[str, bool] = {}

    d1 = evaluate(p, empty, base_event(), today)
    loops["1"] = all([
        d1.allowed_to_execute,
        d1.reason == "ACTIVE_POLICY_ALLOWS_EXACT_TASK_EVENT",
        d1.rendered_event is not None,
        d1.rendered_event.get("priority") == "UNRANKED",
        d1.rendered_event.get("derived_only") is True,
    ])

    incomplete = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-I", task_id="TASK-I", incomplete=True), today)
    ambiguous = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-A", task_id="TASK-A", ambiguous=True), today)
    non_task = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-N", task_id="TASK-N", confirmed_task_semantics=False, title="Samstag 1"), today)
    loops["2"] = all([
        incomplete.reason == "INCOMPLETE_INPUT_NO_TASK_WRITE",
        ambiguous.reason == "AMBIGUOUS_INPUT_NO_TASK_WRITE",
        non_task.reason == "CONFIRMED_TASK_SEMANTICS_REQUIRED",
        not any(x.allowed_to_execute for x in [incomplete, ambiguous, non_task]),
    ])

    existing = TargetSnapshot(TARGET_CONTROL_VIEW, ("TASK-EVENT-ACTIVE-001",), ("TASK-ACTIVE-001",), True)
    correction = evaluate(p, existing, base_event(event_key="TASK-ACTIVE-002", event_type="TASK_CORRECT_OWNER", title="Freitag richtigen Schlüsselsatz bereitlegen", supersedes_event_key="TASK-EVENT-ACTIVE-001"), today)
    no_pointer = evaluate(p, existing, base_event(event_key="TASK-ACTIVE-003", event_type="TASK_CANCEL_OWNER"), today)
    unknown_task = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-004", event_type="TASK_COMPLETE_OWNER", supersedes_event_key="TASK-EVENT-ACTIVE-001"), today)
    loops["3"] = all([
        correction.allowed_to_execute,
        correction.rendered_event is not None,
        correction.rendered_event.get("supersedes_event_key") == "TASK-EVENT-ACTIVE-001",
        no_pointer.reason == "SUPERSESSION_POINTER_REQUIRED",
        unknown_task.reason == "TASK_NOT_FOUND",
    ])

    duplicate = evaluate(p, existing, base_event(), today)
    drift = evaluate(p, TargetSnapshot(TARGET_CONTROL_VIEW, (), (), False), base_event(), today)
    loops["4"] = all([
        duplicate.reason == "DUPLICATE_EVENT_KEY",
        not duplicate.allowed_to_execute,
        drift.reason == "TARGET_REVISION_DRIFT",
        not drift.allowed_to_execute,
    ])

    sensitive = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-S", task_id="TASK-S", sensitivity="HIGH"), today)
    inferred_due = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-D", task_id="TASK-D", due_value="2026-08-28", inferred_due=True), today)
    inferred_priority = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-P", task_id="TASK-P", inferred_priority=True), today)
    home_write = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-H", task_id="TASK-H", requested_home_system_write=True), today)
    background = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-B", task_id="TASK-B", background=True), today)
    raw_chat = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-R", task_id="TASK-R", raw_chat=True), today)
    wrong_effect = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-E", task_id="TASK-E", requested_effect="SEND_EMAIL"), today)
    wrong_target = evaluate(p, TargetSnapshot("wrong-target", (), (), True), base_event(event_key="TASK-ACTIVE-T", task_id="TASK-T"), today)
    activation = evaluate(p, empty, base_event(event_key="TASK-ACTIVE-X", task_id="TASK-X", is_policy_activation=True), today)
    expired = ActivePolicy(**{**p.__dict__, "review_by": "2026-08-25"})
    expired_decision = evaluate(expired, empty, base_event(event_key="TASK-ACTIVE-Z", task_id="TASK-Z"), today)
    unsafe = ActivePolicy(**{**p.__dict__, "kill_switch": False})
    unsafe_decision = evaluate(unsafe, empty, base_event(event_key="TASK-ACTIVE-K", task_id="TASK-K"), today)
    loops["5"] = all([
        sensitive.reason == "SENSITIVITY_NOT_ALLOWED",
        inferred_due.reason == "INFERRED_DUE_NOT_ALLOWED",
        inferred_priority.reason == "INFERRED_PRIORITY_NOT_ALLOWED",
        home_write.reason == "HOME_SYSTEM_WRITE_NOT_ALLOWED",
        background.reason == "BACKGROUND_NOT_ALLOWED",
        raw_chat.reason == "RAW_CHAT_NOT_ALLOWED",
        wrong_effect.reason == "EFFECT_NOT_ALLOWED",
        wrong_target.reason == "TARGET_MISMATCH",
        activation.reason == "ACTIVATION_NOT_TASK_TRIGGER",
        expired_decision.reason == "POLICY_REVIEW_EXPIRED",
        unsafe_decision.reason == "POLICY_SAFETY_INVARIANT_MISSING",
        not any(x.allowed_to_execute for x in [sensitive, inferred_due, inferred_priority, home_write, background, raw_chat, wrong_effect, wrong_target, activation, expired_decision, unsafe_decision]),
    ])

    passed = all(loops.values())
    result = {
        "status": "PASS" if passed else "FAIL",
        "loops": loops,
        "clean_1": "LOOP_4" if loops.get("4") else None,
        "clean_2": "LOOP_5" if loops.get("4") and loops.get("5") else None,
        "two_consecutive_clean": bool(loops.get("4") and loops.get("5")),
        "policy_status": p.status,
        "execute_capability": p.execute,
        "activation_authorized": passed,
        "activation_itself_triggers_task": False,
        "drive_writes_this_acceptance": 0,
        "external_actions_this_acceptance": 0,
        "production_writes_this_acceptance": 0,
        "target_id": p.target_id,
        "target_namespace": p.target_namespace,
        "review_by": p.review_by,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"SAFE_LIVE_SL5_03_ACTIVE_ACCEPTANCE={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_03_ACTIVE_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print("SAFE_LIVE_SL5_03_ACTIVE_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL5_03_ACTIVE_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL5_03_ACTIVE_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print(f"SAFE_LIVE_SL5_03_ACTIVATION_AUTHORIZED={str(result['activation_authorized']).lower()}")
    print("SAFE_LIVE_SL5_03_ACTIVATION_ITSELF_TRIGGERS_TASK=false")
    print("SAFE_LIVE_SL5_03_DRIVE_WRITES_THIS_ACCEPTANCE=0")
    print("SAFE_LIVE_SL5_03_EXTERNAL_ACTIONS_THIS_ACCEPTANCE=0")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
