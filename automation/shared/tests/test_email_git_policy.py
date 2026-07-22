"""Proof that email bodies cannot be selected for Git publication by policy."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
PUBLISH = Path(__file__).resolve().parents[2] / "publish"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(PUBLISH))

from mail.git_policy import IGNORED, TRACKABLE, email_git_disposition  # noqa: E402
import check_public  # noqa: E402


class EmailGitPolicyTests(unittest.TestCase):
    def test_only_content_free_header_and_safe_annotations_are_trackable(self):
        self.assertEqual(email_git_disposition("email/raw/outlook/acct-01/x/manifest.json"), IGNORED)
        self.assertEqual(email_git_disposition("email/derived/acct-01/messages/x/message.yaml"), IGNORED)
        self.assertEqual(email_git_disposition("email/state/acct-01/sync.json"), IGNORED)
        self.assertEqual(email_git_disposition("email/index/acct-01/messages.jsonl"), IGNORED)
        self.assertEqual(email_git_disposition("email/index/acct-01/triage/unresolved.jsonl"), IGNORED)
        self.assertEqual(email_git_disposition("email/annotations/evidence/a.txt"), IGNORED)
        self.assertEqual(email_git_disposition("email/index/acct-01/header.json"), TRACKABLE)
        self.assertEqual(email_git_disposition("email/annotations/acct-01/verified.yaml"), TRACKABLE)

    def test_planted_body_is_excluded_before_public_leak_guard_scans_tracked_files(self):
        # Split so the test source itself contains no accidental personal token.
        planted = "Taylor" + "PrivateMailboxBody"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "email/raw/outlook/acct-01/2026/07/22/fetch/manifest.json"
            raw.parent.mkdir(parents=True)
            raw.write_text(planted, encoding="utf-8")
            header = root / "email/index/acct-01/header.json"
            header.parent.mkdir(parents=True)
            header.write_text('{"content_free":true}\n', encoding="utf-8")
            candidates = [raw, header]
            tracked = [
                path.relative_to(root).as_posix()
                for path in candidates
                if email_git_disposition(path.relative_to(root).as_posix()) == TRACKABLE
            ]
            self.assertEqual(tracked, ["email/index/acct-01/header.json"])
            result = check_public.scan(root=root, tracked=tracked, tokens=[planted])
            self.assertTrue(result["ok"], result["violations"])


if __name__ == "__main__":
    unittest.main()
