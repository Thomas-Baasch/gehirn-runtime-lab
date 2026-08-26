from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CellState:
    active: bool = True
    expired: bool = False
    current: bool = True
    duplicate: bool = False


@dataclass(frozen=True)
class Atom:
    kind: str
    semantic_atom_key: str
    low_sensitivity: bool = True
    confirmed_task: bool = False
    ambiguous: bool = False
    material: bool = False
    qualified_milestone: bool = False
    correction_valid: bool = False
    generic_continue: bool = False


@dataclass(frozen=True)
class RouteResult:
    sl5_01: str
    sl5_02: str
    sl5_03: str
    sl6_authorized: bool = False


def _local(base: str, state: CellState) -> str:
    if not state.active:
        return "BLOCK_INACTIVE"
    if state.expired:
        return "BLOCK_EXPIRED"
    if not state.current:
        return "BLOCK_CURRENTNESS"
    if state.duplicate:
        return "NOOP_DUPLICATE"
    return base


def route(atom: Atom, sl501: CellState, sl502: CellState, sl503: CellState) -> RouteResult:
    if atom.generic_continue:
        return RouteResult("NOOP_GENERIC_CONTINUE", "NOOP_GENERIC_CONTINUE", "NOOP_GENERIC_CONTINUE")
    if not atom.semantic_atom_key.strip():
        return RouteResult("BLOCK_NO_SEMANTIC_KEY", "BLOCK_NO_SEMANTIC_KEY", "BLOCK_NO_SEMANTIC_KEY")
    if not atom.low_sensitivity:
        return RouteResult("BLOCK_SENSITIVITY", "BLOCK_SENSITIVITY", "BLOCK_SENSITIVITY")

    if atom.kind == "OWNER_DIRECT_TASK_EVENT":
        if atom.ambiguous or not atom.confirmed_task:
            return RouteResult("NOOP_NOT_MILESTONE", "NOOP_TASK_DOMINANCE", "BLOCK_UNCONFIRMED_TASK")
        # Task dominance: same semantic atom must never become a parallel SL5-02 OPEN_LOOP delta.
        return RouteResult(
            "NOOP_NOT_MILESTONE",
            "NOOP_TASK_DOMINANCE",
            _local("ALLOW_TASK_EVENT", sl503),
        )

    if atom.kind == "OWNER_TASK_CORRECTION":
        if atom.ambiguous or not atom.correction_valid:
            return RouteResult("NOOP_NOT_MILESTONE", "NOOP_TASK_DOMINANCE", "BLOCK_INVALID_CORRECTION")
        return RouteResult(
            "NOOP_NOT_MILESTONE",
            "NOOP_TASK_DOMINANCE",
            _local("ALLOW_TASK_SUPERSESSION", sl503),
        )

    if atom.kind == "SAFE_LIVE_MATERIAL_MILESTONE":
        if not atom.qualified_milestone:
            return RouteResult("NOOP_NOT_QUALIFIED", "NOOP_NOT_MATERIAL", "NOOP_NOT_TASK")
        # Two different purposes are allowed: audit log (SL5-01) and evidence locator/state delta (SL5-02).
        return RouteResult(
            _local("ALLOW_MILESTONE_COMMENT", sl501),
            _local("ALLOW_MILESTONE_EVIDENCE_DELTA", sl502),
            "NOOP_NOT_TASK",
        )

    if atom.kind == "MATERIAL_NON_TASK_DELTA":
        if not atom.material or atom.ambiguous:
            return RouteResult("NOOP_NOT_MILESTONE", "BLOCK_NOT_CLEAR_MATERIAL", "NOOP_NOT_TASK")
        return RouteResult(
            "NOOP_NOT_MILESTONE",
            _local("ALLOW_MATERIAL_DELTA", sl502),
            "NOOP_NOT_TASK",
        )

    if atom.kind == "AMBIGUOUS_OR_INCOMPLETE":
        return RouteResult("NOOP_AMBIGUOUS", "NOOP_AMBIGUOUS", "NOOP_AMBIGUOUS")

    return RouteResult("BLOCK_UNKNOWN_KIND", "BLOCK_UNKNOWN_KIND", "BLOCK_UNKNOWN_KIND")
