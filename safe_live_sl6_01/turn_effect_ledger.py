from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

ALLOWED_CELLS = {"SL5-01", "SL5-02", "SL5-03"}
CONSUMED_STATES = {"RESERVED", "COMMITTED", "UNKNOWN", "NO_EFFECT_VERIFIED"}


@dataclass(frozen=True)
class BudgetState:
    turn_id: str
    cell: str
    semantic_atom_key: str
    state: str


class TurnEffectLedger:
    """Durable SL6 per-turn/per-child effect budget.

    A reservation consumes the child budget for the whole active turn.  This is
    intentionally stricter than merely counting successful commits: a crash or
    unknown downstream result must never make a second attempt look fresh.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orchestration_turns (
                    turn_id TEXT PRIMARY KEY,
                    owner_input_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('OPEN','CLOSED')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS child_effect_budget (
                    turn_id TEXT NOT NULL,
                    cell TEXT NOT NULL,
                    semantic_atom_key TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('RESERVED','COMMITTED','UNKNOWN','NO_EFFECT_VERIFIED')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(turn_id, cell),
                    FOREIGN KEY(turn_id) REFERENCES orchestration_turns(turn_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    cell TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    @staticmethod
    def _require_token(value: str, label: str) -> None:
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError(f"invalid_{label}")

    @staticmethod
    def _audit(conn: sqlite3.Connection, event_type: str, turn_id: str, cell: str | None, payload: dict) -> None:
        conn.execute(
            "INSERT INTO audit_events(event_type,turn_id,cell,payload_json) VALUES(?,?,?,?)",
            (event_type, turn_id, cell, json.dumps(payload, sort_keys=True, ensure_ascii=False)),
        )

    def open_turn(self, turn_id: str, owner_input_fingerprint: str) -> str:
        self._require_token(turn_id, "turn_id")
        self._require_token(owner_input_fingerprint, "owner_input_fingerprint")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT owner_input_fingerprint,status FROM orchestration_turns WHERE turn_id=?",
                    (turn_id,),
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO orchestration_turns(turn_id,owner_input_fingerprint,status) VALUES(?,?,'OPEN')",
                        (turn_id, owner_input_fingerprint),
                    )
                    self._audit(conn, "TURN_OPENED", turn_id, None, {"fingerprint": owner_input_fingerprint})
                    conn.execute("COMMIT")
                    return "OPENED_NEW"
                if str(row["owner_input_fingerprint"]) != owner_input_fingerprint:
                    self._audit(conn, "TURN_ID_FINGERPRINT_CONFLICT", turn_id, None, {})
                    conn.execute("COMMIT")
                    return "FAIL_CLOSED_TURN_CONFLICT"
                if str(row["status"]) == "CLOSED":
                    self._audit(conn, "CLOSED_TURN_REOPEN_BLOCKED", turn_id, None, {})
                    conn.execute("COMMIT")
                    return "FAIL_CLOSED_TURN_CLOSED"
                self._audit(conn, "TURN_REOPEN_IDEMPOTENT", turn_id, None, {})
                conn.execute("COMMIT")
                return "OPEN_ALREADY"
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def reserve(self, turn_id: str, cell: str, semantic_atom_key: str) -> str:
        self._require_token(turn_id, "turn_id")
        self._require_token(semantic_atom_key, "semantic_atom_key")
        if cell not in ALLOWED_CELLS:
            return "FAIL_CLOSED_UNKNOWN_CELL"
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                turn = conn.execute(
                    "SELECT status FROM orchestration_turns WHERE turn_id=?", (turn_id,)
                ).fetchone()
                if turn is None:
                    self._audit(conn, "MISSING_TURN_BLOCKED", turn_id, cell, {})
                    conn.execute("COMMIT")
                    return "FAIL_CLOSED_MISSING_TURN"
                if str(turn["status"]) != "OPEN":
                    self._audit(conn, "CLOSED_TURN_EFFECT_BLOCKED", turn_id, cell, {})
                    conn.execute("COMMIT")
                    return "FAIL_CLOSED_TURN_CLOSED"

                row = conn.execute(
                    "SELECT semantic_atom_key,state FROM child_effect_budget WHERE turn_id=? AND cell=?",
                    (turn_id, cell),
                ).fetchone()
                if row is not None:
                    self._audit(
                        conn,
                        "SECOND_CHILD_EFFECT_BLOCKED",
                        turn_id,
                        cell,
                        {
                            "existing_atom": str(row["semantic_atom_key"]),
                            "existing_state": str(row["state"]),
                            "requested_atom": semantic_atom_key,
                        },
                    )
                    conn.execute("COMMIT")
                    return "BLOCK_CHILD_BUDGET_CONSUMED"

                conn.execute(
                    "INSERT INTO child_effect_budget(turn_id,cell,semantic_atom_key,state) VALUES(?,?,?,'RESERVED')",
                    (turn_id, cell, semantic_atom_key),
                )
                self._audit(conn, "CHILD_EFFECT_RESERVED", turn_id, cell, {"semantic_atom_key": semantic_atom_key})
                conn.execute("COMMIT")
                return "RESERVED"
            except sqlite3.IntegrityError:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                return "BLOCK_CHILD_BUDGET_CONSUMED"
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def _transition(self, turn_id: str, cell: str, new_state: str) -> str:
        if new_state not in CONSUMED_STATES - {"RESERVED"}:
            raise ValueError("invalid_effect_state")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT state FROM child_effect_budget WHERE turn_id=? AND cell=?",
                    (turn_id, cell),
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return "FAIL_CLOSED_NO_RESERVATION"
                old = str(row["state"])
                if old == new_state:
                    self._audit(conn, "STATE_REPLAY_NOOP", turn_id, cell, {"state": new_state})
                    conn.execute("COMMIT")
                    return "NOOP_SAME_STATE"
                if old != "RESERVED":
                    self._audit(conn, "INVALID_STATE_TRANSITION_BLOCKED", turn_id, cell, {"old": old, "new": new_state})
                    conn.execute("COMMIT")
                    return "FAIL_CLOSED_STATE_TRANSITION"
                conn.execute(
                    "UPDATE child_effect_budget SET state=?, updated_at=CURRENT_TIMESTAMP WHERE turn_id=? AND cell=?",
                    (new_state, turn_id, cell),
                )
                self._audit(conn, f"CHILD_EFFECT_{new_state}", turn_id, cell, {})
                conn.execute("COMMIT")
                return new_state
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def mark_committed(self, turn_id: str, cell: str) -> str:
        return self._transition(turn_id, cell, "COMMITTED")

    def mark_unknown(self, turn_id: str, cell: str) -> str:
        return self._transition(turn_id, cell, "UNKNOWN")

    def mark_no_effect_verified(self, turn_id: str, cell: str) -> str:
        # Still consumes this turn's budget.  A proven no-effect does not reopen
        # the same child slot during the same user/assistant turn.
        return self._transition(turn_id, cell, "NO_EFFECT_VERIFIED")

    def close_turn(self, turn_id: str) -> str:
        self._require_token(turn_id, "turn_id")
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT status FROM orchestration_turns WHERE turn_id=?", (turn_id,)).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return "FAIL_CLOSED_MISSING_TURN"
                if str(row["status"]) == "CLOSED":
                    conn.execute("COMMIT")
                    return "NOOP_ALREADY_CLOSED"
                conn.execute("UPDATE orchestration_turns SET status='CLOSED', updated_at=CURRENT_TIMESTAMP WHERE turn_id=?", (turn_id,))
                self._audit(conn, "TURN_CLOSED", turn_id, None, {})
                conn.execute("COMMIT")
                return "CLOSED"
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                conn.close()

    def budget_state(self, turn_id: str, cell: str) -> BudgetState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT turn_id,cell,semantic_atom_key,state FROM child_effect_budget WHERE turn_id=? AND cell=?",
                (turn_id, cell),
            ).fetchone()
            if row is None:
                return None
            return BudgetState(str(row["turn_id"]), str(row["cell"]), str(row["semantic_atom_key"]), str(row["state"]))

    def audit(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT seq,event_type,turn_id,cell,payload_json FROM audit_events ORDER BY seq").fetchall()
            return [
                {
                    "seq": int(r["seq"]),
                    "event_type": str(r["event_type"]),
                    "turn_id": str(r["turn_id"]),
                    "cell": None if r["cell"] is None else str(r["cell"]),
                    "payload": json.loads(str(r["payload_json"])),
                }
                for r in rows
            ]

    def integrity_ok(self) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                return row is not None and str(row[0]).lower() == "ok"
        except sqlite3.DatabaseError:
            return False
