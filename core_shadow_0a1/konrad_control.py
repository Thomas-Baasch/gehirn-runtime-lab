from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

# Deliberately does NOT import core_shadow_0a1.runtime.
INDEPENDENCE_CLASS = "I0_METHOD_SEPARATE_CODEPATH"


class ControlError(ValueError):
    pass


def challenge(case_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if case_snapshot.get("case_id") != "CS0A1-SYN-001":
        raise ControlError("unexpected_case_id")
    truth = case_snapshot.get("truth_snapshot")
    derived = case_snapshot.get("derived_view")
    if not isinstance(truth, Mapping) or not isinstance(derived, Mapping):
        raise ControlError("required_snapshot_missing")

    stale = list(truth.get("stale_sources") or [])
    derived_not_truth = list(truth.get("derived_sources_not_truth") or [])
    assumption = derived.get("assumption")
    material = bool(stale and derived_not_truth and assumption == "stale_adapter_ready")
    if not material:
        return {
            "finding_id": "KF-CS0A1-000",
            "severity": "NONE",
            "dissent": "No material dissent in supplied synthetic snapshot.",
            "independence_class": INDEPENDENCE_CLASS,
            "invalidates": [],
            "requires_owner": False,
            "read_only": True,
        }
    return {
        "finding_id": "KF-CS0A1-001",
        "severity": "MATERIAL",
        "dissent": "Derived GREEN relied on a stale adapter-readiness assumption and cannot represent current truth.",
        "independence_class": INDEPENDENCE_CLASS,
        "invalidates": ["derived_view.overall", "derived_view.assumption"],
        "requires_owner": False,
        "read_only": True,
        "source_refs": deepcopy(stale + derived_not_truth),
    }
