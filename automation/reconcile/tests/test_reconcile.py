"""Tests for the reconciler's root handling and retry filing.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/reconcile/tests -t automation/reconcile/tests

Two behaviours are pinned here, and they pull in opposite directions on purpose:

  * the missing-root NO-OP is DOCUMENTED, not a defect — the published tree ships
    none of message-queue/, tasks/, memory/, docs/roadmap/, history/, so plain
    ``--check`` must stay green without them. ``--require-roots`` is the opt-in
    maintainer assertion that fails on exactly the same tree;
  * ``file_retries()`` must not create ``message-queue/needs-agent/retries/``
    when there is nothing to file — a repo that deleted that queue used to get it
    silently re-created on every clean run.

Every test runs against a throwaway tree, never the real repo.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RECONCILE_DIR = Path(__file__).resolve().parents[1]
if str(RECONCILE_DIR) not in sys.path:
    sys.path.insert(0, str(RECONCILE_DIR))

import reconcile as R  # noqa: E402


class TempRepo(unittest.TestCase):
    """A temp tree standing in for REPO_ROOT."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="reconcile-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._saved = (R.REPO_ROOT, R.RETRIES_DIR)
        R.REPO_ROOT = self.root
        R.RETRIES_DIR = self.root / "message-queue/needs-agent/retries"
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        R.REPO_ROOT, R.RETRIES_DIR = self._saved

    def make_roots(self, *, skip: tuple[str, ...] = ()) -> None:
        for root in sorted(set(R.CHECK_ROOTS.values())):
            if root in skip:
                continue
            (self.root / root).mkdir(parents=True, exist_ok=True)


class TestRequireRoots(TempRepo):

    def test_all_roots_present_is_clean(self) -> None:
        self.make_roots()
        self.assertEqual(R.check_required_roots(), [])

    def test_missing_root_is_a_finding(self) -> None:
        self.make_roots(skip=("tasks",))
        findings = R.check_required_roots()
        self.assertEqual([f.subject for f in findings], ["tasks"])
        self.assertIn("task-structure", findings[0].message)

    def test_every_root_is_asserted(self) -> None:
        # No roots at all: one finding per distinct guarded root, deduped.
        self.assertEqual(
            [f.subject for f in R.check_required_roots()],
            sorted(set(R.CHECK_ROOTS.values())),
        )

    def test_plain_check_still_passes_on_the_same_tree(self) -> None:
        """The published-export shape: skills/ but no process roots → --check green.

        ``skill-manifests`` is dropped for this run only: it imports
        ``sync_skill_manifests`` out of ``REPO_ROOT/automation/publish``, which a
        bare temp tree has no copy of. It is covered by automation/publish/tests.
        """
        self.make_roots(skip=("message-queue", "tasks", "memory",
                              "docs/roadmap", "history/conversations"))
        saved = R.CHECKS
        R.CHECKS = {k: v for k, v in saved.items() if k != "skill-manifests"}
        self.addCleanup(lambda: setattr(R, "CHECKS", saved))
        plain = R.main(["--check"])
        strict = R.main(["--check", "--require-roots"])
        self.assertEqual(plain, 0, "plain --check must tolerate absent process roots")
        self.assertEqual(strict, 1, "--require-roots must fail on the same tree")

    def test_check_roots_cover_every_check(self) -> None:
        """A new check without a declared root would silently escape the flag."""
        self.assertEqual(set(R.CHECK_ROOTS), set(R.CHECKS))


class TestFileRetries(TempRepo):

    def test_zero_findings_does_not_create_the_queue(self) -> None:
        R.file_retries([], "2026-07-29")
        self.assertFalse(R.RETRIES_DIR.exists())
        self.assertFalse((self.root / "message-queue").exists())

    def test_zero_findings_still_gcs_an_existing_queue(self) -> None:
        R.RETRIES_DIR.mkdir(parents=True)
        stale = R.RETRIES_DIR / "queue-schema--gone.md"
        stale.write_text(f"- **Filed**: 2026-01-01, {R.RECONCILER_SIGNATURE}\n",
                         encoding="utf-8")
        R.file_retries([], "2026-07-29")
        self.assertTrue(R.RETRIES_DIR.is_dir())
        self.assertFalse(stale.exists())

    def test_findings_create_the_queue_and_the_item(self) -> None:
        f = R.Finding("roadmap-fresh", "docs/roadmap/current-state.md", "missing")
        R.file_retries([f], "2026-07-29")
        item = R.RETRIES_DIR / R._retry_name(f)
        self.assertTrue(item.is_file())
        self.assertIn("**Check**: roadmap-fresh", item.read_text(encoding="utf-8"))

    def test_hand_written_items_survive_the_gc(self) -> None:
        R.RETRIES_DIR.mkdir(parents=True)
        mine = R.RETRIES_DIR / "human-filed.md"
        mine.write_text("- **Filed**: 2026-07-01, by a human\n", encoding="utf-8")
        R.file_retries([], "2026-07-29")
        self.assertTrue(mine.is_file())


if __name__ == "__main__":
    unittest.main()
