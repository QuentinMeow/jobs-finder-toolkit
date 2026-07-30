"""Tests for the verify-links gardener routine.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/gardener/tests \
        -t automation/gardener/tests

Every test builds a throwaway repo tree and points ``_common.REPO_ROOT`` at it, so
nothing here reads the real repo (or the private overlay).

Two regressions are pinned:
  * the routine used to read 23 files (AGENTS.md + ``skills/*/{SKILL,LESSONS,
    reference,AGENTS}.md``) out of ~155 tracked docs, so a stale path anywhere in
    ``docs/handbook/``, ``memory/``, ``README.md`` … was invisible;
  * ``check_symlinks()`` used to report "all resolve" when it found NO link root
    to walk — a fail-open that a restructure would trip silently.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import _common as C  # noqa: E402
import verify_links as V  # noqa: E402

BROKEN_REF = "skills/no-such-skill/SKILL.md"


def _legacy_instruction_files() -> list[Path]:
    """The pre-widening source set, kept verbatim to prove what it missed."""
    files = [C.REPO_ROOT / "AGENTS.md"]
    skills = C.REPO_ROOT / "skills"
    for name in ("SKILL.md", "LESSONS.md", "reference.md", "AGENTS.md"):
        files.extend(sorted(skills.glob(f"*/{name}")))
    return [f for f in files if f.is_file()]


class VerifyLinksTestCase(unittest.TestCase):
    """Base: a temp tree standing in for the repo root."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="verify-links-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._saved_root = C.REPO_ROOT
        C.REPO_ROOT = self.root
        self.addCleanup(lambda: setattr(C, "REPO_ROOT", self._saved_root))
        # A skill so the tree looks real; AGENTS.md so the legacy set is non-empty.
        self.write("AGENTS.md", "# contract\n")
        self.write("skills/job-search/SKILL.md", "# job-search\n")

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def git_init(self) -> None:
        """Make the temp tree a git checkout so ``git ls-files`` drives the run."""
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
               "HOME": str(self.root), "PATH": "/usr/bin:/bin:/usr/local/bin"}
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True, env=env)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True, env=env)


class TestSourceSetWidening(VerifyLinksTestCase):
    """A broken ref in a NON-skill doc is a finding (it used to be invisible)."""

    def setUp(self) -> None:
        super().setUp()
        self.write("docs/handbook/architecture.md",
                   f"| `{BROKEN_REF}` | the renamed script |\n")
        self.write("memory/known-issues/stale.md", f"Repro via `{BROKEN_REF}`.\n")
        self.git_init()

    def test_handbook_and_memory_refs_are_now_checked(self) -> None:
        broken, advisory, _ = V.check_references()
        self.assertEqual(advisory, [])
        self.assertEqual(
            sorted((b["file"], b["ref"]) for b in broken),
            [("docs/handbook/architecture.md", BROKEN_REF),
             ("memory/known-issues/stale.md", BROKEN_REF)],
        )

    def test_legacy_source_set_saw_none_of_them(self) -> None:
        """The 'before' half of the proof: 23 files, so neither doc was opened."""
        original = V._instruction_files
        V._instruction_files = _legacy_instruction_files
        self.addCleanup(lambda: setattr(V, "_instruction_files", original))
        broken, _, _ = V.check_references()
        self.assertEqual(broken, [])

    def test_tracked_md_set_is_used_and_ignores_untracked(self) -> None:
        self.write("docs/handbook/scratch-untracked.md", f"`{BROKEN_REF}`\n")  # not added
        names = {p.relative_to(self.root).as_posix() for p in V._instruction_files()}
        self.assertIn("docs/handbook/architecture.md", names)
        self.assertIn("memory/known-issues/stale.md", names)
        self.assertNotIn("docs/handbook/scratch-untracked.md", names)


class TestPlanAndRecordSourcesAreAdvisory(VerifyLinksTestCase):
    """Plans and records name target/past paths on purpose — advisory, not broken."""

    def test_design_task_and_adr_refs_do_not_fail_the_gate(self) -> None:
        self.write("docs/designs/x/execution-plan.md", f"Create `{BROKEN_REF}`.\n")
        self.write("tasks/0_backlog/2026-01-01-x/task.md", f"Produce `{BROKEN_REF}`.\n")
        self.write("memory/decisions/x.md", f"`{BROKEN_REF}` was dissolved.\n")
        self.git_init()
        broken, advisory, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(len(advisory), 3)

    def test_handbook_is_not_treated_as_a_plan(self) -> None:
        self.write("docs/handbook/x.md", f"`{BROKEN_REF}`\n")
        self.git_init()
        broken, advisory, _ = V.check_references()
        self.assertEqual(len(broken), 1)
        self.assertEqual(advisory, [])


class TestAbsentStrictRoots(VerifyLinksTestCase):
    """A strict prefix is strict only in a tree that HAS that root.

    The published export ships no ``memory/``, ``tasks/``, ``message-queue/``,
    ``docs/roadmap/`` or ``history/`` while AGENTS.md and the handbook necessarily name
    them; making them strict everywhere would turn the PUBLISHED repo's gardener
    red — the same trap the reconciler's missing-root no-op exists to avoid.
    """

    def test_ref_into_a_root_this_tree_lacks_is_skipped(self) -> None:
        self.write("docs/handbook/x.md", "See `memory/decisions/whatever.md`.\n")
        self.git_init()
        broken, advisory, skipped = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(advisory, [])
        self.assertEqual(skipped["absent-root"], 1)

    def test_same_ref_is_enforced_once_the_root_exists(self) -> None:
        self.write("docs/handbook/x.md", "See `memory/decisions/whatever.md`.\n")
        self.write("memory/decisions/other.md", "# other\n")
        self.git_init()
        broken, _, skipped = V.check_references()
        self.assertEqual([b["ref"] for b in broken], ["memory/decisions/whatever.md"])
        self.assertEqual(skipped["absent-root"], 0)


class TestGitIgnoredRefs(VerifyLinksTestCase):
    """A git-ignored path exists only in some checkouts — never a claim."""

    def test_ignored_ref_is_skipped(self) -> None:
        self.write(".gitignore", "skills/coding-interview\n")
        self.write("docs/handbook/x.md", "The private `skills/coding-interview/SKILL.md`.\n")
        self.git_init()
        broken, _, skipped = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(skipped["git-ignored"], 1)

    def test_overlay_refs_are_not_swallowed_by_the_ignore_rule(self) -> None:
        """``private/**`` is git-ignored wholesale — the overlay branch owns it."""
        (self.root / "private/docs").mkdir(parents=True)
        self.write(".gitignore", "private/\n")
        self.write("docs/handbook/x.md", "See `private/docs/gone.md`.\n")
        self.git_init()
        broken, _, skipped = V.check_references()
        self.assertEqual([b["ref"] for b in broken], ["private/docs/gone.md"])
        self.assertEqual(skipped["git-ignored"], 0)


class TestNoGitFallback(VerifyLinksTestCase):
    """Not a git checkout (exported tarball): walk, minus ignored/data trees."""

    def test_walk_skips_private_and_tmp(self) -> None:
        self.write("docs/handbook/x.md", "ok\n")
        self.write("private/secret.md", "ok\n")
        self.write("local/scratch/x.md", "ok\n")
        names = {p.relative_to(self.root).as_posix() for p in V._instruction_files()}
        self.assertIn("docs/handbook/x.md", names)
        self.assertNotIn("private/secret.md", names)
        self.assertNotIn("local/scratch/x.md", names)


class TestSymlinkRootsFailClosed(VerifyLinksTestCase):
    """check_symlinks() must not report success after verifying nothing."""

    def test_zero_link_roots_is_a_finding(self) -> None:
        self.assertFalse((self.root / ".claude/skills").exists())
        self.assertFalse((self.root / ".cursor/skills").exists())
        bad = V.check_symlinks()
        self.assertEqual(len(bad), 1)
        self.assertIn("NO skill link root", bad[0]["target"])

    def test_present_root_with_resolving_link_passes(self) -> None:
        skdir = self.root / ".claude/skills"
        skdir.mkdir(parents=True)
        (skdir / "job-search").symlink_to(self.root / "skills/job-search")
        self.assertEqual(V.check_symlinks(), [])

    def test_dangling_link_is_a_finding(self) -> None:
        skdir = self.root / ".cursor/skills"
        skdir.mkdir(parents=True)
        (skdir / "gone").symlink_to(self.root / "skills/gone")
        bad = V.check_symlinks()
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["link"], ".cursor/skills/gone")

    def test_empty_link_root_is_a_finding(self) -> None:
        """A root that exists but holds no symlinks also verified nothing."""
        (self.root / ".claude/skills").mkdir(parents=True)
        bad = V.check_symlinks()
        self.assertEqual([b["link"] for b in bad], [".claude/skills"])
        self.assertIn("no skill symlinks", bad[0]["target"])

    def test_tracked_root_missing_from_the_worktree_is_a_finding(self) -> None:
        skdir = self.root / ".claude/skills"
        skdir.mkdir(parents=True)
        (skdir / "job-search").symlink_to(self.root / "skills/job-search")
        self.git_init()
        shutil.rmtree(self.root / ".claude")
        bad = V.check_symlinks()
        links = [b["link"] for b in bad]
        self.assertIn(".claude/skills", links)
        self.assertIn("TRACKED in git", bad[0]["target"])


class TestReferencesPrivateIsOptional(VerifyLinksTestCase):
    """``references_private/`` is overlay-only and per-user — never a claim.

    Docs still name the pattern with a ``skills/<skill>/references_private/``
    shape even though the folder itself now lives at
    ``config.skill_references_dir("<skill>")``; either spelling must stay
    unresolvable-but-not-broken.
    """

    def test_not_checkable(self) -> None:
        self.assertFalse(V._is_checkable("skills/resume-writer/references_private/"))
        self.assertTrue(V._is_checkable("skills/resume-writer/reference.md"))


if __name__ == "__main__":
    unittest.main()
