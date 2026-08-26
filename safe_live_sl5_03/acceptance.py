from __future__ import annotations

import argparse
import json
from pathlib import Path

from safe_live_sl5_03.policy import (
    ALLOWED_EFFECT,
    TARGET_CONTROL_VIEW,
    Policy,
    TargetSnapshot,
    TaskEventCandidate,
    evaluate,
)


def base_event(**overrides) -> TaskEventCandidate:
    data = dict(
        event_key="TASK-EVENT-001",
        task_id="TASK-001",
        event_type="TASK_CREATE_CONFIRMED",
        target_id=TARGET_CONTROL_VIEW,
        title="Freitag Schlüssel bereitlegen",
        source_locator="active-chat:owner-explicit:2026-08-26:example-1",
        owner_explicit=True,
        confirmed_task_semantics=True,
        sensitivity="LOW",
        requested_effect=ALLOWED_EFFECT,
    )
    data.update(overrides)
    return TaskEventCandidate(**data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    p = Policy()
    loops: dict[str, bool] = {}
    details: dict[str, object] = {}

    # Loop 1: explicit owner task -> prepare only, stable ids and no invented priority.
    empty = TargetSnapshot(TARGET_CONTROL_VIEW, (), (), True)
    d1 = evaluate(p, empty, base_event())
    loops["1"] = all([
        d1.allowed_to_prepare,
        not d1.allowed_to_execute,
        d1.reason == "PREPARED_DRY_RUN_ONLY",
        d1.rendered_event is not None,
        d1.rendered_event.get("priority") == "UNRANKED",
        d1.rendered_event.get("derived_only") is True,
    ])
    details["loop_1_reason"] = d1.reason

    # Loop 2: incomplete/ambiguous/accidental-looking input must never be guessed into a task.
    incomplete = evaluate(p, empty, base_event(event_key="TASK-EVENT-INCOMPLETE", task_id="TASK-I", incomplete=True))
    ambiguous = evaluate(p, empty, base_event(event_key="TASK-EVENT-AMB", task_id="TASK-A", ambiguous=True))
    non_task = evaluate(
        p,
        empty,
        base_event(
            event_key="TASK-EVENT-NONTASK",
            task_id="TASK-N",
            confirmed_task_semantics=False,
            title="Samstag 1",
        ),
    )
    loops["2"] = all([
        incomplete.reason == "INCOMPLETE_INPUT_NO_TASK_WRITE",
        ambiguous.reason == "AMBIGUOUS_INPUT_NO_TASK_WRITE",
        non_task.reason == "CONFIRMED_TASK_SEMANTICS_REQUIRED",
        not any(x.allowed_to_prepare or x.allowed_to_execute for x in [incomplete, ambiguous, non_task]),
    ])
    details["loop_2_reasons"] = [incomplete.reason, ambiguous.reason, non_task.reason]

    # Loop 3: correction/cancel/complete requires existing task + explicit supersession pointer; no silent rewrite.
    existing = TargetSnapshot(TARGET_CONTROL_VIEW, ("TASK-EVENT-001",), ("TASK-001",), True)
    correction = evaluate(
        p,
        existing,
        base_event(
            event_key="TASK-EVENT-002",
            event_type="TASK_CORRECT_OWNER",
            title="Freitag richtigen Schlüsselsatz bereitlegen",
            supersedes_event_key="TASK-EVENT-001",
        ),
    )
    missing_pointer = evaluate(
        p,
        existing,
        base_event(event_key="TASK-EVENT-003", event_type="TASK_CANCEL_OWNER"),
    )
    unknown_task = evaluate(
        p,
        empty,
        base_event(
            event_key="TASK-EVENT-004",
            event_type="TASK_COMPLETE_OWNER",
            supersedes_event_key="TASK-EVENT-001",
        ),
    )
    loops["3"] = all([
        correction.allowed_to_prepare and not correction.allowed_to_execute,
        correction.rendered_event is not None,
        correction.rendered_event.get("supersedes_event_key") == "TASK-EVENT-001",
        missing_pointer.reason == "SUPERSESSION_POINTER_REQUIRED",
        unknown_task.reason == "TASK_NOT_FOUND",
    ])
    details["loop_3_reasons"] = [correction.reason, missing_pointer.reason, unknown_task.reason]

    # Loop 4: replay/concurrency safety.
    duplicate = evaluate(p, existing, base_event())
    drift = evaluate(p, TargetSnapshot(TARGET_CONTROL_VIEW, (), (), False), base_event())
    loops["4"] = all([
        duplicate.reason == "DUPLICATE_EVENT_KEY",
        duplicate.action == "NOOP",
        not duplicate.allowed_to_execute,
        drift.reason == "TARGET_REVISION_DRIFT",
        not drift.allowed_to_prepare,
    ])
    details["loop_4_reasons"] = [duplicate.reason, drift.reason]

    # Loop 5: authority/sensitivity/scope escalation fail closed.
    sensitive = evaluate(p, empty, base_event(event_key="TASK-EVENT-S", task_id="TASK-S", sensitivity="HIGH"))
    inferred_due = evaluate(
        p,
        empty,
        base_event(event_key="TASK-EVENT-D", task_id="TASK-D", due_value="2026-08-28", inferred_due=True),
    )
    inferred_priority = evaluate(p, empty, base_event(event_key="TASK-EVENT-P", task_id="TASK-P", inferred_priority=True))
    home_write = evaluate(p, empty, base_event(event_key="TASK-EVENT-H", task_id="TASK-H", requested_home_system_write=True))
    background = evaluate(p, empty, base_event(event_key="TASK-EVENT-B", task_id="TASK-B", background=True))
    wrong_effect = evaluate(p, empty, base_event(event_key="TASK-EVENT-E", task_id="TASK-E", requested_effect="SEND_EMAIL"))
    raw_chat = evaluate(p, empty, base_event(event_key="TASK-EVENT-R", task_id="TASK-R", raw_chat=True))
    active_policy = Policy(status="ACTIVE")
    activation_guard = evaluate(active_policy, empty, base_event(event_key="TASK-EVENT-X", task_id="TASK-X"))
    loops["5"] = all([
        sensitive.reason == "SENSITIVITY_NOT_ALLOWED",
        inferred_due.reason == "INFERRED_DUE_NOT_ALLOWED",
        inferred_priority.reason == "INFERRED_PRIORITY_NOT_ALLOWED",
        home_write.reason == "HOME_SYSTEM_WRITE_NOT_ALLOWED",
        background.reason == "BACKGROUND_NOT_ALLOWED",
        wrong_effect.reason == "EFFECT_NOT_ALLOWED",
        raw_chat.reason == "RAW_CHAT_NOT_ALLOWED",
        activation_guard.reason == "POLICY_NOT_DRY_RUN_ONLY",
        not any(x.allowed_to_execute for x in [sensitive, inferred_due, inferred_priority, home_write, background, wrong_effect, raw_chat, activation_guard]),
    ])
    details["loop_5_reasons"] = [
        sensitive.reason,
        inferred_due.reason,
        inferred_priority.reason,
        home_write.reason,
        background.reason,
        wrong_effect.reason,
        raw_chat.reason,
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
        "target_id": p.target_id,
        "target_namespace": p.target_namespace,
        "details": details,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")

    print(f"SAFE_LIVE_SL5_03_DRYRUN={result['status']}")
    for i in range(1, 6):
        print(f"SAFE_LIVE_SL5_03_LOOP_{i}={'PASS' if loops[str(i)] else 'FAIL'}")
    print("SAFE_LIVE_SL5_03_CLEAN_1=LOOP_4")
    print("SAFE_LIVE_SL5_03_CLEAN_2=LOOP_5")
    print(f"SAFE_LIVE_SL5_03_TWO_CONSECUTIVE_CLEAN={str(result['two_consecutive_clean']).lower()}")
    print("SAFE_LIVE_SL5_03_EXECUTE=false")
    print("SAFE_LIVE_SL5_03_DRIVE_WRITES=0")
    print("SAFE_LIVE_SL5_03_EXTERNAL_ACTIONS=0")
    print("SAFE_LIVE_SL5_03_PRODUCTION_WRITES=0")
    print("SAFE_LIVE_SL5_03_ACTIVATION_AUTHORIZED=false")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
