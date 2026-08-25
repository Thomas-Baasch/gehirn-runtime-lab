from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

CONTRACT_DRIVE_ID = "1YMD3ynywpfgKYY-v7dzN4eqcx6mA0Pm9RLBjPI7hwjg"
CASE_ID = "CS0A1-SYN-001"
PURPOSE = "core_shadow_0a1"
SCOPE = "synthetic_integration"
SENSITIVITY = "S0_SYNTHETIC"

CLOSED_STATES = {"CLOSED", "ACCEPTED", "VALIDLY_CANCELLED"}
FORBIDDEN_EXTERNAL_ACTIONS = {
    "send_message", "pay", "delete_original", "publish", "production_write",
    "credential_change", "merge", "sign_contract", "change_price",
    "change_policy", "grant_rights",
}


class CoreShadowError(ValueError):
    pass


def _claim(subject: str, role: str, actions: list[str], *, generation: int = 1) -> dict[str, Any]:
    return {
        "subject": subject,
        "role": role,
        "actions": list(actions),
        "resource": f"case:{CASE_ID}",
        "purpose": PURPOSE,
        "scope": SCOPE,
        "sensitivity": SENSITIVITY,
        "delegation": "synthetic_fixture_only",
        "expiry": "fixture_end",
        "generation": generation,
    }


def make_fixture() -> dict[str, Any]:
    obligations = [
        {"obligation_id": "O1", "name": "owner_intake", "owner": "uschi_owner_interface", "predecessor": None, "state": "OPEN", "material": True},
        {"obligation_id": "O2", "name": "operating_priority", "owner": "georg_group_ceo", "predecessor": "O1", "state": "WAITING_PREDECESSOR", "material": True},
        {"obligation_id": "O3", "name": "truth_load", "owner": "external_brain_truth_service", "predecessor": "O2", "state": "WAITING_PREDECESSOR", "material": True},
        {"obligation_id": "O4", "name": "project_next_step", "owner": "peter_project_change", "predecessor": "O3", "state": "WAITING_PREDECESSOR", "material": True},
        {"obligation_id": "O5", "name": "control_challenge", "owner": "konrad_control", "predecessor": "O4", "state": "WAITING_PREDECESSOR", "material": True},
        {"obligation_id": "O6", "name": "truth_reconcile", "owner": "external_brain_truth_service", "predecessor": "O5", "state": "WAITING_PREDECESSOR", "material": True},
        {"obligation_id": "O7", "name": "owner_choice_package", "owner": "uschi_owner_interface", "predecessor": "O6", "state": "WAITING_PREDECESSOR", "material": True},
        {"obligation_id": "O8", "name": "owner_choice", "owner": "thomas_owner", "predecessor": "O7", "state": "WAITING_PREDECESSOR", "material": True},
    ]
    claims = {
        "thomas_owner": _claim("thomas_owner", "OWNER", ["request", "decide"]),
        "uschi_owner_interface": _claim("uschi_owner_interface", "OWNER_INTERFACE", ["intake", "owner_view"]),
        "georg_group_ceo": _claim("georg_group_ceo", "GROUP_CEO", ["prioritize", "mandate_peter"]),
        "peter_project_change": _claim("peter_project_change", "PROJECT_CHANGE", ["project_next_step", "propose_internal_derived_update"]),
        "external_brain_truth_service": _claim("external_brain_truth_service", "TRUTH_SERVICE", ["read_truth", "reconcile_truth"]),
        "konrad_control": _claim("konrad_control", "CONTROL", ["challenge"]),
    }
    return {
        "schema": "core-shadow-0a1.case.v1",
        "contract_drive_id": CONTRACT_DRIVE_ID,
        "synthetic_only": True,
        "contains_personal_data": False,
        "contains_productive_data": False,
        "contains_secrets": False,
        "case_id": CASE_ID,
        "case_version": 1,
        "case_type": "SYNTHETIC_PROJECT_CHANGE",
        "original_request": "Prepare a synthetic, no-effect choice between two valid implementation variants.",
        "original_request_source": "fixture://owner-request/v1",
        "purpose": PURPOSE,
        "scope": SCOPE,
        "sensitivity": SENSITIVITY,
        "current_state": "INTAKE",
        "outcome_target": "Produce a correct synthetic E6 owner-choice packet after truth/control reconciliation.",
        "current_owner": "uschi_owner_interface",
        "source_refs": ["SRC-GOAL", "SRC-CURRENT", "SRC-STALE", "SRC-DERIVED"],
        "valid_time": "2036-SYNTHETIC",
        "observed_time": "fixture-seq-0",
        "epistemic": {"confidence": "MIXED", "conflict": False},
        "rights": {"action_class": "READ_ONLY_OR_ISOLATED_DERIVED", "external_effects_allowed": False},
        "next_step": "USCHI_INTAKE",
        "last_verified_result": None,
        "deadline": None,
        "review": "fixture_end",
        "expiry": "fixture_end",
        "thomas_class": "K0",
        "decision_id": None,
        "control_status": "NOT_REVIEWED",
        "dissent": [],
        "acceptance_status": "NOT_EVALUATED",
        "evidence_refs": [],
        "priority": None,
        "peter_mandate": None,
        "truth_snapshot": None,
        "project_next_step": None,
        "owner_view": None,
        "decision": None,
        "business_outcome_state": "PENDING",
        "handover": None,
        "obligations": obligations,
        "composite_completion_state": "OPEN",
        "open_material_obligations": [o["obligation_id"] for o in obligations],
        "sources": [
            {
                "source_id": "SRC-GOAL",
                "class": "CANON",
                "authority": "OWNER_CONFIRMED_SYNTHETIC",
                "current": True,
                "value": {"goal": "safe synthetic comparison", "external_effects_allowed": False},
            },
            {
                "source_id": "SRC-CURRENT",
                "class": "EVIDENCE",
                "authority": "CURRENT_SYNTHETIC_EVIDENCE",
                "current": True,
                "value": {"adapter_state": "fixture_available", "option_a_value": 80, "option_b_value": 75},
            },
            {
                "source_id": "SRC-STALE",
                "class": "EVIDENCE",
                "authority": "HISTORICAL_SYNTHETIC_EVIDENCE",
                "current": False,
                "value": {"adapter_state": "live_ready", "option_a_value": 99},
            },
            {
                "source_id": "SRC-DERIVED",
                "class": "DERIVED",
                "authority": "NONE",
                "current": True,
                "value": {"overall": "GREEN", "assumption": "stale_adapter_ready"},
            },
        ],
        "derived_view": {"overall": "GREEN", "assumption": "stale_adapter_ready"},
        "claims": claims,
        "generations": {"policy": 1, "resource": 1, "role": 1},
        "guard_results": [],
        "events": [],
        "writer_map": {
            "original_request": "thomas_owner",
            "priority": "georg_group_ceo",
            "current_owner": "core_case_controller",
            "obligation_graph": "core_case_controller",
            "truth_snapshot": "external_brain_truth_service",
            "project_next_step": "peter_project_change",
            "control_status": "konrad_control",
            "thomas_class": "uschi_owner_interface",
            "decision": "thomas_owner",
            "composite_completion_state": "core_case_controller",
        },
    }


def _emit(case: dict[str, Any], event_type: str, actor: str, payload: Mapping[str, Any]) -> None:
    case["events"].append({
        "seq": len(case["events"]) + 1,
        "case_id": case["case_id"],
        "event_type": event_type,
        "actor": actor,
        "payload": deepcopy(dict(payload)),
    })


def _obligation(case: Mapping[str, Any], obligation_id: str) -> Mapping[str, Any]:
    matches = [o for o in case["obligations"] if o["obligation_id"] == obligation_id]
    if len(matches) != 1:
        raise CoreShadowError(f"obligation_identity_invalid:{obligation_id}")
    return matches[0]


def _set_obligation(case: dict[str, Any], obligation_id: str, state: str, actor: str) -> None:
    obligation = _obligation(case, obligation_id)
    predecessor = obligation.get("predecessor")
    if state == "OPEN" and predecessor:
        pred = _obligation(case, predecessor)
        if pred["state"] not in CLOSED_STATES:
            raise CoreShadowError(f"predecessor_not_closed:{obligation_id}")
    obligation["state"] = state
    _emit(case, "OBLIGATION_CHANGED", actor, {"obligation_id": obligation_id, "state": state})
    _recalc_composite(case)


def _recalc_composite(case: dict[str, Any]) -> None:
    open_ids = [
        o["obligation_id"] for o in case["obligations"]
        if o.get("material", True) and o["state"] not in CLOSED_STATES
    ]
    old = case.get("composite_completion_state")
    if not open_ids:
        new = "CLOSED"
    elif open_ids == ["O8"] and _obligation(case, "O7")["state"] in CLOSED_STATES:
        new = "OWNER_DECISION_REQUIRED"
    else:
        new = "OPEN"
    case["open_material_obligations"] = open_ids
    case["composite_completion_state"] = new
    if old != new:
        _emit(case, "COMPOSITE_STATE_CHANGED", "core_case_controller", {"state": new, "open_material_obligations": list(open_ids)})


def _set_owner(case: dict[str, Any], owner: str, actor: str, *, handover_from: str | None = None) -> None:
    previous = case["current_owner"]
    case["current_owner"] = owner
    case["handover"] = {
        "from": handover_from or previous,
        "to": owner,
        "case_generation": case["case_version"],
        "accepted": True,
        "scope": case["scope"],
    }
    _emit(case, "OWNER_CHANGED", actor, {"from": previous, "to": owner})
    _emit(case, "HANDOVER_ACCEPTED", owner, deepcopy(case["handover"]))


def authorize(case: Mapping[str, Any], subject: str, action: str) -> dict[str, Any]:
    claim = case.get("claims", {}).get(subject)
    if not isinstance(claim, Mapping):
        return {"allowed": False, "reason": "UNKNOWN_SUBJECT"}
    required = {
        "resource": f"case:{case['case_id']}",
        "purpose": case["purpose"],
        "scope": case["scope"],
        "sensitivity": case["sensitivity"],
    }
    if action not in claim.get("actions", []):
        return {"allowed": False, "reason": "ACTION_NOT_GRANTED"}
    for key, expected in required.items():
        if claim.get(key) != expected:
            return {"allowed": False, "reason": f"{key.upper()}_MISMATCH"}
    if claim.get("expiry") != "fixture_end":
        return {"allowed": False, "reason": "CLAIM_EXPIRED_OR_UNKNOWN"}
    if claim.get("generation") != case["generations"]["role"]:
        return {"allowed": False, "reason": "ROLE_GENERATION_STALE"}
    return {"allowed": True, "reason": "EXACT_SYNTHETIC_CLAIM_MATCH"}


def request_action(case: dict[str, Any], subject: str, action: str) -> dict[str, Any]:
    if action in FORBIDDEN_EXTERNAL_ACTIONS:
        result = {"action": action, "allowed": False, "reason": "OUTSIDE_ACTION_BOUNDARY"}
        case["guard_results"].append(result)
        _emit(case, "ACTION_BLOCKED", "core_case_controller", result)
        return result
    auth = authorize(case, subject, action)
    result = {"action": action, **auth}
    case["guard_results"].append(result)
    return result


def uschi_intake(case: dict[str, Any]) -> None:
    if not authorize(case, "uschi_owner_interface", "intake")["allowed"]:
        raise CoreShadowError("uschi_intake_not_authorized")
    _set_obligation(case, "O1", "CLOSED", "uschi_owner_interface")
    _set_obligation(case, "O2", "OPEN", "core_case_controller")
    case["current_state"] = "OPERATING_TRIAGE"
    case["next_step"] = "GEORG_PRIORITIZE"
    case["thomas_class"] = "K0"
    _emit(case, "THOMAS_CLASS_SET", "uschi_owner_interface", {"class": "K0", "reason": "no_owner_choice_yet"})
    _set_owner(case, "georg_group_ceo", "uschi_owner_interface")


def georg_prioritize(case: dict[str, Any]) -> None:
    if not authorize(case, "georg_group_ceo", "prioritize")["allowed"]:
        raise CoreShadowError("georg_prioritize_not_authorized")
    case["priority"] = {
        "class": "P1_SYNTHETIC_INTEGRATION",
        "reason": "safe bounded integration value; no external effect",
        "owner_constraints_preserved": True,
    }
    _emit(case, "GEORG_PRIORITY_SET", "georg_group_ceo", case["priority"])
    if not authorize(case, "georg_group_ceo", "mandate_peter")["allowed"]:
        raise CoreShadowError("georg_mandate_not_authorized")
    case["peter_mandate"] = {
        "scope": "synthetic_project_change",
        "allowed": ["project_next_step", "propose_internal_derived_update"],
        "forbidden": ["owner_decision", "control_override", "external_action", "production_write"],
        "generation": case["case_version"],
    }
    _emit(case, "PETER_MANDATE_CREATED", "georg_group_ceo", case["peter_mandate"])
    _set_obligation(case, "O2", "CLOSED", "georg_group_ceo")
    _set_obligation(case, "O3", "OPEN", "core_case_controller")
    _set_owner(case, "peter_project_change", "georg_group_ceo", handover_from="georg_group_ceo")
    case["current_state"] = "PROJECT_CHANGE_MANDATED"
    case["next_step"] = "EXTERNAL_BRAIN_TRUTH_LOAD"


def external_brain_truth_load(case: dict[str, Any]) -> None:
    if not authorize(case, "external_brain_truth_service", "read_truth")["allowed"]:
        raise CoreShadowError("truth_read_not_authorized")
    canon = [s for s in case["sources"] if s["class"] == "CANON" and s["current"]]
    current_evidence = [s for s in case["sources"] if s["class"] == "EVIDENCE" and s["current"]]
    stale = [s["source_id"] for s in case["sources"] if not s["current"]]
    derived = [s["source_id"] for s in case["sources"] if s["class"] == "DERIVED"]
    if len(canon) != 1 or len(current_evidence) != 1:
        raise CoreShadowError("fixture_truth_surface_invalid")
    case["truth_snapshot"] = {
        "canon_source": canon[0]["source_id"],
        "current_evidence_source": current_evidence[0]["source_id"],
        "stale_sources": stale,
        "derived_sources_not_truth": derived,
        "goal": canon[0]["value"]["goal"],
        "external_effects_allowed": canon[0]["value"]["external_effects_allowed"],
        "adapter_state": current_evidence[0]["value"]["adapter_state"],
        "option_a_value": current_evidence[0]["value"]["option_a_value"],
        "option_b_value": current_evidence[0]["value"]["option_b_value"],
        "conflict": bool(stale or derived),
    }
    case["epistemic"] = {"confidence": "CURRENT_WITH_STALE_AND_DERIVED_CONFLICT", "conflict": True}
    _emit(case, "TRUTH_SNAPSHOT_ACCEPTED", "external_brain_truth_service", case["truth_snapshot"])
    _set_obligation(case, "O3", "CLOSED", "external_brain_truth_service")
    _set_obligation(case, "O4", "OPEN", "core_case_controller")
    case["next_step"] = "PETER_PROJECT_NEXT_STEP"


def peter_next_step(case: dict[str, Any]) -> None:
    if not authorize(case, "peter_project_change", "project_next_step")["allowed"]:
        raise CoreShadowError("peter_next_step_not_authorized")
    mandate = case.get("peter_mandate") or {}
    if "project_next_step" not in mandate.get("allowed", []):
        raise CoreShadowError("peter_mandate_missing")
    case["project_next_step"] = {
        "technical_blocker": "no_live_adapter_by_design",
        "selected_safe_step": "validate_synthetic_adapter_and_evidence_only",
        "requires_owner": False,
        "local_scope_state": "CLOSED",
        "external_effect": False,
    }
    _emit(case, "PETER_NEXT_STEP_SET", "peter_project_change", case["project_next_step"])
    case["thomas_class"] = "K0"
    _emit(case, "THOMAS_CLASS_SET", "uschi_owner_interface", {"class": "K0", "reason": "technical_blocker_has_safe_internal_path"})
    _set_obligation(case, "O4", "CLOSED", "peter_project_change")
    _set_obligation(case, "O5", "OPEN", "core_case_controller")
    case["current_state"] = "CONTROL_REVIEW_PENDING"
    case["next_step"] = "KONRAD_CHALLENGE"


def propose_internal_derived_update(case: dict[str, Any]) -> dict[str, Any]:
    if not authorize(case, "peter_project_change", "propose_internal_derived_update")["allowed"]:
        raise CoreShadowError("derived_proposal_not_authorized")
    proposal = {
        "action": "internal_derived_update",
        "resource": f"case:{case['case_id']}:derived_view",
        "purpose": case["purpose"],
        "scope": case["scope"],
        "policy_generation": case["generations"]["policy"],
        "resource_generation": case["generations"]["resource"],
        "role_generation": case["generations"]["role"],
        "new_value": {"overall": "REVIEW_PENDING"},
    }
    _emit(case, "DERIVED_UPDATE_PROPOSED", "peter_project_change", proposal)
    return proposal


def commit_internal_derived_update(case: dict[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    current = case["generations"]
    expected = {
        "policy_generation": current["policy"],
        "resource_generation": current["resource"],
        "role_generation": current["role"],
    }
    for key, generation in expected.items():
        if proposal.get(key) != generation:
            result = {"status": "BLOCKED_STALE_PRECONDITION", "mismatch": key, "external_effect": False}
            case["guard_results"].append({"action": "internal_derived_update", "allowed": False, **result})
            _emit(case, "COMMIT_BLOCKED", "core_case_controller", result)
            return result
    case["derived_view"] = deepcopy(dict(proposal["new_value"]))
    result = {"status": "COMMITTED_ISOLATED_DERIVED", "external_effect": False}
    case["guard_results"].append({"action": "internal_derived_update", "allowed": True, **result})
    _emit(case, "DERIVED_UPDATE_COMMITTED", "core_case_controller", {"value": case["derived_view"]})
    return result


def apply_control_finding(case: dict[str, Any], finding: Mapping[str, Any]) -> None:
    required = {"finding_id", "severity", "dissent", "independence_class", "invalidates", "requires_owner"}
    if not required.issubset(finding):
        raise CoreShadowError("control_finding_incomplete")
    case["control_status"] = "MATERIAL_DISSENT"
    case["dissent"].append(deepcopy(dict(finding)))
    case["derived_view"] = {"overall": "CONFLICTED", "reason": "control_invalidated_stale_assumption"}
    _emit(case, "DISSENT_RECORDED", "konrad_control", dict(finding))
    _set_obligation(case, "O5", "CLOSED", "konrad_control")
    _set_obligation(case, "O6", "OPEN", "core_case_controller")
    case["current_state"] = "TRUTH_RECONCILIATION_REQUIRED"
    case["next_step"] = "EXTERNAL_BRAIN_RECONCILE"


def external_brain_reconcile(case: dict[str, Any]) -> None:
    if not authorize(case, "external_brain_truth_service", "reconcile_truth")["allowed"]:
        raise CoreShadowError("truth_reconcile_not_authorized")
    current = next(s for s in case["sources"] if s["source_id"] == "SRC-CURRENT")
    case["truth_snapshot"] = {
        **case["truth_snapshot"],
        "adapter_state": current["value"]["adapter_state"],
        "option_a_value": current["value"]["option_a_value"],
        "option_b_value": current["value"]["option_b_value"],
        "reconciled_after_dissent": True,
        "stale_source_used_for_decision": False,
        "derived_source_used_as_truth": False,
        "conflict": False,
    }
    case["epistemic"] = {"confidence": "CURRENT_RECONCILED", "conflict": False}
    _emit(case, "TRUTH_RECONCILED", "external_brain_truth_service", case["truth_snapshot"])
    _set_obligation(case, "O6", "CLOSED", "external_brain_truth_service")
    _set_obligation(case, "O7", "OPEN", "core_case_controller")
    case["current_state"] = "OWNER_VIEW_PREPARATION"
    case["next_step"] = "USCHI_OWNER_VIEW"


def uschi_owner_view(case: dict[str, Any]) -> dict[str, Any]:
    if not authorize(case, "uschi_owner_interface", "owner_view")["allowed"]:
        raise CoreShadowError("owner_view_not_authorized")
    if _obligation(case, "O6")["state"] not in CLOSED_STATES:
        raise CoreShadowError("truth_not_reconciled")
    package = {
        "thomas_class": "K2",
        "decision_class": "E6_SYNTHETIC_OWNER_PREFERENCE",
        "question": "Choose OPTION_A or OPTION_B; both satisfy current synthetic constraints.",
        "options": [
            {"id": "OPTION_A", "value": case["truth_snapshot"]["option_a_value"]},
            {"id": "OPTION_B", "value": case["truth_snapshot"]["option_b_value"]},
        ],
        "recommendation": "OPTION_A",
        "dissent_visible": bool(case["dissent"]),
        "dissent_summary": [d["dissent"] for d in case["dissent"]],
        "external_effect": False,
    }
    case["owner_view"] = package
    case["thomas_class"] = "K2"
    _set_owner(case, "thomas_owner", "uschi_owner_interface")
    _emit(case, "OWNER_VIEW_READY", "uschi_owner_interface", package)
    _emit(case, "THOMAS_CLASS_SET", "uschi_owner_interface", {"class": "K2", "reason": "synthetic_E6_owner_choice"})
    _set_obligation(case, "O7", "CLOSED", "uschi_owner_interface")
    _set_obligation(case, "O8", "OPEN", "core_case_controller")
    case["current_state"] = "OWNER_DECISION_REQUIRED"
    case["next_step"] = "SYNTHETIC_OWNER_DECISION"
    return package


def synthetic_owner_decision(case: dict[str, Any], choice: str = "OPTION_A") -> None:
    if not authorize(case, "thomas_owner", "decide")["allowed"]:
        raise CoreShadowError("owner_decision_not_authorized")
    valid = {o["id"] for o in case["owner_view"]["options"]}
    if choice not in valid:
        raise CoreShadowError("owner_choice_invalid")
    case["decision_id"] = "DEC-CS0A1-001"
    case["decision"] = {"decision_id": case["decision_id"], "choice": choice, "effect": "NONE_SYNTHETIC"}
    _emit(case, "OWNER_DECISION_RECORDED", "thomas_owner", case["decision"])
    _set_obligation(case, "O8", "CLOSED", "thomas_owner")
    _set_owner(case, "georg_group_ceo", "thomas_owner")
    case["current_state"] = "BENEFIT_PENDING"
    case["business_outcome_state"] = "BENEFIT_PENDING"
    case["next_step"] = "NO_EXTERNAL_ACTION_TEST_COMPLETE"
    case["last_verified_result"] = "SYNTHETIC_FULL_PATH_COMPLETE"


def summary(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "current_state": case["current_state"],
        "current_owner": case["current_owner"],
        "priority": deepcopy(case.get("priority")),
        "peter_mandate": deepcopy(case.get("peter_mandate")),
        "truth_snapshot": deepcopy(case.get("truth_snapshot")),
        "project_next_step": deepcopy(case.get("project_next_step")),
        "thomas_class": case["thomas_class"],
        "dissent": deepcopy(case["dissent"]),
        "decision": deepcopy(case.get("decision")),
        "obligation_states": {o["obligation_id"]: o["state"] for o in case["obligations"]},
        "composite_completion_state": case["composite_completion_state"],
        "open_material_obligations": list(case["open_material_obligations"]),
        "business_outcome_state": case["business_outcome_state"],
    }


def rebuild_from_events(bundle: Mapping[str, Any]) -> dict[str, Any]:
    obligations = deepcopy(bundle["initial_obligation_states"])
    state: dict[str, Any] = {
        "case_id": bundle["case_id"],
        "current_state": "INTAKE",
        "current_owner": "uschi_owner_interface",
        "priority": None,
        "peter_mandate": None,
        "truth_snapshot": None,
        "project_next_step": None,
        "thomas_class": "K0",
        "dissent": [],
        "decision": None,
        "obligation_states": obligations,
        "composite_completion_state": "OPEN",
        "open_material_obligations": list(obligations),
        "business_outcome_state": "PENDING",
    }
    for event in bundle["events"]:
        event_type = event["event_type"]
        payload = event["payload"]
        if event_type == "OWNER_CHANGED":
            state["current_owner"] = payload["to"]
        elif event_type == "GEORG_PRIORITY_SET":
            state["priority"] = deepcopy(payload)
        elif event_type == "PETER_MANDATE_CREATED":
            state["peter_mandate"] = deepcopy(payload)
        elif event_type in {"TRUTH_SNAPSHOT_ACCEPTED", "TRUTH_RECONCILED"}:
            state["truth_snapshot"] = deepcopy(payload)
        elif event_type == "PETER_NEXT_STEP_SET":
            state["project_next_step"] = deepcopy(payload)
        elif event_type == "THOMAS_CLASS_SET":
            state["thomas_class"] = payload["class"]
        elif event_type == "DISSENT_RECORDED":
            state["dissent"].append(deepcopy(payload))
        elif event_type == "OBLIGATION_CHANGED":
            state["obligation_states"][payload["obligation_id"]] = payload["state"]
        elif event_type == "COMPOSITE_STATE_CHANGED":
            state["composite_completion_state"] = payload["state"]
            state["open_material_obligations"] = list(payload["open_material_obligations"])
        elif event_type == "OWNER_VIEW_READY":
            state["current_state"] = "OWNER_DECISION_REQUIRED"
        elif event_type == "OWNER_DECISION_RECORDED":
            state["decision"] = deepcopy(payload)
            state["current_state"] = "BENEFIT_PENDING"
            state["business_outcome_state"] = "BENEFIT_PENDING"
    return state


def build_evidence_bundle(case: Mapping[str, Any], *, restart_replay_equal: bool, authority_surface: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "core-shadow-0a1.evidence.v1",
        "contract_drive_id": CONTRACT_DRIVE_ID,
        "case_id": case["case_id"],
        "original_request_source": case["original_request_source"],
        "synthetic_only": case["synthetic_only"],
        "contains_personal_data": case["contains_personal_data"],
        "contains_productive_data": case["contains_productive_data"],
        "contains_secrets": case["contains_secrets"],
        "source_refs": list(case["source_refs"]),
        "sources": deepcopy(case["sources"]),
        "claims": deepcopy(case["claims"]),
        "writer_map": deepcopy(case["writer_map"]),
        "initial_obligation_states": {
            "O1": "OPEN", "O2": "WAITING_PREDECESSOR", "O3": "WAITING_PREDECESSOR",
            "O4": "WAITING_PREDECESSOR", "O5": "WAITING_PREDECESSOR", "O6": "WAITING_PREDECESSOR",
            "O7": "WAITING_PREDECESSOR", "O8": "WAITING_PREDECESSOR",
        },
        "events": deepcopy(case["events"]),
        "final_summary": summary(case),
        "guard_results": deepcopy(case["guard_results"]),
        "owner_view": deepcopy(case["owner_view"]),
        "restart_replay_equal": restart_replay_equal,
        "authority_surface": deepcopy(dict(authority_surface)),
        "independence_claim": "I0_METHOD_SEPARATE_CODEPATH",
        "external_actions_executed": 0,
        "production_writes": 0,
        "credentials_used": 0,
        "new_running_cost_eur": 0,
        "merge_authorized": False,
    }


def json_roundtrip(case: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(case, ensure_ascii=False, sort_keys=True))
