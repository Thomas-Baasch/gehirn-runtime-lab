from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

AMBIGUOUS_TEXT = "Das sollten wir nächstes Jahr vielleicht verkaufen."


def slm_probe() -> dict:
    # Keep SLM state isolated and deliberately provide no request/profile context.
    td = tempfile.TemporaryDirectory(prefix="eg-slm-gt04-")
    os.environ["SLM_DATA_DIR"] = td.name

    from superlocalmemory.server.routes.helpers import get_active_profile

    profiles_json = Path(td.name) / "profiles.json"
    resolved_profile = get_active_profile()
    td.cleanup()

    ambiguous_unrouted = resolved_profile in {None, "", "AMBIGUOUS", "UNROUTED"}
    return {
        "candidate": "SuperLocalMemory",
        "version": "4.0.8",
        "release_commit": "a5438ee6028c9bd7ca30959a3d61d133c24592ed",
        "input": AMBIGUOUS_TEXT,
        "explicit_target_supplied": False,
        "profiles_json_present": profiles_json.exists(),
        "native_profile_resolution_without_request_context": resolved_profile,
        "contract_expected": "AMBIGUOUS/UNROUTED with no target project",
        "native_ambiguous_unrouted": ambiguous_unrouted,
        "strict_gt04_result": "PASS" if ambiguous_unrouted else "FAIL",
        "component_role_status": "OPEN_BEHIND_EXTERNAL_ROUTER",
        "reason": (
            "Native no-context profile resolution remained unrouted."
            if ambiguous_unrouted
            else "Native no-context profile resolution silently selected a concrete profile instead of returning AMBIGUOUS/UNROUTED."
        ),
    }


class _FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _FakeSearchHandler:
    def __init__(self):
        self.requests = []

    def handle_search_memories(self, req):
        self.requests.append(req)
        return SimpleNamespace(data={"text_mem": [], "pref_string": ""})


class _FakeLLM:
    def generate(self, messages, model_name_or_path=None):
        return "synthetic response"


def memos_probe() -> dict:
    from memos.api.handlers.chat_handler import ChatHandler
    from memos.api.product_models import ChatRequest

    req = ChatRequest(user_id="synthetic-user", query=AMBIGUOUS_TEXT)
    search = _FakeSearchHandler()
    captured_add = {}

    # Exercise the real ChatHandler method while replacing unrelated LLM/search
    # dependencies with deterministic observation fixtures. No routing logic is
    # added by the fixture; writable/readable fallback remains product-native.
    handler = ChatHandler.__new__(ChatHandler)
    handler.logger = _FakeLogger()
    handler.search_handler = search
    handler.chat_llms = {"synthetic-model": _FakeLLM()}
    handler._filter_memories_by_threshold = lambda memories, *args, **kwargs: memories
    handler._build_system_prompt = lambda **kwargs: ""

    def capture_add(**kwargs):
        captured_add.update(kwargs)

    handler._start_add_to_memory = capture_add

    ChatHandler.handle_chat_complete(handler, req)

    search_req = search.requests[0]
    effective_readable = list(search_req.readable_cube_ids or [])
    effective_writable = list(captured_add.get("writable_cube_ids") or [])
    effective_project = captured_add.get("project_id")

    ambiguous_unrouted = (
        not effective_readable
        and not effective_writable
        and effective_project in {None, "", "AMBIGUOUS", "UNROUTED"}
    )
    return {
        "candidate": "MemTensor/MemOS",
        "distribution": "MemoryOS",
        "version": "2.0.30",
        "release_commit": "f4db521214c29337164ec788bafede7eab236c25",
        "input": AMBIGUOUS_TEXT,
        "explicit_target_supplied": False,
        "request_project_id": req.project_id,
        "request_readable_cube_ids": req.readable_cube_ids,
        "request_writable_cube_ids": req.writable_cube_ids,
        "native_effective_readable_cube_ids": effective_readable,
        "native_effective_writable_cube_ids": effective_writable,
        "native_effective_project_id": effective_project,
        "contract_expected": "AMBIGUOUS/UNROUTED with no target project",
        "native_ambiguous_unrouted": ambiguous_unrouted,
        "strict_gt04_result": "PASS" if ambiguous_unrouted else "FAIL",
        "component_role_status": "OPEN_BEHIND_EXTERNAL_ROUTER",
        "reason": (
            "Native chat/add path remained unrouted."
            if ambiguous_unrouted
            else "Without explicit target cubes/project, native ChatHandler falls back to the user-id cube rather than representing the input as AMBIGUOUS/UNROUTED."
        ),
        "fixture_note": "Search/LLM execution is stubbed only to reach and observe the native ChatHandler scope fallback; the test fixture does not implement routing or ambiguity policy.",
    }


def everos_probe() -> dict:
    from everos.entrypoints.api.routes.memorize import MemorizeAddRequest, MessageItemDTO

    req = MemorizeAddRequest(
        session_id="synthetic-session",
        messages=[
            MessageItemDTO(
                sender_id="synthetic-user",
                role="user",
                timestamp=1787160000000,
                content=AMBIGUOUS_TEXT,
            )
        ],
    )
    dumped = req.model_dump()
    project_id = dumped.get("project_id")
    app_id = dumped.get("app_id")
    ambiguous_unrouted = project_id in {None, "", "AMBIGUOUS", "UNROUTED"}
    return {
        "candidate": "EverOS",
        "version": "1.2.3",
        "release_commit": "48fc9084888bc17100053227284f939a5aca5e91",
        "input": AMBIGUOUS_TEXT,
        "explicit_target_supplied": False,
        "native_request_app_id": app_id,
        "native_request_project_id": project_id,
        "contract_expected": "AMBIGUOUS/UNROUTED with no target project",
        "native_ambiguous_unrouted": ambiguous_unrouted,
        "strict_gt04_result": "PASS" if ambiguous_unrouted else "FAIL",
        "component_role_status": "OPEN_BEHIND_EXTERNAL_ROUTER",
        "reason": (
            "Native memorize request remained unrouted."
            if ambiguous_unrouted
            else "Native MemorizeAddRequest silently assigns the concrete project_id='default' when the caller supplies no target, rather than representing the input as AMBIGUOUS/UNROUTED."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, choices=["slm", "memos", "everos"])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    probe = {"slm": slm_probe, "memos": memos_probe, "everos": everos_probe}[args.candidate]
    candidate_result = probe()
    report = {
        "schema": "externes-gehirn.cross-project-runtime-evidence.v0.1",
        "golden_test": "GT-04",
        "test_name": "AMBIGUOUS_UNROUTED_NO_SILENT_DEFAULT_TARGET",
        "interpretation_scope": "STRICT_UNCHANGED_CANON_ROUTER_PATH",
        **candidate_result,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    # The workflow must finish so FAIL is captured as product evidence rather
    # than being confused with a broken test harness.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
