"""Behavioral tests for the public + optional-private Git inventory."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path


WORKSPACE_DIR = Path(__file__).resolve().parents[1]
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

import status  # noqa: E402


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            f"git {' '.join(args)} failed ({result.returncode}):\n{result.stderr}"
        )
    return result.stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.invalid")
    write(root / "tracked.txt", "base\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-q", "-m", "base commit")


def add_toolkit_markers(root: Path) -> None:
    write(root / "AGENTS.md", "fixture\n")
    write(root / "config.example.yaml", "fixture: true\n")
    write(root / "automation" / "shared" / "config.py", "# fixture\n")
    write(root / "skills" / "job-search" / "SKILL.md", "# fixture\n")


@contextmanager
def changed_cwd(path: Path):
    before = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


class WorkspaceStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "toolkit"
        init_repo(self.root)
        add_toolkit_markers(self.root)
        git(self.root, "add", "AGENTS.md", "config.example.yaml", "automation", "skills")
        git(self.root, "commit", "-q", "-m", "toolkit markers")

    def _make_branch_fixture(self) -> Path:
        main_oid = git(self.root, "rev-parse", "main")
        git(self.root, "update-ref", "refs/remotes/origin/main", main_oid)
        git(self.root, "config", "branch.main.remote", "origin")
        git(self.root, "config", "branch.main.merge", "refs/heads/main")
        git(self.root, "remote", "add", "origin", "https://token@example.invalid/repo.git")

        git(self.root, "branch", "old-local", main_oid)
        git(self.root, "switch", "-q", "-c", "feature")
        write(self.root / "feature.txt", "new branch\n")
        git(self.root, "add", "feature.txt")
        git(self.root, "commit", "-q", "-m", "unmerged feature")
        feature_oid = git(self.root, "rev-parse", "HEAD")
        git(self.root, "switch", "-q", "main")

        git(self.root, "update-ref", "refs/remotes/origin/remote-only", feature_oid)
        git(self.root, "update-ref", "refs/remotes/origin/old-remote", main_oid)
        git(self.root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

        git(self.root, "branch", "ahead-local", feature_oid)
        git(self.root, "update-ref", "refs/remotes/origin/ahead-local", main_oid)
        git(self.root, "config", "branch.ahead-local.remote", "origin")
        git(self.root, "config", "branch.ahead-local.merge", "refs/heads/ahead-local")

        git(self.root, "branch", "behind-local", main_oid)
        git(self.root, "update-ref", "refs/remotes/origin/behind-local", feature_oid)
        git(self.root, "config", "branch.behind-local.remote", "origin")
        git(self.root, "config", "branch.behind-local.merge", "refs/heads/behind-local")

        git(self.root, "switch", "-q", "-c", "remote-source", "main")
        write(self.root / "remote.txt", "parallel remote commit\n")
        git(self.root, "add", "remote.txt")
        git(self.root, "commit", "-q", "-m", "parallel remote")
        remote_oid = git(self.root, "rev-parse", "HEAD")
        git(self.root, "switch", "-q", "main")
        git(self.root, "branch", "-D", "remote-source")
        git(self.root, "branch", "diverged-local", feature_oid)
        git(self.root, "update-ref", "refs/remotes/origin/diverged-local", remote_oid)
        git(self.root, "config", "branch.diverged-local.remote", "origin")
        git(self.root, "config", "branch.diverged-local.merge", "refs/heads/diverged-local")

        git(self.root, "branch", "missing-upstream", main_oid)
        git(self.root, "config", "branch.missing-upstream.remote", "origin")
        git(self.root, "config", "branch.missing-upstream.merge", "refs/heads/missing-upstream")

        linked = Path(self.temp.name) / "detached worktree"
        git(self.root, "worktree", "add", "-q", "--detach", str(linked), "main")

        write(self.root / "tracked.txt", "staged\n")
        git(self.root, "add", "tracked.txt")
        write(self.root / "tracked.txt", "staged then modified\n")
        write(self.root / "untracked file.txt", "untracked\n")
        return linked

    def test_full_inventory_shows_every_worktree_and_branch_with_truthful_state(self) -> None:
        linked = self._make_branch_fixture()
        repo = status.inspect_repository("PUBLIC", self.root)
        output = status.render([repo], self.root, verbose=False, palette=status.Palette(False))

        self.assertIn("2 worktrees · 1 dirty", output)
        self.assertIn("main", output)
        self.assertIn("L+R", output)
        self.assertIn("synced", output)
        self.assertIn("old-local", output)
        self.assertIn("local only", output)
        self.assertIn("merged", output)
        self.assertIn("feature", output)
        self.assertIn("unmerged", output)
        self.assertIn("origin/remote-only", output)
        self.assertIn("origin/old-remote", output)
        self.assertIn("cached only", output)
        self.assertIn("ahead 1", output)
        self.assertIn("behind 1", output)
        self.assertIn("diverged +1/-1", output)
        self.assertIn("upstream missing", output)
        self.assertNotIn("origin/HEAD", output)
        self.assertIn("(detached @", output)
        self.assertIn(str(linked), output)
        self.assertIn("dirty 2 · S1 · M1 · ?1", output)
        self.assertNotIn("untracked file.txt", output)
        self.assertNotIn("token@", output)

    def test_default_summary_is_one_action_line_without_cached_remote_noise(self) -> None:
        self._make_branch_fixture()
        repo = status.inspect_repository("PUBLIC", self.root)
        output = status.render_summary([repo], status.Palette(False))

        self.assertEqual(len(output.splitlines()), 1)
        self.assertTrue(output.startswith("ACTION: public main synced"), output)
        self.assertIn("1 of 2 worktrees dirty", output)
        self.assertIn("6 local work branches", output)
        self.assertNotIn("cached remote", output)
        self.assertNotIn("origin/remote-only", output)
        self.assertNotIn("Legend", output)

    def test_default_summary_is_ok_when_only_synced_main_is_clean(self) -> None:
        main_oid = git(self.root, "rev-parse", "main")
        git(self.root, "update-ref", "refs/remotes/origin/main", main_oid)
        git(self.root, "config", "branch.main.remote", "origin")
        git(self.root, "config", "branch.main.merge", "refs/heads/main")
        git(self.root, "remote", "add", "origin", "https://example.invalid/repo.git")
        write(self.root / ".git" / "FETCH_HEAD", "")

        repo = status.inspect_repository("PUBLIC", self.root)
        output = status.render_summary([repo], status.Palette(False))

        self.assertEqual(
            output,
            "OK: public main synced · 1 worktree clean · 0 local work branches",
        )

    def test_verbose_view_adds_files_commits_remotes_and_redacts_credentials(self) -> None:
        self._make_branch_fixture()
        repo = status.inspect_repository("PUBLIC", self.root)
        output = status.render([repo], self.root, verbose=True, palette=status.Palette(False))

        self.assertIn("MM  tracked.txt", output)
        self.assertIn("??  untracked file.txt", output)
        self.assertIn("toolkit markers", output)
        self.assertIn("unmerged feature", output)
        self.assertIn("REMOTES", output)
        self.assertIn("https://***@example.invalid/repo.git", output)
        self.assertNotIn("https://token@", output)
        self.assertIn("checked out at", output)

    def test_optional_private_repository_is_included_only_when_it_is_git(self) -> None:
        private = self.root / "private"
        private.mkdir()
        self.assertEqual(status.discover_repositories(self.root), [("PUBLIC", self.root.resolve())])

        init_repo(private)
        self.assertEqual(
            status.discover_repositories(self.root),
            [("PUBLIC", self.root.resolve()), ("PRIVATE", private.resolve())],
        )

    def test_queries_do_not_depend_on_the_callers_current_directory(self) -> None:
        away = Path(self.temp.name) / "away"
        away.mkdir()
        with changed_cwd(away):
            repo = status.inspect_repository("PUBLIC", self.root)
        self.assertEqual(repo.root, self.root.resolve())
        self.assertEqual(repo.worktrees[0].branch, "main")

    def test_toolkit_guard_refuses_an_unrelated_repository(self) -> None:
        unrelated = Path(self.temp.name) / "unrelated"
        init_repo(unrelated)
        with self.assertRaisesRegex(status.GitError, "refusing to run"):
            status.validate_toolkit_root(unrelated)

        add_toolkit_markers(unrelated)
        status.validate_toolkit_root(unrelated)

    def test_renames_are_one_changed_path_and_verbose_shows_both_names(self) -> None:
        git(self.root, "mv", "tracked.txt", "renamed.txt")
        repo = status.inspect_repository("PUBLIC", self.root)
        self.assertEqual(len(repo.worktrees[0].changes), 1)
        output = status.render([repo], self.root, verbose=True, palette=status.Palette(False))
        self.assertIn("tracked.txt → renamed.txt", output)


if __name__ == "__main__":
    unittest.main()
