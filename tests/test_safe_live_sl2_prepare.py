import unittest

from safe_live_sl2.prepare import build_draft, evaluate


def current_fixture():
    return {
        "repo": "Thomas-Baasch/gehirn-runtime-lab",
        "issue42": {"number": 42, "state": "open", "updated_at": "2026-08-25T05:11:50Z", "title": "CORE-SHADOW 0B"},
        "issue42_latest_comment_id": 5405656092,
        "sl1_marker_present": True,
        "firewall_marker_present": True,
        "unresolved_conflict": False,
        "runs": {
            "32811173598": {"conclusion": "success", "head_sha": "005bc3ac67b3ddfaa51c479eff4ca65724dd3910"},
            "32811552246": {"conclusion": "success", "head_sha": "6f87f43ac9cc63e86eecc39b5d23adfe773715e0"},
        },
        "artifacts": {
            "32811173598": [{"id": 9549835571, "digest": "sha256:x", "expired": False}],
            "32811552246": [{"id": 9549958533, "digest": "sha256:y", "expired": False}],
        },
    }


class SafeLiveSL2Tests(unittest.TestCase):
    def test_normal_prepare_only(self):
        result = evaluate(current_fixture())
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["prepared_action"]["execute"])
        self.assertEqual(result["prepared_action"]["effect_class"], "PREPARE_ONLY")
        self.assertEqual(result["clean_1"], "LOOP_4")
        self.assertEqual(result["clean_2"], "LOOP_5")

    def test_wrong_target_blocks(self):
        self.assertEqual(build_draft(current_fixture(), target_issue=41)["status"], "BLOCKED")

    def test_stale_blocks(self):
        cur = current_fixture()
        cur["sl1_marker_present"] = False
        self.assertEqual(build_draft(cur)["reason"], "sl1_current_marker_missing")

    def test_effect_escalation_blocks(self):
        self.assertEqual(build_draft(current_fixture(), requested_effect="POST_COMMENT")["reason"], "effect_escalation_not_authorized")

    def test_conflict_blocks(self):
        cur = current_fixture()
        cur["unresolved_conflict"] = True
        self.assertEqual(build_draft(cur)["reason"], "unresolved_current_conflict")


if __name__ == "__main__":
    unittest.main()
