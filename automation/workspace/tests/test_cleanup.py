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
import os
import shlex
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


# ── the main working tree, from every vantage point ──────────────────────────
#
# THE INCIDENT THESE PIN. The planner's only guard against retiring the
# repository root compared each worktree against the planner's OWN root. Run
# from a linked worktree — which is how every agent here runs everything — that
# root IS the linked worktree, so the main working tree compared unequal, passed
# every "safe to retire" precondition, and the emitted script began:
#
#     mkdir -p local/workspace/trash-<id>
#     mv /path/to/repo local/workspace/trash-<id>/repo
#
# moving the directory that physically contains `.git` INTO a trash directory
# nested inside one of its own linked worktrees. It only appeared WITH --fetch,
# because only a fetched base makes the root's topic branch look merged.
#
# The shared merge-shape fixture could not have caught it: there the main
# working tree stays on `main`, where the base-branch rule keeps its BRANCH for
# an unrelated reason, and no worktree in it is retirable at all — so the retire
# path had no test passing through it. These scenarios put the main working tree
# on a merged topic branch with a clean tree, and assert on the SCRIPT TEXT,
# because the script is the artefact that would have run.


class MainWorktreeScenario(F.GitTestCase):
    """A toolkit repo, a real origin, and two linked worktrees to run from."""

    def build_scenario(self, *, root_on: str) -> None:
        root = self.scratch / "toolkit"
        root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)],
                       check=True, env=dict(os.environ))
        F.add_toolkit_markers(root)
        # `local/` holds the planner's own script, plan and trash directory. The
        # real repository ignores it; a fixture that did not would report the
        # main working tree DIRTY from the second run onward and keep it for the
        # wrong reason, hiding the very bug these tests exist to pin.
        F.write(root / ".gitignore", "local/\n")
        F.write(root / "seed.txt", "seed\n")
        self.commit(root, "base commit")
        F.add_origin(self, root)

        # A topic branch that really landed: pushed, merged into main, main
        # pushed. Every containment and every push precondition passes for it.
        self.git(root, "switch", "-q", "-c", "codex/landed", "main")
        F.write(root / "landed.txt", "work that landed\n")
        self.commit(root, "codex/landed: the work")
        self.git(root, "push", "-q", "origin", "codex/landed")
        self.git(root, "switch", "-q", "main")
        self.git(root, "merge", "-q", "--no-ff", "codex/landed",
                 "-m", "Merge codex/landed")
        self.git(root, "push", "-q", "origin", "main")
        self.git(root, "fetch", "-q", "--prune", "origin")

        linked = self.scratch / "linked"
        # The vantage point: a linked worktree the planner is RUN FROM. This is
        # the configuration that produced the incident, and it is the one a
        # comparison against the planner's own root cannot survive.
        self.vantage = linked / "vantage"
        self.git(root, "worktree", "add", "-q", "-b", "vantage-work",
                 str(self.vantage), "main")
        # A linked worktree that genuinely IS retirable: merged, clean,
        # unlocked, not under `.claude/worktrees`. The guard must keep proposing
        # it — a fix that turns this tool into a no-op is not a fix.
        self.retirable = linked / "retirable"
        self.git(root, "worktree", "add", "-q", "-b", "linked-landed",
                 str(self.retirable), "main")

        self.git(root, "switch", "-q", root_on)
        self.assertEqual(
            self.out(root, "status", "--porcelain"), "",
            "the main working tree must be CLEAN here, or this fixture tests "
            "the dirty-tree rule instead of the guard")
        self.root = root

    # ── reading the artefact the owner would actually run ────────────────────

    def emitted_moves(self, script: str) -> list[tuple[Path, Path]]:
        """Every ``mv SRC DST`` a shell would RUN, unquoted.

        Parsed, not pattern-matched: what matters is what the shell does with
        this file, and a `mv` inside a `#` comment or behind the `# STALE:`
        prefix is not a move.
        """
        moves: list[tuple[Path, Path]] = []
        for line in script.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = shlex.split(stripped)
            if parts and parts[0] == "mv":
                self.assertEqual(len(parts), 3, f"unexpected mv shape: {line}")
                moves.append((Path(parts[1]), Path(parts[2])))
        return moves

    def assert_script_is_safe(self, script: str) -> None:
        """The two invariants every emitted script must satisfy, always."""
        for source, destination in self.emitted_moves(script):
            with self.subTest(mv=(str(source), str(destination))):
                self.assertFalse(
                    cleanup.move_is_self_nesting(source, destination),
                    "an emitted mv would move a directory into itself")
                self.assertIsNot(
                    cleanup.is_main_worktree(source), True,
                    "an emitted mv targets the MAIN working tree")

    def assert_root_is_never_moved(self, script: str) -> None:
        self.assertNotIn(f"mv {shlex.quote(str(self.root))} ", script)
        moved = [source.resolve() for source, _ in self.emitted_moves(script)]
        self.assertNotIn(self.root.resolve(), moved,
                         "the emitted script moves the repository root")

    def plan_from(self, vantage: Path, *argv: str) -> tuple[int, dict, str]:
        buffer = io.StringIO()
        code = cleanup.main(
            ["--repo-root", str(vantage), "--fetch", *argv], out=buffer)
        produced = sorted(
            (vantage / "local" / "workspace").glob("cleanup-*.json"))
        self.assertTrue(produced, f"no plan was written under {vantage}")
        plan = json.loads(produced[-1].read_text(encoding="utf-8"))
        script = produced[-1].with_suffix(".sh").read_text(encoding="utf-8")
        self.assert_script_is_safe(script)
        return code, plan, script

    def worktree_row(self, plan: dict, path: Path) -> dict:
        target = Path(path).resolve()
        rows = [row for row in plan["worktrees"]
                if Path(row["path"]).resolve() == target]
        self.assertEqual(len(rows), 1, f"{path} is not in the plan")
        return rows[0]


class MainWorktreeIsNeverProposedTests(MainWorktreeScenario):
    def test_on_a_merged_topic_branch_with_a_clean_tree_it_is_kept(self) -> None:
        self.build_scenario(root_on="codex/landed")
        _, plan, script = self.plan_from(self.root)
        row = self.worktree_row(plan, self.root)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertIn(cleanup.KEEP_MAIN, row["keep_reasons"])
        self.assert_root_is_never_moved(script)

    def test_the_same_holds_from_a_LINKED_worktree(self) -> None:
        # The exact configuration that produced the incident: the planner's own
        # root is a linked worktree, so "is this my root" answers NO for the
        # main working tree. Only a guard that asks git which directory owns the
        # repository can keep it here.
        self.build_scenario(root_on="codex/landed")
        _, plan, script = self.plan_from(self.vantage)
        row = self.worktree_row(plan, self.root)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertIn(cleanup.KEEP_MAIN, row["keep_reasons"])
        self.assertNotIn(cleanup.KEEP_RUNNING_HERE, row["keep_reasons"],
                         "nothing but the main-working-tree guard may be "
                         "holding it here — that is the point of this test")
        self.assert_root_is_never_moved(script)
        self.assertNotIn(str(self.root) + "\n", script,
                         "the repository root should not appear in this script "
                         "at all: the planner is not running from it")

    def test_on_the_base_branch_itself_it_is_kept_from_either_vantage(self) -> None:
        self.build_scenario(root_on="main")
        for label, vantage in (("main working tree", self.root),
                               ("linked worktree", self.vantage)):
            with self.subTest(run_from=label):
                _, plan, script = self.plan_from(vantage)
                row = self.worktree_row(plan, self.root)
                self.assertEqual(row["action"], "keep", row["keep_reasons"])
                self.assertIn(cleanup.KEEP_MAIN, row["keep_reasons"])
                self.assert_root_is_never_moved(script)

    def test_the_worktree_the_planner_runs_from_is_kept_and_says_so(self) -> None:
        # Argued in cleanup.py: this one is retirable in principle, but the
        # planner's own script, plan and trash directory live inside it, so a
        # run started HERE will not propose it. Re-run from elsewhere and it is
        # proposable again — which the next test relies on.
        self.build_scenario(root_on="codex/landed")
        _, plan, _ = self.plan_from(self.vantage)
        row = self.worktree_row(plan, self.vantage)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertIn(cleanup.KEEP_RUNNING_HERE, row["keep_reasons"])


class StillProposesWhatItShouldTests(MainWorktreeScenario):
    def test_a_genuinely_retirable_linked_worktree_is_still_proposed(self) -> None:
        # The over-correction guard. A fix that keeps the main working tree by
        # keeping EVERYTHING has removed the tool instead of the bug.
        self.build_scenario(root_on="codex/landed")
        for label, vantage in (("main working tree", self.root),
                               ("linked worktree", self.vantage)):
            with self.subTest(run_from=label):
                _, plan, script = self.plan_from(vantage)
                row = self.worktree_row(plan, self.retirable)
                self.assertEqual(row["action"], "retire", row["keep_reasons"])
                self.assertEqual(row["keep_reasons"], [])
                moved = [source.resolve()
                         for source, _ in self.emitted_moves(script)]
                self.assertIn(self.retirable.resolve(), moved,
                              "the retirable worktree was classified but the "
                              "script did not emit its move")

    def test_the_move_it_emits_lands_beside_the_trash_root_not_inside_it(self) -> None:
        self.build_scenario(root_on="codex/landed")
        _, plan, script = self.plan_from(self.root)
        moves = {source.resolve(): destination
                 for source, destination in self.emitted_moves(script)}
        destination = moves[self.retirable.resolve()]
        self.assertTrue(destination.is_absolute(),
                        "an emitted destination must not depend on an earlier "
                        f"`cd` to mean what it says: {destination}")
        self.assertEqual(destination.name, self.retirable.name)
        self.assertIn(f"trash-{plan['run_id']}", str(destination))


class SelfNestingMoveTests(MainWorktreeScenario):
    def build_nested(self) -> None:
        """An OUTER worktree with another worktree inside its ignored `local/`.

        Run the planner from the inner one and every trash directory it can
        offer is inside the outer one, so retiring the outer would emit
        ``mv OUTER OUTER/local/workspace/trash-<id>/outer``. This is the
        incident's shape with the main working tree taken out of it, so the
        containment guard has to stand on its own here.
        """
        self.build_scenario(root_on="codex/landed")
        self.outer = self.scratch / "linked" / "outer"
        self.git(self.root, "worktree", "add", "-q", "-b", "outer-work",
                 str(self.outer), "main")
        self.inner = self.outer / "local" / "nested"
        self.git(self.root, "worktree", "add", "-q", "-b", "inner-work",
                 str(self.inner), "main")
        self.assertEqual(
            self.out(self.outer, "status", "--porcelain"), "",
            "the nested worktree must be IGNORED, or `outer` is merely dirty "
            "and this scenario proves nothing about containment")

    def test_no_emitted_move_can_land_inside_the_directory_it_moves(self) -> None:
        self.build_nested()
        _, plan, script = self.plan_from(self.inner)
        row = self.worktree_row(plan, self.outer)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertIn(cleanup.KEEP_SELF_NESTING, row["keep_reasons"])
        self.assertIn(cleanup.KEEP_CONTAINS_WORKTREE, row["keep_reasons"])
        moved = [source.resolve() for source, _ in self.emitted_moves(script)]
        self.assertNotIn(self.outer.resolve(), moved)
        # assert_script_is_safe already re-checked every emitted move; this is
        # the constructive half — the dangerous one was never written.

    def test_a_worktree_holding_another_worktree_is_never_moved(self) -> None:
        self.build_nested()
        # Run from the MAIN working tree, where the trash directory is nowhere
        # near `outer`, so self-nesting cannot be what keeps it. Carrying a live
        # nested worktree along with the move is reason enough on its own.
        _, plan, script = self.plan_from(self.root)
        row = self.worktree_row(plan, self.outer)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertIn(cleanup.KEEP_CONTAINS_WORKTREE, row["keep_reasons"])
        self.assertNotIn(cleanup.KEEP_SELF_NESTING, row["keep_reasons"])
        moved = [source.resolve() for source, _ in self.emitted_moves(script)]
        self.assertNotIn(self.outer.resolve(), moved)


class EmitterRefusesByConstructionTests(MainWorktreeScenario):
    """``build_script`` is the only place a destructive line is written.

    So these bypass the classifier entirely and hand the emitter a plan that
    says "retire the main working tree" — the state a classifier regression
    would produce. Nothing about the classifier is on trial here; the question
    is whether the emitter can be talked into writing the line.
    """

    def hand_made(self, path: Path) -> cleanup.WorktreeItem:
        return cleanup.WorktreeItem(path=str(path), branch="refs/heads/main",
                                    action="retire")

    def script_for(self, vantage: Path, *items: cleanup.WorktreeItem) -> str:
        return cleanup.build_script(
            run_id="TESTRUN", root=vantage, base_ref="refs/remotes/origin/main",
            stale=False, branches=[], worktrees=list(items))

    def test_it_will_not_write_a_move_of_the_main_working_tree(self) -> None:
        self.build_scenario(root_on="codex/landed")
        for label, vantage in (("main working tree", self.root),
                               ("linked worktree", self.vantage)):
            with self.subTest(run_from=label):
                script = self.script_for(vantage, self.hand_made(self.root))
                self.assert_script_is_safe(script)
                self.assert_root_is_never_moved(script)
                self.assertEqual(self.emitted_moves(script), [])
                self.assertIn("REFUSED", script,
                              "a refusal must be visible, never silent")

    def test_a_refused_move_is_reflected_in_the_plan_not_only_the_script(self) -> None:
        self.build_scenario(root_on="codex/landed")
        items = [self.hand_made(self.root)]
        cleanup.apply_emitter_refusals(self.vantage, "TESTRUN", items)
        self.assertEqual(items[0].action, "keep")
        self.assertTrue(items[0].keep_reasons)

    def test_a_path_with_a_newline_cannot_break_out_of_its_comment(self) -> None:
        # `git worktree list --porcelain -z` carries a newline inside a path
        # faithfully. `shlex.quote` protects the `mv`; it does NOT protect the
        # `# worktree <path>` comment above it, whose tail would be left
        # standing as a command.
        self.build_scenario(root_on="codex/landed")
        hostile = self.hand_made(Path(f"{self.scratch}/evil\nrm -rf /"))
        script = self.script_for(self.vantage, hostile)
        commands = [line for line in script.splitlines()
                    if line.strip() and not line.strip().startswith("#")]
        self.assertNotIn("rm -rf /", commands)
        self.assertEqual(self.emitted_moves(script), [])

    def test_a_multi_line_branch_intent_cannot_break_out_of_its_comment(self) -> None:
        # A branch description is MULTI-LINE by design (`git branch
        # --edit-description`), and its first line becomes the `#   <intent>`
        # comment above the branch's commands. It is single-line by the time it
        # reaches the emitter today — but that promise is made in another
        # module, and this is the emitter's own guarantee.
        self.build_scenario(root_on="codex/landed")
        branch = cleanup.BranchItem(
            name="linked-landed", ref="refs/heads/linked-landed", tip="0" * 40,
            state="merged", merged="merged", intent="tidy up\nrm -rf /",
            age_seconds=0)
        script = cleanup.build_script(
            run_id="TESTRUN", root=self.root, base_ref="refs/remotes/origin/main",
            stale=False, branches=[branch], worktrees=[])
        commands = [line for line in script.splitlines()
                    if line.strip() and not line.strip().startswith("#")]
        self.assertNotIn("rm -rf /", commands)

    def test_two_worktrees_sharing_a_basename_get_different_destinations(self) -> None:
        # `mv a b` where `b` is an EXISTING DIRECTORY moves `a` INSIDE it, so a
        # shared basename would nest the second worktree inside the first and
        # the trash directory itself would be what swallowed it.
        self.build_scenario(root_on="codex/landed")
        first = self.scratch / "linked" / "one" / "agent-1"
        second = self.scratch / "linked" / "two" / "agent-1"
        self.git(self.root, "worktree", "add", "-q", "-b", "one-work",
                 str(first), "main")
        self.git(self.root, "worktree", "add", "-q", "-b", "two-work",
                 str(second), "main")
        _, _, script = self.plan_from(self.root)
        destinations = [destination for _, destination in self.emitted_moves(script)]
        moved = {source.resolve() for source, _ in self.emitted_moves(script)}
        self.assertLessEqual({first.resolve(), second.resolve()}, moved)
        self.assertEqual(len(destinations), len(set(destinations)),
                         f"two moves share a destination: {destinations}")


class MainWorktreePrimitiveTests(MainWorktreeScenario):
    def test_git_dir_equals_git_common_dir_only_in_the_main_working_tree(self) -> None:
        self.build_scenario(root_on="codex/landed")
        self.assertIs(cleanup.is_main_worktree(self.root), True)
        for linked in (self.vantage, self.retirable):
            with self.subTest(worktree=linked.name):
                self.assertIs(cleanup.is_main_worktree(linked), False)

    def test_an_unanswerable_probe_returns_None_rather_than_False(self) -> None:
        # False means "proven not the main working tree" and unlocks a move.
        # A directory git cannot answer for must never produce it.
        self.build_scenario(root_on="codex/landed")
        self.assertIsNone(cleanup.is_main_worktree(self.scratch / "nowhere"))
        stranger = self.scratch / "stranger"
        stranger.mkdir()
        self.assertIsNone(cleanup.is_main_worktree(stranger))

    def test_the_union_finds_the_main_working_tree_from_a_linked_worktree(self) -> None:
        self.build_scenario(root_on="codex/landed")
        verdicts = cleanup.main_worktree_verdicts([])   # signal 1 contributes nothing
        found = cleanup.main_worktree_paths(self.vantage, verdicts)
        self.assertIn(self.root.resolve(), found,
                      "signals 2 and 3 must find it without signal 1")


class MoveContainmentUnitTests(F.GitTestCase):
    """The predicate itself. No git, no filesystem — just the arithmetic."""

    def test_a_destination_inside_the_source_is_self_nesting(self) -> None:
        source = Path("/repo")
        for destination in ("/repo", "/repo/local/trash/repo", "/repo/x"):
            with self.subTest(destination=destination):
                self.assertTrue(
                    cleanup.move_is_self_nesting(source, Path(destination)))

    def test_a_destination_beside_or_above_the_source_is_not(self) -> None:
        source = Path("/repo/worktrees/agent-1")
        for destination in ("/repo/trash/agent-1", "/elsewhere/agent-1",
                            "/repo/worktrees/agent-1-backup"):
            with self.subTest(destination=destination):
                self.assertFalse(
                    cleanup.move_is_self_nesting(source, Path(destination)))

    def test_a_sibling_prefix_is_not_containment(self) -> None:
        # "/repo/agent-1" is a string prefix of "/repo/agent-10" and contains
        # none of it. Path parts, never string prefixes.
        self.assertFalse(cleanup.move_is_self_nesting(
            Path("/repo/agent-1"), Path("/repo/agent-10/inner")))

    def test_unique_destinations_never_repeat_within_a_run(self) -> None:
        trash = Path("/repo/local/workspace/trash-1")
        taken: set[Path] = set()
        chosen = []
        for source in (Path("/a/agent-1"), Path("/b/agent-1"), Path("/c/agent-1")):
            destination = cleanup._unique_destination(trash, source, taken)
            taken.add(destination.resolve())
            chosen.append(destination)
        self.assertEqual(len(set(chosen)), 3, chosen)
        self.assertEqual(chosen[0], trash / "agent-1")


if __name__ == "__main__":
    import unittest

    unittest.main()
