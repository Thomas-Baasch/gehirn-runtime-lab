from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

from safe_live_sl6_01.turn_effect_ledger import TurnEffectLedger

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
    durable_turn_ledger_required: bool = True


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


@dataclass(frozen=True)
class GuardedCommitResult:
    committed: tuple[str, ...]
    blocked: tuple[tuple[str, str], ...]
    stopped_on_unknown: str | None
    not_attempted: tuple[str, ...]


def evaluate(policy: Policy, children: Iterable[ChildState], candidates: Iterable[Candidate], *, as_of: date, background: bool=False, activation_event: bool=False) -> Decision:
    if policy.status != "ACTIVE" or not policy.owner_authorized or not policy.execute_orchestration:
        return Decision(False, "SL6_NOT_ACTIVE_AUTHORIZED", (), (), ())
    if not policy.kill_switch or not policy.no_inheritance or not policy.durable_turn_ledger_required:
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


def _planned_pairs(decision: Decision) -> tuple[tuple[str, str], ...]:
    return tuple(zip(decision.planned_cells, decision.planned_atoms, strict=True))


def guarded_commit_sequence(
    decision: Decision,
    *,
    ledger: TurnEffectLedger | None,
    orchestration_turn_id: str | None,
    outcomes: dict[str, str] | None = None,
    before_effect: Callable[[str, str], None] | None = None,
) -> GuardedCommitResult:
    """Apply the durable per-turn budget immediately before each child effect.

    `outcomes` is a harness/runtime adapter seam.  COMMITTED means the child
    effect and mandatory readback succeeded.  NO_EFFECT means readback proves
    no child effect occurred.  UNKNOWN means downstream outcome is uncertain;
    the child slot remains consumed and all later children are stopped.
    """
    if not decision.allowed_to_orchestrate:
        return GuardedCommitResult((), (), None, decision.planned_cells)
    if ledger is None or not orchestration_turn_id:
        return GuardedCommitResult((), (("SL6", "FAIL_CLOSED_DURABLE_TURN_LEDGER_REQUIRED"),), None, decision.planned_cells)

    outcomes = outcomes or {}
    committed: list[str] = []
    blocked: list[tuple[str, str]] = []
    pairs = _planned_pairs(decision)
    for i, (cell, atom) in enumerate(pairs):
        try:
            reservation = ledger.reserve(orchestration_turn_id, cell, atom)
        except Exception:
            return GuardedCommitResult(tuple(committed), tuple(blocked + [(cell, "FAIL_CLOSED_LEDGER_ERROR")]), None, tuple(c for c, _ in pairs[i+1:]))

        if reservation == "BLOCK_CHILD_BUDGET_CONSUMED":
            blocked.append((cell, "NOOP_CHILD_BUDGET_ALREADY_CONSUMED"))
            continue
        if reservation != "RESERVED":
            return GuardedCommitResult(tuple(committed), tuple(blocked + [(cell, reservation)]), None, tuple(c for c, _ in pairs[i+1:]))

        if before_effect is not None:
            before_effect(cell, atom)

        outcome = outcomes.get(cell, "COMMITTED")
        if outcome == "COMMITTED":
            if ledger.mark_committed(orchestration_turn_id, cell) not in {"COMMITTED", "NOOP_SAME_STATE"}:
                return GuardedCommitResult(tuple(committed), tuple(blocked + [(cell, "FAIL_CLOSED_LEDGER_COMMIT_STATE")]), None, tuple(c for c, _ in pairs[i+1:]))
            committed.append(cell)
            continue
        if outcome == "NO_EFFECT":
            ledger.mark_no_effect_verified(orchestration_turn_id, cell)
            blocked.append((cell, "NO_EFFECT_VERIFIED_BUDGET_CONSUMED"))
            continue
        if outcome == "UNKNOWN":
            ledger.mark_unknown(orchestration_turn_id, cell)
            return GuardedCommitResult(tuple(committed), tuple(blocked), cell, tuple(c for c, _ in pairs[i+1:]))
        ledger.mark_unknown(orchestration_turn_id, cell)
        return GuardedCommitResult(tuple(committed), tuple(blocked + [(cell, "FAIL_CLOSED_UNKNOWN_OUTCOME")]), cell, tuple(c for c, _ in pairs[i+1:]))

    return GuardedCommitResult(tuple(committed), tuple(blocked), None, ())


def simulate_commit_sequence(decision: Decision, unknown_cell: str|None=None) -> tuple[tuple[str,...], str|None, tuple[str,...]]:
    """Historical dry-run helper retained for backwards compatibility.

    Active/revalidated execution must use `guarded_commit_sequence`; this helper
    alone does not enforce cross-call same-turn budgets.
    """
    if not decision.allowed_to_orchestrate:
        return (), None, decision.planned_cells
    committed: list[str] = []
    for i, cell in enumerate(decision.planned_cells):
        if cell == unknown_cell:
            return tuple(committed), cell, tuple(decision.planned_cells[i+1:])
        committed.append(cell)
    return tuple(committed), None, ()
