"""Leak-guard proof for the store: overlay tokens never reach the public tree.

The store holds real personal data in the PRIVATE overlay data root
(``private/data/``, git-ignored). This test proves two things the raw-data-layer
sign-off requires:

1. a personal token seeded into a fake overlay data root is NOT present in any
   tracked public file (the tracked ``examples/data`` fixture passes the guard even
   with that token active); and
2. the overlay data path is denied on path alone, so if such a file were ever
   accidentally tracked the guard fails closed.

Following the sibling ``test_leak_guard.py`` convention, the seeded token is
assembled from split fragments so THIS source stays guard-clean while the runtime
overlay file it writes still trips the guard.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_PUBLISH_DIR = Path(__file__).resolve().parents[1]
if str(_PUBLISH_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISH_DIR))

import check_public  # noqa: E402

REPO_ROOT = check_public.REPO_ROOT
FIXTURE = REPO_ROOT / "examples" / "data"

# A personal-identity token that lives ONLY in the overlay (assembled so this file
# stays guard-clean — see module docstring).
SEEDED_TOKEN = "Dana" + "Harrison" + "OverlaySecret"


class StoreLeakGuardTests(unittest.TestCase):
    def setUp(self):
        if not FIXTURE.is_dir():
            self.skipTest("fixture store missing; run generate_fixture_store.py")

    def test_overlay_token_never_reaches_public_and_fixture_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Public tracked tree: a copy of the committed fixture store.
            shutil.copytree(FIXTURE, root / "examples" / "data")
            # Private overlay data root holding the seeded personal token — this is
            # git-ignored in the real repo, so it is NOT in the tracked list below.
            overlay = root / "private" / "data" / "jobs" / "state"
            overlay.mkdir(parents=True, exist_ok=True)
            (overlay / "identifiers.yaml").write_text(
                "schema_version: 1\nprofile:\n  profile-01: "
                f"{SEEDED_TOKEN}\naccount: {{}}\n", encoding="utf-8")

            tracked = [p.relative_to(root).as_posix()
                       for p in root.rglob("*")
                       if p.is_file() and "private/" not in
                       p.relative_to(root).as_posix()]

            # The seeded token is active, but it lives only in the (untracked)
            # overlay — so a scan of the tracked tree is CLEAN.
            result = check_public.scan(root=root, tracked=tracked,
                                       tokens=[SEEDED_TOKEN])
            self.assertTrue(result["ok"], result["violations"])
            # Sanity: the overlay file with the token really exists and is untracked.
            self.assertTrue((overlay / "identifiers.yaml").exists())
            self.assertNotIn("private/data/jobs/state/identifiers.yaml", tracked)

    def test_overlay_data_path_is_denied_if_ever_tracked(self):
        # If an overlay data file were somehow tracked, the guard fails closed.
        violations = check_public.find_personal_overlay_violations(
            ["private/data/jobs/state/identifiers.yaml"])
        self.assertTrue(violations)
        self.assertEqual(violations[0]["category"], "personal_overlay")

    def test_fixture_is_guard_clean_with_no_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copytree(FIXTURE, root / "examples" / "data")
            result = check_public.scan(root=root, tokens=[])
            self.assertTrue(result["ok"], result["violations"])


if __name__ == "__main__":
    unittest.main()
