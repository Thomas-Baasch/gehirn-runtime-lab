from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from superlocalmemory.access.rbac import Permission, RbacEngine
from superlocalmemory.server.rbac_enforce import require_permission
from superlocalmemory.storage.migrations import M024_rbac_users_roles as m024


SECRET_CONTENT = "SYNTHETIC_SECRET_PROJECT_A_CONTENT"
SECRET_METADATA = "sensitivity=CONFIDENTIAL;purpose=PROJECT_A_ONLY"


def request_for(rbac: RbacEngine, token: str = ""):
    headers = {"X-SLM-User-Session": token} if token else {}
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(rbac=rbac)),
        headers=headers,
        cookies={},
    )


def decision(rbac: RbacEngine, token: str, profile: str) -> dict:
    req = request_for(rbac, token)
    try:
        principal = require_permission(req, Permission.READ, profile=profile)
        return {
            "allowed": True,
            "status_code": 200,
            "detail": None,
            "principal_kind": principal.get("kind"),
            "principal_user_id": principal.get("user_id"),
        }
    except HTTPException as exc:
        detail = str(exc.detail)
        return {
            "allowed": False,
            "status_code": exc.status_code,
            "detail": detail,
            "principal_kind": None,
            "principal_user_id": None,
            "leaks_secret_content": SECRET_CONTENT in detail,
            "leaks_secret_metadata": SECRET_METADATA in detail,
        }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eg-slm-gt09-") as td:
        db = Path(td) / "memory.db"
        with sqlite3.connect(db) as conn:
            m024.apply(conn)
            assert m024.verify(conn)

        rbac = RbacEngine(db)
        user = rbac.create_user("viewer-a", "synthetic-password-1234")
        user_id = user["user_id"]
        rbac.set_membership("project_a", user_id, "viewer")
        rbac.set_require_login(True)
        token = rbac.create_session(user_id)

        allow_a = decision(rbac, token, "project_a")
        deny_b = decision(rbac, token, "project_b")
        no_session = decision(rbac, "", "project_a")
        invalid_session = decision(rbac, "definitely-invalid-session", "project_a")

        direct_read_a = rbac.has_permission(user_id, "project_a", Permission.READ)
        direct_read_b = rbac.has_permission(user_id, "project_b", Permission.READ)
        profiles = rbac.list_user_profiles(user_id)

        no_leak_b = (
            deny_b["status_code"] == 403
            and not deny_b.get("leaks_secret_content", False)
            and not deny_b.get("leaks_secret_metadata", False)
        )
        no_leak_auth = all(
            d["status_code"] == 401
            and not d.get("leaks_secret_content", False)
            and not d.get("leaks_secret_metadata", False)
            for d in (no_session, invalid_session)
        )
        component_pass = all(
            [
                allow_a["allowed"],
                allow_a["status_code"] == 200,
                direct_read_a,
                not direct_read_b,
                no_leak_b,
                no_leak_auth,
                profiles == [{"profile_id": "project_a", "role": "viewer"}],
            ]
        )

        report = {
            "schema": "externes-gehirn.component-runtime-evidence.v0.1",
            "candidate": "SuperLocalMemory",
            "version": "4.0.8",
            "release_commit": "a5438ee6028c9bd7ca30959a3d61d133c24592ed",
            "tested_role": "GT09_ACCESS_RBAC_SUBSTRATE",
            "golden_test_informed_but_not_fully_claimed": "GT-09",
            "input": {
                "principal": "viewer-a",
                "allowed_profile": "project_a",
                "blocked_profile": "project_b",
                "synthetic_sensitive_content_marker": SECRET_CONTENT,
                "synthetic_sensitive_metadata_marker": SECRET_METADATA,
                "company_mode_require_login": True,
            },
            "observations": {
                "allowed_project_a": allow_a,
                "blocked_project_b": deny_b,
                "no_session_project_a": no_session,
                "invalid_session_project_a": invalid_session,
                "direct_read_permission_project_a": direct_read_a,
                "direct_read_permission_project_b": direct_read_b,
                "user_profile_memberships": profiles,
                "blocked_response_no_content_or_metadata_marker_leak": no_leak_b,
                "auth_failure_responses_no_content_or_metadata_marker_leak": no_leak_auth,
            },
            "component_result": "PASS" if component_pass else "FAIL",
            "full_gt09_result": "NOT_CLAIMED",
            "reason": (
                "SLM native RBAC/session/profile layer enforced project A allow and project B deny-by-default, with generic 401/403 failures that did not expose the synthetic content or metadata markers. This validates the access-control substrate only. The product-neutral contract also requires sensitivity/purpose policy semantics; that separate dimension is not proven by this RBAC probe and must be enforced before a full GT-09 PASS can be claimed."
                if component_pass
                else "One or more native SLM RBAC/session/profile isolation properties required for the GT-09 access-control substrate failed."
            ),
        }

        out = Path("reports/critical/slm_gt09_access_component.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if component_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
