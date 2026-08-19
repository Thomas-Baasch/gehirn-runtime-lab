from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import everos
from everos.memory.reflection.orchestrator import ReflectionOrchestrator
from everos.memory.strategies.reflect_episodes import reflect_episodes


class FakeEpisodeStore:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    async def update(self, values: dict, *, where: str) -> None:
        self.updates.append({"values": dict(values), "where": where})


class FakeFactStore:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    async def update(self, values: dict, *, where: str) -> None:
        self.updates.append({"values": dict(values), "where": where})


class FakeClusterRepo:
    def __init__(self, members: set[str]) -> None:
        self.members = set(members)
        self.removed: list[dict] = []
        self.added: list[dict] = []
        self.metadata_updates: list[dict] = []

    async def remove_members(self, cluster_id: str, member_ids: set[str]) -> None:
        self.members -= set(member_ids)
        self.removed.append({"cluster_id": cluster_id, "member_ids": sorted(member_ids)})

    async def add_member(self, cluster_id: str, member_id: str, member_type: str) -> None:
        self.members.add(member_id)
        self.added.append(
            {"cluster_id": cluster_id, "member_id": member_id, "member_type": member_type}
        )

    async def update_metadata(self, cluster_id: str, **kwargs) -> None:
        self.metadata_updates.append({"cluster_id": cluster_id, **kwargs})


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class Unused:
    pass


def scan_package_tokens(module_name: str, tokens: list[str]) -> dict[str, list[str]]:
    spec = importlib.util.find_spec(module_name)
    roots: list[Path] = []
    if spec is not None:
        if spec.submodule_search_locations:
            roots.extend(Path(p) for p in spec.submodule_search_locations)
        elif spec.origin:
            roots.append(Path(spec.origin).parent)

    hits: dict[str, list[str]] = {token: [] for token in tokens}
    seen_files: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path in seen_files:
                continue
            seen_files.add(path)
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for token in tokens:
                if token in text:
                    try:
                        rel = str(path.relative_to(root))
                    except ValueError:
                        rel = path.name
                    hits[token].append(rel)
    return hits


async def execute_native_deprecation_control() -> dict:
    old_ids = {"ep_price_490", "ep_price_510"}
    merged_id = "ep_price_merged_current"
    app_id = "synthetic_app"
    project_id = "synthetic_project"
    owner_id = "synthetic_user"

    episode_store = FakeEpisodeStore()
    fact_store = FakeFactStore()
    cluster_repo = FakeClusterRepo(old_ids)

    orchestrator = ReflectionOrchestrator(
        cluster_repo=cluster_repo,
        episode_store=episode_store,
        atomic_fact_store=fact_store,
        episode_writer=Unused(),
        report_repo=Unused(),
        reflector=Unused(),
        embedder=FakeEmbedder(),
    )

    dep_ep_count = await orchestrator._deprecate_lance_episodes(
        entry_ids=old_ids,
        owner_id=owner_id,
        app_id=app_id,
        project_id=project_id,
        merged_entry_id=merged_id,
    )
    dep_fact_count = await orchestrator._deprecate_lance_facts(
        parent_ids=old_ids,
        owner_id=owner_id,
        merged_entry_id=merged_id,
    )

    episodes = [
        SimpleNamespace(timestamp=datetime(2026, 8, 1, tzinfo=UTC)),
        SimpleNamespace(timestamp=datetime(2026, 8, 2, tzinfo=UTC)),
    ]
    algo_result = SimpleNamespace(
        episode="The current price is 510 Euro.",
        subject="Current price",
    )
    await orchestrator._update_cluster_after_merge(
        cluster_id="cluster-price",
        to_deprecate=old_ids,
        merged_entry_id=merged_id,
        algo_result=algo_result,
        episodes=episodes,
    )

    episode_scope_bound = all(
        u["values"] == {"deprecated_by": merged_id}
        and f"owner_id = '{owner_id}'" in u["where"]
        and f"app_id = '{app_id}'" in u["where"]
        and f"project_id = '{project_id}'" in u["where"]
        for u in episode_store.updates
    )
    originals_deprecated = (
        dep_ep_count == 2
        and len(episode_store.updates) == 2
        and all(u["values"] == {"deprecated_by": merged_id} for u in episode_store.updates)
    )
    facts_deprecated = (
        dep_fact_count == 2
        and len(fact_store.updates) == 2
        and all(u["values"] == {"deprecated_by": merged_id} for u in fact_store.updates)
    )
    collapsed_to_single_merged_member = cluster_repo.members == {merged_id}
    metadata_count_one = bool(
        cluster_repo.metadata_updates
        and cluster_repo.metadata_updates[-1].get("count") == 1
    )

    return {
        "original_episode_ids": sorted(old_ids),
        "merged_entry_id": merged_id,
        "deprecated_episode_update_count": dep_ep_count,
        "deprecated_fact_update_count": dep_fact_count,
        "episode_updates": episode_store.updates,
        "fact_updates": fact_store.updates,
        "episode_deprecation_is_app_project_owner_scoped": episode_scope_bound,
        "original_episodes_marked_deprecated_by_merged": originals_deprecated,
        "original_facts_marked_deprecated_by_merged": facts_deprecated,
        "final_cluster_members": sorted(cluster_repo.members),
        "cluster_collapsed_to_single_merged_member": collapsed_to_single_merged_member,
        "cluster_metadata_count_one": metadata_count_one,
    }


async def main_async() -> int:
    installed_root = Path(inspect.getfile(everos)).resolve().parent
    everos_surface = scan_package_tokens(
        "everos", ["epistemic_status", "CONFLICTING", "knowledge_type", "deprecated_by"]
    )
    everalgo_surface = scan_package_tokens(
        "everalgo.user_memory", ["contradict", "latest", "current state"]
    )

    safe_default = reflect_episodes.meta.enabled is False
    deprecation = await execute_native_deprecation_control()
    native_collapse_observed = bool(
        deprecation["original_episodes_marked_deprecated_by_merged"]
        and deprecation["cluster_collapsed_to_single_merged_member"]
        and deprecation["cluster_metadata_count_one"]
    )
    first_class_conflicting_literal_present = bool(
        everos_surface["epistemic_status"] or everos_surface["CONFLICTING"]
    )

    # Strict GT-08 requires contradictory current claims to coexist as CONFLICTING.
    # Reflection OFF is a useful safe mode but does not establish that semantic state.
    # The enabled Reflection deprecation path demonstrably collapses originals behind
    # one merged current member, so unchanged EverOS cannot pass strict GT-08 as Canon router.
    strict_gt08_pass = False

    report = {
        "schema": "externes-gehirn.cross-project-runtime-evidence.v0.1",
        "candidate": "EverOS",
        "distribution": "everos",
        "version": "1.2.3",
        "release_commit": "48fc9084888bc17100053227284f939a5aca5e91",
        "golden_test": "GT-08",
        "controls": {
            "safe_mode_reflection_off": {
                "strategy_name": reflect_episodes.meta.name,
                "enabled_default": reflect_episodes.meta.enabled,
                "safe_default_confirmed": safe_default,
            },
            "negative_control_native_reflection_deprecation": deprecation,
        },
        "runtime_surface_scan": {
            "everos_package_root": str(installed_root),
            "everos_token_hits": everos_surface,
            "everalgo_user_memory_policy_token_hits": everalgo_surface,
            "first_class_conflicting_literal_present_on_installed_everos_surface": first_class_conflicting_literal_present,
        },
        "observations": {
            "reflection_off_by_default_runtime_confirmed": safe_default,
            "enabled_reflection_deprecation_collapses_originals_behind_merged_current_member": native_collapse_observed,
            "original_episode_deprecation_scoped_by_owner_app_project": deprecation[
                "episode_deprecation_is_app_project_owner_scoped"
            ],
        },
        "result": "PASS" if strict_gt08_pass else "FAIL",
        "critical_fail": not strict_gt08_pass,
        "reason": (
            "EverOS preserved both contradictory current claims as first-class CONFLICTING records."
            if strict_gt08_pass
            else "Reflection is safely disabled by default, but that alone does not provide the contract's CONFLICTING epistemic state. On the native enabled Reflection deprecation path, original episodes/facts are marked deprecated_by a merged entry and the cluster is reduced to one merged current member. Therefore EverOS v1.2.3 does not satisfy strict GT-08 unchanged as the Canon router."
        ),
        "scope_note": "Observation stores and embedder are deterministic test fixtures only. The decisions to write deprecated_by, remove old cluster members, add the merged member, and set cluster count=1 are executed by EverOS native ReflectionOrchestrator methods. No adapter conflict policy is added.",
    }

    out = Path("reports/critical/everos_gt08_controls.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
