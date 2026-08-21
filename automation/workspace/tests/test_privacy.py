"""What the dashboard may say about the PRIVATE OVERLAY, and what it may not.

WHY THIS FILE IS SEPARATE, AND WHY IT IS SHORT ON NUANCE. ``private/`` is a
git-ignored, separate repository holding the owner's real identity — employers,
applications, interview material. ``AGENTS.md`` mandates ``status.py`` as every
session's FIRST command, so anything it prints lands in every agent's context
and in whatever an agent then pastes into a public PR description, commit
message or issue. Reproduced before this file existed: one ``-v`` run printed an
employer name inside a branch name, the same name in a commit subject, the
owner's own ``git branch --edit-description`` prose, an
``applications/<stage>/<employer>/`` path and an absolute home path.

The assertion is therefore blunt and total: a fabricated token is stamped into
every one of those fields in a fixture overlay, and it must appear NOWHERE in
the table, in ``-v``, or in ``--json``. A test that enumerated "the fields we
remembered to scrub" would have passed before the fix too.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/workspace/tests
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_WORKSPACE_DIR = _TESTS_DIR.parent
for _path in (str(_TESTS_DIR), str(_WORKSPACE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _fixtures as F  # noqa: E402
import status  # noqa: E402


class OverlayRedactionTests(F.GitTestCase):
    """One fabricated token, every output mode, zero appearances."""

    def setUp(self) -> None:
        super().setUp()
        self.workspace = self.scratch / "toolkit"
        self.overlay = self.workspace / status.PRIVATE_MOUNT
        self.facts = F.build_private_overlay(self, self.overlay)
        self.secret = self.facts["secret"]
        self.repo = status.inspect_repository(
            status.PRIVATE_LABEL, self.overlay, now=F.FIXED_EPOCH)

    # ── the outputs ─────────────────────────────────────────────────────────
    def outputs(self) -> dict[str, str]:
        return {
            "table": status.render([self.repo], self.workspace, False,
                                   status.Palette(False)),
            "verbose": status.render([self.repo], self.workspace, True,
                                     status.Palette(False)),
            "verbose+color": status.render([self.repo], self.workspace, True,
                                           status.Palette(True)),
            "stale": status.render([self.repo], self.workspace, True,
                                   status.Palette(False), stale_days=1),
            "json": json.dumps(status.workspace_json([self.repo],
                                                     now=F.FIXED_EPOCH),
                               indent=2, sort_keys=True),
        }

    def test_the_fixture_really_does_carry_the_token_everywhere(self) -> None:
        """Guard the guard: if the fixture stops leaking, the test proves nothing."""
        self.assertIn(self.secret,
                      self.out(self.overlay, "branch", "--format=%(refname)"))
        self.assertIn(self.secret, self.out(self.overlay, "log", "--format=%s", "-3",
                                            self.facts["conventional"]))
        self.assertIn(self.secret, self.out(
            self.overlay, "config", f"branch.{self.facts['conventional']}.description"))
        self.assertIn(self.secret, self.out(self.overlay, "ls-files"))
        self.assertIn(self.secret, self.out(self.overlay, "remote", "get-url", "origin"))
        self.assertIn(self.secret, self.out(self.overlay, "worktree", "list"))
        self.assertIn(self.secret, self.out(self.overlay, "status", "--porcelain"))

    def test_without_redaction_the_same_fixture_leaks_all_of_it(self) -> None:
        """The counterfactual, so the test above cannot pass by accident.

        Redaction disarmed, this is what the dashboard printed before the fix —
        and every one of these is a field the auditor caught in a real ``-v``
        run: a branch name, a commit subject, the owner's own branch
        description, an ``applications/<stage>/<employer>/`` path, and the
        overlay's absolute location.
        """
        raw = status.inspect_repository(status.PRIVATE_LABEL, self.overlay,
                                        now=F.FIXED_EPOCH, private=False)
        leaked = status.render([raw], self.workspace, True, status.Palette(False))
        self.assertIn(self.secret, leaked.lower())
        # The table truncates long names, so match the part that survives it.
        self.assertIn(f"codex/{self.secret}", leaked)          # branch name
        self.assertIn("onsite loop", leaked)                   # commit subject
        self.assertIn("send the thank-you note", leaked)       # branch description
        self.assertIn(self.facts["stage"], leaked)             # overlay file path
        self.assertIn(str(self.overlay), leaked)               # absolute location
        self.assertIn("holding the", leaked)                   # a worktree lock reason
        self.assertIn("github.com", leaked)                    # the remote URL

    def test_the_token_reaches_no_output_in_any_mode(self) -> None:
        for mode, text in self.outputs().items():
            with self.subTest(mode=mode):
                self.assertNotIn(self.secret, text.lower())

    def test_no_overlay_path_reaches_any_output(self) -> None:
        """Paths below the overlay root, and the root's own absolute location."""
        forbidden = (
            str(self.overlay),                  # the overlay's absolute location
            str(self.facts["linked"]),          # a linked worktree's location
            str(self.facts["locked"]),
            str(self.facts["gone"]),
            str(self.home),                     # the fixture's HOME
            self.facts["stage"],                # applications/<stage>/<employer>
            "applications/",
        )
        for mode, text in self.outputs().items():
            for needle in forbidden:
                with self.subTest(mode=mode, needle=needle):
                    self.assertNotIn(needle, text)

    def test_the_output_still_says_what_it_is_withholding(self) -> None:
        """Silence that does not announce itself reads as "there is nothing here"."""
        table = status.render([self.repo], self.workspace, False, status.Palette(False))
        self.assertIn("private overlay", table)
        self.assertIn("withheld", table)
        payload = status.workspace_json([self.repo], now=F.FIXED_EPOCH)
        record = payload["repositories"][0]
        self.assertTrue(record["private"])
        self.assertIsNotNone(record["redaction"])

    # ── what SURVIVES redaction, because withholding everything is useless ──
    def test_structure_counts_ages_and_states_all_survive(self) -> None:
        self.assertEqual(len(self.repo.worktrees), 4)   # main + linked + locked + gone
        self.assertEqual(self.repo.local_ref_count, 3)
        self.assertEqual(self.repo.remote_ref_count, 1)
        self.assertEqual(self.repo.base_ref, "refs/remotes/origin/main")
        by_state = {branch.name: branch.state for branch in self.repo.branches}
        self.assertTrue(by_state, "redaction removed the branch rows entirely")
        for branch in self.repo.branches:
            with self.subTest(branch=branch.name):
                self.assertIn(branch.state, status.STATES)
                self.assertIsNotNone(branch.age_seconds)
        # The one dirty worktree is still reported dirty, by count.
        dirty = [w for w in self.repo.worktrees if w.dirty]
        self.assertEqual(len(dirty), 1)
        self.assertEqual(dirty[0].untracked, 1)

    def test_a_branch_row_and_its_worktree_row_still_join(self) -> None:
        """The ordinal has to keep doing the one job the real name did here."""
        labels = {branch.name for branch in self.repo.branches}
        for worktree in self.repo.worktrees:
            if worktree.branch_ref is None:
                continue
            with self.subTest(worktree=worktree.branch):
                self.assertIn(worktree.branch, labels)

    # ── the branch-name rule ────────────────────────────────────────────────
    def test_branch_names_degrade_to_an_ordinal_keeping_only_safe_prefixes(self) -> None:
        names = sorted(branch.name for branch in self.repo.branches)
        # `main` survives verbatim (it is the base ref, and a literal in the
        # public source); a conventional prefix survives with an ordinal behind
        # it; anything else is an ordinal alone.
        self.assertIn("main", names)
        self.assertTrue(any(name.startswith("codex/#") for name in names), names)
        self.assertTrue(any(name.lstrip("#").isdigit() for name in names), names)
        upstreams = {branch.upstream.short_name for branch in self.repo.branches
                     if branch.upstream is not None}
        self.assertEqual(upstreams, {"origin/main"})

    def test_the_label_rule_directly(self) -> None:
        rule = status.redact_branch_label
        self.assertEqual(rule("main", 1, "L"), "main")
        self.assertEqual(rule("codex/acme-onsite", 3, "L"), "codex/#3")
        self.assertEqual(rule("acme-onsite", 3, "L"), "#3")
        # An unrecognised leading segment is NOT a prefix — it is the name.
        self.assertEqual(rule("acme/onsite", 3, "L"), "#3")
        self.assertEqual(rule("origin/codex/acme", 4, "R"), "origin/codex/#4")
        self.assertEqual(rule("acme-fork/main", 4, "R"), "#4")

    # ── the redaction is armed by more than a caller's spelling ─────────────
    def test_location_arms_redaction_even_under_another_label(self) -> None:
        """`gardener/workspace_hygiene.py` inspects the overlay as "REPO"."""
        self.assertTrue(status.is_private_overlay("REPO", self.overlay))
        repo = status.inspect_repository("REPO", self.overlay, now=F.FIXED_EPOCH)
        self.assertTrue(repo.private)
        rendered = status.render([repo], self.workspace, True, status.Palette(False))
        self.assertNotIn(self.secret, rendered.lower())

    def test_discovery_labels_the_overlay_so_the_cli_arms_it(self) -> None:
        found = dict(status.discover_repositories(self.workspace))
        self.assertIn(status.PRIVATE_LABEL, found)
        self.assertEqual(found[status.PRIVATE_LABEL], self.overlay.resolve())

    def test_a_git_failure_in_the_overlay_reports_no_git_prose(self) -> None:
        """`_git` builds its message from the repo path and git's own stderr."""
        broken = self.overlay / "no-such-place" / self.secret
        with self.assertRaises(status.GitError) as raised:
            status.inspect_repository(status.PRIVATE_LABEL, broken,
                                      now=F.FIXED_EPOCH)
        message = str(raised.exception)
        self.assertNotIn(self.secret, message.lower())
        self.assertIn("withheld", message)

    def test_the_public_repository_is_not_redacted(self) -> None:
        """The fix must change nothing about what the PUBLIC repo prints."""
        public = self.scratch / "public"
        F.build_merge_shapes(self, public)
        repo = status.inspect_repository(status.PUBLIC_LABEL, public,
                                         now=F.FIXED_EPOCH)
        self.assertFalse(repo.private)
        rendered = status.render([repo], public, True, status.Palette(False))
        self.assertIn("open-work: start the feature", rendered)   # commit subject
        self.assertIn("open-work", rendered)                      # real branch name
        self.assertIn("seed.txt", rendered)                       # changed file path


if __name__ == "__main__":
    import unittest

    unittest.main()
