"""The cleanup planner: what it proposes, what it refuses, what it never runs.

Two properties must never regress, and both are asserted against a real
repository rather than described:

* **the planner destroys nothing.** A dry run leaves every ref, every object and
  every branch byte-identical; ``--execute`` only ADDS refs and prunes worktree
  metadata whose directory is already gone. The emitted script contains no
  ``rm``, no ``git clean``, no ``git worktree remove`` and no ``branch -D``.
* **it never proposes a branch holding unique work.** The merge-shape matrix
  from ``_fixtures`` is fed straight through the planner, and every branch in
  ``UNIQUE_WORK`` must come out kept, with the reason printed.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/workspace/tests
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_WORKSPACE_DIR = _TESTS_DIR.parent
for _path in (str(_TESTS_DIR), str(_WORKSPACE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _fixtures as F  # noqa: E402
import cleanup  # noqa: E402


class PlannerTestCase(F.GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.scratch / "toolkit"
        self.facts = F.build_merge_shapes(self, self.root)

    def run_planner(self, *argv: str) -> tuple[int, str]:
        buffer = io.StringIO()
        code = cleanup.main(["--repo-root", str(self.root), *argv], out=buffer)
        return code, buffer.getvalue()

    def latest(self, suffix: str) -> Path:
        produced = sorted((self.root / "local" / "workspace").glob(f"cleanup-*{suffix}"))
        self.assertTrue(produced, f"no cleanup-*{suffix} was written")
        return produced[-1]

    def plan_json(self) -> dict:
        return json.loads(self.latest(".json").read_text(encoding="utf-8"))

    def refs(self) -> dict[str, str]:
        listing = self.out(self.root, "for-each-ref",
                           "--format=%(refname) %(objectname)")
        refs: dict[str, str] = {}
        for line in listing.splitlines():
            name, _, oid = line.partition(" ")
            if name:
                refs[name] = oid
        return refs

    def objects(self) -> set[str]:
        base = self.root / ".git" / "objects"
        return {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}


class DoesNotDestroyTests(PlannerTestCase):
    def test_a_dry_run_changes_no_ref_and_no_object(self) -> None:
        refs_before, objects_before = self.refs(), self.objects()
        code, report = self.run_planner()
        self.assertEqual(code, 1, "no --fetch means stale, which is exit 1")
        self.assertEqual(self.refs(), refs_before)
        self.assertEqual(self.objects(), objects_before)
        self.assertIn("STALE", report)

    def test_execute_only_adds_refs_and_never_deletes_a_branch(self) -> None:
        before = self.refs()
        code, _ = self.run_planner("--fetch", "--execute")
        self.assertIn(code, (0, 1))
        after = self.refs()
        for name, oid in before.items():
            with self.subTest(ref=name):
                self.assertIn(name, after, f"{name} disappeared")
                self.assertEqual(after[name], oid, f"{name} moved")
        added = set(after) - set(before)
        self.assertTrue(added, "--execute should have written backup refs")
        for name in added:
            self.assertTrue(name.startswith("refs/agent-trash/"),
                            f"--execute wrote an unexpected ref: {name}")

    def test_the_emitted_script_contains_no_destructive_verb(self) -> None:
        self.run_planner("--fetch")
        script = self.latest(".sh").read_text(encoding="utf-8")
        commands = [line for line in script.splitlines()
                    if line.strip() and not line.strip().startswith("#")]
        joined = "\n".join(commands)
        for forbidden in ("rm -", "rm ", "git clean", "worktree remove",
                          "branch -D", "--force", "reset --hard"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)
        self.assertIn("git branch -d ", joined)

    def test_no_force_flag_exists_anywhere_in_the_interface(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            cleanup.build_parser().parse_args(["--force"])
        self.assertEqual(raised.exception.code, 2)
        source = (_WORKSPACE_DIR / "cleanup.py").read_text(encoding="utf-8")
        self.assertNotIn('"--force"', source)
        self.assertNotIn('"-D"', source)


class ProposalTests(PlannerTestCase):
    def test_no_branch_holding_unique_work_is_ever_proposed(self) -> None:
        self.run_planner("--fetch")
        rows = {row["name"]: row for row in self.plan_json()["branches"]}
        for name in F.UNIQUE_WORK:
            with self.subTest(branch=name):
                self.assertIn(name, rows)
                self.assertFalse(rows[name]["proposed"],
                                 f"{name} holds unrecoverable work")
                self.assertTrue(rows[name]["keep_reasons"])

    def test_a_merged_pushed_branch_with_no_worktree_is_proposed(self) -> None:
        self.run_planner("--fetch")
        rows = {row["name"]: row for row in self.plan_json()["branches"]}
        self.assertTrue(rows["true-merge"]["proposed"], rows["true-merge"])
        self.assertEqual(rows["true-merge"]["unpushed_commits"], 0)

    def test_a_squash_merged_branch_is_merged_but_kept_for_its_commits(self) -> None:
        # Its CONTENT is in main — that is what the containment probe says — but
        # its commits exist on no remote, so deleting the branch would lose the
        # commits themselves. Kept, with the count printed.
        self.run_planner("--fetch")
        row = {r["name"]: r for r in self.plan_json()["branches"]}["squash-merge"]
        self.assertEqual(row["merged"], "merged")
        self.assertFalse(row["proposed"])
        self.assertGreater(row["unpushed_commits"], 0)
        self.assertTrue(any("no remote-tracking ref" in reason
                            for reason in row["keep_reasons"]))

    def test_a_branch_named_by_a_review_ledger_row_is_kept(self) -> None:
        ledger = self.root / cleanup.REVIEW_LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            "- commit: abcdef12\n"
            "  finding: 'reviewed on the true-merge branch'\n", encoding="utf-8")
        self.run_planner("--fetch")
        row = {r["name"]: r for r in self.plan_json()["branches"]}["true-merge"]
        self.assertFalse(row["proposed"])
        self.assertIn(cleanup.KEEP_LEDGER, row["keep_reasons"])

    def test_a_wedged_branch_is_kept_until_its_registration_is_pruned(self) -> None:
        self.run_planner("--fetch")
        rows = {r["name"]: r for r in self.plan_json()["branches"]}
        for name in ("prunable-work", "locked-gone-work"):
            with self.subTest(branch=name):
                self.assertFalse(rows[name]["proposed"])
                self.assertIn(cleanup.KEEP_WEDGED, rows[name]["keep_reasons"])

    def test_dirty_locked_and_harness_worktrees_are_never_retired(self) -> None:
        self.run_planner("--fetch")
        rows = {Path(row["path"]).name: row for row in self.plan_json()["worktrees"]}
        self.assertNotEqual(rows["dirty"]["action"], "retire")
        self.assertNotEqual(rows["locked-live"]["action"], "retire")
        self.assertNotEqual(rows["untracked"]["action"], "retire",
                            "untracked files have no git recovery story")
        self.assertEqual(rows["prunable"]["action"], "prune")

    def test_a_locked_registration_whose_directory_is_gone_is_explained(self) -> None:
        # `git worktree prune` declines a locked entry, and git suppresses its
        # `prunable` annotation, so it wedges its branch invisibly. The planner
        # must say so rather than claim it can clear it.
        self.run_planner("--fetch")
        row = {Path(r["path"]).name: r
               for r in self.plan_json()["worktrees"]}["locked-gone"]
        self.assertEqual(row["action"], "keep")
        self.assertTrue(row["gone"])
        self.assertIn(cleanup.KEEP_LOCKED_GONE, row["keep_reasons"])

    def test_a_harness_owned_worktree_is_reported_and_left_alone(self) -> None:
        harness = self.root / ".claude" / "worktrees" / "agent-1"
        harness.parent.mkdir(parents=True, exist_ok=True)
        self.git(self.root, "worktree", "add", "-q", "-b", "harness-work",
                 str(harness), "main")
        self.run_planner("--fetch")
        rows = {row["path"]: row for row in self.plan_json()["worktrees"]}
        row = [value for key, value in rows.items() if "agent-1" in key][0]
        self.assertEqual(row["action"], "keep")
        self.assertIn(cleanup.KEEP_HARNESS, row["keep_reasons"])


class ExecuteTests(PlannerTestCase):
    def test_the_backup_ref_survives_gc_prune_now(self) -> None:
        # The measured fact this exists for: after `branch -D` the reflog holds
        # NOTHING, and `gc --prune=now` erases the object immediately. A ref
        # makes the tip reachable, so it is no longer governed by the
        # unreachable grace period at all.
        code, _ = self.run_planner("--fetch", "--execute")
        self.assertIn(code, (0, 1))
        rows = [row for row in self.plan_json()["branches"] if row["proposed"]]
        self.assertTrue(rows, "fixture produced no proposals to back up")
        row = rows[0]
        self.assertTrue(row["backup_written"])

        self.git(self.root, "branch", "-D", row["name"])
        reflog = self.out(self.root, "reflog", "--all", check=False)
        self.assertNotIn(row["tip"][:8], reflog,
                         "fixture no longer reproduces the empty-reflog case")
        self.git(self.root, "gc", "--prune=now", "--quiet")

        survived = self.git(self.root, "cat-file", "-e", row["tip"], check=False)
        self.assertEqual(survived.returncode, 0,
                         "the backup ref did not keep the tip reachable")
        self.assertEqual(
            self.out(self.root, "rev-parse", "--verify",
                     row["backup_ref"] + "^{commit}"), row["tip"])

    def test_execute_prunes_a_gone_registration_and_unwedges_the_branch(self) -> None:
        refused = self.git(self.root, "switch", "prunable-work", check=False)
        self.assertNotEqual(refused.returncode, 0)

        self.run_planner("--fetch", "--execute")

        switched = self.git(self.root, "switch", "prunable-work", check=False)
        self.assertEqual(switched.returncode, 0, switched.stderr)
        self.git(self.root, "switch", "main")
        rows = {Path(row["path"]).name: row for row in self.plan_json()["worktrees"]}
        self.assertTrue(rows["prunable"]["pruned"])

    def test_the_archive_tag_is_opt_in_and_annotated(self) -> None:
        self.run_planner("--fetch", "--execute")
        self.assertEqual(self.out(self.root, "tag", "-l"), "")

        self.run_planner("--fetch", "--execute", "--archive-tag")
        tags = self.out(self.root, "tag", "-l").splitlines()
        self.assertTrue(tags, "--archive-tag wrote no tag")
        for tag in tags:
            with self.subTest(tag=tag):
                self.assertTrue(tag.startswith("archive/"))
                self.assertEqual(self.out(self.root, "cat-file", "-t", tag), "tag")

    def _fingerprint(self) -> str:
        plan = self.plan_json()
        return json.dumps({
            "branches": [(row["name"], row["proposed"], row["keep_reasons"])
                         for row in plan["branches"]],
            "worktrees": [(Path(row["path"]).name, row["action"])
                          for row in plan["worktrees"]],
        }, sort_keys=True)

    def test_two_dry_runs_produce_an_identical_plan(self) -> None:
        self.run_planner("--fetch")
        first = self._fingerprint()
        self.run_planner("--fetch")
        self.assertEqual(first, self._fingerprint())

    def test_repeated_execute_runs_converge_instead_of_compounding(self) -> None:
        # The first --execute prunes the registration whose directory is gone,
        # which UN-WEDGES that branch — so run 2 legitimately sees a world run 1
        # changed. What must never happen is a plan that keeps drifting: runs 2
        # and 3 are identical, and no branch is ever removed by any of them.
        branches_before = set(self.refs())
        self.run_planner("--fetch", "--execute")
        self.run_planner("--fetch", "--execute")
        second = self._fingerprint()
        self.run_planner("--fetch", "--execute")
        self.assertEqual(second, self._fingerprint())
        self.assertTrue(branches_before <= set(self.refs()),
                        "a repeated run removed a ref")

    def test_a_stale_run_still_performs_only_safe_steps_and_stays_exit_1(self) -> None:
        code, report = self.run_planner("--execute")
        self.assertEqual(code, 1)
        self.assertIn("STALE", report)
        script = self.latest(".sh").read_text(encoding="utf-8")
        commands = [line for line in script.splitlines()
                    if line.strip() and not line.strip().startswith("#")]
        self.assertEqual([line for line in commands if line.startswith("git")], [],
                         "a stale plan must emit no runnable git command")


class RefusalTests(PlannerTestCase):
    def test_it_refuses_a_repository_that_is_not_this_toolkit(self) -> None:
        stranger = self.scratch / "stranger"
        stranger.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(stranger)], check=True)
        buffer = io.StringIO()
        code = cleanup.main(["--repo-root", str(stranger)], out=buffer)
        self.assertEqual(code, 3)
        self.assertIn(cleanup.CODE_TOOLKIT_GUARD, buffer.getvalue())

    def test_it_refuses_while_a_merge_is_in_progress(self) -> None:
        (self.root / ".git" / "MERGE_HEAD").write_text(
            self.out(self.root, "rev-parse", "HEAD") + "\n", encoding="utf-8")
        code, report = self.run_planner("--fetch")
        self.assertEqual(code, 3)
        self.assertIn(cleanup.CODE_OPERATION_IN_PROGRESS, report)

    def test_it_refuses_when_the_fetch_fails_rather_than_calling_it_stale(self) -> None:
        self.git(self.root, "remote", "set-url", "origin",
                 str(self.scratch / "does-not-exist.git"))
        code, report = self.run_planner("--fetch")
        self.assertEqual(code, 3)
        self.assertIn(cleanup.CODE_FETCH_FAILED, report)

    def test_a_fresh_run_with_nothing_needing_judgement_exits_zero(self) -> None:
        code, _ = self.run_planner("--fetch")
        self.assertEqual(code, 0)

    def test_the_process_boundary_reports_the_same_exit_code(self) -> None:
        # An exit code read any other way is not the exit code a caller sees.
        result = subprocess.run(
            [sys.executable, str(_WORKSPACE_DIR / "cleanup.py"),
             "--repo-root", str(self.root)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("STALE", result.stdout)


class PrivacyTests(PlannerTestCase):
    def test_the_private_overlay_is_counted_and_never_named(self) -> None:
        overlay = self.root / "private"
        overlay.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(overlay)], check=True)
        F.write(overlay / "secret.md", "a private item\n")
        self.git(overlay, "add", "-A")
        self.git(overlay, "commit", "-q", "-m", "private base")
        self.git(overlay, "branch", "acme-corp-onsite-loop-scheduling")

        code, report = self.run_planner("--fetch")
        self.assertIn(code, (0, 1))
        self.assertIn("PRIVATE OVERLAY", report)
        self.assertIn("counts only", report)
        self.assertNotIn("acme-corp", report)
        payload = json.dumps(self.plan_json())
        self.assertNotIn("acme-corp", payload)
        self.assertEqual(self.plan_json()["private_overlay"]["branches"], 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
