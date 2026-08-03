"""Integration tests for the public toolkit's immutable pre-push leak scan.

Run from the repository root with:
    .venv/bin/python -m unittest automation.hooks.tests.test_public_pre_push

Each test copies the hook and its guard into a throwaway Git repository. The
stdin records are the exact protocol Git gives a pre-push hook, so these tests
cover ref selection as well as the guard's object materialization.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_PUSH = REPO_ROOT / "automation/hooks/pre-push"
PUBLISH_DIR = REPO_ROOT / "automation/publish"
ZERO_OID = "0" * 40
REMOTE_URL = "ssh://git@git.example.test/public/toolkit.git"
PROBE_TOKEN = "SuperSecretSlug"


class PublicPrePushTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="public-pre-push-")).resolve()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.bin = self.repo / ".stub-bin"
        self.bin.mkdir()
        python = self.bin / "python3"
        python.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        python.chmod(0o755)
        self.env = dict(os.environ)
        self.env.update({
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "JOBHUNT_PERSONAL_TOKENS": PROBE_TOKEN,
        })
        self.git("init", "-q", ".")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "Test")
        (self.repo / "automation/hooks").mkdir(parents=True)
        (self.repo / "automation/publish").mkdir(parents=True)
        shutil.copy2(PRE_PUSH, self.repo / "automation/hooks/pre-push")
        for name in ("check_public.py", "sync_skill_manifests.py"):
            shutil.copy2(PUBLISH_DIR / name, self.repo / "automation/publish" / name)
        self.write(".gitignore", ".stub-bin/\n")
        self.write("README.md", "clean\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.clean_oid = self.oid()

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ("git", *args), cwd=self.repo, env=self.env,
            capture_output=True, text=True, check=True,
        )

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def oid(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref).stdout.strip()

    def commit_notes(self, text: str, message: str) -> str:
        self.write("notes.md", text)
        self.git("add", "notes.md")
        self.git("commit", "-qm", message)
        return self.oid()

    def update(self, local_ref: str, local_oid: str,
               remote_ref: str = "refs/heads/topic",
               remote_oid: str = ZERO_OID) -> str:
        return f"{local_ref} {local_oid} {remote_ref} {remote_oid}\n"

    def run_hook(self, updates: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.repo / "automation/hooks/pre-push"), "origin", REMOTE_URL],
            cwd=self.repo, env=self.env, input=updates,
            capture_output=True, text=True,
        )

    def test_non_head_ref_tree_is_scanned(self) -> None:
        self.git("switch", "-qc", "leaky")
        leaky_oid = self.commit_notes(f"hello {PROBE_TOKEN}\n", "leak")
        self.git("switch", "-q", "main")
        self.assertEqual(self.oid(), self.clean_oid)

        result = self.run_hook(self.update("refs/heads/leaky", leaky_oid))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("refs/heads/leaky", result.stdout + result.stderr)
        self.assertIn(PROBE_TOKEN, result.stdout)

    def test_multi_ref_push_fails_when_later_tree_leaks(self) -> None:
        self.git("switch", "-qc", "leaky")
        leaky_oid = self.commit_notes(f"hello {PROBE_TOKEN}\n", "leak")
        updates = (
            self.update("refs/heads/main", self.clean_oid, "refs/heads/main")
            + self.update("refs/heads/leaky", leaky_oid, "refs/heads/leaky")
        )

        result = self.run_hook(updates)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("PASSED for 'refs/heads/main'", output)
        self.assertIn("refs/heads/leaky", output)

    def test_each_clean_ref_in_multi_ref_push_is_scanned(self) -> None:
        updates = (
            self.update("refs/heads/main", self.clean_oid, "refs/heads/main")
            + self.update("refs/heads/topic", self.clean_oid, "refs/heads/topic")
        )

        result = self.run_hook(updates)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASSED for 'refs/heads/main'", result.stdout)
        self.assertIn("PASSED for 'refs/heads/topic'", result.stdout)

    def test_deletion_is_skipped(self) -> None:
        self.write("notes.md", f"dirty {PROBE_TOKEN}\n")
        deletion = self.update(
            "(delete)", ZERO_OID, "refs/heads/obsolete", self.clean_oid)

        result = self.run_hook(deletion)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no non-deletion ref updates", result.stdout)

    def test_clean_dirty_edit_cannot_mask_leak_in_outgoing_oid(self) -> None:
        leaky_oid = self.commit_notes(f"hello {PROBE_TOKEN}\n", "leak")
        self.write("notes.md", "clean in worktree only\n")

        result = self.run_hook(self.update("refs/heads/topic", leaky_oid))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(PROBE_TOKEN, result.stdout)

    def test_dirty_leak_does_not_block_clean_outgoing_oid(self) -> None:
        self.write("notes.md", f"dirty {PROBE_TOKEN}\n")

        result = self.run_hook(
            self.update("refs/heads/main", self.clean_oid, "refs/heads/main"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASSED for 'refs/heads/main'", result.stdout)


if __name__ == "__main__":
    unittest.main()
