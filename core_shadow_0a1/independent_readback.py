from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

# Deliberately does NOT import runtime.py or konrad_control.py.
EXPECTED_CASE = "CS0A1-SYN-001"
EXPECTED_CONTRACT = "1YMD3ynywpfgKYY-v7dzN4eqcx6mA0Pm9RLBjPI7hwjg"


class IndependentReadbackError(ValueError):
    pass


def evaluate(bundle: Mapping[str, Any]) -> dict[str, Any]:
    if bundle.get("schema") != "core-shadow-0a1.evidence.v1":
        raise IndependentReadbackError("evidence_schema_invalid")
    if bundle.get("case_id") != EXPECTED_CASE:
        raise IndependentReadbackError("case_id_invalid")
    if bundle.get("contract_drive_id") != EXPECTED_CONTRACT:
        raise IndependentReadbackError("contract_ref_invalid")

    observations = bundle.get("observations")
    final = bundle.get("final_summary")
    sources = bundle.get("sources")
    events = bundle.get("events")
    if not isinstance(observations, Mapping):
        raise IndependentReadbackError("observations_missing")
    if not isinstance(final, Mapping):
        raise IndependentReadbackError("final_summary_missing")
    if not isinstance(sources, list):
        raise IndependentReadbackError("sources_missing")
    if not isinstance(events, list) or not events:
        raise IndependentReadbackError("events_missing")

    case_ids = {e.get("case_id") for e in events if isinstance(e, Mapping)}
    writers = bundle.get("writer_map") or {}
    stale_ids = {s.get("source_id") for s in sources if isinstance(s, Mapping) and s.get("current") is False}
    derived_ids = {s.get("source_id") for s in sources if isinstance(s, Mapping) and s.get("class") == "DERIVED"}
    truth = final.get("truth_snapshot") or {}
    owner_view = bundle.get("owner_view") or {}
    dissent = final.get("dissent") or []
    obligations = final.get("obligation_states") or {}
    authority = bundle.get("authority_surface") or {}

    tests: list[dict[str, Any]] = []

    def add(test_id: str, passed: bool, detail: str) -> None:
        tests.append({"id": test_id, "pass": bool(passed), "detail": detail})

    add("CS-01", bool(bundle.get("source_refs")) and bundle.get("original_request_source", "").startswith("fixture://"), "external/fixture source references are explicit; chat state is not a truth source")
    add("CS-02", case_ids == {EXPECTED_CASE}, f"event case ids={sorted(str(x) for x in case_ids)}")
    add("CS-03", bool(writers) and all(isinstance(v, str) and v for v in writers.values()), "every listed load-bearing field names exactly one writer; no field carries competing writers")
    add("CS-04", bool(stale_ids) and not bool(stale_ids & {truth.get("canon_source"), truth.get("current_evidence_source")}) and truth.get("stale_source_used_for_decision") is False, f"stale={sorted(stale_ids)}")
    add("CS-05", bool(derived_ids) and truth.get("derived_source_used_as_truth") is False and not bool(derived_ids & {truth.get("canon_source"), truth.get("current_evidence_source")}), f"derived={sorted(derived_ids)}")
    add("CS-06", observations.get("peter_local_state") == "CLOSED" and observations.get("thomas_class_at_peter_close") == "K0" and observations.get("peter_requires_owner") is False, "technical blocker followed safe internal path without owner escalation")
    add("CS-07", owner_view.get("thomas_class") == "K2" and owner_view.get("decision_class") == "E6_SYNTHETIC_OWNER_PREFERENCE" and final.get("decision", {}).get("choice") in {"OPTION_A", "OPTION_B"}, "owner choice appears only as synthetic E6 K2 package")
    add("CS-08", bool(dissent) and owner_view.get("dissent_visible") is True and truth.get("reconciled_after_dissent") is True, "material dissent remains visible and triggered reconciliation")
    add("CS-09", bundle.get("independence_claim") == "I0_METHOD_SEPARATE_CODEPATH" and all(d.get("independence_class") == "I0_METHOD_SEPARATE_CODEPATH" for d in dissent), "no false I2/I3 independence claim")
    unknown = observations.get("unknown_authority_result") or {}
    add("CS-10", unknown.get("allowed") is False and unknown.get("reason") == "UNKNOWN_SUBJECT", "unknown authority fails closed")
    outside = observations.get("outside_action_result") or {}
    add("CS-11", outside.get("allowed") is False and outside.get("reason") == "OUTSIDE_ACTION_BOUNDARY" and bundle.get("external_actions_executed") == 0, "external action attempt blocked; no outside effect executed")
    add("CS-12", bundle.get("synthetic_only") is True and bundle.get("contains_personal_data") is False and bundle.get("contains_productive_data") is False and bundle.get("contains_secrets") is False, "fixture is synthetic and contains no personal/productive/secret data")
    add("CS-13", bundle.get("restart_replay_equal") is True, "JSON crash/restart path equals uninterrupted final load-bearing state")
    add("CS-14", observations.get("rebuild_equal") is True and observations.get("rebuild_summary") == final, "event/evidence rebuild reproduces final load-bearing summary without chat history")
    add("CS-15", owner_view.get("thomas_class") == "K2" and len(owner_view.get("options") or []) == 2 and bool(owner_view.get("question")) and owner_view.get("dissent_visible") is True, "owner view contains correct class, options, question and dissent")
    add("CS-16", observations.get("independent_readback_input_only") is True, "this evaluator reads evidence only and does not import primary decision/routing logic")
    mandate = final.get("peter_mandate") or {}
    priority = final.get("priority") or {}
    add("CS-17", priority.get("owner_constraints_preserved") is True and "project_next_step" in mandate.get("allowed", []) and "owner_decision" in mandate.get("forbidden", []) and "control_override" in mandate.get("forbidden", []), "GEORG prioritizes/mandates but cannot take owner decision, PETER execution, or control override")
    add("CS-18", observations.get("composite_at_peter_close") == "OPEN" and bool(observations.get("open_at_peter_close")) and final.get("composite_completion_state") == "CLOSED" and not final.get("open_material_obligations") and all(state == "CLOSED" for state in obligations.values()), "local PETER close did not close composite while material obligations remained; final close has no orphan")
    add("CS-19", observations.get("old_commit_status") == "BLOCKED_STALE_PRECONDITION" and observations.get("revalidated_commit_status") == "COMMITTED_ISOLATED_DERIVED", "commit-time generation mismatch blocks stale approval until revalidated")
    add("CS-20", authority.get("status") == "PASS" and authority.get("external_effect_interfaces") == [] and authority.get("workflow_write_permissions") == [] and bundle.get("production_writes") == 0 and bundle.get("credentials_used") == 0 and bundle.get("new_running_cost_eur") == 0 and bundle.get("merge_authorized") is False, "separate static surface review found no external-effect or privileged interface")

    passed = sum(1 for t in tests if t["pass"])
    return {
        "schema": "core-shadow-0a1.independent-readback.v1",
        "independence_class": "I0_METHOD_SEPARATE_CODEPATH",
        "case_id": EXPECTED_CASE,
        "passed": passed,
        "total": len(tests),
        "status": "PASS" if passed == 20 and len(tests) == 20 else "FAIL",
        "tests": tests,
        "load_bearing_outcome": {
            "composite_completion_state": final.get("composite_completion_state"),
            "thomas_class_before_synthetic_decision": owner_view.get("thomas_class"),
            "decision": deepcopy(final.get("decision")),
            "dissent_count": len(dissent),
            "business_outcome_state": final.get("business_outcome_state"),
        },
    }
