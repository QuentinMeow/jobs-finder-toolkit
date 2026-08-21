"""The merge-shape matrix and the derived lifecycle fields.

THE INVARIANT THIS FILE EXISTS FOR: **no branch holding unique work is ever
reported merged.** Everything downstream — the cleanup planner, the gardener
report, an agent reading the dashboard — treats ``merged`` as permission to
stop caring about a branch, so one false ``merged`` is one lost afternoon of
somebody's work. The matrix below is every shape that has been observed to
produce one, including the two that defeat the obvious implementations:

* a SQUASH-MERGE, which ``git branch --merged`` and ``git cherry`` both miss;
* a WHITESPACE VARIANT, which ``git patch-id`` declares identical to the commit
  already in main although the two files differ in Python-significant
  indentation.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/workspace/tests
"""

from __future__ import annotations

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
import status  # noqa: E402


class MergeShapeMatrixTests(F.SharedShapesTestCase):
    """Every merge shape, against one repository, in one inspection."""

    def setUp(self) -> None:
        super().setUp()
        self.now = F.FIXED_EPOCH
        self.repo = status.inspect_repository("PUBLIC", self.root, now=self.now)
        self.by_name = {branch.name: branch for branch in self.repo.branches}

    # ── the data-loss invariant ─────────────────────────────────────────────
    def test_no_branch_holding_unique_work_is_ever_reported_merged(self) -> None:
        for name in self.facts["unique"]:
            with self.subTest(branch=name):
                branch = self.by_name[name]
                self.assertNotEqual(
                    branch.merged, "merged",
                    f"{name} holds content that exists nowhere else; reporting it "
                    f"merged authorises deleting unrecoverable work")
                self.assertNotEqual(branch.state, status.STATE_MERGED)

    def test_every_contained_branch_is_reported_merged(self) -> None:
        for name in self.facts["contained"]:
            with self.subTest(branch=name):
                self.assertEqual(self.by_name[name].merged, "merged")

    def test_squash_merge_is_caught_where_git_branch_merged_misses_it(self) -> None:
        listed = self.out(self.root, "branch", "--merged", "main")
        self.assertNotIn("squash-merge", listed,
                         "fixture no longer reproduces the squash-merge blind spot")
        self.assertIn("true-merge", listed)
        self.assertEqual(self.by_name["squash-merge"].merged, "merged")

    def test_whitespace_variant_defeats_patch_id_but_not_containment(self) -> None:
        # `git cherry` answers with `-` for a commit it believes is already
        # upstream. Here it is wrong: the two files differ by Python-significant
        # indentation, and patch-id normalises whitespace away.
        cherry = self.out(self.root, "cherry", "main", "ws-variant")
        self.assertTrue(cherry.startswith("-"),
                        f"fixture no longer reproduces the patch-id trap: {cherry!r}")
        self.assertEqual(self.by_name["ws-variant"].merged, "unmerged")
        branch_file = self.out(self.root, "show", "ws-variant:indent.py")
        main_file = self.out(self.root, "show", "main:indent.py")
        self.assertNotEqual(branch_file, main_file)

    def test_merged_then_reverted_and_empty_commit_read_merged_by_design(self) -> None:
        # Both are documented, deliberate answers rather than accidents: the
        # reverted branch's content is still reachable in main's history, and an
        # empty commit contributes no content at all.
        self.assertEqual(self.by_name["merged-then-revert"].merged, "merged")
        self.assertEqual(self.by_name["empty-commit"].merged, "merged")

    def test_partially_merged_branch_is_unmerged_on_its_second_commit(self) -> None:
        self.assertEqual(self.by_name["partially-merged"].merged, "unmerged")
        # Proof the fixture really is partial: main has the first file, not the second.
        self.assertEqual(self.out(self.root, "cat-file", "-t", "main:part1.txt"), "blob")
        missing = self.git(self.root, "cat-file", "-t", "main:part2.txt", check=False)
        self.assertNotEqual(missing.returncode, 0)

    # ── worktree shapes ─────────────────────────────────────────────────────
    def test_states_describe_every_worktree_shape(self) -> None:
        expected = {
            "open-work": status.STATE_STALE,          # unmerged, nobody on it
            "dirty-work": status.STATE_ACTIVE,        # edited seconds ago
            "locked-work": status.STATE_ACTIVE,       # old, but locked
            "untracked-work": status.STATE_MERGED,
            "prunable-work": status.STATE_WEDGED,
            "locked-gone-work": status.STATE_WEDGED,
        }
        for name, state in expected.items():
            with self.subTest(branch=name):
                self.assertEqual(self.by_name[name].state, state)

    def test_a_locked_worktree_reads_active_however_old_its_evidence_is(self) -> None:
        branch = self.by_name["locked-work"]
        self.assertTrue(branch.locked)
        self.assertGreater(branch.age_seconds, 30 * F.DAY,
                           "fixture should have back-dated this worktree")
        self.assertEqual(branch.state, status.STATE_ACTIVE)

    def test_locked_worktree_whose_directory_is_gone_is_wedged_not_prunable(self) -> None:
        # V-G: the lock suppresses git's own `prunable` annotation, so the entry
        # is invisible to every porcelain answer while it still owns the branch.
        porcelain = self.out(self.root, "worktree", "list", "--porcelain")
        record = [block for block in porcelain.split("\n\n")
                  if "locked-gone-work" in block]
        self.assertEqual(len(record), 1)
        self.assertNotIn("prunable", record[0])
        self.assertIn("locked", record[0])
        branch = self.by_name["locked-gone-work"]
        self.assertEqual(branch.state, status.STATE_WEDGED)
        self.assertIsNotNone(branch.wedged_at)

    def test_detached_worktree_has_no_branch_and_renders_as_detached(self) -> None:
        detached = [w for w in self.repo.worktrees
                    if w.path.name == self.facts["worktrees"]["detached"].name]
        self.assertEqual(len(detached), 1)
        self.assertTrue(detached[0].detached)
        self.assertIsNone(detached[0].branch_ref)
        rendered = status.render([self.repo], self.root, False, status.Palette(False))
        self.assertIn("(detached @", rendered)

    def test_untracked_only_worktree_counts_as_dirty(self) -> None:
        # Untracked files have NO git recovery story, so they must never read
        # "clean" — that is the difference between `mv` and an unrecoverable rm.
        worktree = [w for w in self.repo.worktrees
                    if w.path.name == self.facts["worktrees"]["untracked"].name][0]
        self.assertTrue(worktree.dirty)
        self.assertEqual(worktree.untracked, 1)
        self.assertEqual(worktree.staged, 0)

    # ── the probe writes nothing ────────────────────────────────────────────
    def test_the_merge_probe_leaves_the_object_store_and_fsck_clean(self) -> None:
        objects = self.root / ".git" / "objects"

        def snapshot() -> set[str]:
            return {str(p.relative_to(objects)) for p in objects.rglob("*") if p.is_file()}

        before = snapshot()
        status.inspect_repository("PUBLIC", self.root, now=self.now)
        self.assertEqual(snapshot(), before,
                         "merge-tree --write-tree escaped its object sandbox")
        fsck = self.git(self.root, "fsck", "--no-progress", check=False)
        self.assertEqual(fsck.returncode, 0, fsck.stderr)

    def test_probe_reports_unknown_rather_than_merged_for_an_unanswerable_ref(self) -> None:
        probe = status.open_merge_probe(self.root)
        self.addCleanup(probe.close)
        base_tree = status._base_tree(self.root, "refs/heads/main")
        verdict = status._merged_state(
            self.root, "refs/heads/no-such-branch", "refs/heads/main", probe, base_tree)
        self.assertEqual(verdict, "unknown")


class WedgeRecoveryTests(F.GitTestCase):
    """The one test here that MUTATES, so it gets its own repository."""

    def setUp(self) -> None:
        super().setUp()
        self.root = self.scratch / "toolkit"
        F.build_merge_shapes(self, self.root)

    def test_worktree_prune_unwedges_a_branch_git_switch_refused(self) -> None:
        refused = self.git(self.root, "switch", "prunable-work", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("already used by worktree", refused.stderr)

        self.git(self.root, "worktree", "prune")

        switched = self.git(self.root, "switch", "prunable-work", check=False)
        self.assertEqual(switched.returncode, 0, switched.stderr)
        self.git(self.root, "switch", "main")
        after = status.inspect_repository("PUBLIC", self.root, now=F.FIXED_EPOCH)
        state = {b.name: b.state for b in after.branches}["prunable-work"]
        self.assertNotEqual(state, status.STATE_WEDGED)


class DegradedProbeTests(F.SharedShapesTestCase):
    """An old Git must degrade LOUDLY, and only ever under-report `merged`."""

    def test_ancestor_only_probe_under_reports_but_never_over_reports(self) -> None:
        degraded = status.MergeProbe(mode=status.PROBE_ANCESTOR_ONLY,
                                     note=status.PROBE_DEGRADED_NOTE)
        verdicts = {
            name: status._merged_state(self.root, f"refs/heads/{name}",
                                       "refs/heads/main", degraded, None)
            for name in ("true-merge", "squash-merge", "ws-variant", "open-work")
        }
        self.assertEqual(verdicts["true-merge"], "merged")
        # The squash-merge reads UNMERGED here. That is the cost of degrading,
        # and it errs towards keeping a branch, never towards deleting one.
        self.assertEqual(verdicts["squash-merge"], "unmerged")
        self.assertEqual(verdicts["ws-variant"], "unmerged")
        self.assertEqual(verdicts["open-work"], "unmerged")

    def test_the_degraded_note_is_printed_rather_than_hidden(self) -> None:
        repo = status.inspect_repository("PUBLIC", self.root, now=F.FIXED_EPOCH)
        repo.merge_probe = status.PROBE_ANCESTOR_ONLY
        repo.merge_probe_note = status.PROBE_DEGRADED_NOTE
        rendered = status.render([repo], self.root, False, status.Palette(False))
        self.assertIn("DEGRADED merge probe", rendered)
        self.assertIn("MISSES squash-merges", rendered)

    def test_version_probe_reads_this_git(self) -> None:
        version = status.git_version(self.root)
        self.assertTrue(version, "git --version did not parse")
        self.assertGreaterEqual(version[0], 2)


class IntentTests(F.GitTestCase):
    """Component 1: git's own branch descriptions, and the fallback."""

    def setUp(self) -> None:
        super().setUp()
        self.root = self.scratch / "toolkit"
        F.build_merge_shapes(self, self.root)

    def _branches(self) -> dict[str, status.Branch]:
        repo = status.inspect_repository("PUBLIC", self.root, now=F.FIXED_EPOCH)
        return {branch.name: branch for branch in repo.branches}

    def test_a_description_beats_the_commit_fallback_and_carries_next(self) -> None:
        self.git(self.root, "config", "branch.open-work.description",
                 "rewrite the ranking filter\nnext: land the JSON schema change")
        branch = self._branches()["open-work"]
        self.assertEqual(branch.intent, "rewrite the ranking filter")
        self.assertEqual(branch.intent_source, status.INTENT_DESCRIPTION)
        self.assertEqual(branch.next_action, "land the JSON schema change")

    def test_without_a_description_intent_is_the_first_commit_subject(self) -> None:
        branch = self._branches()["open-work"]
        # The branch's FIRST commit, not its tip — what it was started for.
        self.assertEqual(branch.intent, "open-work: start the feature")
        self.assertEqual(branch.intent_source, status.INTENT_FIRST_COMMIT)
        self.assertEqual(branch.ref.subject, "open-work: keep going")

    def test_a_description_survives_gc_and_is_shared_across_worktrees(self) -> None:
        self.git(self.root, "config", "branch.dirty-work.description", "half-finished")
        self.git(self.root, "gc", "--prune=now", "--quiet")
        self.assertEqual(
            self.out(self.root, "config", "--get", "branch.dirty-work.description"),
            "half-finished")
        # Read from a LINKED worktree: .git/config is shared, so the description
        # is one fact for the whole checkout rather than per-directory state.
        linked = self.scratch / "worktrees" / "dirty"
        self.assertEqual(
            self.out(linked, "config", "--get", "branch.dirty-work.description"),
            "half-finished")
        self.assertEqual(self._branches()["dirty-work"].intent, "half-finished")

    def test_multi_line_descriptions_survive_the_null_separated_read(self) -> None:
        self.git(self.root, "config", "branch.open-work.description",
                 "first line\nsecond line\nnext: third")
        self.git(self.root, "config", "branch.dirty-work.description", "another branch")
        descriptions = status.branch_descriptions(self.root)
        self.assertEqual(descriptions["open-work"],
                         "first line\nsecond line\nnext: third")
        self.assertEqual(descriptions["dirty-work"], "another branch")

    def test_no_descriptions_at_all_is_not_an_error(self) -> None:
        self.assertEqual(status.branch_descriptions(self.root), {})


class AgeTests(F.SharedShapesTestCase):
    """Wall clock, and the laptop-sleep case a monotonic clock gets backwards."""

    def test_a_multi_day_sleep_moves_a_branch_out_of_active(self) -> None:
        # 63.7 h is the interval `time.monotonic()` was MEASURED to lose across
        # laptop sleep on this machine. An age computed from it would still read
        # `active` on the far side; wall clock does not.
        slept = 229_413
        fresh = status.inspect_repository("PUBLIC", self.root, now=F.FIXED_EPOCH)
        after = status.inspect_repository("PUBLIC", self.root,
                                          now=F.FIXED_EPOCH + slept)
        before_state = {b.name: b for b in fresh.branches}["dirty-work"]
        after_state = {b.name: b for b in after.branches}["dirty-work"]
        self.assertEqual(before_state.state, status.STATE_ACTIVE)
        self.assertEqual(after_state.state, status.STATE_STALE)
        # The age has to have grown by roughly the whole sleep. The tolerance is
        # the fixture's own build time: its files are stamped by the real clock
        # while `now` is the epoch captured when the module loaded, and the
        # clamp at zero absorbs that gap on the near side.
        self.assertGreater(after_state.age_seconds, status.IDLE_MAX_SECONDS)
        self.assertGreaterEqual(after_state.age_seconds - before_state.age_seconds,
                                slept - 600)

    def test_the_age_bands_are_wall_clock_arithmetic(self) -> None:
        base = F.FIXED_EPOCH
        self.assertEqual(status._age_seconds(base - 60, base), 60)
        self.assertEqual(status._age_seconds(None, base), None)

    def test_a_clock_that_steps_backwards_never_produces_a_negative_age(self) -> None:
        # Wall clock steps backwards on an NTP correction and on resume from
        # suspend. A negative age would render as a commit from the future.
        self.assertEqual(status._age_seconds(F.FIXED_EPOCH + 5000, F.FIXED_EPOCH), 0)

    def test_evidence_prefers_the_newer_of_tip_date_and_worktree_files(self) -> None:
        branches = {b.name: b for b in
                    status.inspect_repository("PUBLIC", self.root,
                                              now=F.FIXED_EPOCH).branches}
        # dirty-work was committed two days ago and edited a moment ago.
        self.assertEqual(branches["dirty-work"].evidence_source, "worktree-mtime")
        # open-work has no worktree at all, so its tip is the only evidence.
        self.assertEqual(branches["open-work"].evidence_source, "tip-commit")

    def test_state_rule_is_a_pure_function_of_its_evidence(self) -> None:
        call = status.lifecycle_state
        common = dict(merged="unmerged", upstream_missing=False, wedged=False,
                      locked=False)
        self.assertEqual(call(age_seconds=5, **common), status.STATE_ACTIVE)
        self.assertEqual(call(age_seconds=3600, **common), status.STATE_IDLE)
        self.assertEqual(call(age_seconds=5 * F.DAY, **common), status.STATE_STALE)
        self.assertEqual(call(**{**common, "merged": "merged"}, age_seconds=5),
                         status.STATE_MERGED)
        self.assertEqual(call(**{**common, "upstream_missing": True}, age_seconds=5),
                         status.STATE_ORPHANED)
        # wedged outranks everything: it is the one state that BLOCKS work.
        self.assertEqual(
            call(merged="merged", upstream_missing=True, wedged=True, locked=True,
                 age_seconds=5),
            status.STATE_WEDGED)


class JsonOutputTests(F.SharedShapesTestCase):
    """``--json`` is the machine contract; its shape is pinned here."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = status.inspect_repository("PUBLIC", self.root, now=F.FIXED_EPOCH)
        self.payload = json.loads(json.dumps(
            status.workspace_json([self.repo], now=F.FIXED_EPOCH)))

    def test_top_level_shape(self) -> None:
        self.assertEqual(self.payload["schema"], "workspace-status/v1")
        self.assertEqual(self.payload["generated_epoch"], F.FIXED_EPOCH)
        self.assertTrue(self.payload["generated_at"].endswith("Z"))
        self.assertFalse(self.payload["fetched"],
                         "the dashboard never fetches; the JSON must say so")
        self.assertEqual(set(self.payload["states"]), set(status.STATES))
        self.assertEqual(self.payload["thresholds"]["active_max_seconds"],
                         status.ACTIVE_MAX_SECONDS)

    def test_every_branch_row_carries_the_lifecycle_fields(self) -> None:
        rows = {row["name"]: row for row in self.payload["repositories"][0]["branches"]}
        row = rows["open-work"]
        for key in ("state", "intent", "intent_source", "age_seconds",
                    "evidence_epoch", "evidence_source", "merged", "sync",
                    "next_action", "pull_request", "wedged_at", "worktree_path"):
            self.assertIn(key, row)
        self.assertEqual(row["state"], status.STATE_STALE)
        self.assertIsNone(row["pull_request"])
        self.assertEqual(rows["locked-gone-work"]["state"], status.STATE_WEDGED)
        self.assertIsNotNone(rows["locked-gone-work"]["wedged_at"])

    def test_worktree_rows_carry_the_gone_flag_and_change_counts(self) -> None:
        rows = {Path(row["path"]).name: row
                for row in self.payload["repositories"][0]["worktrees"]}
        self.assertTrue(rows["prunable"]["gone"])
        self.assertTrue(rows["locked-gone"]["gone"])
        self.assertTrue(rows["locked-gone"]["directory_missing"])
        self.assertFalse(rows["dirty"]["gone"])
        self.assertEqual(rows["untracked"]["untracked"], 1)

    def test_the_command_emits_valid_json_and_exits_zero(self) -> None:
        # The exit code and the stream are the contract a caller sees, so this
        # one goes through the process boundary rather than the function.
        script = _WORKSPACE_DIR / "status.py"
        result = subprocess.run(
            [sys.executable, str(script), "--json"],
            cwd=str(status.REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "workspace-status/v1")


class PullRequestTests(F.SharedShapesTestCase):
    """``--pr`` is the one network answer here, so it must fail LOUDLY."""

    def test_an_unanswerable_question_returns_a_reason_never_an_empty_answer(self) -> None:
        # The fixture's "origin" is a local directory, so `gh` cannot answer for
        # it — and neither can a machine with no `gh` at all. Both must produce a
        # REASON: "no pull request" and "nobody could tell us" must not look
        # alike, or a branch with an open PR reads as abandoned.
        index, error = status.pull_request_index(self.root, timeout=15.0)
        self.assertEqual(index, {})
        self.assertIsNotNone(error)
        self.assertTrue(error.strip())

    def test_the_reason_is_printed_rather_than_swallowed(self) -> None:
        repo = status.inspect_repository("PUBLIC", self.root, now=F.FIXED_EPOCH)
        repo.pr_requested = True
        repo.pr_error = "gh is not installed"
        rendered = status.render([repo], self.root, False, status.Palette(False))
        self.assertIn("pull-request state unavailable: gh is not installed", rendered)

    def test_a_known_pr_state_lands_on_its_branch_row(self) -> None:
        repo = status.inspect_repository("PUBLIC", self.root, now=F.FIXED_EPOCH)
        # No network: the index is the seam, and this is what the gh call fills.
        branches, *_ = status._branches(self.root, repo.worktrees, None,
                                        {"open-work": "#7 OPEN"}, F.FIXED_EPOCH)
        rows = {branch.name: branch for branch in branches}
        self.assertEqual(rows["open-work"].pr, "#7 OPEN")
        self.assertIsNone(rows["true-merge"].pr)


class RenderTests(F.SharedShapesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo = status.inspect_repository("PUBLIC", self.root, now=F.FIXED_EPOCH)

    def test_the_table_shows_state_age_and_intent(self) -> None:
        rendered = status.render([self.repo], self.root, False, status.Palette(False))
        self.assertIn("open-work", rendered)
        self.assertIn(status.STATE_WEDGED, rendered)
        self.assertIn("open-work: start the feature", rendered)
        self.assertIn("State (derived, never stored)", rendered)

    def test_stale_filter_keeps_only_untouched_rows(self) -> None:
        rendered = status.render([self.repo], self.root, False, status.Palette(False),
                                 stale_days=1)
        self.assertIn("untouched for 1+ days", rendered)
        # dirty-work was edited a moment ago; open-work's tip is three days old.
        # Only the BRANCHES block is filtered — the worktree inventory above it
        # still lists every registration, stale or not.
        branch_block = rendered.split("BRANCHES", 1)[1]
        self.assertIn("open-work", branch_block)
        self.assertNotIn("dirty-work", branch_block)

    def test_verbose_explains_the_wedge_and_the_evidence(self) -> None:
        rendered = status.render([self.repo], self.root, True, status.Palette(False))
        self.assertIn("WEDGED", rendered)
        self.assertIn("git worktree prune", rendered)
        self.assertIn("intent from", rendered)
        self.assertIn("age from", rendered)


if __name__ == "__main__":
    import unittest

    unittest.main()
