from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

COMMIT_ORDER = {"SL5-03": 0, "SL5-02": 1, "SL5-01": 2}
ALLOWED_CELLS = tuple(COMMIT_ORDER)


@dataclass(frozen=True)
class OrchestrationPolicy:
    status: str = "DRY_RUN_ONLY"
    max_effects_per_turn: int = 3
    max_commits_per_cell: int = 1
    background_allowed: bool = False
    execute_allowed: bool = False
    kill_switch_present: bool = True
    sl6_authorized: bool = False
    as_of: date = date(2026, 8, 26)
    child_review_by: tuple[tuple[str, date], ...] = (
        ("SL5-01", date(2026, 9, 1)),
        ("SL5-02", date(2026, 9, 2)),
        ("SL5-03", date(2026, 9, 2)),
    )

    @property
    def earliest_child_review(self) -> date:
        return min(d for _, d in self.child_review_by)


@dataclass(frozen=True)
class EffectCandidate:
    cell: str
    semantic_atom_key: str
    effect_type: str
    low_sensitivity: bool = True
    child_active: bool = True
    child_current: bool = True
    child_expired: bool = False
    duplicate: bool = False
    ambiguous_dependency: bool = False


@dataclass(frozen=True)
class PreflightResult:
    batch_allowed: bool
    batch_reason: str
    planned_cells: tuple[str, ...]
    planned_atom_keys: tuple[str, ...]
    blocked: tuple[tuple[str, str], ...]
    execute: bool = False
    sl6_authorized: bool = False


def preflight(policy: OrchestrationPolicy, candidates: Iterable[EffectCandidate], *, background: bool = False) -> PreflightResult:
    cs = tuple(candidates)
    if policy.status != "DRY_RUN_ONLY":
        return PreflightResult(False, "POLICY_NOT_DRY_RUN_ONLY", (), (), ())
    if policy.execute_allowed or policy.sl6_authorized:
        return PreflightResult(False, "DRY_RUN_AUTHORITY_VIOLATION", (), (), ())
    if background or policy.background_allowed:
        return PreflightResult(False, "BACKGROUND_NOT_ALLOWED", (), (), ())
    if not policy.kill_switch_present:
        return PreflightResult(False, "KILL_SWITCH_REQUIRED", (), (), ())
    if policy.as_of > policy.earliest_child_review:
        return PreflightResult(False, "EARLIEST_CHILD_REVIEW_FENCE_EXPIRED", (), (), ())
    if len(cs) > policy.max_effects_per_turn:
        return PreflightResult(False, "VOLUME_LIMIT_EXCEEDED", (), (), ())
    if any(c.cell not in ALLOWED_CELLS for c in cs):
        return PreflightResult(False, "UNKNOWN_CELL", (), (), ())
    if any(c.ambiguous_dependency for c in cs):
        return PreflightResult(False, "AMBIGUOUS_DEPENDENCY", (), (), ())

    cell_counts: dict[str, int] = {}
    atom_counts: dict[str, int] = {}
    for c in cs:
        cell_counts[c.cell] = cell_counts.get(c.cell, 0) + 1
        atom_counts[c.semantic_atom_key] = atom_counts.get(c.semantic_atom_key, 0) + 1
    if any(v > policy.max_commits_per_cell for v in cell_counts.values()):
        return PreflightResult(False, "PER_CELL_LIMIT_EXCEEDED", (), (), ())
    if any(v > 1 for v in atom_counts.values()):
        return PreflightResult(False, "SEMANTIC_ATOM_COLLISION", (), (), ())

    planned: list[EffectCandidate] = []
    blocked: list[tuple[str, str]] = []
    for c in cs:
        if not c.low_sensitivity:
            blocked.append((c.cell, "SENSITIVITY_NOT_ALLOWED"))
            continue
        if not c.child_active:
            blocked.append((c.cell, "CHILD_INACTIVE"))
            continue
        if c.child_expired:
            blocked.append((c.cell, "CHILD_EXPIRED"))
            continue
        if not c.child_current:
            blocked.append((c.cell, "CHILD_CURRENTNESS_BLOCK"))
            continue
        if c.duplicate:
            blocked.append((c.cell, "NOOP_DUPLICATE"))
            continue
        planned.append(c)

    planned.sort(key=lambda c: COMMIT_ORDER[c.cell])
    return PreflightResult(
        True,
        "PREFLIGHT_OK",
        tuple(c.cell for c in planned),
        tuple(c.semantic_atom_key for c in planned),
        tuple(blocked),
    )


@dataclass(frozen=True)
class CommitSimulation:
    committed: tuple[str, ...]
    stopped_on_unknown: str | None
    not_attempted: tuple[str, ...]


def simulate_commits(result: PreflightResult, *, unknown_cell: str | None = None) -> CommitSimulation:
    if not result.batch_allowed:
        return CommitSimulation((), None, result.planned_cells)
    committed: list[str] = []
    for i, cell in enumerate(result.planned_cells):
        if unknown_cell == cell:
            return CommitSimulation(tuple(committed), cell, tuple(result.planned_cells[i + 1 :]))
        committed.append(cell)
    return CommitSimulation(tuple(committed), None, ())
