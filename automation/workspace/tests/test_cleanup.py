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
import shutil
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

    def test_a_squash_merged_branch_is_proposed_and_says_what_it_waived(self) -> None:
        # Its CONTENT is in main — that is what the containment probe says — and
        # its own commits are on no remote-tracking ref, which after a
        # squash-merge is a state no future push can change. The rule "every
        # commit exists on a remote" is a PROXY for "deleting this loses
        # nothing"; here the proxy is permanently unsatisfiable while the thing
        # it stands for is provably true, so the proxy yields — loudly, in a
        # note, and only behind a fresh fetch and a pinned tip.
        self.run_planner("--fetch")
        row = {r["name"]: r for r in self.plan_json()["branches"]}["squash-merge"]
        self.assertEqual(row["merged"], "merged")
        self.assertTrue(row["proposed"], row["keep_reasons"])
        self.assertGreater(row["unpushed_commits"], 0)
        self.assertTrue(any("no remote-tracking ref" in note
                            for note in row["notes"]),
                        f"the waiver must be stated: {row['notes']}")
        self.assertTrue(any("pinned" in note for note in row["notes"]))

    def test_the_unpushed_waiver_needs_a_fetch_and_says_so(self) -> None:
        # Without --fetch there is no fetched base to have proved containment
        # against, so the rule is NOT waived and the branch is kept.
        self.run_planner()
        row = {r["name"]: r for r in self.plan_json()["branches"]}["squash-merge"]
        self.assertFalse(row["proposed"])
        self.assertTrue(any("no remote-tracking ref" in reason
                            for reason in row["keep_reasons"]))

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
        # `/.claude/worktrees/` is ignored for the same reason and with the same
        # spelling the real repository uses: a harness worktree living inside
        # the main working tree must not make that tree dirty, or every
        # harness scenario below would be kept by the dirty-tree rule and prove
        # nothing about the harness rule.
        F.write(root / ".gitignore", "local/\n/.claude/worktrees/\n")
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
            # Each item is now its own guarded block, so the `mv` a shell runs
            # sits inside an `if`/`elif` CONDITION rather than on a line of its
            # own. Peel the keywords instead of matching only bare lines — a
            # helper that quietly stopped finding the moves would let every
            # containment assertion below pass by finding nothing.
            if stripped.endswith("; then"):
                stripped = stripped[: -len("; then")]
            parts = shlex.split(stripped)
            while parts and parts[0] in ("if", "elif", "else", "then", "!"):
                parts.pop(0)
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
        self.script_path = produced[-1].with_suffix(".sh")
        script = self.script_path.read_text(encoding="utf-8")
        self.assert_script_is_safe(script)
        return code, plan, script

    def latest_script_path(self) -> Path:
        """The file the owner would actually run, from the last ``plan_from``."""
        return self.script_path

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


# ── the per-worktree reflog, and the commits only it holds ───────────────────
#
# THE AUDIT FINDING THESE PIN. Backup refs were written PER BRANCH only, and a
# worktree carries its OWN reflog at `.git/worktrees/<id>/logs/HEAD`. The
# emitted script does `mv` then `git worktree prune`, and prune deletes that
# whole administrative directory — the reflog with it. A commit reachable from
# no ref and recorded only there is then reachable from nothing at all, and no
# backup ref was ever written for it.
#
# MEASURED, in this fixture, on git 2.55:
#   * a commit made ON the worktree's branch and then `reset --hard` away is
#     recorded in BOTH `worktrees/<id>/logs/HEAD` and the COMMON
#     `logs/refs/heads/<branch>` — so retiring the worktree alone does not lose
#     it, but nothing except a reflog is holding it either, and `git branch -d`
#     on a later run deletes that branch reflog too;
#   * a commit made while the worktree's HEAD is DETACHED, after HEAD moves back
#     to the branch, is recorded in `worktrees/<id>/logs/HEAD` and NOWHERE else.
#     `mv` + `git worktree prune` + `git gc --prune=now` erased it outright.
# Both shapes are built below, and both must come out with a backup ref.


class WorktreeReflogScenario(MainWorktreeScenario):
    """``self.retirable`` with two commits that live only in its own reflog."""

    def build_orphans(self) -> None:
        self.build_scenario(root_on="codex/landed")
        worktree = self.retirable

        # Shape 1 — the auditor's literal steps: commit, then reset it away.
        F.write(worktree / "reset-away.txt", "committed, then reset away\n")
        self.git(worktree, "add", "-A")
        self.git(worktree, "commit", "-q", "-m", "work that was reset away")
        self.reset_away = self.out(worktree, "rev-parse", "HEAD")
        self.git(worktree, "reset", "-q", "--hard", "HEAD~1")

        # Shape 2 — the same loss with NO common reflog behind it at all.
        self.git(worktree, "switch", "-q", "--detach", "HEAD")
        F.write(worktree / "detached.txt", "committed on a detached HEAD\n")
        self.git(worktree, "add", "-A")
        self.git(worktree, "commit", "-q", "-m", "work made on a detached HEAD")
        self.detached_only = self.out(worktree, "rev-parse", "HEAD")
        self.git(worktree, "switch", "-q", "linked-landed")
        self.git(worktree, "clean", "-qfd")

        self.assertEqual(
            self.out(worktree, "status", "--porcelain"), "",
            "the worktree must be CLEAN here, or this scenario tests the "
            "dirty-tree rule instead of the reflog sweep")
        self.assert_lives_only_in_the_worktree_reflog(self.detached_only)

    # ── the premise, asserted rather than assumed ────────────────────────────

    def common_reflog_text(self) -> str:
        logs = self.root / ".git" / "logs"
        return "\n".join(path.read_text(encoding="utf-8", errors="replace")
                         for path in sorted(logs.rglob("*")) if path.is_file())

    def worktree_reflog_text(self) -> str:
        holder = self.root / ".git" / "worktrees"
        if not holder.is_dir():
            return ""
        return "\n".join(path.read_text(encoding="utf-8", errors="replace")
                         for path in sorted(holder.rglob("logs/HEAD"))
                         if path.is_file())

    def assert_lives_only_in_the_worktree_reflog(self, oid: str) -> None:
        self.assertNotIn(oid, self.common_reflog_text(),
                         "this commit is in a COMMON reflog, so the fixture no "
                         "longer reproduces the worktree-only case")
        self.assertIn(oid, self.worktree_reflog_text())
        unreachable = self.out(self.root, "rev-list", "--single-worktree",
                               "--ignore-missing", oid, "--not", "--all")
        self.assertIn(oid, unreachable.split(),
                      "this commit is reachable from a ref, so nothing here is "
                      "at risk and the test proves nothing")

    def run_emitted_script(self, script_path: Path) -> None:
        result = subprocess.run(
            ["sh", str(script_path)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, check=False, env=dict(os.environ))
        self.assertEqual(result.returncode, 0,
                         f"the emitted script failed:\n{result.stdout}\n{result.stderr}")

    def backups_for(self, row: dict) -> dict[str, str]:
        """``{commit: backup ref}`` the plan claims for this worktree row."""
        return {entry["commit"]: entry["ref"] for entry in row["backup_refs"]}


class WorktreeReflogBackupTests(WorktreeReflogScenario):
    def test_the_emitted_script_leaves_a_reflog_only_commit_reachable(self) -> None:
        # THE AUDIT FINDING ITSELF, asserted on the outcome and on nothing else:
        # run the tool's own script, then ask git whether the work still exists.
        # Against the per-branch-only backup this fails on `detached-only`,
        # which `git gc --prune=now` erases outright.
        self.build_orphans()
        _, plan, _ = self.plan_from(self.root)
        self.assertEqual(self.worktree_row(plan, self.retirable)["action"],
                         "retire", "the fixture must reach the retire path")

        self.run_emitted_script(self.latest_script_path())
        self.assertNotIn(self.detached_only, self.worktree_reflog_text(),
                         "`git worktree prune` did not destroy the reflog, so "
                         "this run no longer exercises the hazard")
        self.git(self.root, "gc", "--prune=now", "--quiet")
        for label, oid in (("detached-only", self.detached_only),
                           ("reset-away", self.reset_away)):
            with self.subTest(commit=label):
                self.assertEqual(
                    self.git(self.root, "cat-file", "-e", oid,
                             check=False).returncode, 0,
                    f"{label} {oid[:8]} was reachable only from this "
                    f"worktree's reflog and the emitted script orphaned it")

    def test_a_reflog_only_commit_gets_a_backup_ref_the_script_writes(self) -> None:
        # The DEFAULT path: a dry run writes no ref itself, so the script it
        # emits has to write and verify them before its own `mv`.
        self.build_orphans()
        _, plan, script = self.plan_from(self.root)
        row = self.worktree_row(plan, self.retirable)
        self.assertEqual(row["action"], "retire", row["keep_reasons"])

        backups = self.backups_for(row)
        for label, oid in (("detached-only", self.detached_only),
                           ("reset-away", self.reset_away)):
            with self.subTest(commit=label):
                self.assertIn(oid, backups,
                              "no backup ref was planned for a commit that "
                              "lives only in this worktree's reflog")
                # The exact emitted spelling, compare-and-swap included: the
                # trailing '' is git's "this ref must not already exist", which
                # is what stops one backup being written over another.
                self.assertIn(
                    f"git update-ref -m 'pre-delete backup' "
                    f"{shlex.quote(backups[oid])} {oid} ''", script)

        self.run_emitted_script(self.latest_script_path())
        self.git(self.root, "gc", "--prune=now", "--quiet")
        for oid, ref in backups.items():
            with self.subTest(commit=oid[:8]):
                self.assertEqual(
                    self.out(self.root, "rev-parse", "--verify", ref + "^{commit}"),
                    oid, "a backup ref the plan promised does not resolve")

    def test_execute_writes_and_verifies_those_refs_up_front(self) -> None:
        self.build_orphans()
        _, plan, _ = self.plan_from(self.root, "--execute")
        row = self.worktree_row(plan, self.retirable)
        self.assertEqual(row["action"], "retire", row["keep_reasons"])
        self.assertTrue(row["backups_written"])
        for oid, ref in self.backups_for(row).items():
            with self.subTest(commit=oid[:8]):
                self.assertEqual(
                    self.out(self.root, "rev-parse", "--verify", ref + "^{commit}"),
                    oid, "--execute claimed a backup ref that does not resolve")

    def test_a_worktree_with_nothing_at_risk_gets_no_backup_refs(self) -> None:
        # The over-correction guard: a ref per reflog line, forever, would be a
        # different bug. Only commits reachable from NO ref may be pinned.
        self.build_scenario(root_on="codex/landed")
        _, plan, script = self.plan_from(self.root)
        row = self.worktree_row(plan, self.retirable)
        self.assertEqual(row["action"], "retire", row["keep_reasons"])
        self.assertEqual(row["backup_refs"], [])
        self.assertNotIn("-worktrees/", script)

    def test_the_sweep_never_regresses_the_no_mv_of_the_repo_root_rule(self) -> None:
        # PR #347's invariant, re-asserted on the script this feature rewrites.
        self.build_orphans()
        _, _, script = self.plan_from(self.root)
        self.assert_root_is_never_moved(script)
        self.assert_script_is_safe(script)


class WorktreeReflogUnitTests(WorktreeReflogScenario):
    def test_reachable_reflog_commits_are_deduped_away(self) -> None:
        self.build_orphans()
        reflog, stash = cleanup.worktree_reflog_commits(self.retirable)
        self.assertIn(self.detached_only, reflog)
        self.assertEqual(stash, [])
        orphans = cleanup.unreachable_commits(self.root, reflog, protected=stash)
        self.assertIsNotNone(orphans)
        self.assertLess(len(orphans), len(reflog),
                        "every reflog line was treated as at-risk; the "
                        "reachability dedupe is not running")
        for oid in orphans:
            with self.subTest(commit=oid[:8]):
                self.assertIn(oid, reflog, "the sweep walked past its inputs")

    def test_an_unreadable_worktree_reports_None_rather_than_nothing(self) -> None:
        # None is "unanswerable" and keeps. An empty list would read as
        # "nothing is at risk" and unlock a move.
        self.build_scenario(root_on="codex/landed")
        self.assertIsNone(cleanup.worktree_reflog_commits(self.scratch / "nowhere"))

    def test_more_orphans_than_the_cap_keeps_the_worktree(self) -> None:
        # The valve fails CLOSED: over the cap the worktree is kept and says
        # why. Truncating a backup set is the one outcome this whole feature
        # exists to prevent, so it may not be what running out of room does.
        self.build_orphans()
        item = cleanup.WorktreeItem(path=str(self.retirable), branch=None,
                                    action="keep")
        original = cleanup.MAX_WORKTREE_BACKUP_REFS
        cleanup.MAX_WORKTREE_BACKUP_REFS = 0
        self.addCleanup(setattr, cleanup, "MAX_WORKTREE_BACKUP_REFS", original)
        reasons = cleanup.plan_worktree_backups(
            self.root, item, self.retirable, run_id="TESTRUN")
        self.assertTrue(reasons)
        self.assertIn(cleanup.KEEP_TOO_MANY_ORPHANS, reasons[0])
        self.assertEqual(item.backups, [],
                         "a capped sweep must pin nothing, not pin some")

    def test_a_directory_name_git_would_refuse_degrades_to_a_usable_ref(self) -> None:
        # `slug` guarantees the character class, not ref legality: a component
        # may not start with `.` or contain `..`. A ref git rejects would drop
        # the worktree for a reason unrelated to the owner's work.
        oid = "0" * 40
        for name in ("..", ".hidden", "agent.lock", ""):
            with self.subTest(directory=name):
                ref = cleanup.worktree_backup_ref("RUN", Path("/x") / name, oid)
                checked = subprocess.run(
                    ["git", "check-ref-format", ref],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                self.assertEqual(checked.returncode, 0,
                                 f"git refuses the ref {ref}")

    def test_a_worktree_ref_can_never_collide_with_a_branch_backup(self) -> None:
        # git cannot hold both a ref `a/b` and a ref `a/b/c`. A branch named
        # exactly like a worktree directory is the collision that would make one
        # backup write fail — and a failed write is a dropped item.
        branch_ref = f"{cleanup.TRASH_REF_ROOT}/RUN/{cleanup.slug('agent-1')}"
        worktree_ref = cleanup.worktree_backup_ref("RUN", Path("/x/agent-1"),
                                                   "0" * 40)
        self.assertFalse(worktree_ref.startswith(branch_ref + "/"))
        self.assertNotEqual(worktree_ref, branch_ref)


# ── harness-owned worktrees: kept by default, retirable only on request ───────
#
# The owner's stated pain is that agent worktrees pile up and get cleaned by
# hand — with `git worktree remove`, which
# `docs/handbook/post-merge-cutover.md` names as prohibited. Keeping them
# unconditionally is what pushed an operator to that command; proposing them
# unconditionally would put a second sweeper on directories the Claude Code
# harness already sweeps. The flag is the third answer: opt-in, auditable, and
# subject to every precondition an ordinary worktree faces.


class HarnessWorktreeScenario(MainWorktreeScenario):
    def build_harness(self, *, name: str = "agent-1", branch: str = "harness-work",
                      start: str = "main") -> Path:
        self.build_scenario(root_on="codex/landed")
        harness = self.root / ".claude" / "worktrees" / name
        harness.parent.mkdir(parents=True, exist_ok=True)
        self.git(self.root, "worktree", "add", "-q", "-b", branch,
                 str(harness), start)
        self.assertEqual(
            self.out(self.root, "status", "--porcelain"), "",
            "`.claude/worktrees` must be ignored, or the main working tree is "
            "merely dirty and this scenario proves nothing")
        return harness


class HarnessWorktreeDefaultTests(HarnessWorktreeScenario):
    def test_by_default_it_is_kept_and_the_reason_names_the_flag(self) -> None:
        harness = self.build_harness()
        _, plan, _ = self.plan_from(self.root)
        row = self.worktree_row(plan, harness)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertIn(cleanup.KEEP_HARNESS, row["keep_reasons"])
        self.assertIn("--include-harness-worktrees", cleanup.KEEP_HARNESS,
                      "an operator reading the plan must learn the supported "
                      "path, or they reach for `git worktree remove` instead")

    def test_the_flag_proposes_it_and_says_the_tool_still_only_emits(self) -> None:
        harness = self.build_harness()
        code, plan, script = self.plan_from(self.root,
                                            "--include-harness-worktrees")
        self.assertIn(code, (0, 1))
        row = self.worktree_row(plan, harness)
        self.assertEqual(row["action"], "retire", row["keep_reasons"])
        self.assertTrue(plan["include_harness_worktrees"])
        moved = [source.resolve() for source, _ in self.emitted_moves(script)]
        self.assertIn(harness.resolve(), moved)
        header = script.split("set -eu", 1)[0]
        self.assertIn("post-merge-cutover.md", header)
        self.assertIn("worktree remove", header,
                      "the header must name the command this tool still does "
                      "not run, or the tension is undocumented")

    def test_the_report_carries_the_same_note(self) -> None:
        self.build_harness()
        buffer = io.StringIO()
        cleanup.main(["--repo-root", str(self.root), "--fetch",
                      "--include-harness-worktrees"], out=buffer)
        report = buffer.getvalue()
        self.assertIn("post-merge-cutover.md", report)
        self.assertIn("--include-harness-worktrees", report)


class HarnessWorktreePreconditionTests(HarnessWorktreeScenario):
    def test_the_flag_does_not_waive_the_dirty_tree_rule(self) -> None:
        harness = self.build_harness()
        F.write(harness / "scratch.md", "untracked — no git recovery story\n")
        _, plan, script = self.plan_from(self.root, "--include-harness-worktrees")
        row = self.worktree_row(plan, harness)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertTrue(any(cleanup.KEEP_DIRTY in reason
                            for reason in row["keep_reasons"]))
        moved = [source.resolve() for source, _ in self.emitted_moves(script)]
        self.assertNotIn(harness.resolve(), moved)

    def test_the_flag_does_not_waive_the_unmerged_rule(self) -> None:
        harness = self.build_harness()
        F.write(harness / "unpushed.txt", "work that exists nowhere else\n")
        self.git(harness, "add", "-A")
        self.git(harness, "commit", "-q", "-m", "harness: unmerged, unpushed work")
        _, plan, script = self.plan_from(self.root, "--include-harness-worktrees")
        row = self.worktree_row(plan, harness)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertIn(cleanup.KEEP_UNMERGED, row["keep_reasons"])
        moved = [source.resolve() for source, _ in self.emitted_moves(script)]
        self.assertNotIn(harness.resolve(), moved)

    def test_the_flag_does_not_waive_the_locked_rule(self) -> None:
        harness = self.build_harness()
        self.git(self.root, "worktree", "lock", "--reason",
                 "a live agent session holds this", str(harness))
        _, plan, _ = self.plan_from(self.root, "--include-harness-worktrees")
        row = self.worktree_row(plan, harness)
        self.assertEqual(row["action"], "keep", row["keep_reasons"])
        self.assertIn(cleanup.KEEP_LOCKED, row["keep_reasons"])

    def test_the_flag_does_not_waive_the_reflog_sweep(self) -> None:
        harness = self.build_harness(start="codex/landed")
        self.git(harness, "switch", "-q", "--detach", "HEAD")
        F.write(harness / "detached.txt", "only the worktree reflog holds this\n")
        self.git(harness, "add", "-A")
        self.git(harness, "commit", "-q", "-m", "harness: detached work")
        orphan = self.out(harness, "rev-parse", "HEAD")
        self.git(harness, "switch", "-q", "harness-work")
        self.git(harness, "clean", "-qfd")
        _, plan, script = self.plan_from(self.root, "--include-harness-worktrees")
        row = self.worktree_row(plan, harness)
        self.assertEqual(row["action"], "retire", row["keep_reasons"])
        backups = {entry["commit"]: entry["ref"] for entry in row["backup_refs"]}
        self.assertIn(orphan, backups)
        self.assertIn(
            f"git update-ref -m 'pre-delete backup' "
            f"{shlex.quote(backups[orphan])} {orphan} ''", script)

    def test_the_emitted_script_still_moves_and_never_removes(self) -> None:
        self.build_harness()
        _, _, script = self.plan_from(self.root, "--include-harness-worktrees")
        commands = [line for line in script.splitlines()
                    if line.strip() and not line.strip().startswith("#")]
        joined = "\n".join(commands)
        for forbidden in ("rm -", "rm ", "git clean", "worktree remove",
                          "branch -D", "--force", "reset --hard"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)
        self.assertIn("mv ", joined)
        self.assert_root_is_never_moved(script)


# ── the review ledger: reachability, never a name ────────────────────────────
#
# THE BUG THESE PIN. The keep rule was `branch.name in <the ledger's raw text>`.
# Measured on the real repository, that kept `fix/filter-pipeline-reports`
# forever because one row's `finding:` prose says "Merge of origin/main into
# fix/filter-pipeline-reports…" — while its tip is an ANCESTOR of `origin/main`
# and it holds zero commits `origin/main` does not, so no row could degrade.
# Two defects in one: the wrong question (a name carries no object; only
# reachability decides whether a row becomes UNKNOWN OBJECT), and a match set
# polluted with DIRECTORY PATHS — `docs/handbook`, `tasks/0` and friends all
# occur in that file and would pin a branch named after any of them.
#
# The feedback loop is what makes it compound: every branch that lands writes a
# ledger row, and an agent writing that row names the branch it is on. Under a
# name match, the ritual every branch performs on its way in is what makes it
# unretirable on its way out.


class ReviewLedgerReachabilityTests(PlannerTestCase):
    def write_ledger(self, text: str) -> None:
        ledger = self.root / cleanup.REVIEW_LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(text, encoding="utf-8")

    def branch_rows(self) -> dict:
        return {row["name"]: row for row in self.plan_json()["branches"]}

    def ledger_reasons(self, row: dict) -> list[str]:
        return [reason for reason in row["keep_reasons"]
                if "review ledger" in reason or "review-ledger" in reason]

    def test_a_branch_named_only_in_a_finding_string_is_proposed(self) -> None:
        # The live instance, reduced: the ledger's prose names the branch, and
        # the commit that row is KEYED to is one `origin/main` already reaches.
        # Nothing about deleting the branch can turn that row into UNKNOWN
        # OBJECT, so the name must buy it nothing.
        base = self.out(self.root, "rev-parse", "refs/remotes/origin/main")
        self.write_ledger(
            f"- base: {base[:8]}\n"
            f"  reviewed_by: agent\n"
            f"  finding: 'Merge of origin/main into true-merge. Every covered\n"
            f"    file arrives byte-identical from origin/main.'\n")
        self.run_planner("--fetch")
        row = self.branch_rows()["true-merge"]
        self.assertTrue(row["proposed"],
                        f"kept on a bare name match: {row['keep_reasons']}")
        self.assertEqual(self.ledger_reasons(row), [])

    def test_a_branch_holding_a_ledger_commit_the_base_cannot_reach_is_kept(
            self) -> None:
        # The hazard the rule actually exists for. `squash-merge`'s CONTENT is
        # in main under a different commit, so the containment probe passes and
        # its own commit is reachable from main by nothing. Push it so every
        # other precondition clears, and it is proposable — until the ledger
        # names that commit, at which point deleting the branch is what would
        # make the row uninspectable in a fresh clone.
        self.git(self.root, "push", "-q", "-u", "origin", "squash-merge")
        self.git(self.root, "fetch", "-q", "--prune", "origin")
        tip = self.out(self.root, "rev-parse", "refs/heads/squash-merge")

        self.run_planner("--fetch")
        control = self.branch_rows()["squash-merge"]
        self.assertTrue(control["proposed"],
                        f"the fixture never reaches the ledger rule: "
                        f"{control['keep_reasons']}")

        self.write_ledger(f"- base: {tip[:8]}\n"
                          f"  reviewed_by: agent\n"
                          f"  finding: 'nothing here names any branch'\n")
        self.run_planner("--fetch")
        row = self.branch_rows()["squash-merge"]
        self.assertFalse(row["proposed"])
        self.assertTrue(self.ledger_reasons(row), row["keep_reasons"])
        self.assertIn(tip[:8], " ".join(row["keep_reasons"]),
                      "the reason must name the commit that is at risk")

    def test_directory_paths_in_the_ledger_pin_nothing(self) -> None:
        # `grep -oE '(fix|feat|docs|tasks|codex)/[a-z0-9-]+'` over the real
        # ledger returns `docs/handbook`, `docs/designs`, `docs/roadmap`,
        # `tasks/0`, `tasks/3` and `tasks/4` alongside actual branch names. A
        # substring rule cannot tell those apart; a reachability rule never asks.
        paths = ("docs/handbook", "docs/roadmap", "tasks/0", "codex/landed")
        for name in paths:
            self.git(self.root, "branch", name, "main")
        self.write_ledger(
            "- base: 0000000\n"
            "  finding: 'Read docs/handbook/public-private-split.md and\n"
            "    docs/roadmap/current-state.md; filed under tasks/0_backlog/ and\n"
            "    reviewed on codex/landed.'\n")
        self.run_planner("--fetch")
        rows = self.branch_rows()
        for name in paths:
            with self.subTest(branch=name):
                self.assertIn(name, rows)
                self.assertTrue(
                    rows[name]["proposed"],
                    f"a directory path in the ledger pinned {name}: "
                    f"{rows[name]['keep_reasons']}")

    def test_an_absent_ledger_is_not_an_unanswerable_probe(self) -> None:
        # Fail-closed must fire on "git could not say", never on "there is no
        # ledger" — a public export omits that file, and a planner that kept
        # every branch there would be a no-op wearing a safety argument.
        self.assertFalse((self.root / cleanup.REVIEW_LEDGER).exists())
        self.run_planner("--fetch")
        row = self.branch_rows()["true-merge"]
        self.assertTrue(row["proposed"], row["keep_reasons"])


# ── `git branch -d` asks a different question than the containment probe ─────
#
# THE BUG THESE PIN. The planner's merged-test asks "does the BASE REF already
# have this content". `git branch -d` asks "is this branch an ancestor of its
# own UPSTREAM, or of HEAD when it has none" (builtin/branch.c, `branch_merged`).
# Measured on the real repository: `fix/cleanup-worktree-gaps` held zero commits
# `origin/main` did not, stood one commit ahead of
# `origin/fix/cleanup-worktree-gaps`, was PROPOSED, and the emitted script died
# on `error: the branch … is not fully merged`.
#
# There is no non-forcing repair, and that was checked rather than assumed:
# `-D`, `update-ref -d`, deleting the tracking ref and `--unset-upstream` all
# work only by removing the evidence git consults, and the tracking ref here is
# not stale — the branch is still on the remote and the next fetch restores it.
# So the outcome is an honest KEEP that names the upstream and the remedies that
# belong to the owner.


class DeletableBranchesScenario(F.GitTestCase):
    """A toolkit repo whose topic branches all clear every precondition."""

    def build_repo(self, *names: str) -> None:
        self.root = self.scratch / "toolkit"
        self.root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)],
                       check=True, env=dict(os.environ))
        F.add_toolkit_markers(self.root)
        F.write(self.root / ".gitignore", "local/\n")
        F.write(self.root / "seed.txt", "seed\n")
        self.commit(self.root, "base commit")
        F.add_origin(self, self.root)
        for name in names:
            self.land(name)
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")

    def land(self, name: str) -> str:
        """A branch that really landed: pushed with an upstream, then merged."""
        self.git(self.root, "switch", "-q", "-c", name, "main")
        F.write(self.root / f"{cleanup.slug(name)}.txt", f"work on {name}\n")
        tip = self.commit(self.root, f"{name}: the work")
        self.git(self.root, "push", "-q", "-u", "origin", name)
        self.git(self.root, "switch", "-q", "main")
        self.git(self.root, "merge", "-q", "--no-ff", name, "-m", f"Merge {name}")
        return tip

    def plan(self, *argv: str) -> tuple[int, dict, str, Path]:
        buffer = io.StringIO()
        code = cleanup.main(
            ["--repo-root", str(self.root), "--fetch", *argv], out=buffer)
        produced = sorted((self.root / "local" / "workspace").glob("cleanup-*.json"))
        self.assertTrue(produced, "no plan was written")
        plan = json.loads(produced[-1].read_text(encoding="utf-8"))
        script_path = produced[-1].with_suffix(".sh")
        return code, plan, script_path.read_text(encoding="utf-8"), script_path

    def deletions_in(self, script: str) -> list[str]:
        """Every branch a shell running this script would actually try to delete.

        BOTH spellings. `git branch -d` is the ordinary one; a branch `-d`
        structurally cannot accept is deleted by `git update-ref -d <ref> <tip>`
        instead — a compare-and-swap — and a helper that only knew about the
        first would report "no deletion" for a script that deletes.
        """
        names = []
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.endswith("; then"):
                stripped = stripped[: -len("; then")]
            parts = shlex.split(stripped)
            while parts and parts[0] in ("if", "elif", "else", "then", "!"):
                parts.pop(0)
            if parts[:3] == ["git", "branch", "-d"]:
                names.append(parts[3])
            elif (parts[:3] == ["git", "update-ref", "-d"]
                    and len(parts) > 3 and parts[3].startswith("refs/heads/")):
                names.append(parts[3].removeprefix("refs/heads/"))
        return names

    def cas_deletions_in(self, script: str) -> list[str]:
        """Only the compare-and-swap deletions, with the tip each one demands."""
        found = []
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.endswith("; then"):
                stripped = stripped[: -len("; then")]
            parts = shlex.split(stripped)
            while parts and parts[0] in ("if", "elif", "else", "then", "!"):
                parts.pop(0)
            if (parts[:3] == ["git", "update-ref", "-d"] and len(parts) == 5
                    and parts[3].startswith("refs/heads/")):
                found.append((parts[3].removeprefix("refs/heads/"), parts[4]))
        return found

    def branch_rows(self, plan: dict) -> dict:
        return {row["name"]: row for row in plan["branches"]}

    def run_script(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False, env=dict(os.environ))

    def local_branches(self) -> set[str]:
        return set(self.out(self.root, "for-each-ref", "--format=%(refname:short)",
                            "refs/heads").split())


class DeleteRefusalIsPredictedTests(DeletableBranchesScenario):
    def test_a_branch_ahead_of_its_own_upstream_is_retired_by_swap(self) -> None:
        # The live shape: the local branch is moved onto the merge commit, so it
        # holds NO commit `origin/main` lacks and is still one ahead of
        # `origin/<branch>`. Content-contained, fully pushed — and refused by -d,
        # which judges against the UPSTREAM rather than against the base ref this
        # planner tested. It used to be kept forever on that verdict.
        self.build_repo("codex/landed")
        self.git(self.root, "branch", "-f", "codex/landed", "main")
        self.assertEqual(
            self.out(self.root, "rev-list", "codex/landed",
                     "--not", "refs/remotes/origin/main"), "",
            "the fixture must hold no commit origin/main lacks")
        self.assertEqual(
            self.out(self.root, "rev-list", "--left-right", "--count",
                     "codex/landed...refs/remotes/origin/codex/landed"), "1\t0")
        tip = self.out(self.root, "rev-parse", "codex/landed")

        _, plan, script, path = self.plan()
        row = self.branch_rows(plan)["codex/landed"]
        self.assertTrue(row["proposed"], row["keep_reasons"])
        self.assertEqual(row["delete_method"], cleanup.DELETE_CAS)
        # The verdict it supersedes is QUOTED, not hidden: a reader of the plan
        # still learns exactly what `git branch -d` said and about which ref.
        notes = " ".join(row["notes"])
        self.assertIn("refs/remotes/origin/codex/landed", notes,
                      "the note must name the upstream git judges -d against")
        self.assertIn("upstream", notes)
        self.assertNotIn("git branch -d codex/landed", script)
        self.assertEqual(self.cas_deletions_in(script), [("codex/landed", tip)],
                         "the swap must demand the exact tip the plan proved")

        result = self.run_script(path)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertNotIn("codex/landed", self.local_branches())
        self.assertEqual(
            self.out(self.root, "rev-parse", "--verify",
                     row["backup_ref"] + "^{commit}"), tip,
            "the tip must still be pinned after the swap deleted the branch")

    def test_a_branch_the_remote_head_deleted_is_retired_by_swap(self) -> None:
        # THE SHAPE THIS REPOSITORY ACTUALLY PRODUCES, and the one that was
        # unretirable by TWO independent gates at once. Squash-merged, then the
        # remote head branch deleted, then `--fetch --prune`:
        #   * every commit is now on no remote-tracking ref, and none ever can be
        #     again — the branch they were pushed to is gone;
        #   * `-d` falls back to HEAD, which a squash-merge is not an ancestor of.
        # Neither gate could ever clear, while `origin/main` demonstrably held
        # every byte. `--fetch --prune` was itself the step that destroyed the
        # evidence permitting retirement.
        self.build_repo("codex/landed")
        self.git(self.root, "switch", "-q", "-c", "codex/squashed", "main")
        F.write(self.root / "squashed.txt", "squashed work\n")
        self.commit(self.root, "codex/squashed: the work")
        self.git(self.root, "push", "-q", "-u", "origin", "codex/squashed")
        self.git(self.root, "switch", "-q", "main")
        self.git(self.root, "merge", "-q", "--squash", "codex/squashed")
        self.commit(self.root, "codex/squashed landed as one commit")
        self.git(self.root, "push", "-q", "origin", "main")
        # GitHub's "delete head branch after merge", then our own prune.
        self.git(self.root, "push", "-q", "origin", ":codex/squashed")
        self.git(self.root, "fetch", "-q", "--prune", "origin")
        tip = self.out(self.root, "rev-parse", "codex/squashed")

        _, plan, script, path = self.plan()
        row = self.branch_rows(plan)["codex/squashed"]
        self.assertEqual(row["merged"], "merged", "the content IS in the base")
        self.assertGreater(row["unpushed_commits"], 0,
                           "the fixture must reproduce the permanent-unpushed shape")
        self.assertTrue(row["proposed"], row["keep_reasons"])
        self.assertEqual(row["delete_method"], cleanup.DELETE_CAS)
        notes = " ".join(row["notes"])
        self.assertIn("HEAD", notes, "the superseded -d verdict must be quoted")
        self.assertIn("no remote-tracking ref", notes,
                      "the waived unpushed rule must be stated, not silent")
        self.assertEqual(self.cas_deletions_in(script), [("codex/squashed", tip)])

        result = self.run_script(path)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertNotIn("codex/squashed", self.local_branches())
        self.assertEqual(
            self.out(self.root, "rev-parse", "--verify",
                     row["backup_ref"] + "^{commit}"), tip)
        # And the commits are still there afterwards, not merely the ref.
        self.git(self.root, "gc", "--prune=now", "--quiet")
        self.assertEqual(
            self.git(self.root, "cat-file", "-e", tip, check=False).returncode, 0)

    def test_a_branch_the_base_does_not_contain_is_never_swapped(self) -> None:
        # The supersession is not "ignore -d". It rests ENTIRELY on this tool's
        # own containment proof, so with that proof absent the refusal stands.
        self.build_repo("codex/landed")
        self.git(self.root, "switch", "-q", "-c", "codex/open", "main")
        F.write(self.root / "open.txt", "work that never landed\n")
        self.commit(self.root, "codex/open: unique work")
        self.git(self.root, "switch", "-q", "main")

        _, plan, script, _ = self.plan()
        row = self.branch_rows(plan)["codex/open"]
        self.assertFalse(row["proposed"], row["notes"])
        self.assertEqual(row["delete_method"], cleanup.DELETE_BRANCH_D)
        self.assertNotIn("codex/open", self.deletions_in(script))

    def test_a_swap_is_never_emitted_on_a_stale_plan(self) -> None:
        # Containment is only evidence when it was judged against a FETCHED
        # base. Without --fetch there is no such judgement, so `-d`'s refusal is
        # all there is and the branch is kept.
        self.build_repo("codex/landed")
        self.git(self.root, "branch", "-f", "codex/landed", "main")
        buffer = io.StringIO()
        cleanup.main(["--repo-root", str(self.root)], out=buffer)
        produced = sorted((self.root / "local" / "workspace").glob("cleanup-*.json"))
        plan = json.loads(produced[-1].read_text(encoding="utf-8"))
        row = self.branch_rows(plan)["codex/landed"]
        self.assertFalse(row["proposed"], row["notes"])
        self.assertIn("STALE", " ".join(row["keep_reasons"]))

    def test_every_deletion_the_script_emits_actually_succeeds(self) -> None:
        # The property, asserted the only way that settles it: run the script
        # the owner would run and read git's answer. Both spellings are covered:
        # `codex/one` by `git branch -d`, `codex/two` — which -d refuses — by the
        # compare-and-swap.
        self.build_repo("codex/one", "codex/two")
        self.git(self.root, "branch", "-f", "codex/two", "main")   # -d will refuse
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")

        _, plan, script, path = self.plan()
        self.assertEqual(sorted(self.deletions_in(script)),
                         ["codex/one", "codex/two"])
        self.assertEqual([name for name, _ in self.cas_deletions_in(script)],
                         ["codex/two"],
                         "only the branch -d refuses may use the swap")
        result = self.run_script(path)
        self.assertEqual(result.returncode, 0,
                         f"the emitted script failed:\n{result.stdout}\n{result.stderr}")
        self.assertEqual(self.local_branches(), {"main"})

    def test_a_swap_refuses_a_branch_that_moved_after_the_plan(self) -> None:
        # What the compare-and-swap gives back that a plain deletion would not.
        # `git branch -d` re-checks itself at RUN time, which is the only reason
        # the branch path ever survived a plan going stale between being written
        # and being run; `git update-ref -d <ref> <tip>` re-checks the tip.
        self.build_repo("codex/two")
        self.git(self.root, "branch", "-f", "codex/two", "main")
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")
        _, plan, script, path = self.plan()
        self.assertEqual([name for name, _ in self.cas_deletions_in(script)],
                         ["codex/two"])

        # A new, unmerged commit lands on the branch AFTER the plan is written.
        self.git(self.root, "switch", "-q", "codex/two")
        F.write(self.root / "raced.txt", "work that arrived after the plan\n")
        raced = self.commit(self.root, "codex/two: raced work")
        self.git(self.root, "switch", "-q", "main")

        result = self.run_script(path)
        self.assertEqual(result.returncode, 1, "a refusal must fail the run")
        self.assertIn("REFUSED", result.stdout + result.stderr)
        self.assertIn("codex/two", self.local_branches(),
                      "the swap must refuse a branch that moved")
        self.assertEqual(self.out(self.root, "rev-parse", "codex/two"), raced)

    def test_a_swap_refuses_a_branch_a_worktree_checked_out(self) -> None:
        # The other run-time check `git branch -d` performs and a bare
        # compare-and-swap does not, so it is written out explicitly.
        self.build_repo("codex/two")
        self.git(self.root, "branch", "-f", "codex/two", "main")
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")
        _, _, script, path = self.plan()
        self.assertEqual([name for name, _ in self.cas_deletions_in(script)],
                         ["codex/two"])

        held = self.scratch / "held"
        self.git(self.root, "worktree", "add", "-q", str(held), "codex/two")

        result = self.run_script(path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("codex/two", self.local_branches(),
                      "a branch a worktree holds must never be swapped away")


# ── one refusal must not cancel the items after it ───────────────────────────
#
# THE BUG THESE PIN. The emitted script was a bare `set -eu` list. When the
# unpredicted `git branch -d` above was refused, the shell exited on that line
# and the two remaining, perfectly safe deletions never ran — leaving the
# operator a failure that named neither what had worked nor what had not. What
# must stay fatal is a backup ref that does not read back: that still stops ITS
# OWN item's deletion, because a deletion standing behind nothing is the hazard
# the backup exists for.


class OneRefusalDoesNotCancelTheRestTests(DeletableBranchesScenario):
    def sabotage_middle(self, script: str) -> str:
        """Make the MIDDLE emitted deletion refuse at RUN time, not plan time.

        Prediction now stops a doomed `-d` being written at all, so a refusal
        can only be produced the way the real gap produces one: the plan is
        written, and the branch moves before the owner runs the script.
        """
        names = self.deletions_in(script)
        self.assertEqual(len(names), 3, f"expected three deletions, got {names}")
        target = names[1]
        self.git(self.root, "branch", "-f", target, "refs/heads/codex/spare")
        return target

    def test_the_two_safe_items_still_run_and_the_run_still_fails(self) -> None:
        self.build_repo("codex/one", "codex/two", "codex/three")
        self.git(self.root, "switch", "-q", "-c", "codex/spare", "main")
        F.write(self.root / "spare.txt", "never merged\n")
        self.commit(self.root, "codex/spare: unmerged work")
        self.git(self.root, "switch", "-q", "main")
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")

        _, _, script, path = self.plan()
        refused = self.sabotage_middle(script)
        safe = [name for name in self.deletions_in(script) if name != refused]

        result = self.run_script(path)
        self.assertNotEqual(result.returncode, 0,
                            "a refusal must never be reported as success")
        survivors = self.local_branches()
        for name in safe:
            with self.subTest(branch=name):
                self.assertNotIn(
                    name, survivors,
                    f"{name} was independent of {refused} and never ran")
        self.assertIn(refused, survivors, "the refused branch must survive")

        combined = result.stdout + result.stderr
        self.assertIn("workspace cleanup summary", combined)
        self.assertIn(f"REFUSED  branch {refused}", combined,
                      f"the summary must name the refusal:\n{combined}")
        for name in safe:
            with self.subTest(branch=name):
                self.assertIn(f"done     branch {name}", combined,
                              f"the summary must name what succeeded:\n{combined}")

    def test_a_backup_ref_that_cannot_be_written_still_stops_its_own_delete(
            self) -> None:
        # The line that may NOT become advisory. A ref cannot be created where a
        # directory of refs already stands, so pre-creating a child of one
        # item's backup ref makes its `update-ref` fail — and that item's
        # `git branch -d` must not run, while the others still do.
        self.build_repo("codex/one", "codex/two", "codex/three")
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")

        _, _, script, path = self.plan()
        names = self.deletions_in(script)
        self.assertEqual(len(names), 3, names)
        blocked = names[0]
        ref = [row["backup_ref"] for row in json.loads(
            path.with_suffix(".json").read_text(encoding="utf-8"))["branches"]
            if row["name"] == blocked][0]
        self.git(self.root, "update-ref", f"{ref}/occupied",
                 self.out(self.root, "rev-parse", "main"))

        result = self.run_script(path)
        self.assertNotEqual(result.returncode, 0)
        survivors = self.local_branches()
        self.assertIn(blocked, survivors,
                      "a branch whose backup ref failed was deleted anyway")
        for name in names[1:]:
            with self.subTest(branch=name):
                self.assertNotIn(name, survivors)
        self.assertIn("backup ref did not read back",
                      result.stdout + result.stderr)

    def test_a_plan_with_nothing_refused_still_exits_zero(self) -> None:
        # The other half of "exit non-zero if anything refused": a clean run
        # must not start failing because the script grew a summary.
        self.build_repo("codex/one", "codex/two")
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")
        _, _, script, path = self.plan()
        result = self.run_script(path)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn("every item in this plan completed.", result.stdout)
        self.assertFalse({"codex/one", "codex/two"} & self.local_branches())


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


# ── the reflog `git worktree prune` was destroying ───────────────────────────
#
# THE MEASURED LOSS, with its control arm. `classify` used to send a worktree
# whose directory is gone straight to `action="prune"` and `continue` — BEFORE
# the reflog sweep — and `--execute` then ran `git worktree prune`, which
# deletes `.git/worktrees/<id>/` entire. A commit made while that worktree's
# HEAD was detached lives only in the `logs/HEAD` inside it.
#
# The control arm is what makes this a defect rather than a caveat: the OWNER
# deleting the directory and running `git gc --prune=now` does NOT lose the
# commit. Running this tool did. Both arms are asserted below.


class GoneWorktreeReflogScenario(F.GitTestCase):
    """A registration whose directory is gone, holding a reflog-only commit."""

    def build(self) -> None:
        self.root = self.scratch / "toolkit"
        self.root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)],
                       check=True, env=dict(os.environ))
        F.add_toolkit_markers(self.root)
        F.write(self.root / ".gitignore", "local/\n")
        F.write(self.root / "seed.txt", "seed\n")
        self.commit(self.root, "base commit")
        F.add_origin(self, self.root)

        self.worktree = self.scratch / "gone"
        self.git(self.root, "worktree", "add", "-q", "-b", "gone-work",
                 str(self.worktree), "main")
        # The shape with NO common reflog behind it at all: committed on a
        # detached HEAD, then HEAD returns to the branch.
        self.git(self.worktree, "switch", "-q", "--detach")
        F.write(self.worktree / "orphan.txt", "only the worktree reflog has this\n")
        self.git(self.worktree, "add", "-A")
        self.git(self.worktree, "commit", "-q", "-m", "detached experiment")
        self.orphan = self.out(self.worktree, "rev-parse", "HEAD")
        self.git(self.worktree, "switch", "-q", "gone-work")
        self.assertEqual(
            self.out(self.root, "for-each-ref", "--contains", self.orphan,
                     "--format=%(refname)"), "",
            "the fixture must hold a commit NO ref reaches")
        shutil.rmtree(self.worktree)

    def plan(self, *argv: str) -> tuple[int, dict, str]:
        buffer = io.StringIO()
        code = cleanup.main(["--repo-root", str(self.root), "--fetch", *argv],
                            out=buffer)
        produced = sorted((self.root / "local" / "workspace").glob("cleanup-*.json"))
        self.assertTrue(produced, "no plan was written")
        plan = json.loads(produced[-1].read_text(encoding="utf-8"))
        return code, plan, buffer.getvalue()

    def row(self, plan: dict) -> dict:
        target = Path(self.worktree).resolve()
        rows = [r for r in plan["worktrees"]
                if Path(r["path"]).resolve() == target]
        self.assertEqual(len(rows), 1, plan["worktrees"])
        return rows[0]


class PrunePathSweepsTheReflogTests(GoneWorktreeReflogScenario):
    def test_the_owner_doing_it_by_hand_does_not_lose_the_commit(self) -> None:
        # THE CONTROL ARM. Without this the test below proves only that git
        # keeps commits alive, not that the tool was the thing destroying them.
        self.build()
        self.git(self.root, "gc", "--prune=now", "--quiet")
        self.assertEqual(
            self.git(self.root, "cat-file", "-e", self.orphan,
                     check=False).returncode, 0,
            "the per-worktree reflog should still be protecting this commit")

    def test_execute_pins_the_reflog_only_commit_before_it_prunes(self) -> None:
        self.build()
        code, plan, report = self.plan("--execute")
        self.assertIn(code, (0, 1))
        row = self.row(plan)
        self.assertEqual(row["action"], "prune", row["keep_reasons"])
        self.assertTrue(row["pruned"], "the registration was not pruned")
        backups = {e["commit"]: e["ref"] for e in row["backup_refs"]}
        self.assertIn(self.orphan, backups,
                      "no backup ref was written for the commit `git worktree "
                      "prune` was about to destroy")
        self.assertTrue(row["backups_written"])

        # The registration — and its `logs/HEAD` — really is gone now.
        self.assertNotIn(str(self.worktree.resolve()),
                         self.out(self.root, "worktree", "list", "--porcelain"))
        self.git(self.root, "gc", "--prune=now", "--quiet")
        self.assertEqual(
            self.git(self.root, "cat-file", "-e", self.orphan,
                     check=False).returncode, 0,
            "`--execute` destroyed a commit only the worktree reflog held")
        self.assertEqual(
            self.out(self.root, "rev-parse", "--verify",
                     backups[self.orphan] + "^{commit}"), self.orphan)
        # And the branch is un-wedged, which is the whole point of pruning.
        self.assertEqual(
            self.git(self.root, "switch", "gone-work", check=False).returncode, 0)

    def test_a_dry_run_plans_the_pins_and_prunes_nothing(self) -> None:
        self.build()
        _, plan, _ = self.plan()
        row = self.row(plan)
        self.assertEqual(row["action"], "prune")
        self.assertFalse(row["pruned"])
        self.assertFalse(row["backups_written"])
        self.assertIn(self.orphan,
                      {e["commit"] for e in row["backup_refs"]})
        self.assertIn(str(self.worktree.resolve()),
                      self.out(self.root, "worktree", "list", "--porcelain"))

    def test_an_unreadable_reflog_keeps_the_registration_instead(self) -> None:
        # A killed session leaves damaged administrative data behind. The
        # commits prune is about to destroy cannot then be enumerated, and an
        # unanswerable probe is a reason to keep — never to proceed.
        self.build()
        admin = self.root / ".git" / "worktrees" / self.worktree.name
        F.write(admin / "commondir", "GARBAGE-NOT-A-DIRECTORY")

        _, plan, _ = self.plan("--execute")
        row = self.row(plan)
        self.assertEqual(row["action"], "keep", row)
        self.assertIn(cleanup.KEEP_NO_REFLOG, row["keep_reasons"])
        self.assertFalse(row["pruned"])
        self.assertIn(str(self.worktree.resolve()),
                      self.out(self.root, "worktree", "list", "--porcelain"),
                      "a registration whose reflog cannot be read was pruned")

    def test_one_unsweepable_entry_holds_back_every_other_prune(self) -> None:
        # `git worktree prune` HAS NO TARGET — it sweeps every prunable
        # registration at once. So a per-item KEEP is not a decision prune can
        # honour, and letting it run anyway would destroy the very commits the
        # keep exists to protect. All or nothing, and the report names the
        # entry that stopped it.
        self.build()
        healthy = self.scratch / "healthy"
        self.git(self.root, "worktree", "add", "-q", "-b", "healthy-work",
                 str(healthy), "main")
        shutil.rmtree(healthy)
        admin = self.root / ".git" / "worktrees" / self.worktree.name
        F.write(admin / "commondir", "GARBAGE-NOT-A-DIRECTORY")

        _, plan, report = self.plan("--execute")
        rows = {Path(r["path"]).name: r for r in plan["worktrees"]}
        self.assertEqual(rows["healthy"]["action"], "keep", rows["healthy"])
        self.assertTrue(any(cleanup.KEEP_PRUNE_HELD_BACK in reason
                            for reason in rows["healthy"]["keep_reasons"]),
                        rows["healthy"]["keep_reasons"])
        listed = self.out(self.root, "worktree", "list", "--porcelain")
        self.assertIn(str(healthy.resolve()), listed,
                      "prune ran while one gone entry was still unswept")


class GoneWorktreeReflogUnitTests(GoneWorktreeReflogScenario):
    def test_the_admin_directory_is_found_by_its_gitdir_file(self) -> None:
        self.build()
        admin = cleanup.worktree_admin_dir(self.root, self.worktree)
        self.assertIsNotNone(admin)
        self.assertEqual(admin.name, self.worktree.name)
        self.assertTrue((admin / "logs" / "HEAD").is_file(),
                        "the reflog must still be readable after the working "
                        "directory is gone — that is the whole premise")

    def test_a_path_that_was_never_a_worktree_answers_None(self) -> None:
        self.build()
        self.assertIsNone(
            cleanup.worktree_admin_dir(self.root, self.scratch / "never"))
        self.assertIsNone(
            cleanup.gone_worktree_reflog_commits(self.root,
                                                 self.scratch / "never"))

    def test_the_gone_reflog_lists_the_commit_the_live_one_would(self) -> None:
        self.build()
        enumerated = cleanup.gone_worktree_reflog_commits(self.root, self.worktree)
        self.assertIsNotNone(enumerated)
        self.assertIn(self.orphan, enumerated[0])

    def test_hold_back_is_all_or_nothing_and_idempotent(self) -> None:
        blocked = cleanup.WorktreeItem(path="/a", branch=None, action="keep",
                                       gone=True)
        healthy = cleanup.WorktreeItem(path="/b", branch=None, action="prune",
                                       gone=True)
        items = [blocked, healthy]
        self.assertTrue(cleanup.hold_back_prunes(items))
        self.assertEqual(healthy.action, "keep")
        reasons = list(healthy.keep_reasons)
        cleanup.hold_back_prunes(items)
        self.assertEqual(healthy.keep_reasons, reasons,
                         "a second pass must not restate the reason")

    def test_nothing_is_held_back_when_every_gone_entry_is_sweepable(self) -> None:
        items = [cleanup.WorktreeItem(path="/b", branch=None, action="prune",
                                      gone=True)]
        self.assertFalse(cleanup.hold_back_prunes(items))
        self.assertEqual(items[0].action, "prune")

    def test_a_locked_gone_entry_never_holds_anything_back(self) -> None:
        # git declines to prune a locked registration regardless, which is
        # exactly why it wedges its branch. It is not evidence of anything.
        locked = cleanup.WorktreeItem(path="/a", branch=None, action="keep",
                                      gone=True, locked=True)
        healthy = cleanup.WorktreeItem(path="/b", branch=None, action="prune",
                                       gone=True)
        self.assertFalse(cleanup.hold_back_prunes([locked, healthy]))
        self.assertEqual(healthy.action, "prune")


# ── two branch names, one backup ref ─────────────────────────────────────────
#
# `slug` maps `/` to `-` and lowercases, so `feat/a` and `feat-a` derived the
# IDENTICAL `refs/agent-trash/<run>/feat-a`, and `git update-ref` with no
# old-value guard let the second write silently replace the first. Both plan
# rows still said `backup_written: true`; the emitted script wrote the same ref
# twice with different oids and then printed "Nothing was lost". Measured end to
# end through an ordinary fetch --prune / gc sequence: one tip unrecoverable.


class BranchBackupCollisionScenario(F.GitTestCase):
    def build(self, *names: str) -> None:
        self.root = self.scratch / "toolkit"
        self.root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)],
                       check=True, env=dict(os.environ))
        F.add_toolkit_markers(self.root)
        F.write(self.root / ".gitignore", "local/\n")
        F.write(self.root / "seed.txt", "seed\n")
        self.commit(self.root, "base commit")
        F.add_origin(self, self.root)
        self.tips = {}
        for index, name in enumerate(names):
            self.git(self.root, "switch", "-q", "-c", name, "main")
            F.write(self.root / f"work-{index}.txt", f"work on {name}\n")
            self.tips[name] = self.commit(self.root, f"{name}: the work")
            self.git(self.root, "push", "-q", "-u", "origin", name)
            self.git(self.root, "switch", "-q", "main")
        # Main moves on its own FIRST. Without this the cherry-picks below
        # rebuild each commit onto its original parent, and with the fixture's
        # pinned author and committer dates that reproduces a byte-identical
        # commit object — the same sha, so nothing would be at risk.
        F.write(self.root / "main-moved.txt", "main moved on\n")
        self.commit(self.root, "main: unrelated work")
        for name in names:
            # CHERRY-PICKED, not merged. This is not a detail: `merge --no-ff`
            # would make each branch's own commit an ancestor of main, and then
            # main itself keeps both tips alive whatever the backup refs do —
            # so a collision that destroyed one backup would be invisible. The
            # rebase-merge shape (`merge_stack.py` produces it after a rebase)
            # lands the CONTENT under a new sha and leaves the original commit
            # reachable from nothing but its own branch and its remote head.
            self.git(self.root, "cherry-pick", self.tips[name])
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")
        for name in names:
            self.assertNotEqual(
                self.git(self.root, "merge-base", "--is-ancestor",
                         self.tips[name], "refs/remotes/origin/main",
                         check=False).returncode, 0,
                f"{name}'s own commit is on origin/main, so nothing here is at "
                f"risk and the collision would be invisible")

    def plan(self, *argv: str) -> tuple[dict, Path]:
        buffer = io.StringIO()
        cleanup.main(["--repo-root", str(self.root), "--fetch", *argv],
                     out=buffer)
        produced = sorted((self.root / "local" / "workspace").glob("cleanup-*.json"))
        return (json.loads(produced[-1].read_text(encoding="utf-8")),
                produced[-1].with_suffix(".sh"))


class BranchBackupRefsNeverCollideTests(BranchBackupCollisionScenario):
    COLLIDING = ("feat/a", "feat-a")

    def test_two_names_that_slug_alike_get_two_backup_refs(self) -> None:
        self.build(*self.COLLIDING)
        self.assertEqual(cleanup.slug("feat/a"), cleanup.slug("feat-a"),
                         "the fixture no longer reproduces the slug collision")
        plan, _ = self.plan("--execute")
        rows = {r["name"]: r for r in plan["branches"] if r["name"] in self.COLLIDING}
        self.assertEqual(len(rows), 2, plan["branches"])
        refs = set()
        for name, row in rows.items():
            with self.subTest(branch=name):
                self.assertTrue(row["proposed"], row["keep_reasons"])
                self.assertTrue(row["backup_written"])
                refs.add(row["backup_ref"])
        self.assertEqual(len(refs), 2,
                         f"two branches share one backup ref: {refs}")
        for name, row in rows.items():
            with self.subTest(branch=name):
                self.assertEqual(
                    self.out(self.root, "rev-parse", "--verify",
                             row["backup_ref"] + "^{commit}"),
                    self.tips[name])

    def test_both_tips_survive_the_script_a_prune_and_a_gc(self) -> None:
        # The end-to-end loss chain, run: delete the branches through the
        # emitted script, drop the remote heads the way GitHub does, prune the
        # tracking refs, expire every reflog, collect. Both tips must still
        # resolve, from their own backup refs.
        self.build(*self.COLLIDING)
        plan, script_path = self.plan()
        result = subprocess.run(["sh", str(script_path)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, check=False,
                                env=dict(os.environ))
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        for name in self.COLLIDING:
            self.git(self.root, "push", "-q", "origin", f":{name}")
        self.git(self.root, "fetch", "-q", "--prune", "origin")
        self.git(self.root, "reflog", "expire", "--expire=now",
                 "--expire-unreachable=now", "--all")
        self.git(self.root, "gc", "--prune=now", "--quiet")
        for name, tip in self.tips.items():
            with self.subTest(branch=name):
                self.assertEqual(
                    self.git(self.root, "cat-file", "-e", tip,
                             check=False).returncode, 0,
                    f"the tip of {name} is unrecoverable")

    def test_the_emitted_script_writes_two_distinct_refs(self) -> None:
        self.build(*self.COLLIDING)
        _, script_path = self.plan()
        script = script_path.read_text(encoding="utf-8")
        marker = "git update-ref -m 'pre-delete backup' "
        written = [line.split(marker, 1)[1].split()[0]
                   for line in script.splitlines() if marker in line]
        self.assertEqual(len(written), 2, written)
        self.assertEqual(len(written), len(set(written)),
                         f"the script writes one ref twice: {written}")


class PinIsCompareAndSwapTests(F.GitTestCase):
    """``_pin`` may never write over a backup ref another item is holding."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.scratch / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)],
                       check=True, env=dict(os.environ))
        F.write(self.repo / "a.txt", "a\n")
        self.first = self.commit(self.repo, "first")
        F.write(self.repo / "b.txt", "b\n")
        self.second = self.commit(self.repo, "second")

    def test_a_first_pin_is_written_and_verified(self) -> None:
        self.assertTrue(cleanup._pin(self.repo, "refs/agent-trash/t/x",
                                     self.first, "RUN"))
        self.assertEqual(
            self.out(self.repo, "rev-parse", "refs/agent-trash/t/x"), self.first)

    def test_pinning_the_same_commit_again_is_idempotent(self) -> None:
        # `--execute` writes the ref, and then the script the owner runs writes
        # it again. Refusing on "already exists" would turn every second run
        # into a wall of refusals.
        cleanup._pin(self.repo, "refs/agent-trash/t/x", self.first, "RUN")
        self.assertTrue(cleanup._pin(self.repo, "refs/agent-trash/t/x",
                                     self.first, "RUN"))

    def test_a_different_commit_is_REFUSED_not_written_over(self) -> None:
        cleanup._pin(self.repo, "refs/agent-trash/t/x", self.first, "RUN")
        self.assertFalse(cleanup._pin(self.repo, "refs/agent-trash/t/x",
                                      self.second, "RUN"),
                         "a colliding pin reported success")
        self.assertEqual(
            self.out(self.repo, "rev-parse", "refs/agent-trash/t/x"), self.first,
            "the first item's backup was overwritten")


# ── an unanswerable probe is not a clean tree ────────────────────────────────


class UnreadableStatusScenario(MainWorktreeScenario):
    def corrupt_index_of(self, worktree: Path) -> None:
        """The state a killed agent session leaves behind."""
        admin = Path(self.out(worktree, "rev-parse", "--absolute-git-dir"))
        (admin / "index").write_bytes(b"GARBAGE")
        self.assertNotEqual(
            self.git(worktree, "status", "--porcelain", check=False).returncode, 0,
            "the fixture must make `git status` actually fail")


class WorktreeStatusFailsClosedTests(UnreadableStatusScenario):
    def test_a_worktree_whose_status_fails_is_kept_not_retired(self) -> None:
        self.build_scenario(root_on="main")
        F.write(self.retirable / "uncommitted.txt", "work with no git recovery\n")
        self.corrupt_index_of(self.retirable)

        _, plan, script = self.plan_from(self.root)
        row = self.worktree_row(plan, self.retirable)
        self.assertEqual(row["action"], "keep", row)
        self.assertTrue(any(cleanup.KEEP_STATUS_UNREADABLE in reason
                            for reason in row["keep_reasons"]),
                        row["keep_reasons"])
        self.assertIsNotNone(row["status_error"],
                             "the plan must carry what the dashboard carries")
        self.assertNotIn(self.retirable,
                         [source for source, _ in self.emitted_moves(script)])

    def test_the_untracked_file_it_was_protecting_is_still_there(self) -> None:
        self.build_scenario(root_on="main")
        precious = self.retirable / "uncommitted.txt"
        F.write(precious, "work with no git recovery\n")
        self.corrupt_index_of(self.retirable)
        self.plan_from(self.root)
        self.assertTrue(precious.is_file())


# ── a plan is not a promise about the world at run time ──────────────────────
#
# `git branch -d` re-checks its own preconditions when it RUNS — raced with new
# unmerged commits it refused, exit 1, branch intact. `mv` has no opinion.
# Measured: a worktree that was clean and unlocked at plan time, then locked by
# a live agent and given an untracked file, was moved anyway; `git worktree
# prune` then declined the LOCKED registration, leaving the branch permanently
# wedged while the summary said "every item in this plan completed", exit 0.


class PostPlanMutationTests(MainWorktreeScenario):
    def run_script(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["sh", str(path)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, check=False,
                              env=dict(os.environ))

    def assert_planned_to_move(self, script: str) -> None:
        self.assertIn(self.retirable.resolve(),
                      [s.resolve() for s, _ in self.emitted_moves(script)],
                      "the plan must have proposed this move, or the race is "
                      "not being tested at all")

    def test_a_worktree_locked_after_the_plan_is_not_moved(self) -> None:
        self.build_scenario(root_on="main")
        _, _, script = self.plan_from(self.root)
        self.assert_planned_to_move(script)

        F.write(self.retirable / "URGENT.txt", "LIVE UNCOMMITTED WORK\n")
        self.git(self.root, "worktree", "lock", "--reason",
                 "claude agent agent-99 (pid 1234)", str(self.retirable))

        result = self.run_script(self.latest_script_path())
        self.assertEqual(result.returncode, 1,
                         "a refusal must never be reported as success")
        self.assertIn("REFUSED", result.stdout + result.stderr)
        self.assertTrue(self.retirable.is_dir(),
                        "a locked, dirty worktree was moved out from under a "
                        "live session")
        self.assertTrue((self.retirable / "URGENT.txt").is_file())
        # And the registration is not wedged: it still points at a directory
        # that exists, which is the second half of the measured damage.
        listed = self.out(self.root, "worktree", "list", "--porcelain")
        self.assertIn(str(self.retirable), listed)
        self.assertNotIn("prunable", listed)

    def test_a_worktree_dirtied_after_the_plan_is_not_moved(self) -> None:
        self.build_scenario(root_on="main")
        _, _, script = self.plan_from(self.root)
        self.assert_planned_to_move(script)
        F.write(self.retirable / "late.txt", "arrived after the plan\n")

        result = self.run_script(self.latest_script_path())
        self.assertEqual(result.returncode, 1)
        self.assertTrue((self.retirable / "late.txt").is_file())

    def test_a_worktree_whose_status_breaks_after_the_plan_is_not_moved(self) -> None:
        # Unreadable is refused exactly like dirty, at run time as at plan time.
        self.build_scenario(root_on="main")
        _, _, script = self.plan_from(self.root)
        self.assert_planned_to_move(script)
        admin = Path(self.out(self.retirable, "rev-parse", "--absolute-git-dir"))
        (admin / "index").write_bytes(b"GARBAGE")

        result = self.run_script(self.latest_script_path())
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.retirable.is_dir())

    def test_an_untouched_worktree_in_the_same_run_still_moves(self) -> None:
        # The re-check must not become a reason nothing ever happens: one item
        # refusing is a finding about THAT item.
        self.build_scenario(root_on="main")
        other = self.scratch / "linked" / "second"
        self.git(self.root, "worktree", "add", "-q", "-b", "second-landed",
                 str(other), "main")
        _, _, script = self.plan_from(self.root)
        self.git(self.root, "worktree", "lock", "--reason", "held",
                 str(self.retirable))

        result = self.run_script(self.latest_script_path())
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.retirable.is_dir(), "the locked one was moved")
        self.assertFalse(other.is_dir(), "the untouched one was not moved")


# ── "no branch" is not "no evidence" ─────────────────────────────────────────
#
# Every Claude Code harness worktree is detached BY CONSTRUCTION, so an
# unconditional `detached HEAD — no branch to judge it by` keep fired on 100% of
# them, forever: `--include-harness-worktrees` waived the harness rule and
# landed on this one, which no flag could waive. The polarity was backwards —
# git refuses to delete a branch a worktree has checked out, so a worktree
# sitting detached at a commit the base already contains is the state that makes
# cleanup POSSIBLE.
#
# THE COUNTER-EVIDENCE THAT SHAPES THE RULE (claude-code#74719, a real data-loss
# report): a detached-HEAD worktree holding an UNPUSHED commit was reaped on age
# alone. Age is not consulted here at all, and containment must be proven
# positively against the FETCHED base before anything is proposed.


class DetachedWorktreeScenario(MainWorktreeScenario):
    def add_detached(self, name: str, at: str) -> Path:
        path = self.scratch / "linked" / name
        self.git(self.root, "worktree", "add", "-q", "--detach", str(path), at)
        return path


class DetachedWorktreeEvidenceTests(DetachedWorktreeScenario):
    def test_detached_at_a_commit_the_base_contains_is_proposed(self) -> None:
        self.build_scenario(root_on="main")
        detached = self.add_detached("agent-detached", "refs/remotes/origin/main")

        _, plan, script = self.plan_from(self.root)
        row = self.worktree_row(plan, detached)
        self.assertEqual(row["action"], "retire", row["keep_reasons"])
        self.assertTrue(row["detached"])
        self.assertTrue(any("already contains" in note for note in row["notes"]),
                        row["notes"])
        self.assertIn(detached.resolve(),
                      [s.resolve() for s, _ in self.emitted_moves(script)])

    def test_detached_holding_an_unpushed_commit_is_KEPT(self) -> None:
        # THE DATA-LOSS CASE. This is the one that must never regress: the
        # worktree is clean, unlocked and idle, and every signal except
        # containment says "finished".
        self.build_scenario(root_on="main")
        detached = self.add_detached("agent-unpushed", "refs/remotes/origin/main")
        F.write(detached / "unpushed.txt", "work that exists nowhere else\n")
        self.git(detached, "add", "-A")
        self.git(detached, "commit", "-q", "-m", "unpushed experiment")
        head = self.out(detached, "rev-parse", "HEAD")
        self.assertEqual(self.out(detached, "status", "--porcelain"), "",
                         "the worktree must be CLEAN, or this tests the dirty "
                         "rule instead of the containment rule")

        _, plan, script = self.plan_from(self.root)
        row = self.worktree_row(plan, detached)
        self.assertEqual(row["action"], "keep", row)
        self.assertIn(cleanup.KEEP_DETACHED_UNCONTAINED, row["keep_reasons"])
        self.assertNotIn(detached.resolve(),
                         [s.resolve() for s, _ in self.emitted_moves(script)])
        # Nothing anywhere in this run may reach that commit's directory.
        self.assertTrue((detached / "unpushed.txt").is_file())
        self.assertEqual(self.out(detached, "rev-parse", "HEAD"), head)

    def test_the_harness_flag_does_not_waive_the_containment_rule(self) -> None:
        self.build_scenario(root_on="main")
        harness = self.root / ".claude" / "worktrees" / "agent-1"
        harness.parent.mkdir(parents=True, exist_ok=True)
        self.git(self.root, "worktree", "add", "-q", "--detach", str(harness),
                 "refs/remotes/origin/main")
        F.write(harness / "unpushed.txt", "work that exists nowhere else\n")
        self.git(harness, "add", "-A")
        self.git(harness, "commit", "-q", "-m", "unpushed experiment")

        _, plan, _ = self.plan_from(self.root, "--include-harness-worktrees")
        row = self.worktree_row(plan, harness)
        self.assertEqual(row["action"], "keep", row)
        self.assertIn(cleanup.KEEP_DETACHED_UNCONTAINED, row["keep_reasons"])

    def test_a_detached_harness_worktree_is_proposed_with_the_flag(self) -> None:
        # The owner's original complaint, in one assertion: with the flag, a
        # finished harness worktree is finally proposed rather than kept
        # forever by a rule no flag could reach.
        self.build_scenario(root_on="main")
        harness = self.root / ".claude" / "worktrees" / "agent-1"
        harness.parent.mkdir(parents=True, exist_ok=True)
        self.git(self.root, "worktree", "add", "-q", "--detach", str(harness),
                 "refs/remotes/origin/main")

        _, kept, _ = self.plan_from(self.root)
        self.assertEqual(self.worktree_row(kept, harness)["action"], "keep",
                         "the harness rule itself must still hold by default")
        _, plan, _ = self.plan_from(self.root, "--include-harness-worktrees")
        self.assertEqual(self.worktree_row(plan, harness)["action"], "retire",
                         self.worktree_row(plan, harness)["keep_reasons"])

    def test_a_dirty_detached_worktree_is_kept(self) -> None:
        self.build_scenario(root_on="main")
        detached = self.add_detached("agent-dirty", "refs/remotes/origin/main")
        F.write(detached / "scratch.md", "untracked, no git recovery story\n")
        _, plan, _ = self.plan_from(self.root)
        row = self.worktree_row(plan, detached)
        self.assertEqual(row["action"], "keep", row)
        self.assertTrue(any(cleanup.KEEP_DIRTY in reason
                            for reason in row["keep_reasons"]),
                        row["keep_reasons"])

    def test_a_locked_detached_worktree_is_kept(self) -> None:
        self.build_scenario(root_on="main")
        detached = self.add_detached("agent-locked", "refs/remotes/origin/main")
        self.git(self.root, "worktree", "lock", "--reason", "a live session",
                 str(detached))
        _, plan, _ = self.plan_from(self.root)
        row = self.worktree_row(plan, detached)
        self.assertEqual(row["action"], "keep", row)
        self.assertIn(cleanup.KEEP_LOCKED, row["keep_reasons"])

    def test_a_stale_run_never_proposes_a_detached_worktree(self) -> None:
        # Containment is evidence only when it was judged against a FETCHED
        # base, so without --fetch the old refusal stands.
        self.build_scenario(root_on="main")
        detached = self.add_detached("agent-detached", "refs/remotes/origin/main")
        buffer = io.StringIO()
        cleanup.main(["--repo-root", str(self.root)], out=buffer)
        produced = sorted((self.root / "local" / "workspace").glob("cleanup-*.json"))
        plan = json.loads(produced[-1].read_text(encoding="utf-8"))
        row = self.worktree_row(plan, detached)
        self.assertEqual(row["action"], "keep", row)
        self.assertTrue(any("--fetch" in reason for reason in row["keep_reasons"]),
                        row["keep_reasons"])


# ── a conflict is an answer, and the answer is "not contained" ───────────────
#
# `git merge-tree --write-tree` exits 1 for a CONFLICTING merge and still prints
# a tree. For every conflict class git resolves by keeping OUR side verbatim —
# a file git auto-detects as binary (any NUL byte), a path carrying `-merge` in
# `.gitattributes`, a submodule pointer — that printed tree IS the base tree, so
# "result == base tree" reads CONTAINED for a branch whose content exists
# nowhere in the base. This repository tracks 22 files with NUL bytes.


class ConflictIsNotContainmentScenario(F.GitTestCase):
    def build(self) -> None:
        self.root = self.scratch / "toolkit"
        self.root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)],
                       check=True, env=dict(os.environ))
        F.add_toolkit_markers(self.root)
        F.write(self.root / ".gitignore", "local/\n")
        F.write(self.root / "seed.txt", "seed\n")
        self.commit(self.root, "base commit")
        F.add_origin(self, self.root)

    def plan(self) -> dict:
        buffer = io.StringIO()
        cleanup.main(["--repo-root", str(self.root), "--fetch"], out=buffer)
        produced = sorted((self.root / "local" / "workspace").glob("cleanup-*.json"))
        return json.loads(produced[-1].read_text(encoding="utf-8"))

    def row(self, plan: dict, name: str) -> dict:
        rows = {r["name"]: r for r in plan["branches"]}
        self.assertIn(name, rows)
        return rows[name]


class BinaryAndSubmoduleAreNotContainedTests(ConflictIsNotContainmentScenario):
    def test_a_conflicting_binary_file_is_not_proposed(self) -> None:
        self.build()
        (self.root / "blob.bin").write_bytes(b"\x00base payload\x00")
        self.commit(self.root, "base: add a binary file")
        self.git(self.root, "push", "-q", "origin", "main")

        self.git(self.root, "switch", "-q", "-c", "binwork", "main")
        (self.root / "blob.bin").write_bytes(b"\x00WORK THAT EXISTS NOWHERE ELSE\x00")
        self.commit(self.root, "binwork: regenerate the binary")
        self.git(self.root, "push", "-q", "-u", "origin", "binwork")
        self.git(self.root, "switch", "-q", "main")
        (self.root / "blob.bin").write_bytes(b"\x00main moved on\x00")
        self.commit(self.root, "main: regenerate it differently")
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")

        contained = cleanup.Containment(self.root, "refs/remotes/origin/main")
        try:
            self.assertIs(contained.contains("refs/heads/binwork"), False,
                          "a merge-tree CONFLICT read as containment")
        finally:
            contained.close()
        row = self.row(self.plan(), "binwork")
        self.assertFalse(row["proposed"],
                         "proposed a branch whose content is nowhere in the base")

    def test_a_submodule_pointer_the_base_lacks_is_not_proposed(self) -> None:
        self.build()
        inner = self.scratch / "inner.git"
        subprocess.run(["git", "init", "-q", "-b", "main", str(inner)],
                       check=True, env=dict(os.environ))
        F.write(inner / "one.txt", "one\n")
        self.commit(inner, "inner: one")
        self.git(self.root, "-c", "protocol.file.allow=always", "submodule",
                 "add", "-q", str(inner), "sub")
        self.commit(self.root, "base: add the submodule")
        self.git(self.root, "push", "-q", "origin", "main")

        base = self.out(inner, "rev-parse", "HEAD")
        self.git(inner, "switch", "-q", "-c", "side-a", base)
        F.write(inner / "a.txt", "a\n")
        side_a = self.commit(inner, "inner: side a")
        self.git(inner, "switch", "-q", "-c", "side-b", base)
        F.write(inner / "b.txt", "b\n")
        side_b = self.commit(inner, "inner: side b")
        self.assertNotEqual(
            self.git(inner, "merge-base", "--is-ancestor", side_a, side_b,
                     check=False).returncode, 0,
            "the two submodule pointers must DIVERGE — git fast-forwards a "
            "pointer that is an ancestor of the other side's, and a linear "
            "advance is genuinely contained")

        self.git(self.root, "switch", "-q", "-c", "subwork", "main")
        self.git(self.root / "sub", "fetch", "-q", "origin")
        self.git(self.root / "sub", "checkout", "-q", side_a)
        self.commit(self.root, "subwork: advance the submodule")
        self.git(self.root, "push", "-q", "-u", "origin", "subwork")
        self.git(self.root, "switch", "-q", "main")
        self.git(self.root / "sub", "fetch", "-q", "origin")
        self.git(self.root / "sub", "checkout", "-q", side_b)
        self.commit(self.root, "main: advance the submodule elsewhere")
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")

        contained = cleanup.Containment(self.root, "refs/remotes/origin/main")
        try:
            self.assertIs(contained.contains("refs/heads/subwork"), False)
        finally:
            contained.close()
        row = self.row(self.plan(), "subwork")
        self.assertFalse(row["proposed"], row)


class WhitespaceIsNotContainmentTests(F.SharedShapesTestCase):
    def test_an_indentation_only_variant_never_reads_as_contained(self) -> None:
        # `git patch-id` calls an 8-space and a 2-space Python body IDENTICAL.
        # In a tree where indentation is semantic that is a data-loss answer, so
        # no patch-id probe may sit anywhere near this decision.
        contained = cleanup.Containment(self.root, "refs/heads/main")
        try:
            self.assertIs(contained.contains("refs/heads/ws-variant"), False)
        finally:
            contained.close()


# ── the verbs this tool may never use, wherever they could appear ────────────


class ForbiddenVerbAuditTests(MainWorktreeScenario):
    """No prohibited verb in the SOURCE, the INTERFACE or any EMITTED script.

    ``git worktree remove``, ``git branch -D`` and ``--force`` are prohibited by
    ``docs/handbook/post-merge-cutover.md``, and the prohibition is worth
    exactly as much as the test that reads every path they could appear on.
    ``git update-ref -d <ref> <oldvalue>`` is NOT one of them and is deliberately
    distinguished here: it is a compare-and-swap that git refuses unless the ref
    still holds the exact value the plan proved, which is a CHECK rather than the
    absence of one.
    """

    FORBIDDEN = ("git branch -D", "branch -D", "--force", "worktree remove",
                 "git clean", "rm -rf", "rm -r ", "reset --hard", "-f -f",
                 "update-ref -d refs/remotes")

    def executable_lines(self, script: str) -> str:
        return "\n".join(line for line in script.splitlines()
                         if line.strip() and not line.strip().startswith("#"))

    def test_no_emitted_script_carries_a_prohibited_verb(self) -> None:
        # Every shape at once, so this is not a test about one lucky fixture.
        self.build_scenario(root_on="main")
        harness = self.root / ".claude" / "worktrees" / "agent-1"
        harness.parent.mkdir(parents=True, exist_ok=True)
        self.git(self.root, "worktree", "add", "-q", "--detach", str(harness),
                 "refs/remotes/origin/main")
        self.git(self.root, "branch", "--set-upstream-to=origin/codex/landed",
                 "codex/landed")
        self.git(self.root, "branch", "-f", "codex/landed", "main")   # forces a swap
        gone = self.scratch / "linked" / "gone"
        self.git(self.root, "worktree", "add", "-q", "-b", "gone-work",
                 str(gone), "main")
        shutil.rmtree(gone)

        for argv in ((), ("--include-harness-worktrees",)):
            with self.subTest(argv=argv):
                _, _, script = self.plan_from(self.root, *argv)
                runnable = self.executable_lines(script)
                for verb in self.FORBIDDEN:
                    self.assertNotIn(verb, runnable,
                                     f"the emitted script runs `{verb}`")

    def test_the_source_carries_no_prohibited_verb_either(self) -> None:
        source = (_WORKSPACE_DIR / "cleanup.py").read_text(encoding="utf-8")
        for verb in ("worktree\", \"remove", "branch\", \"-D", '"--force"',
                     '"-D"', '"-f"'):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, source)

    def test_the_swap_is_a_check_and_names_its_expected_value(self) -> None:
        # A compare-and-swap with no old value would be strictly more forcing
        # than the flag that is banned. It is only admissible BECAUSE it carries
        # one, so the emitter is held to that shape here.
        self.build_scenario(root_on="main")
        # `-d` judges against the branch's own upstream when one resolves, so a
        # branch ahead of a LIVE `origin/<branch>` is the shape it refuses.
        self.git(self.root, "branch", "--set-upstream-to=origin/codex/landed",
                 "codex/landed")
        self.git(self.root, "branch", "-f", "codex/landed", "main")
        _, plan, script = self.plan_from(self.root)
        row = {r["name"]: r for r in plan["branches"]}["codex/landed"]
        self.assertEqual(row["delete_method"], cleanup.DELETE_CAS,
                         row["keep_reasons"] + row["notes"])
        for line in self.executable_lines(script).splitlines():
            if "git update-ref -d" in line:
                parts = shlex.split(line.strip().removesuffix("; then"))
                while parts and parts[0] in ("if", "elif", "!"):
                    parts.pop(0)
                self.assertEqual(len(parts), 5,
                                 f"a swap with no expected value: {line}")
                self.assertEqual(parts[4], row["tip"])
                break
        else:
            self.fail("no compare-and-swap deletion was emitted")


# ── remote branches: visible at last, and still untouched ────────────────────
#
# `classify` used to `continue` past every ref whose scope is "R", so a
# repository with seventeen merged branches sitting on its remote produced a
# plan mentioning none of them — a tool whose whole purpose is "stop things
# accumulating", silent about the accumulation. They are listed now.
#
# They are still not deleted, and the reason is this repository's own record:
# `skills/github-workflow/reference.md` documents incident #136, where deleting
# a base branch CLOSED the pull request stacked above it one second later. The
# precondition that would make a deletion safe — no open PR names it as head or
# as base — needs a GitHub API call, and this planner's single network call
# (`git fetch --prune origin`) is a property worth keeping. So: listed,
# explained, and emitted nowhere.


class RemoteBranchScenario(F.GitTestCase):
    def build(self, *names: str) -> None:
        self.root = self.scratch / "toolkit"
        self.root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)],
                       check=True, env=dict(os.environ))
        F.add_toolkit_markers(self.root)
        F.write(self.root / ".gitignore", "local/\n")
        F.write(self.root / "seed.txt", "seed\n")
        self.commit(self.root, "base commit")
        F.add_origin(self, self.root)
        for index, name in enumerate(names):
            self.git(self.root, "switch", "-q", "-c", name, "main")
            F.write(self.root / f"work-{index}.txt", f"work on {name}\n")
            self.commit(self.root, f"{name}: the work")
            self.git(self.root, "push", "-q", "origin", name)
            self.git(self.root, "switch", "-q", "main")
            self.git(self.root, "merge", "-q", "--no-ff", name,
                     "-m", f"Merge {name}")
            # LOCAL branch deleted, remote head kept — a merged branch nobody
            # cleaned up on GitHub. That is the pile this section is about.
            self.git(self.root, "branch", "-d", name)
        self.git(self.root, "push", "-q", "origin", "main")
        self.git(self.root, "fetch", "-q", "--prune", "origin")

    def plan(self, *argv: str) -> tuple[dict, str, Path]:
        buffer = io.StringIO()
        cleanup.main(["--repo-root", str(self.root), *argv], out=buffer)
        produced = sorted((self.root / "local" / "workspace").glob("cleanup-*.json"))
        return (json.loads(produced[-1].read_text(encoding="utf-8")),
                buffer.getvalue(), produced[-1].with_suffix(".sh"))

    def rows(self, plan: dict) -> dict:
        return {r["name"]: r for r in plan["remote_branches"]["cached"]}


class RemoteBranchesAreListedNeverTouchedTests(RemoteBranchScenario):
    def test_a_merged_remote_branch_appears_in_the_plan_at_all(self) -> None:
        self.build("codex/one", "codex/two")
        plan, report, _ = self.plan("--fetch")
        rows = self.rows(plan)
        for name in ("origin/codex/one", "origin/codex/two"):
            with self.subTest(branch=name):
                self.assertIn(name, rows, "a merged remote branch is invisible")
                self.assertTrue(rows[name]["candidate"],
                                rows[name]["keep_reasons"])
        self.assertIn("REMOTE BRANCHES", report,
                      "the pile must be visible without any flag")

    def test_every_candidate_carries_its_unmet_preconditions(self) -> None:
        self.build("codex/one")
        plan, _, _ = self.plan("--fetch")
        row = self.rows(plan)["origin/codex/one"]
        self.assertFalse(row["emitted"])
        joined = " ".join(row["unmet_preconditions"])
        self.assertIn("#136", joined,
                      "the incident that decides this must be named on the row")
        self.assertIn("head OR as base", joined)
        self.assertIn(cleanup.REMOTE_DECISION, joined,
                      "the open owner decision must be reachable from the row")

    def test_nothing_about_a_remote_branch_reaches_the_emitted_script(self) -> None:
        self.build("codex/one", "codex/two")
        _, _, script_path = self.plan("--fetch")
        script = script_path.read_text(encoding="utf-8")
        runnable = "\n".join(line for line in script.splitlines()
                             if line.strip() and not line.strip().startswith("#"))
        for forbidden in ("git push", "--force-with-lease", "--delete",
                          ":refs/heads/", "refs/remotes/origin/codex"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, runnable)
        for name in ("codex/one", "codex/two"):
            self.assertNotIn(f"origin/{name}", runnable)

    def test_the_planner_still_makes_exactly_one_network_call(self) -> None:
        # The property the whole section rests on. `git` is shadowed by a
        # recorder on PATH, so every invocation the planner makes is captured —
        # no mocking of git's behaviour, just a record of what was asked.
        self.build("codex/one")
        bindir = self.scratch / "bin"
        bindir.mkdir()
        log = self.scratch / "git-calls.log"
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git, "git must be available to exercise the planner")
        shim = bindir / "git"
        shim.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> {shlex.quote(str(log))}\n'
            f'exec /usr/bin/env -u PATH_SHIM {shlex.quote(str(real_git))} "$@"\n',
            encoding="utf-8")
        shim.chmod(0o755)
        previous = os.environ["PATH"]
        os.environ["PATH"] = f"{bindir}:{previous}"
        self.addCleanup(os.environ.__setitem__, "PATH", previous)

        self.plan("--fetch", "--remote-branches")
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        self.assertTrue(calls, "the shim recorded nothing; the test proves nothing")
        reaching = [c for c in calls
                    if any(verb in c.split()
                           for verb in ("fetch", "push", "ls-remote", "clone",
                                        "pull"))]
        self.assertEqual(len(reaching), 1, f"expected one network call: {reaching}")
        self.assertIn("fetch", reaching[0])
        self.assertNotIn("push", " ".join(calls))

    def test_the_remote_default_pointer_is_never_a_candidate(self) -> None:
        # `refs/remotes/origin/HEAD` short-names to the bare REMOTE NAME
        # (`origin`), which no leaf-name test would ever catch — and it points
        # at the default branch rather than being a branch anybody works on.
        # Measured while writing this: `git fetch --prune` DELETES a plain ref
        # at that path and replaces it with a symref, so the stale run is the
        # one that can carry the plain shape end to end.
        self.build("codex/one")
        self.git(self.root, "update-ref", "--no-deref", "-d",
                 "refs/remotes/origin/HEAD", check=False)
        self.git(self.root, "update-ref", "--no-deref",
                 "refs/remotes/origin/HEAD",
                 self.out(self.root, "rev-parse", "refs/remotes/origin/main"))
        self.assertEqual(
            self.out(self.root, "for-each-ref", "--format=%(symref)",
                     "refs/remotes/origin/HEAD"), "",
            "the fixture must build the PLAIN shape, not the symref")

        plan, _, _ = self.plan()
        rows = self.rows(plan)
        self.assertIn("origin", rows, "the fixture no longer has origin/HEAD")
        self.assertFalse(rows["origin"]["candidate"], rows["origin"])
        self.assertIn(cleanup.REMOTE_KEEP_PROTECTED, rows["origin"]["keep_reasons"],
                      "the remote's default-branch pointer read as an ordinary "
                      "branch")

    def test_the_symbolic_default_pointer_is_never_a_candidate_either(self) -> None:
        self.build("codex/one")
        self.git(self.root, "remote", "set-head", "origin", "main")
        plan, _, _ = self.plan("--fetch")
        row = self.rows(plan).get("origin")
        if row is not None:      # the dashboard may drop symrefs before this
            self.assertFalse(row["candidate"], row)

    def test_an_unmerged_remote_branch_is_not_a_candidate(self) -> None:
        self.build("codex/one")
        self.git(self.root, "switch", "-q", "-c", "codex/open", "main")
        F.write(self.root / "open.txt", "work that never landed\n")
        self.commit(self.root, "codex/open: unique work")
        self.git(self.root, "push", "-q", "origin", "codex/open")
        self.git(self.root, "switch", "-q", "main")
        self.git(self.root, "branch", "-D", "codex/open")
        self.git(self.root, "fetch", "-q", "--prune", "origin")

        plan, _, _ = self.plan("--fetch")
        row = self.rows(plan)["origin/codex/open"]
        self.assertFalse(row["candidate"], row)
        self.assertIn(cleanup.REMOTE_KEEP_UNCONTAINED, row["keep_reasons"])

    def test_a_stale_run_calls_no_remote_branch_a_candidate(self) -> None:
        self.build("codex/one")
        plan, _, _ = self.plan()
        row = self.rows(plan)["origin/codex/one"]
        self.assertFalse(row["candidate"], row)
        self.assertIn(cleanup.REMOTE_KEEP_STALE, row["keep_reasons"])

    def test_the_listing_flag_only_changes_what_is_printed(self) -> None:
        self.build("codex/one", "codex/two")
        quiet_plan, quiet, _ = self.plan("--fetch")
        loud_plan, loud, _ = self.plan("--fetch", "--remote-branches")
        self.assertEqual(self.rows(quiet_plan).keys(), self.rows(loud_plan).keys(),
                         "the flag must not change the classification")
        self.assertNotIn("origin/codex/one", quiet)
        self.assertIn("origin/codex/one", loud)
        self.assertIn("--remote-branches", quiet,
                      "the summary must say how to see the list")


if __name__ == "__main__":
    import unittest

    unittest.main()
