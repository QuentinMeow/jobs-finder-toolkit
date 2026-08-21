"""Tests for the workspace-hygiene gardener routine.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/gardener/tests \
        -t automation/gardener/tests

Three properties, and they are the three that make this a reminder rather than a
gate: it FINDS a branch whose content is already in main and whose worktree is
gone, it EXITS 0 while doing so, and it names nothing at all from the private
overlay. The deep merge-shape coverage lives with the dashboard it borrows
(``automation/workspace/tests``); this file pins the routine's own contract.

Every test runs against a throwaway git repository — never the real repo and
never the overlay (``test_fixture_isolation.py`` is the standing guard).
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import workspace_hygiene as WH  # noqa: E402

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Gardener Test",
    "GIT_AUTHOR_EMAIL": "gardener@example.invalid",
    "GIT_COMMITTER_NAME": "Gardener Test",
    "GIT_COMMITTER_EMAIL": "gardener@example.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


class WorkspaceTree(unittest.TestCase):
    """A scratch repository standing in for the toolkit checkout."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="workspace-hygiene-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = self.root.parent / (self.root.name + "-home")
        self.home.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        previous = {key: os.environ.get(key) for key in (*GIT_ENV, "HOME")}

        def restore() -> None:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)
        os.environ.update(GIT_ENV)
        os.environ["HOME"] = str(self.home)

        saved = WH.C.REPO_ROOT
        WH.C.REPO_ROOT = self.root
        self.addCleanup(lambda: setattr(WH.C, "REPO_ROOT", saved))
        self._build()

    def git(self, repo: Path, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(repo), *args], check=False,
                                capture_output=True, text=True, env=dict(os.environ))
        if result.returncode:
            raise AssertionError(f"git {' '.join(args)}: {result.stderr}")
        return result.stdout.strip()

    def _write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _build(self) -> None:
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)],
                       check=True, env=dict(os.environ))
        self._write(self.root / "AGENTS.md", "fixture\n")
        self._write(self.root / "config.example.yaml", "fixture: true\n")
        self._write(self.root / "automation" / "shared" / "config.py", "# fixture\n")
        self._write(self.root / "skills" / "job-search" / "SKILL.md", "# fixture\n")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "base")
        # A branch whose content main already has, with nobody on it.
        self.git(self.root, "branch", "finished-work")
        # A branch with unique work.
        self.git(self.root, "switch", "-q", "-c", "open-work")
        self._write(self.root / "open.txt", "unique\n")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "-m", "open-work: unique work")
        self.git(self.root, "switch", "-q", "main")
        # A registration whose directory the owner deleted: it wedges its branch.
        holder = self.root.parent / (self.root.name + "-worktrees")
        holder.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, holder, ignore_errors=True)
        self.git(self.root, "worktree", "add", "-q", "-b", "wedged-work",
                 str(holder / "gone"), "main")
        shutil.rmtree(holder / "gone")

    def report(self) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = WH.run()
        self.assertEqual(code, 0, "a hygiene reminder must never fail a caller")
        return buffer.getvalue()


class FindingsTests(WorkspaceTree):
    def test_it_finds_the_finished_branch_and_names_its_evidence(self) -> None:
        report = self.report()
        self.assertIn("finished-work", report)
        # The SOURCE beside the number: this verdict is local and unfetched, and
        # a reader who does not know that would treat it as permission to delete.
        self.assertIn("LOCAL evidence, no fetch was performed", report)
        self.assertIn("automation/workspace/cleanup.py", report)

    def test_it_reports_a_wedged_branch_and_the_command_that_frees_it(self) -> None:
        report = self.report()
        self.assertIn("WEDGED", report)
        self.assertIn("wedged-work", report)
        self.assertIn("git worktree prune", report)

    def test_a_branch_with_unique_work_is_never_listed_as_finished(self) -> None:
        finished = [entry["name"] for entry in WH.scan(self.root)["merged_idle"]]
        self.assertIn("finished-work", finished)
        self.assertNotIn("open-work", finished)

    def test_it_exits_zero_and_changes_nothing(self) -> None:
        before = self.git(self.root, "for-each-ref",
                          "--format=%(refname) %(objectname)")
        self.report()
        self.assertEqual(self.git(self.root, "for-each-ref",
                                  "--format=%(refname) %(objectname)"), before)

    def test_a_tree_that_is_not_a_repository_is_not_an_error(self) -> None:
        plain = Path(tempfile.mkdtemp(prefix="workspace-hygiene-plain-")).resolve()
        self.addCleanup(shutil.rmtree, plain, ignore_errors=True)
        result = WH.scan(plain)
        self.assertFalse(result["present"])
        self.assertEqual(result["merged_idle"], [])


class PrivacyTests(WorkspaceTree):
    def test_the_overlay_is_counted_and_never_named(self) -> None:
        overlay = self.root / "private"
        overlay.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(overlay)], check=True,
                       env=dict(os.environ))
        self._write(overlay / "item.md", "private\n")
        self.git(overlay, "add", "-A")
        self.git(overlay, "commit", "-q", "-m", "private base")
        self.git(overlay, "branch", "acme-corp-onsite-loop")

        report = self.report()
        self.assertIn(WH.PRIVATE_POLICY, report)
        self.assertIn("2 local branch(es)", report)
        self.assertNotIn("acme-corp", report,
                         "an overlay branch name is content, not a label")


class RegistrationTests(unittest.TestCase):
    """A routine nobody can invoke is a file, not a routine."""

    def test_the_front_end_lists_it_and_runs_it_dry(self) -> None:
        import gardener  # noqa: PLC0415  (front-end imported only for this assertion)
        self.assertIn("workspace-hygiene", gardener.ROUTINES)
        self.assertIn("workspace-hygiene", gardener.ALL_ORDER)
        _, supports_apply = gardener.ROUTINES["workspace-hygiene"]
        self.assertFalse(supports_apply, "report-only: --apply must be a no-op")
        self.assertEqual(gardener.ALL_ORDER[-1], "verify-links",
                         "verify-links stays last: its exit code is the --all gate")


if __name__ == "__main__":
    unittest.main()
