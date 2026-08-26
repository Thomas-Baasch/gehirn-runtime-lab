from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

ORDER = {"SL5-03": 0, "SL5-02": 1, "SL5-01": 2}
EXPECTED = {
    "SL5-01": ("SAFE_LIVE_SL5_01_MATERIAL_MILESTONE_LOGGING_V0_1", date(2026, 9, 1), "ISSUE_COMMENT"),
    "SL5-02": ("SAFE_LIVE_SL5_02_ACTIVE_TURN_MATERIAL_DELTA_PERSISTENCE_V0_1", date(2026, 9, 2), "DRIVE_DERIVED_DELTA_APPEND_OR_NOOP_ONLY"),
    "SL5-03": ("SAFE_LIVE_SL5_03_USCHI_OWNER_DIRECT_TASK_EVENT_CONTROL_V0_1", date(2026, 9, 2), "DRIVE_USCHI_TASK_EVENT_APPEND_OR_NOOP_ONLY"),
}

@dataclass(frozen=True)
class Policy:
    status: str = "ACTIVE"
    active_from: date = date(2026, 8, 26)
    review_by: date = date(2026, 9, 1)
    owner_authorized: bool = True
    max_effects_per_turn: int = 3
    max_commits_per_cell: int = 1
    execute_orchestration: bool = True
    background_allowed: bool = False
    activation_is_not_trigger: bool = True
    kill_switch: bool = True
    no_inheritance: bool = True

@dataclass(frozen=True)
class ChildState:
    cell: str
    policy_id: str
    status: str
    review_by: date
    allowed_effect: str
    current: bool = True

@dataclass(frozen=True)
class Candidate:
    cell: str
    semantic_atom_key: str
    effect_type: str
    low_sensitivity: bool = True
    duplicate: bool = False
    ambiguous_dependency: bool = False
    owner_task_semantics: bool = False

@dataclass(frozen=True)
class Decision:
    allowed_to_orchestrate: bool
    reason: str
    planned_cells: tuple[str, ...]
    planned_atoms: tuple[str, ...]
    blocked: tuple[tuple[str, str], ...]


def evaluate(policy: Policy, children: Iterable[ChildState], candidates: Iterable[Candidate], *, as_of: date, background: bool=False, activation_event: bool=False) -> Decision:
    if policy.status != "ACTIVE" or not policy.owner_authorized or not policy.execute_orchestration:
        return Decision(False, "SL6_NOT_ACTIVE_AUTHORIZED", (), (), ())
    if not policy.kill_switch or not policy.no_inheritance:
        return Decision(False, "SL6_GUARD_MISSING", (), (), ())
    if background or policy.background_allowed:
        return Decision(False, "BACKGROUND_NOT_ALLOWED", (), (), ())
    if activation_event and policy.activation_is_not_trigger:
        return Decision(False, "ACTIVATION_IS_NOT_TRIGGER", (), (), ())
    if as_of > policy.review_by:
        return Decision(False, "SL6_REVIEW_FENCE_EXPIRED", (), (), ())

    child_map = {c.cell: c for c in children}
    for cell, (pid, review_by, effect) in EXPECTED.items():
        c = child_map.get(cell)
        if c is None:
            return Decision(False, f"CHILD_MISSING:{cell}", (), (), ())
        if c.policy_id != pid or c.allowed_effect != effect:
            return Decision(False, f"CHILD_ID_OR_EFFECT_DRIFT:{cell}", (), (), ())
        if c.status != "ACTIVE" or not c.current:
            return Decision(False, f"CHILD_NOT_CURRENT_ACTIVE:{cell}", (), (), ())
        if c.review_by != review_by or as_of > c.review_by:
            return Decision(False, f"CHILD_REVIEW_FENCE:{cell}", (), (), ())

    cs = tuple(candidates)
    if len(cs) > policy.max_effects_per_turn:
        return Decision(False, "VOLUME_LIMIT_EXCEEDED", (), (), ())
    if any(c.cell not in EXPECTED for c in cs):
        return Decision(False, "UNKNOWN_CELL", (), (), ())
    if any(c.ambiguous_dependency for c in cs):
        return Decision(False, "AMBIGUOUS_DEPENDENCY", (), (), ())

    counts: dict[str,int] = {}
    atoms: dict[str,int] = {}
    for c in cs:
        counts[c.cell] = counts.get(c.cell, 0) + 1
        atoms[c.semantic_atom_key] = atoms.get(c.semantic_atom_key, 0) + 1
    if any(v > policy.max_commits_per_cell for v in counts.values()):
        return Decision(False, "PER_CELL_LIMIT_EXCEEDED", (), (), ())
    if any(v > 1 for v in atoms.values()):
        return Decision(False, "SEMANTIC_ATOM_COLLISION", (), (), ())

    planned: list[Candidate] = []
    blocked: list[tuple[str,str]] = []
    for c in cs:
        if not c.low_sensitivity:
            blocked.append((c.cell, "SENSITIVITY_NOT_ALLOWED")); continue
        if c.duplicate:
            blocked.append((c.cell, "NOOP_DUPLICATE")); continue
        if c.cell == "SL5-02" and c.owner_task_semantics:
            blocked.append((c.cell, "TASK_DOMINANCE_TO_SL5_03")); continue
        planned.append(c)
    planned.sort(key=lambda x: ORDER[x.cell])
    return Decision(True, "ORCHESTRATION_PREFLIGHT_OK", tuple(c.cell for c in planned), tuple(c.semantic_atom_key for c in planned), tuple(blocked))


def simulate_commit_sequence(decision: Decision, unknown_cell: str|None=None) -> tuple[tuple[str,...], str|None, tuple[str,...]]:
    if not decision.allowed_to_orchestrate:
        return (), None, decision.planned_cells
    committed: list[str] = []
    for i, cell in enumerate(decision.planned_cells):
        if cell == unknown_cell:
            return tuple(committed), cell, tuple(decision.planned_cells[i+1:])
        committed.append(cell)
    return tuple(committed), None, ()
