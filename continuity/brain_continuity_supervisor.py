from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "continuity" / "brain-continuity-contract.json"


class ContinuityState(str, Enum):
    WORKING = "WORKING"
    GRACE = "GRACE"
    PROGRESS_CONFIRMED = "PROGRESS_CONFIRMED"
    EXECUTION_GAP = "EXECUTION_GAP"
    WAITING_EXPECTED = "WAITING_EXPECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Contract:
    policy: str
    frozen_at: datetime
    progress_markers: tuple[str, ...]
    branch: str
    status_issue: int
    stale_after_seconds: int


@dataclass(frozen=True)
class CommitObservation:
    message: str
    committed_at: datetime


@dataclass(frozen=True)
class Decision:
    state: ContinuityState
    reason: str
    active_run_count: int
    dispatch_allowed: bool = False


class RuntimeErrorSafe(RuntimeError):
    pass


def _norm(value: object | None) -> str:
    return " ".join(str(value or "").strip().split())


def _parse_dt(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeErrorSafe("invalid_contract_timestamp") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def load_contract(path: Path = CONTRACT_PATH) -> Contract:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeErrorSafe("contract_unreadable") from exc
    if payload.get("schema") != "externes-gehirn.continuity-contract":
        raise RuntimeErrorSafe("contract_schema_mismatch")
    expected = payload.get("expected_contract")
    watch = payload.get("watch")
    rights = payload.get("rights")
    if not isinstance(expected, Mapping) or not isinstance(watch, Mapping) or not isinstance(rights, Mapping):
        raise RuntimeErrorSafe("contract_structure_invalid")
    if rights.get("dispatch_workflow") is not False or rights.get("merge") is not False:
        raise RuntimeErrorSafe("unsafe_rights_contract")
    markers = expected.get("progress_markers")
    if not isinstance(markers, list) or not markers or not all(_norm(x) for x in markers):
        raise RuntimeErrorSafe("progress_markers_invalid")
    issue = int(watch.get("status_issue") or 0)
    stale = int(watch.get("stale_after_seconds") or 0)
    branch = _norm(watch.get("branch"))
    if issue <= 0 or stale <= 0 or not branch:
        raise RuntimeErrorSafe("watch_contract_invalid")
    return Contract(
        policy=_norm(payload.get("continuation_policy")),
        frozen_at=_parse_dt(_norm(expected.get("frozen_at_utc"))),
        progress_markers=tuple(_norm(x).casefold() for x in markers),
        branch=branch,
        status_issue=issue,
        stale_after_seconds=stale,
    )


def _commit_matches(commit: CommitObservation, contract: Contract) -> bool:
    if commit.committed_at < contract.frozen_at:
        return False
    message = commit.message.casefold()
    return any(marker in message for marker in contract.progress_markers)


def evaluate(
    contract: Contract,
    *,
    now: datetime,
    active_run_count: int,
    recent_commits: Sequence[CommitObservation],
) -> Decision:
    if contract.policy in {"PARKED", "WAITING_EXTERNAL", "MANUAL_ON_DEMAND"}:
        return Decision(ContinuityState.WAITING_EXPECTED, "contract_not_autonomous", active_run_count)

    if contract.policy != "AUTONOMOUS_EXPECTED_WHEN_NEXT_CONTRACT_FROZEN":
        return Decision(ContinuityState.UNKNOWN, "unknown_continuation_policy", active_run_count)

    if active_run_count > 0:
        return Decision(ContinuityState.WORKING, "active_non_supervisor_run_present", active_run_count)

    if any(_commit_matches(commit, contract) for commit in recent_commits):
        return Decision(ContinuityState.PROGRESS_CONFIRMED, "phase_progress_commit_after_freeze", 0)

    age = max(0, int((now.astimezone(timezone.utc) - contract.frozen_at).total_seconds()))
    if age <= contract.stale_after_seconds:
        return Decision(ContinuityState.GRACE, "frozen_contract_within_grace_period", 0)

    return Decision(
        ContinuityState.EXECUTION_GAP,
        "frozen_next_contract_without_active_run_or_matching_progress_commit",
        0,
        dispatch_allowed=False,
    )


def _repository() -> str:
    repo = _norm(os.environ.get("GITHUB_REPOSITORY"))
    if not repo or "/" not in repo:
        raise RuntimeErrorSafe("missing_github_repository")
    return repo


def _token() -> str:
    token = _norm(os.environ.get("GITHUB_TOKEN"))
    if not token:
        raise RuntimeErrorSafe("missing_github_token")
    return token


def _api_root() -> str:
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def _api_json(method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {_token()}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "brain-continuity-supervisor",
    }
    if payload is not None:
        data = json.dumps(dict(payload), sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(f"{_api_root()}{path}", data=data, method=method.upper(), headers=headers)
    try:
        with urlopen(req, timeout=30) as response:  # noqa: S310 - fixed GitHub API root
            raw = response.read()
    except HTTPError as exc:
        raise RuntimeErrorSafe(f"github_api_http_{exc.code}") from exc
    except URLError as exc:
        raise RuntimeErrorSafe("github_api_unreachable") from exc
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeErrorSafe("github_api_invalid_json") from exc


def _active_runs(branch: str) -> list[Mapping[str, Any]]:
    statuses = ("in_progress", "queued", "waiting", "requested", "pending")
    found: dict[int, Mapping[str, Any]] = {}
    for status in statuses:
        payload = _api_json(
            "GET",
            f"/repos/{_repository()}/actions/runs?branch={quote(branch, safe='')}&status={status}&per_page=100",
        )
        if not isinstance(payload, Mapping):
            continue
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            continue
        for run in runs:
            if not isinstance(run, Mapping):
                continue
            if _norm(run.get("name")) == "Externes Gehirn Continuity Supervisor":
                continue
            run_id = int(run.get("id") or 0)
            if run_id > 0:
                found[run_id] = run
    return list(found.values())


def _recent_commits(branch: str) -> list[CommitObservation]:
    payload = _api_json(
        "GET",
        f"/repos/{_repository()}/commits?sha={quote(branch, safe='')}&per_page=30",
    )
    if not isinstance(payload, list):
        raise RuntimeErrorSafe("commit_history_unreadable")
    observations: list[CommitObservation] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        commit = item.get("commit")
        if not isinstance(commit, Mapping):
            continue
        message = _norm(commit.get("message"))
        committer = commit.get("committer")
        if not isinstance(committer, Mapping):
            continue
        date_text = _norm(committer.get("date"))
        if not date_text:
            continue
        try:
            committed_at = _parse_dt(date_text)
        except RuntimeErrorSafe:
            continue
        observations.append(CommitObservation(message=message, committed_at=committed_at))
    return observations


def _status_body(decision: Decision, contract: Contract, *, now: datetime) -> str:
    thomas = "nichts"
    if decision.state is ContinuityState.EXECUTION_GAP:
        thomas = "nichts sofort; der Portfolio-Bericht soll den fehlenden Ausführungsagenten sichtbar machen."
    return "\n".join(
        [
            "# Externes Gehirn Continuity",
            "",
            f"**Stand:** {decision.state.value}",
            f"**Continuation policy:** `{contract.policy}`",
            f"**Aktive fachliche Runs:** {decision.active_run_count}",
            f"**Grund:** `{decision.reason}`",
            "**Nächster fachlicher Vertrag:** Phase C – Truth-Aware Answer-Set (extern frozen before runtime)",
            "**Automatischer beliebiger Entwicklungs-Dispatch:** NEIN – kein verifizierter Executor vorhanden.",
            f"**Thomas muss:** {thomas}",
            f"**Letzte Prüfung:** {now.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "Keine Stackentscheidung, keine Threshold-Absenkung, kein Merge und keine Außenwirkung aus diesem Supervisor.",
        ]
    )


def run_live() -> Decision:
    contract = load_contract()
    now = datetime.now(timezone.utc)
    decision = evaluate(
        contract,
        now=now,
        active_run_count=len(_active_runs(contract.branch)),
        recent_commits=_recent_commits(contract.branch),
    )
    _api_json(
        "PATCH",
        f"/repos/{_repository()}/issues/{contract.status_issue}",
        {"body": _status_body(decision, contract, now=now)},
    )
    return decision


def main() -> int:
    try:
        decision = run_live()
    except (RuntimeErrorSafe, ValueError) as exc:
        print(f"BRAIN_CONTINUITY_SUPERVISOR_FAIL:{exc}")
        return 1
    print(f"BRAIN_CONTINUITY_STATE={decision.state.value}")
    print(f"BRAIN_CONTINUITY_REASON={decision.reason}")
    print("BRAIN_CONTINUITY_DISPATCH_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
