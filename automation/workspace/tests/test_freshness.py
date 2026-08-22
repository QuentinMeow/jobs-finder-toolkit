"""What ``merged`` is measured AGAINST, and how much of the table is still true.

TWO DEFECTS, ONE THEME: the dashboard knew the truth and did not say it.

* THE BASE ROTS. ``merged`` used to be judged against ``refs/heads/main``
  unconditionally. Local main is only as fresh as the last `git pull`; measured
  on this workspace, every branch that landed while the checkout sat 88 commits
  behind graded ``unmerged`` forever, so nothing was ever offered for
  retirement. ``refs/remotes/origin/main`` is what local main is going to
  become, so it is the better answer — and whichever is used is PRINTED, because
  a base that silently rots is the whole defect.
* THE CACHE HAS AN AGE. ``behind 88`` was rendered in the one column with no
  style path, appeared in no summary and no state, and — unfetched — the same
  88-commit gap rendered ``synced``. ``--stale 1`` then deleted the ``main`` row
  outright, so the reader's own position vanished from the map.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/workspace/tests
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Colour is part of what these tests assert, so they cannot render without it —
# but they still have to FIND the line they are asserting about.
ANSI = re.compile(r"\x1b\[[0-9;]*m")

_TESTS_DIR = Path(__file__).resolve().parent
_WORKSPACE_DIR = _TESTS_DIR.parent
for _path in (str(_TESTS_DIR), str(_WORKSPACE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _fixtures as F  # noqa: E402
import cleanup  # noqa: E402
import status  # noqa: E402


class BehindMainScenario(F.GitTestCase):
    """A checkout whose local ``main`` is behind the remote-tracking one.

    The shape the incident had, in miniature: ``feature`` was squash-merged and
    is contained by ``origin/main``; local ``main`` predates that and contains
    nothing of it. The two candidate bases therefore give OPPOSITE answers, which
    is what makes "which base" a real question rather than a detail.
    """

    BEHIND = 4

    def setUp(self) -> None:
        super().setUp()
        self.root = self.scratch / "toolkit"
        self.root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)],
                       check=True, env=dict(os.environ))
        F.add_toolkit_markers(self.root)
        F.write(self.root / "seed.txt", "seed\n")
        self.commit(self.root, "base commit", epoch=F.FIXED_EPOCH - 30 * F.DAY)
        self.stale_main = self.out(self.root, "rev-parse", "HEAD")

        self.git(self.root, "switch", "-q", "-c", "feature", "main")
        F.write(self.root / "feature.txt", "the feature\n")
        self.commit(self.root, "feature: the work", epoch=F.FIXED_EPOCH - 5 * F.DAY)
        self.git(self.root, "switch", "-q", "main")
        # `origin` moves on: the feature lands as a SQUASH (the way work lands
        # here), plus filler so "behind" is a number worth printing.
        self.git(self.root, "merge", "-q", "--squash", "feature")
        self.commit(self.root, "feature landed as one commit",
                    epoch=F.FIXED_EPOCH - 5 * F.DAY)
        for index in range(self.BEHIND - 1):
            F.write(self.root / f"later{index}.txt", "later\n")
            self.commit(self.root, f"later work {index}",
                        epoch=F.FIXED_EPOCH - 4 * F.DAY)
        self.git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        # …and the local checkout never pulled any of it.
        self.git(self.root, "reset", "-q", "--hard", self.stale_main)
        self.git(self.root, "remote", "add", "origin",
                 str(self.scratch / "origin.git"))
        self.git(self.root, "config", "branch.main.remote", "origin")
        self.git(self.root, "config", "branch.main.merge", "refs/heads/main")

    def touch_fetch_head(self, epoch: int) -> Path:
        """Give the checkout a dated ``FETCH_HEAD``, the way a fetch would."""
        path = self.root / ".git" / "FETCH_HEAD"
        path.write_text("", encoding="utf-8")
        os.utime(path, (epoch, epoch))
        return path

    def inspect(self, now: int | None = None) -> status.Repository:
        return status.inspect_repository(
            status.PUBLIC_LABEL, self.root,
            now=F.FIXED_EPOCH if now is None else now)

    def checkout_line(self, rendered: str) -> str:
        """The verdict row itself — not the disclaimer that points at it."""
        for line in rendered.splitlines():
            if ANSI.sub("", line).lstrip().startswith("CHECKOUT"):
                return line
        self.fail(f"no CHECKOUT verdict was rendered:\n{rendered}")


class BaseRefTests(BehindMainScenario):
    def test_the_fixture_really_does_split_the_two_bases(self) -> None:
        """Guard the guard: both bases must not agree, or nothing is proven."""
        behind = self.out(self.root, "rev-list", "--count",
                          "main..refs/remotes/origin/main")
        self.assertEqual(int(behind), self.BEHIND)
        listed = self.out(self.root, "branch", "--merged", "main")
        self.assertNotIn("feature", listed)

    def test_resolve_base_prefers_the_remote_tracking_ref(self) -> None:
        self.assertEqual(status.resolve_base(self.root),
                         "refs/remotes/origin/main")

    def test_resolve_base_falls_back_when_there_is_no_remote_tracking_ref(self) -> None:
        self.git(self.root, "update-ref", "-d", "refs/remotes/origin/main")
        self.assertEqual(status.resolve_base(self.root), "refs/heads/main")

    def test_resolve_base_answers_none_when_neither_ref_exists(self) -> None:
        self.git(self.root, "update-ref", "-d", "refs/remotes/origin/main")
        self.git(self.root, "switch", "-q", "feature")
        self.git(self.root, "branch", "-q", "-D", "main")
        self.assertIsNone(status.resolve_base(self.root))
        self.assertIsNone(status.resolve_base(self.root, prefer_remote=False))

    def test_the_planner_shares_this_one_implementation(self) -> None:
        """Two copies of "what does merged mean" is how the two drifted apart."""
        self.assertEqual(cleanup.resolve_base(self.root, fetched=True),
                         status.resolve_base(self.root, prefer_remote=True))
        self.assertEqual(cleanup.resolve_base(self.root, fetched=False),
                         status.resolve_base(self.root, prefer_remote=False))
        # The planner's preference is the one difference, and it is deliberate:
        # it prefers the remote base only once it has actually fetched one.
        self.assertEqual(cleanup.resolve_base(self.root, fetched=True),
                         "refs/remotes/origin/main")
        self.assertEqual(cleanup.resolve_base(self.root, fetched=False),
                         "refs/heads/main")

    def test_a_branch_already_in_origin_main_is_merged_though_local_main_is_behind(
            self) -> None:
        repo = self.inspect()
        self.assertEqual(repo.base_ref, "refs/remotes/origin/main")
        feature = {branch.name: branch for branch in repo.branches}["feature"]
        self.assertEqual(feature.merged, "merged")
        self.assertEqual(feature.state, status.STATE_MERGED)

    def test_against_the_stale_local_main_the_same_branch_reads_unmerged(self) -> None:
        """The defect, stated as an experiment rather than as a claim."""
        probe = status.open_merge_probe(self.root)
        self.addCleanup(probe.close)
        stale = status._merged_state(
            self.root, "refs/heads/feature", "refs/heads/main", probe,
            status._base_tree(self.root, "refs/heads/main"))
        self.assertEqual(stale, "unmerged")

    def test_which_base_was_used_is_printed(self) -> None:
        repo = self.inspect()
        rendered = status.render([repo], self.root, False, status.Palette(False))
        self.assertIn("merged is judged against refs/remotes/origin/main", rendered)

    def test_a_repository_with_no_base_says_merge_state_is_unavailable(self) -> None:
        self.git(self.root, "update-ref", "-d", "refs/remotes/origin/main")
        self.git(self.root, "switch", "-q", "feature")
        self.git(self.root, "branch", "-q", "-D", "main")
        repo = self.inspect()
        self.assertIsNone(repo.base_ref)
        rendered = status.render([repo], self.root, False, status.Palette(False))
        self.assertIn("merge state is unavailable", rendered)


class CheckoutVerdictTests(BehindMainScenario):
    """The verdict line: how far behind, and how old the knowledge that says so."""

    def test_the_thresholds_directly(self) -> None:
        call = status.checkout_freshness
        self.assertEqual(call(has_remote=False, age_seconds=0),
                         status.FRESHNESS_NO_REMOTE)
        self.assertEqual(call(has_remote=True, age_seconds=None),
                         status.FRESHNESS_UNKNOWN)
        self.assertEqual(call(has_remote=True, age_seconds=60),
                         status.FRESHNESS_FRESH)
        self.assertEqual(
            call(has_remote=True, age_seconds=status.CHECKOUT_DATED_SECONDS - 1),
            status.FRESHNESS_FRESH)
        self.assertEqual(
            call(has_remote=True, age_seconds=status.CHECKOUT_DATED_SECONDS),
            status.FRESHNESS_DATED)
        self.assertEqual(
            call(has_remote=True, age_seconds=status.CHECKOUT_BLIND_SECONDS - 1),
            status.FRESHNESS_DATED)
        self.assertEqual(
            call(has_remote=True, age_seconds=status.CHECKOUT_BLIND_SECONDS),
            status.FRESHNESS_BLIND)

    def test_the_verdict_carries_the_gap_and_the_age_of_the_cache(self) -> None:
        self.touch_fetch_head(F.FIXED_EPOCH - 2 * 3600)
        repo = self.inspect()
        self.assertIsNotNone(repo.checkout)
        self.assertEqual(repo.checkout.behind, self.BEHIND)
        self.assertEqual(repo.checkout.freshness, status.FRESHNESS_FRESH)
        rendered = status.render([repo], self.root, False, status.Palette(False))
        line = self.checkout_line(rendered)
        self.assertIn(f"behind {self.BEHIND}", line)
        self.assertIn("remote knowledge", line)
        self.assertIn("2h", line)

    def test_a_day_of_commits_behind_is_a_calm_fact_not_an_alarm(self) -> None:
        """This repository merged 88 commits in 18 hours.

        A banner keyed on the commit COUNT would be red every day and read by
        nobody inside a week, so the count is reported and the AGE of the cache
        is what the verdict is keyed on.
        """
        self.touch_fetch_head(F.FIXED_EPOCH - 3600)
        repo = self.inspect()
        rendered = status.render([repo], self.root, False, status.Palette(True))
        line = self.checkout_line(rendered)
        self.assertIn(status.FRESHNESS_FRESH, line)
        self.assertNotIn(status.FRESHNESS_BLIND, line)
        self.assertNotIn("git fetch --prune", line)

    def test_a_week_old_cache_shouts_because_the_table_is_then_fiction(self) -> None:
        self.touch_fetch_head(F.FIXED_EPOCH - status.CHECKOUT_BLIND_SECONDS - 60)
        repo = self.inspect()
        self.assertEqual(repo.checkout.freshness, status.FRESHNESS_BLIND)
        palette = status.Palette(True)
        rendered = status.render([repo], self.root, False, palette)
        line = self.checkout_line(rendered)
        self.assertIn(status.FRESHNESS_BLIND, line)
        self.assertIn(palette.RED, line)
        self.assertIn("git fetch --prune", line)

    def test_a_checkout_that_never_fetched_says_so_rather_than_guessing(self) -> None:
        fetch_head = self.root / ".git" / "FETCH_HEAD"
        self.assertFalse(fetch_head.exists(), "git init should write no FETCH_HEAD")
        repo = self.inspect()
        self.assertIsNone(repo.checkout.fetched_epoch)
        self.assertEqual(repo.checkout.freshness, status.FRESHNESS_UNKNOWN)
        rendered = status.render([repo], self.root, False, status.Palette(False))
        self.assertIn("never fetched in this checkout", rendered)

    def test_the_newest_fetch_across_linked_worktrees_counts(self) -> None:
        """FETCH_HEAD is PER-WORKTREE, and agents here fetch from linked ones."""
        self.touch_fetch_head(F.FIXED_EPOCH - 30 * F.DAY)
        linked = self.scratch / "linked"
        self.git(self.root, "worktree", "add", "-q", "--detach", str(linked), "main")
        per_worktree = (self.root / ".git" / "worktrees" / "linked" / "FETCH_HEAD")
        per_worktree.write_text("", encoding="utf-8")
        os.utime(per_worktree, (F.FIXED_EPOCH - 60, F.FIXED_EPOCH - 60))
        repo = self.inspect()
        self.assertEqual(repo.checkout.freshness, status.FRESHNESS_FRESH)

    def test_the_cache_disclaimer_points_at_the_verdict(self) -> None:
        repo = self.inspect()
        rendered = status.render([repo], self.root, False, status.Palette(False))
        self.assertIn("no fetch was performed", rendered)
        self.assertIn("says how old that cache is", rendered)

    # ── the sync column was the incident's hiding place ─────────────────────
    def test_behind_is_styled_where_it_used_to_be_the_one_unstyled_token(self) -> None:
        repo = self.inspect()
        palette = status.Palette(True)
        rendered = status.render([repo], self.root, False, palette)
        row = [line for line in rendered.splitlines()
               if " main " in line and "behind" in line]
        self.assertTrue(row, f"no main branch row with a behind count:\n{rendered}")
        self.assertIn(palette.YELLOW, row[0])
        self.assertEqual(status._sync_style("synced", palette), palette.GREEN)
        self.assertEqual(status._sync_style("behind 88", palette), palette.YELLOW)
        self.assertEqual(status._sync_style("diverged +1/-2", palette), palette.RED)
        self.assertEqual(status._sync_style("upstream missing", palette), palette.RED)


class StaleFilterTests(BehindMainScenario):
    def test_the_checked_out_row_survives_the_filter(self) -> None:
        """`--stale 1` used to delete the `main` row, and with it the evidence."""
        repo = self.inspect()
        rendered = status.render([repo], self.root, False, status.Palette(False),
                                 stale_days=1)
        block = rendered.split("BRANCHES", 1)[1]
        rows = [line for line in block.splitlines() if line.startswith("    ")]
        checked_out = [line for line in rows if line.lstrip().startswith("*")]
        self.assertTrue(checked_out,
                        f"the checked-out row was filtered away:\n{rendered}")
        self.assertIn("main", checked_out[0])
        self.assertIn("behind", checked_out[0])

    def test_the_heading_says_the_checked_out_row_is_exempt(self) -> None:
        rendered = status.render([self.inspect()], self.root, False,
                                 status.Palette(False), stale_days=1)
        self.assertIn("the checked-out row is always shown", rendered)

    def test_a_zero_day_filter_still_shows_everything(self) -> None:
        rendered = status.render([self.inspect()], self.root, False,
                                 status.Palette(False), stale_days=0)
        self.assertIn("feature", rendered)
        self.assertIn("main", rendered)


class JsonModeTests(BehindMainScenario):
    """``--json`` is pasted into issues at least as often as the table is."""

    def payload(self, repositories) -> dict:
        text = json.dumps(status.workspace_json(repositories, now=F.FIXED_EPOCH),
                          indent=2, sort_keys=True)
        return json.loads(text)

    def test_the_public_payload_carries_the_base_and_the_verdict(self) -> None:
        payload = self.payload([self.inspect()])
        self.assertEqual(payload["schema"], status.JSON_SCHEMA)
        record = payload["repositories"][0]
        self.assertEqual(record["base_ref"], "refs/remotes/origin/main")
        self.assertFalse(record["private"])
        self.assertIsNone(record["redaction"])
        checkout = record["checkout"]
        self.assertEqual(checkout["behind"], self.BEHIND)
        self.assertEqual(checkout["freshness"], status.FRESHNESS_UNKNOWN)
        self.assertIn("checkout_blind_seconds", payload["thresholds"])

    def test_a_public_and_a_private_repository_serialise_together(self) -> None:
        # OUTSIDE the public fixture: the real overlay is git-ignored, and an
        # overlay nested in a tracked tree would leak through the PUBLIC
        # repo's untracked-file list rather than through any redaction.
        overlay_root = self.scratch / "elsewhere" / status.PRIVATE_MOUNT
        facts = F.build_private_overlay(self, overlay_root)
        overlay = status.inspect_repository(status.PRIVATE_LABEL, overlay_root,
                                            now=F.FIXED_EPOCH)
        payload = self.payload([self.inspect(), overlay])
        labels = [record["label"] for record in payload["repositories"]]
        self.assertEqual(labels, [status.PUBLIC_LABEL, status.PRIVATE_LABEL])
        self.assertNotIn(facts["secret"], json.dumps(payload).lower())
        private = payload["repositories"][1]
        self.assertTrue(private["private"])
        self.assertIsNotNone(private["checkout"])


if __name__ == "__main__":
    import unittest

    unittest.main()
