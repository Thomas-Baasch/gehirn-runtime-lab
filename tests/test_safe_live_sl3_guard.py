import unittest

from safe_live_sl3.guard import (
    ALLOWED_EFFECT,
    EXPECTED_BRANCH,
    EXPECTED_REPO,
    MARKER_PATH,
    authorize,
)


class SL3GuardTests(unittest.TestCase):
    def test_exact_scope_authorized(self):
        self.assertEqual(authorize(repo=EXPECTED_REPO, branch=EXPECTED_BRANCH, path=MARKER_PATH, effect=ALLOWED_EFFECT, target_exists=False, branch_head_matches_expected=True), (True, "authorized"))

    def test_wrong_branch_blocks(self):
        self.assertFalse(authorize(repo=EXPECTED_REPO, branch="main", path=MARKER_PATH, effect=ALLOWED_EFFECT, target_exists=False, branch_head_matches_expected=True)[0])

    def test_wrong_path_blocks(self):
        self.assertFalse(authorize(repo=EXPECTED_REPO, branch=EXPECTED_BRANCH, path="README.md", effect=ALLOWED_EFFECT, target_exists=False, branch_head_matches_expected=True)[0])

    def test_existing_target_blocks_overwrite(self):
        self.assertFalse(authorize(repo=EXPECTED_REPO, branch=EXPECTED_BRANCH, path=MARKER_PATH, effect=ALLOWED_EFFECT, target_exists=True, branch_head_matches_expected=True)[0])

    def test_effect_escalation_blocks(self):
        self.assertFalse(authorize(repo=EXPECTED_REPO, branch=EXPECTED_BRANCH, path=MARKER_PATH, effect="POST_COMMENT", target_exists=False, branch_head_matches_expected=True)[0])

    def test_head_drift_blocks(self):
        self.assertFalse(authorize(repo=EXPECTED_REPO, branch=EXPECTED_BRANCH, path=MARKER_PATH, effect=ALLOWED_EFFECT, target_exists=False, branch_head_matches_expected=False)[0])


if __name__ == "__main__":
    unittest.main()
