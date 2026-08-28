"""Tests for `merge_stack.py` — the two-track PR merge driver.

Run with (from the repo root):
    .venv/bin/python -m unittest discover skills/github-workflow/scripts/tests

The module is loaded from its absolute path rather than imported by name: a
skill's `scripts/` is not a package on `sys.path`, and nothing here may reach
repo-root Python (`docs/handbook/skills-and-vendoring.md`).

**No test here touches the network.** Every `gh` invocation is answered by
`FakeGh`, which is installed over the module's single `_run_gh` seam. A test that
reached GitHub would merge something.
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "merge_stack.py"


def _load():
    spec = importlib.util.spec_from_file_location("merge_stack", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


merge_stack = _load()

#: The real local-git runner, captured before any test swaps in `FakeGit`. Only
#: the cutover tests use it, and only ever against a throwaway repository.
REAL_RUN_GIT = merge_stack._run_git

REPO = "owner/name"
UUID = "3f2b1c9a-0d4e-4f6a-8b1c-2d3e4f5a6b7c"


def stacked(number, *, position=1, size=3, stack_number=88, state="OPEN",
            base="main", head="a" * 40, draft=False, mergeable="MERGEABLE",
            check_state="SUCCESS"):
    return {
        "number": number, "state": state, "isDraft": draft,
        "baseRefName": base, "headRefOid": head, "mergeable": mergeable,
        "commits": {"nodes": [{"commit": {
            "oid": head,
            "statusCheckRollup": (None if check_state is None else
                                  {"state": check_state}),
        }}]},
        "stackEntry": {"position": position,
                       "stack": {"number": stack_number, "size": size}},
    }


def plain(number, *, state="OPEN", base="main", head="b" * 40, draft=False,
          mergeable="MERGEABLE", check_state="SUCCESS"):
    return {
        "number": number, "state": state, "isDraft": draft,
        "baseRefName": base, "headRefOid": head, "mergeable": mergeable,
        "commits": {"nodes": [{"commit": {
            "oid": head,
            "statusCheckRollup": (None if check_state is None else
                                  {"state": check_state}),
        }}]},
        "stackEntry": None,
    }


class FakeGh:
    """A scripted `gh`. Every call is recorded; unexpected calls fail loudly."""

    def __init__(self, *, pulls=None, responses=None):
        #: number -> a single pull dict, or a LIST consumed one classify at a time
        #: (so a test can make the head move, or a PR merge, between reads).
        self.pulls = pulls or {}
        #: an argv-substring -> (code, stdout, stderr) override table, matched in
        #: insertion order against the joined argv.
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def _classify_payload(self, number):
        record = self.pulls[number]
        if isinstance(record, list):
            record = record.pop(0) if len(record) > 1 else record[0]
        return json.dumps({"data": {"repository": {"pullRequest": record}}})

    def __call__(self, args):
        self.calls.append(list(args))
        joined = " ".join(args)
        for needle, response in self.responses.items():
            if needle in joined:
                return response
        if args[:2] == ["api", "graphql"]:
            number = int(next(a for a in args if a.startswith("number=")
                              ).split("=")[1])
            if number not in self.pulls:
                return (0, json.dumps(
                    {"data": {"repository": {"pullRequest": None}}}), "")
            return (0, self._classify_payload(number), "")
        if args[:2] == ["repo", "view"]:
            return (0, REPO + "\n", "")
        raise AssertionError(f"unscripted gh call: {args}")

    def ran(self, needle):
        return [call for call in self.calls if needle in " ".join(call)]


class FakeGit:
    """A scripted local `git`, installed over `_run_git` for every test here.

    The DEFAULT answer is a failure. That is the safety property: a test that
    reaches `git` without saying so gets "not a git repository" instead of
    fetching and fast-forwarding the developer's own checkout, which is exactly
    what the post-merge cutover does when it is given a real one.
    """

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args, cwd=None, env=None):
        self.calls.append((list(args), cwd))
        joined = " ".join(args)
        for needle, response in self.responses.items():
            if needle in joined:
                return response
        return (128, "", "fatal: not a git repository (test seam)")

    def ran(self, needle):
        return [call for call in self.calls if needle in " ".join(call[0])]


class GhTestCase(unittest.TestCase):
    def install(self, fake, git=None):
        self._original = merge_stack._run_gh
        merge_stack._run_gh = fake
        self.addCleanup(lambda: setattr(merge_stack, "_run_gh", self._original))
        original_git = merge_stack._run_git
        self.git = git if git is not None else FakeGit()
        merge_stack._run_git = self.git
        self.addCleanup(lambda: setattr(merge_stack, "_run_git", original_git))
        return fake

    def run_main(self, argv, fake, git=None):
        """Return (exit code, stdout AND stderr) — refusals print to stderr."""
        self.install(fake, git)
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = merge_stack.main(argv)
        return code, buffer.getvalue()

    def assertRefuses(self, argv, fake, fragment):
        code, out = self.run_main(argv, fake)
        self.assertEqual(code, 1, out)
        self.assertIn("REFUSED", out)
        self.assertIn(fragment, out)
        return out


FAST = ["--poll-interval", "0", "--timeout", "0"]


class ClassificationTests(GhTestCase):
    def test_stack_membership_is_read_from_graphql(self):
        fake = FakeGh(pulls={87: stacked(87, position=1, size=7)})
        code, out = self.run_main(["--repo", REPO, "87"], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("#87", out)
        self.assertIn("#88 pos 1/7", out)
        self.assertEqual(len(fake.ran("api graphql")), 1)

    def test_a_non_stacked_pr_is_track_b(self):
        fake = FakeGh(pulls={41: plain(41)})
        code, out = self.run_main(["--repo", REPO, "41"], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("not stacked", out)

    def test_a_graphql_error_refuses_rather_than_guessing_a_track(self):
        fake = FakeGh(responses={"api graphql": (
            0, json.dumps({"errors": [{"message": "no field stackEntry"}]}), "")})
        self.assertRefuses(["--repo", REPO, "41"], fake, "stackEntry")

    def test_a_failed_classification_query_refuses(self):
        fake = FakeGh(responses={"api graphql": (1, "", "gh: bad credentials")})
        with self.assertRaises(merge_stack.Refusal) as caught:
            self.install(fake)
            merge_stack.classify(REPO, 41)
        self.assertIn("guessing a track", str(caught.exception))

    def test_a_missing_field_refuses(self):
        broken = plain(41)
        del broken["stackEntry"]
        fake = FakeGh(pulls={41: broken})
        self.install(fake)
        with self.assertRaises(merge_stack.Refusal) as caught:
            merge_stack.classify(REPO, 41)
        self.assertIn("stackEntry", str(caught.exception))

    def test_a_number_that_is_a_stack_says_so(self):
        """`gh pr view 190` fails because 190 is a STACK, not a deleted PR."""
        fake = FakeGh(pulls={})
        self.install(fake)
        with self.assertRaises(merge_stack.Refusal) as caught:
            merge_stack.classify(REPO, 190)
        self.assertIn("STACK", str(caught.exception))

    def test_gh_s_own_resolution_error_gets_the_stack_message_too(self):
        """The real failure path: `gh api graphql` exits 1 on an unknown number."""
        fake = FakeGh(responses={"api graphql": (
            1, "", "gh: Could not resolve to a PullRequest with the number of "
                   "190.")})
        self.install(fake)
        with self.assertRaises(merge_stack.Refusal) as caught:
            merge_stack.classify(REPO, 190)
        self.assertIn("/stacks", str(caught.exception))

    def test_stack_entry_null_is_a_verdict_not_a_missing_field(self):
        self.assertEqual(merge_stack.track_of(plain(41)), "B")
        self.assertEqual(merge_stack.track_of(stacked(87)), "A")


class DryRunTests(GhTestCase):
    def test_dry_run_is_the_default_and_merges_nothing(self):
        fake = FakeGh(pulls={41: plain(41)})
        code, out = self.run_main(["--repo", REPO, "41"], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("DRY RUN", out)
        self.assertEqual(fake.ran("pr merge"), [])
        self.assertEqual(fake.ran("merge-async"), [])

    def test_dry_run_prints_the_exact_planned_command_per_track(self):
        fake = FakeGh(pulls={87: stacked(87), 41: plain(41)})
        _, out = self.run_main(["--repo", REPO, "87", "41"], fake)
        self.assertIn(f"gh api --method PUT repos/{REPO}/pulls/87/merge-async", out)
        self.assertIn(f"gh pr merge 41 --repo {REPO} --merge", out)

    def test_dry_run_of_a_stacked_pr_never_plans_a_retarget(self):
        """Inside a native stack GitHub rebases the next entry itself."""
        fake = FakeGh(pulls={87: stacked(87), 86: stacked(86, position=2)})
        _, out = self.run_main(["--repo", REPO, "87", "86"], fake)
        self.assertNotIn("gh pr edit", out)

    def test_dry_run_of_two_plain_prs_plans_the_retarget(self):
        fake = FakeGh(pulls={41: plain(41), 42: plain(42, base="feat/01")})
        _, out = self.run_main(["--repo", REPO, "41", "42"], fake)
        self.assertIn("gh pr edit 42", out)

    def test_dry_run_does_not_hide_a_bad_base(self):
        """Refusals belong to --execute; the dry run's job is to SHOW the base."""
        fake = FakeGh(pulls={42: plain(42, base="feat/01-parser")})
        code, out = self.run_main(["--repo", REPO, "42"], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("feat/01-parser", out)

    def test_atomic_dry_run_names_one_top_request_and_the_full_sweep(self):
        fake = FakeGh(pulls={
            81: stacked(81, position=1, size=3),
            84: stacked(84, position=2, size=3),
            87: stacked(87, position=3, size=3),
        })
        code, out = self.run_main(
            ["--repo", REPO, "--atomic", "81", "84", "87"], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("one top-entry async request", out)
        self.assertIn("merging #87 at position 3 sweeps positions 1..3", out)
        self.assertIn("#81, #84, #87", out)
        self.assertEqual(out.count("--method PUT"), 1, out)

    def test_atomic_dry_run_distinguishes_historical_prefix_from_open_sweep(self):
        """The live #375 shape plans no second PUT for its merged bottom."""
        fake = FakeGh(pulls={
            371: stacked(371, position=1, size=2, stack_number=375,
                         state="MERGED", head="a" * 40),
            374: stacked(374, position=2, size=2, stack_number=375,
                         head="b" * 40),
        })
        code, out = self.run_main(
            ["--repo", REPO, "--atomic", "371", "374"], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("historical merged prefix", out)
        self.assertIn("verify each with GET /merge -> 204", out)
        self.assertIn("sweeps OPEN positions 2..2 (#374)", out)
        self.assertEqual(out.count("--method PUT"), 1, out)
        self.assertIn("pulls/374/merge-async", out)
        self.assertNotIn("pulls/371/merge-async", out)
        self.assertEqual(fake.ran("/merge"), [],
                         "a dry run describes but does not perform confirmation")

    def test_atomic_dry_run_refuses_a_lone_historical_position_two(self):
        fake = FakeGh(pulls={
            374: stacked(374, position=2, size=2, stack_number=375),
        })
        code, out = self.run_main(
            ["--repo", REPO, "--atomic", "374"], fake)
        self.assertEqual(code, 1, out)
        self.assertIn("complete contiguous prefix [1]", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_non_atomic_dry_run_refuses_position_two_instead_of_printing_put(self):
        """The unsupported live command must not tell the caller to execute."""
        fake = FakeGh(pulls={
            374: stacked(374, position=2, size=2, stack_number=375),
        })
        code, out = self.run_main(["--repo", REPO, "374"], fake)
        self.assertEqual(code, 1, out)
        self.assertIn("not the bottom", out)
        self.assertNotIn("--method PUT", out)
        self.assertNotIn("Re-run with --execute", out)


class TrackATests(GhTestCase):
    def _fake(self, *, put=None, polls=None, merge_check=None, pulls=None):
        put = put or (0, json.dumps(
            {"status": "pending", "details": {"uuid": UUID}}), "")
        polls = polls if polls is not None else [
            (0, json.dumps({"status": "merged"}), "")]
        merge_check = merge_check or (0, "", "")
        remaining = list(polls)

        def poll_response(_):
            return remaining.pop(0) if len(remaining) > 1 else remaining[0]

        fake = FakeGh(pulls=pulls or {87: stacked(87)})
        fake.responses = {
            "--method PUT": put,
            f"merge-async/{UUID}": poll_response,
            "/merge": merge_check,
        }
        original = fake.__call__

        def dispatch(args):
            fake.calls.append(list(args))
            joined = " ".join(args)
            for needle, response in fake.responses.items():
                if needle in joined:
                    return response(args) if callable(response) else response
            fake.calls.pop()
            return original(args)

        return fake, dispatch

    def _run(self, fake, dispatch, argv):
        """Return (exit code, stdout AND stderr) — refusals print to stderr."""
        self.install(dispatch)
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = merge_stack.main(argv)
        return code, buffer.getvalue()

    def test_happy_path_uses_merge_async_and_confirms_independently(self):
        fake, dispatch = self._fake()
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 0, out)
        self.assertTrue(fake.ran("--method PUT"), fake.calls)
        self.assertTrue(fake.ran(f"pulls/87/merge-async/{UUID}"), fake.calls)
        self.assertTrue(fake.ran("api repos/owner/name/pulls/87/merge"),
                        fake.calls)
        self.assertEqual(fake.ran("pr merge"), [],
                         "a stack member must never go through `gh pr merge`")
        self.assertIn("MERGED (confirmed", out)

    def test_the_put_alone_is_never_treated_as_success(self):
        """202 + `gh` exit 0 is a receipt. Without a terminal poll, nothing merged."""
        fake, dispatch = self._fake(
            polls=[(0, json.dumps({"status": "pending"}), "")])
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1, out)
        self.assertNotIn("MERGED (confirmed", out)

    def test_enqueued_is_terminal_but_not_success(self):
        fake, dispatch = self._fake(
            polls=[(0, json.dumps({"status": "enqueued"}), "")])
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1, out)
        self.assertNotIn("MERGED (confirmed", out)

    def test_failed_is_a_refusal(self):
        fake, dispatch = self._fake(
            polls=[(0, json.dumps({"status": "failed"}), "")])
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1)

    def test_an_unknown_status_is_not_interpreted(self):
        fake, dispatch = self._fake(
            polls=[(0, json.dumps({"status": "sparkling"}), "")])
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1)

    def test_the_poll_ceiling_refuses_while_still_pending(self):
        with self.assertRaises(merge_stack.Refusal) as caught:
            self.install(FakeGh(responses={f"merge-async/{UUID}": (
                0, json.dumps({"status": "pending"}), "")}))
            merge_stack.poll_async(REPO, 87, UUID, 0.0, 0.0)
        self.assertIn("do NOT re-fire", str(caught.exception))

    def test_a_409_polls_the_in_flight_request_instead_of_re_firing(self):
        fake, dispatch = self._fake(
            put=(1, "", f"gh: already in flight {UUID} (HTTP 409)"))
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(fake.ran("--method PUT")), 1,
                         "a 409 must not be answered by re-firing the PUT")
        self.assertIn("NOT re-firing", out)

    def test_the_two_confirmation_sources_disagreeing_refuses(self):
        fake, dispatch = self._fake(merge_check=(1, "", "gh: (HTTP 404)"))
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1, out)

    def test_a_confirmation_that_is_neither_204_nor_404_refuses(self):
        fake, dispatch = self._fake(merge_check=(1, "", "gh: (HTTP 500)"))
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1)

    def test_position_above_the_bottom_refuses_without_atomic(self):
        fake, dispatch = self._fake(pulls={84: stacked(84, position=4, size=7)})
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "84"])
        self.assertEqual(code, 1, out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_full_prefix_uses_one_top_entry_request(self):
        fake, dispatch = self._fake(pulls={
            81: stacked(81, position=1, size=4),
            82: stacked(82, position=2, size=4),
            83: stacked(83, position=3, size=4),
            84: stacked(84, position=4, size=4),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST,
             "81", "82", "83", "84"])
        self.assertEqual(code, 0, out)
        puts = fake.ran("--method PUT")
        self.assertEqual(len(puts), 1, fake.calls)
        self.assertIn("pulls/84/merge-async", " ".join(puts[0]))
        self.assertIn("atomic preflight passed", out)
        self.assertIn("sweeps positions 1..4", out)
        for number in (81, 82, 83, 84):
            self.assertIn(
                ["api", f"repos/{REPO}/pulls/{number}/merge"], fake.calls)

    def test_atomic_resumes_after_confirmed_historical_prefix(self):
        """Exact live shape: MERGED pos1 + OPEN pos2 sends only pos2's PUT."""
        cutovers = []
        original_cutover = merge_stack.run_cutover
        merge_stack.run_cutover = lambda opts, pulls: cutovers.append(
            [pull["number"] for pull in pulls])
        self.addCleanup(
            lambda: setattr(merge_stack, "run_cutover", original_cutover))
        fake, dispatch = self._fake(pulls={
            371: [stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED", head="a" * 40,
                          check_state=None),
                  stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED", head="a" * 40,
                          check_state=None)],
            374: [stacked(374, position=2, size=2, stack_number=375,
                          head="b" * 40),
                  stacked(374, position=2, size=2, stack_number=375,
                          head="b" * 40)],
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371", "374"])
        self.assertEqual(code, 0, out)
        puts = fake.ran("--method PUT")
        self.assertEqual(len(puts), 1, fake.calls)
        self.assertIn("pulls/374/merge-async", " ".join(puts[0]))
        self.assertNotIn("pulls/371/merge-async", " ".join(puts[0]))
        prefix_check = ["api", f"repos/{REPO}/pulls/371/merge"]
        self.assertIn(prefix_check, fake.calls)
        graphql_indices = [index for index, call in enumerate(fake.calls)
                           if "api graphql" in " ".join(call)]
        self.assertLess(fake.calls.index(prefix_check), max(graphql_indices))
        self.assertLess(max(graphql_indices), fake.calls.index(puts[0]))
        self.assertIn("pre-existing MERGED", out)
        self.assertIn("skipping it without a PUT", out)
        self.assertNotIn("#371 swept", out)
        self.assertEqual(cutovers, [[374]],
                         "historical branches did not land in this cutover")

    def test_atomic_resumes_after_two_confirmed_historical_members(self):
        fake, dispatch = self._fake(pulls={
            371: [stacked(371, position=1, size=3, stack_number=375,
                          state="MERGED", head="a" * 40),
                  stacked(371, position=1, size=3, stack_number=375,
                          state="MERGED", head="a" * 40)],
            372: [stacked(372, position=2, size=3, stack_number=375,
                          state="MERGED", head="b" * 40),
                  stacked(372, position=2, size=3, stack_number=375,
                          state="MERGED", head="b" * 40)],
            374: [stacked(374, position=3, size=3, stack_number=375,
                          head="c" * 40),
                  stacked(374, position=3, size=3, stack_number=375,
                          head="c" * 40)],
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", "--no-cutover",
             *FAST, "371", "372", "374"])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(fake.ran("--method PUT")), 1, fake.calls)
        self.assertIn(["api", f"repos/{REPO}/pulls/371/merge"], fake.calls)
        self.assertIn(["api", f"repos/{REPO}/pulls/372/merge"], fake.calls)
        self.assertIn("historical merged member(s) were verified", out)

    def test_atomic_refuses_when_historical_prefix_is_not_confirmed_merged(self):
        fake, dispatch = self._fake(pulls={
            371: [stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED"),
                  stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED")],
            374: stacked(374, position=2, size=2, stack_number=375),
        })
        fake.responses = {
            f"pulls/371/merge": (1, "", "gh: Not Found (HTTP 404)"),
            **fake.responses,
        }
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371", "374"])
        self.assertEqual(code, 1, out)
        self.assertIn("GraphQL says MERGED", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_refuses_unknown_historical_confirmation_status(self):
        fake, dispatch = self._fake(pulls={
            371: [stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED"),
                  stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED")],
            374: stacked(374, position=2, size=2, stack_number=375),
        })
        fake.responses = {
            f"pulls/371/merge": (1, "", "gh: Server Error (HTTP 500)"),
            **fake.responses,
        }
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371", "374"])
        self.assertEqual(code, 1, out)
        self.assertIn("neither 204 nor 404", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_refuses_nonleading_merged_member_before_any_put(self):
        fake, dispatch = self._fake(pulls={
            371: stacked(371, position=1, size=3, stack_number=375),
            372: stacked(372, position=2, size=3, stack_number=375,
                         state="MERGED"),
            374: stacked(374, position=3, size=3, stack_number=375),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST,
             "371", "372", "374"])
        self.assertEqual(code, 1, out)
        self.assertIn("one leading contiguous prefix", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_refuses_closed_unmerged_predecessor_before_any_put(self):
        fake, dispatch = self._fake(pulls={
            371: stacked(371, position=1, size=2, stack_number=375,
                         state="CLOSED"),
            374: stacked(374, position=2, size=2, stack_number=375),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371", "374"])
        self.assertEqual(code, 1, out)
        self.assertIn("not OPEN", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_refuses_only_merged_members_before_any_put(self):
        fake, dispatch = self._fake(pulls={
            371: stacked(371, position=1, size=1, stack_number=375,
                         state="MERGED"),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371"])
        self.assertEqual(code, 1, out)
        self.assertIn("only already-MERGED members", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_refuses_resume_topology_drift_before_any_put(self):
        fake, dispatch = self._fake(pulls={
            371: [stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED"),
                  stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED")],
            374: [stacked(374, position=2, size=2, stack_number=375,
                          head="b" * 40),
                  stacked(374, position=2, size=2, stack_number=376,
                          head="b" * 40)],
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371", "374"])
        self.assertEqual(code, 1, out)
        self.assertIn("stack plan changed", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_refuses_resume_base_drift_before_any_put(self):
        fake, dispatch = self._fake(pulls={
            371: [stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED"),
                  stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED")],
            374: [stacked(374, position=2, size=2, stack_number=375,
                          base="main", head="b" * 40),
                  stacked(374, position=2, size=2, stack_number=375,
                          base="release", head="b" * 40)],
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371", "374"])
        self.assertEqual(code, 1, out)
        self.assertIn("base='main'->'release'", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_refuses_resume_state_drift_before_any_put(self):
        fake, dispatch = self._fake(pulls={
            371: [stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED"),
                  stacked(371, position=1, size=2, stack_number=375,
                          state="CLOSED")],
            374: stacked(374, position=2, size=2, stack_number=375),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371", "374"])
        self.assertEqual(code, 1, out)
        self.assertIn("state='MERGED'->'CLOSED'", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_refuses_open_member_that_is_not_mergeable(self):
        fake, dispatch = self._fake(pulls={
            371: [stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED"),
                  stacked(371, position=1, size=2, stack_number=375,
                          state="MERGED")],
            374: stacked(374, position=2, size=2, stack_number=375,
                         mergeable="CONFLICTING"),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "371", "374"])
        self.assertEqual(code, 1, out)
        self.assertIn("not 'MERGEABLE'", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_requires_every_swept_position_to_be_named(self):
        fake, dispatch = self._fake(pulls={
            81: stacked(81, position=1, size=4),
            84: stacked(84, position=4, size=4),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "81", "84"])
        self.assertEqual(code, 1, out)
        self.assertIn("every swept member", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_requires_one_stack(self):
        fake, dispatch = self._fake(pulls={
            81: stacked(81, position=1, size=2, stack_number=88),
            84: stacked(84, position=2, size=2, stack_number=99),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "81", "84"])
        self.assertEqual(code, 1, out)
        self.assertIn("different stacks", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_preflight_refuses_a_moved_member_head_before_the_put(self):
        fake, dispatch = self._fake(pulls={
            81: [stacked(81, position=1, size=2, head="a" * 40),
                 stacked(81, position=1, size=2, head="c" * 40)],
            84: stacked(84, position=2, size=2, head="b" * 40),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "81", "84"])
        self.assertEqual(code, 1, out)
        self.assertIn("head moved", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_preflight_refuses_a_draft_member_before_the_put(self):
        fake, dispatch = self._fake(pulls={
            81: stacked(81, position=1, size=2),
            84: [stacked(84, position=2, size=2),
                 stacked(84, position=2, size=2, draft=True)],
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "81", "84"])
        self.assertEqual(code, 1, out)
        self.assertIn("DRAFT", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_preflight_refuses_a_pending_rollup_before_the_put(self):
        fake, dispatch = self._fake(pulls={
            81: stacked(81, position=1, size=2),
            84: stacked(84, position=2, size=2, check_state="PENDING"),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "81", "84"])
        self.assertEqual(code, 1, out)
        self.assertIn("'PENDING', not 'SUCCESS'", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_preflight_refuses_a_failing_rollup_before_the_put(self):
        fake, dispatch = self._fake(pulls={
            81: stacked(81, position=1, size=2, check_state="FAILURE"),
            84: stacked(84, position=2, size=2),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "81", "84"])
        self.assertEqual(code, 1, out)
        self.assertIn("'FAILURE', not 'SUCCESS'", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_preflight_refuses_a_missing_rollup_before_the_put(self):
        fake, dispatch = self._fake(pulls={
            81: stacked(81, position=1, size=2),
            84: stacked(84, position=2, size=2, check_state=None),
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "81", "84"])
        self.assertEqual(code, 1, out)
        self.assertIn("no usable statusCheckRollup", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_atomic_preflight_refuses_an_unavailable_rollup_shape(self):
        malformed = stacked(84, position=2, size=2)
        del malformed["commits"]["nodes"][0]["commit"]["statusCheckRollup"]
        fake, dispatch = self._fake(pulls={
            81: stacked(81, position=1, size=2),
            84: malformed,
        })
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "81", "84"])
        self.assertEqual(code, 1, out)
        self.assertIn("no usable statusCheckRollup", out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_a_stacked_pr_whose_base_reads_main_is_still_position_checked(self):
        """`baseRefName == main` proves NOTHING inside a stack."""
        fake, dispatch = self._fake(
            pulls={84: stacked(84, position=4, size=7, base="main")})
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "84"])
        self.assertEqual(code, 1)

    def test_a_head_that_moved_since_classification_refuses(self):
        fake, dispatch = self._fake(
            pulls={87: [stacked(87, head="a" * 40), stacked(87, head="c" * 40)]})
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1, out)
        self.assertEqual(fake.ran("--method PUT"), [])

    def test_a_draft_refuses(self):
        fake, dispatch = self._fake(pulls={87: stacked(87, draft=True)})
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1)

    def test_a_closed_pr_refuses(self):
        fake, dispatch = self._fake(pulls={87: stacked(87, state="CLOSED")})
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1)

    def test_an_already_merged_pr_refuses(self):
        fake, dispatch = self._fake(pulls={87: stacked(87, state="MERGED")})
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "87"])
        self.assertEqual(code, 1)

    def test_non_atomic_stack_positions_above_one_refuse_before_any_put(self):
        fake, dispatch = self._fake(pulls={
            87: [stacked(87, position=1, size=2)],
            86: [stacked(86, position=2, size=2),
                 stacked(86, position=2, size=2, state="MERGED")],
        })
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "87", "86"])
        self.assertEqual(code, 1, out)
        self.assertIn("not the bottom", out)
        self.assertEqual(fake.ran("--method PUT"), [])


class TrackBTests(GhTestCase):
    def _fake(self, pulls, *, merge=(0, "", ""), merge_check=(0, "", ""),
              edit=(0, "", "")):
        fake = FakeGh(pulls=pulls)
        responses = {"pr merge": merge, "pr edit": edit, "/merge": merge_check}
        original = FakeGh.__call__

        def dispatch(args):
            fake.calls.append(list(args))
            joined = " ".join(args)
            for needle, response in responses.items():
                if needle in joined:
                    return response
            fake.calls.pop()
            return original(fake, args)

        return fake, dispatch

    def _run(self, fake, dispatch, argv):
        """Return (exit code, stdout AND stderr) — refusals print to stderr."""
        self.install(dispatch)
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = merge_stack.main(argv)
        return code, buffer.getvalue()

    def test_happy_path_merges_then_confirms(self):
        fake, dispatch = self._fake({41: plain(41)})
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "41"])
        self.assertEqual(code, 0, out)
        self.assertTrue(fake.ran("pr merge 41"), fake.calls)
        self.assertTrue(fake.ran("--match-head-commit"), fake.calls)
        self.assertEqual(fake.ran("merge-async"), [])
        self.assertIn("MERGED (confirmed", out)

    def test_ordinary_merge_leaves_check_enforcement_to_branch_protection(self):
        fake, dispatch = self._fake({41: plain(41, check_state="PENDING")})
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "41"])
        self.assertEqual(code, 0, out)
        self.assertTrue(fake.ran("pr merge 41"), fake.calls)

    def test_a_stale_base_refuses_the_198_way(self):
        fake, dispatch = self._fake({198: plain(198, base="chore/08-earlier")})
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "198"])
        self.assertEqual(code, 1, out)
        self.assertEqual(fake.ran("pr merge"), [],
                         "nothing may merge onto a stale base")

    def test_an_explicit_base_is_honoured(self):
        fake, dispatch = self._fake({42: plain(42, base="release")})
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--base", "release", *FAST, "42"])
        self.assertEqual(code, 0, out)

    def test_the_next_pr_is_retargeted_and_read_back(self):
        fake, dispatch = self._fake({
            41: plain(41),
            42: [plain(42, base="feat/01-parser"),
                 plain(42, base="feat/01-parser"), plain(42, base="main"),
                 plain(42, base="main")],
        })
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "41", "42"])
        self.assertEqual(code, 0, out)
        edits = fake.ran("pr edit 42")
        self.assertEqual(edits, [["pr", "edit", "42", "--repo", REPO,
                                  "--base", "main"]], fake.calls)
        self.assertIn("read back and confirmed", out)
        edit_index = fake.calls.index(edits[0])
        self.assertTrue(any("api graphql" in " ".join(call)
                            for call in fake.calls[:edit_index]), fake.calls)
        self.assertTrue(any("api graphql" in " ".join(call)
                            for call in fake.calls[edit_index + 1:]), fake.calls)

    def test_an_already_correct_child_base_is_a_noop_without_edit(self):
        fake, dispatch = self._fake({41: plain(41), 42: plain(42)})
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "41", "42"])
        self.assertEqual(code, 0, out)
        self.assertEqual(fake.ran("pr edit 42"), [], fake.calls)
        self.assertIn("already targets main", out)
        self.assertIn("no duplicate CI", out)

    def test_a_retarget_that_did_not_take_refuses(self):
        """An unverified retarget is the same bug as no retarget."""
        fake, dispatch = self._fake({
            41: plain(41),
            42: [plain(42, base="feat/01-parser")],
        })
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "41", "42"])
        self.assertEqual(code, 1, out)
        self.assertIn("did NOT take", out)
        self.assertEqual(fake.ran("pr merge 42"), [])

    def test_a_failed_retarget_command_refuses(self):
        fake, dispatch = self._fake(
            {41: plain(41), 42: [plain(42, base="feat/01")]},
            edit=(1, "", "gh: Base ref must be a branch"))
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "41", "42"])
        self.assertEqual(code, 1)

    def test_a_403_names_stack_membership_as_the_likely_cause(self):
        fake, dispatch = self._fake({41: plain(41)},
                                    merge=(1, "", "gh: Forbidden (HTTP 403)"))
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "41"])
        self.assertEqual(code, 1, out)

    def test_merge_exit_zero_with_a_404_confirmation_refuses(self):
        fake, dispatch = self._fake({41: plain(41)},
                                    merge_check=(1, "", "gh: (HTTP 404)"))
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "41"])
        self.assertEqual(code, 1)

    def test_a_head_that_moved_since_classification_refuses(self):
        fake, dispatch = self._fake(
            {41: [plain(41, head="b" * 40), plain(41, head="d" * 40)]})
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "41"])
        self.assertEqual(code, 1, out)
        self.assertEqual(fake.ran("pr merge"), [])

    def test_a_draft_refuses(self):
        fake, dispatch = self._fake({41: plain(41, draft=True)})
        code, _ = self._run(fake, dispatch,
                            ["--repo", REPO, "--execute", *FAST, "41"])
        self.assertEqual(code, 1)


class ConfirmationTests(GhTestCase):
    def test_204_is_merged_and_404_is_not(self):
        self.install(lambda args: (0, "", ""))
        self.assertTrue(merge_stack.confirm_merged(REPO, 198))
        self.install(lambda args: (1, "", "gh: Not Found (HTTP 404)"))
        self.assertFalse(merge_stack.confirm_merged(REPO, 40))

    def test_any_other_status_refuses(self):
        self.install(lambda args: (1, "", "gh: Bad gateway (HTTP 502)"))
        with self.assertRaises(merge_stack.Refusal):
            merge_stack.confirm_merged(REPO, 40)


class CliTests(unittest.TestCase):
    """Argument handling only — every case here exits before any `gh` call."""

    def _run(self, argv):
        return subprocess.run([sys.executable, str(SCRIPT), *argv],
                              capture_output=True, text=True)

    def test_squash_is_rejected_at_argument_parsing(self):
        result = self._run(["--squash", "41"])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--squash", result.stderr)
        self.assertIn("review-ledger", result.stderr)

    def test_rebase_is_rejected_at_argument_parsing(self):
        result = self._run(["41", "--rebase"])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--rebase", result.stderr)

    def test_delete_branch_is_rejected_at_argument_parsing(self):
        result = self._run(["--delete-branch", "41"])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("#136", result.stderr)

    def test_short_forms_are_rejected_too(self):
        for flag in ("-s", "-r", "-d"):
            with self.subTest(flag=flag):
                result = self._run([flag, "41"])
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_a_banned_flag_with_a_value_is_rejected(self):
        result = self._run(["--squash=true", "41"])
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_no_pr_numbers_is_a_usage_error(self):
        result = self._run([])
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_help_does_not_advertise_a_banned_strategy_as_a_flag(self):
        result = self._run(["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ("--squash", "--rebase", "--delete-branch"):
            self.assertNotIn(f"  {flag}", result.stdout)
        self.assertIn("--execute", result.stdout)


# ── the post-merge cutover ───────────────────────────────────────────────────
#
# REAL temporary git repositories, never a mock — the convention this repo's own
# workspace suite states in `automation/workspace/tests/_fixtures.py`. Every fact
# asserted below is a fact about GIT (what `merge --ff-only` refuses, what
# `branch -d` refuses, what `merge-tree --write-tree` says about a branch), so a
# mocked git would only prove the mock agrees with the code that wrote it.
#
# THE ENVIRONMENT IS PINNED for the same reason it is pinned there: without
# `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`/`HOME` the developer's own
# `~/.gitconfig` decides commit signing, hook paths and `merge.ff`, so the suite
# passes on one machine and fails on another for reasons no diff explains.
# `merge_stack._run_git` runs git as a SUBPROCESS inheriting `os.environ`, so the
# pinning happens in the process environment.


def pinned_env(home: Path) -> dict:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_AUTHOR_NAME": "Cutover Test",
        "GIT_AUTHOR_EMAIL": "cutover@example.invalid",
        "GIT_COMMITTER_NAME": "Cutover Test",
        "GIT_COMMITTER_EMAIL": "cutover@example.invalid",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "true",
        # A fixture must never reach the network, whatever a ref name looks like.
        "GIT_ALLOW_PROTOCOL": "file",
    }


class CutoverTestCase(unittest.TestCase):
    """A real bare `origin` plus a real main working tree, per test."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name)
        self.home = self.scratch / "home"
        self.home.mkdir()
        previous = {key: os.environ.get(key) for key in pinned_env(self.home)}

        def restore():
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(restore)
        os.environ.update(pinned_env(self.home))

        self.origin = self.scratch / "origin.git"
        self.main = self.scratch / "toolkit"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main",
                        str(self.origin)], check=True, env=dict(os.environ))
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.main)],
                       check=True, env=dict(os.environ))
        self.write("seed.txt", "seed\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base commit")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "-u", "origin", "main")

    # ── helpers ──────────────────────────────────────────────────────────────

    def git(self, *args, repo=None, check=True):
        result = subprocess.run(
            ["git", "-C", str(repo or self.main), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            check=False, env=dict(os.environ))
        if check and result.returncode:
            raise AssertionError(f"git {' '.join(args)} failed "
                                 f"({result.returncode}):\n{result.stderr}")
        return result

    def out(self, *args, **kwargs):
        return self.git(*args, **kwargs).stdout.strip()

    def write(self, name, text, repo=None):
        path = (repo or self.main) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def sha(self, ref="refs/heads/main", repo=None):
        return self.out("rev-parse", ref, repo=repo)

    def advance_origin(self, message="upstream commit"):
        """Land a commit on `origin/main` from somewhere else entirely."""
        pusher = self.scratch / f"pusher-{abs(hash(message)) % 100000}"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(pusher)],
                       check=True, env=dict(os.environ))
        self.write(f"{message.replace(' ', '-')}.txt", message + "\n", repo=pusher)
        self.git("add", "-A", repo=pusher)
        self.git("commit", "-q", "-m", message, repo=pusher)
        self.git("push", "-q", "origin", "main", repo=pusher)
        return self.sha("refs/heads/main", repo=pusher)

    def cutover(self, branches=(), start=None, **kwargs):
        lines: list[str] = []
        merge_stack.cutover(list(branches), start=str(start or self.main),
                            emit=lines.append, **kwargs)
        return "\n".join(lines)

    def branches(self):
        return set(self.out("for-each-ref", "--format=%(refname:short)",
                            "refs/heads").split())


class CutoverFastForwardTests(CutoverTestCase):
    def test_a_clean_fast_forward_moves_main_and_receipts_both_shas(self):
        before = self.sha()
        expected = self.advance_origin("first upstream commit")
        out = self.cutover()
        self.assertNotIn("REFUSED", out)
        self.assertIn(f"receipt: main {before[:12]}..{expected[:12]}, 1 commits",
                      out)
        self.assertEqual(self.sha(), expected)
        self.assertEqual(self.out("status", "--porcelain"), "")

    def test_already_up_to_date_is_a_zero_commit_receipt_not_silence(self):
        before = self.sha()
        out = self.cutover()
        self.assertNotIn("REFUSED", out)
        self.assertIn(f"receipt: main {before[:12]}..{before[:12]}, 0 commits",
                      out)
        self.assertIn("gap: none", out)
        self.assertEqual(self.sha(), before)

    def test_the_main_working_tree_is_found_from_a_linked_worktree(self):
        linked = self.scratch / "linked"
        self.git("worktree", "add", "-q", "-b", "side", str(linked), "main")
        self.assertEqual(merge_stack.find_main_worktree(str(linked)),
                         os.path.realpath(self.main))
        before = self.sha()
        expected = self.advance_origin("upstream while in a worktree")
        out = self.cutover(start=linked)
        self.assertIn(f"main working tree: {os.path.realpath(self.main)}", out)
        self.assertIn(f"receipt: main {before[:12]}..{expected[:12]}, 1 commits",
                      out)
        self.assertEqual(self.sha(), expected)


class CutoverRefusalTests(CutoverTestCase):
    def assertRefused(self, out, fragment):
        self.assertIn("CUTOVER REFUSED", out)
        self.assertIn(fragment, out)
        self.assertIn("receipt: main ", out)

    def test_a_dirty_main_working_tree_is_refused_and_nothing_moves(self):
        """The live case: a concurrent session's uncommitted work."""
        before = self.sha()
        self.advance_origin("upstream commit")
        self.write("seed.txt", "a concurrent session is editing this\n")
        out = self.cutover()
        self.assertRefused(out, "uncommitted changes to 1 tracked path")
        self.assertIn("seed.txt", out)
        self.assertIn(f"receipt: main {before[:12]}..{before[:12]}, 0 commits",
                      out)
        self.assertIn("gap: local main is 1 commit(s) behind", out)
        self.assertEqual(self.sha(), before)
        self.assertEqual(
            (self.main / "seed.txt").read_text(encoding="utf-8"),
            "a concurrent session is editing this\n")

    def test_untracked_files_alone_do_not_block_the_fast_forward(self):
        expected = self.advance_origin("upstream commit")
        self.write("scratch.md", "not on any branch\n")
        out = self.cutover()
        self.assertNotIn("REFUSED", out)
        self.assertIn("1 untracked path(s)", out)
        self.assertEqual(self.sha(), expected)
        self.assertTrue((self.main / "scratch.md").exists())

    def test_a_diverged_local_main_is_refused(self):
        self.advance_origin("upstream commit")
        self.write("local.txt", "local only\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "a local commit on main")
        before = self.sha()
        out = self.cutover()
        self.assertRefused(out, "DIVERGED")
        self.assertIn("1 commit(s) that origin/main does not have", out)
        self.assertEqual(self.sha(), before)

    def test_main_checked_out_in_another_worktree_is_refused(self):
        self.git("switch", "-q", "-c", "side")
        other = self.scratch / "other"
        self.git("worktree", "add", "-q", str(other), "main")
        before = self.sha()
        self.advance_origin("upstream commit")
        out = self.cutover()
        self.assertRefused(out, "main is checked out in")
        self.assertIn(str(other), out)
        self.assertEqual(self.sha(), before)

    def test_main_not_checked_out_at_all_is_refused(self):
        self.git("switch", "-q", "-c", "side")
        before = self.sha()
        self.advance_origin("upstream commit")
        out = self.cutover()
        self.assertRefused(out, "does not have main checked out")
        self.assertIn("HEAD is side", out)
        self.assertEqual(self.sha(), before)

    def test_no_origin_remote_is_refused(self):
        before = self.sha()
        self.git("remote", "remove", "origin")
        out = self.cutover()
        self.assertRefused(out, "no remote named 'origin'")
        self.assertIn(f"receipt: main {before[:12]}..{before[:12]}, 0 commits",
                      out)
        self.assertIn("gap: UNKNOWN", out)

    def test_a_failed_fetch_is_refused(self):
        before = self.sha()
        shutil.rmtree(self.origin)
        out = self.cutover()
        self.assertRefused(out, "git fetch origin` exited")
        self.assertIn(f"receipt: main {before[:12]}..{before[:12]}, 0 commits",
                      out)
        self.assertIn("gap: UNKNOWN", out)

    def test_an_in_progress_operation_is_refused(self):
        before = self.sha()
        self.advance_origin("upstream commit")
        (self.main / ".git" / "MERGE_HEAD").write_text(before + "\n",
                                                       encoding="utf-8")
        out = self.cutover()
        self.assertRefused(out, "a merge is in progress")
        self.assertEqual(self.sha(), before)

    def test_every_refusal_says_the_merge_itself_is_unaffected(self):
        self.git("remote", "remove", "origin")
        out = self.cutover()
        self.assertIn("The merge itself is unaffected", out)


class BranchRetirementTests(CutoverTestCase):
    def land_branch(self, name="feat/x", body="branch work\n"):
        """A branch whose content `origin/main` ends up carrying."""
        self.git("switch", "-q", "-c", name)
        self.write(f"{name.replace('/', '-')}.txt", body)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"{name}: the work")
        self.git("push", "-q", "-u", "origin", name)
        self.git("push", "-q", "origin", f"{name}:main")
        self.git("switch", "-q", "main")
        return name

    def test_a_merged_branch_with_no_worktree_is_deleted_with_dash_d(self):
        name = self.land_branch()
        out = self.cutover([name])
        self.assertIn(f"branch {name}: DELETED locally", out)
        self.assertNotIn(name, self.branches())
        # The REMOTE branch is untouched, deliberately: deleting a base branch
        # closed #136, and remote sweeping is the owner's call.
        self.assertIn(f"{name}", self.out("for-each-ref",
                                          "--format=%(refname:short)",
                                          "refs/remotes"))
        self.assertIn(f"origin/{name} is now retirable on the remote", out)
        self.assertIn("deletes NO remote branch", out)
        self.assertEqual(
            self.out("for-each-ref", "--format=%(refname:short)",
                     f"refs/heads/{name}", repo=self.origin), name)

    def test_a_branch_checked_out_in_a_worktree_is_kept_with_the_reason(self):
        name = self.land_branch()
        held = self.scratch / "held"
        self.git("worktree", "add", "-q", str(held), name)
        out = self.cutover([name])
        self.assertIn(f"branch {name}: KEPT -- checked out in the worktree", out)
        self.assertIn(str(held), out)
        self.assertIn("never removes a worktree", out)
        self.assertIn("automation/workspace/cleanup.py", out)
        self.assertIn(name, self.branches())
        self.assertTrue(held.exists())

    def test_a_branch_that_is_not_contained_is_kept_with_the_reason(self):
        self.git("switch", "-q", "-c", "feat/unmerged")
        self.write("unique.txt", "nothing upstream has this\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "feat/unmerged: unique work")
        self.git("switch", "-q", "main")
        out = self.cutover(["feat/unmerged"])
        self.assertIn("branch feat/unmerged: KEPT -- its content is NOT "
                      "contained in origin/main", out)
        self.assertIn("feat/unmerged", self.branches())

    def test_the_probe_is_containment_not_ancestry(self):
        """A squash-merge: `git branch --merged` misses it, merge-tree does not.

        It is still KEPT, and that is the honest answer rather than a gap in the
        probe: `git branch -d` asks a DIFFERENT question (ancestry of the
        branch's upstream, or of HEAD when it has none), and a squash-merged
        branch with no upstream is an ancestor of neither. Containment decides
        whether this tool may PROPOSE the deletion; git decides whether it
        happens, and git's "no" is reported verbatim instead of forced past.
        """
        self.git("switch", "-q", "-c", "feat/squashed")
        self.write("squashed.txt", "squashed content\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "feat/squashed: the work")
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--squash", "feat/squashed")
        self.git("commit", "-q", "-m", "squash-merge of feat/squashed")
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")

        self.assertNotIn("feat/squashed",
                         self.out("branch", "--merged", "origin/main"))
        self.assertEqual(
            merge_stack.containment(str(self.main), "origin/main",
                                    "feat/squashed"),
            merge_stack.CONTAINED)

        out = self.cutover(["feat/squashed"])
        self.assertIn("branch feat/squashed: KEPT", out)
        self.assertIn("`git branch -d` declined", out)
        self.assertIn("feat/squashed", self.branches())

    def test_whitespace_only_duplication_is_not_called_contained(self):
        """`git patch-id` calls these identical. The merge-tree probe does not.

        A patch-id probe here would be a data-loss answer, so it is not used:
        an 8-space and a 2-space Python body produce the SAME patch id.
        """
        self.git("switch", "-q", "-c", "ws-variant")
        self.write("indent.py", "def f():\n        return 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "ws-variant: eight-space body")
        self.git("switch", "-q", "main")
        self.write("indent.py", "def f():\n  return 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "main: two-space body")
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")
        self.assertEqual(
            merge_stack.containment(str(self.main), "origin/main", "ws-variant"),
            merge_stack.NOT_CONTAINED)
        out = self.cutover(["ws-variant"])
        self.assertIn("branch ws-variant: KEPT -- its content is NOT contained",
                      out)
        self.assertIn("ws-variant", self.branches())

    def test_an_unanswerable_containment_probe_keeps_the_branch(self):
        self.assertEqual(
            merge_stack.containment(str(self.main), "origin/no-such-base",
                                    "main"),
            merge_stack.CONTAINMENT_UNKNOWN)

    def test_a_branch_git_refuses_to_delete_is_kept_with_gits_own_reason(self):
        """Contained in `origin/main`, but AHEAD of its own upstream.

        `git branch -d` judges against the branch's upstream, not against the
        base ref this probe tested, so it declines — and the only ways to make
        it accept are `-D`, `update-ref -d`, or unsetting the upstream, all of
        which work by removing the evidence git consults. So: KEPT.
        """
        name = self.land_branch("feat/ahead")
        self.git("switch", "-q", name)
        self.git("commit", "-q", "--allow-empty", "-m", "an unpushed commit")
        self.git("switch", "-q", "main")
        out = self.cutover([name])
        self.assertIn(f"branch {name}: KEPT", out)
        self.assertIn("`git branch -d` declined", out)
        self.assertIn("There is no -D here", out)
        self.assertIn(name, self.branches())

    def test_a_branch_that_does_not_exist_locally_is_reported_not_invented(self):
        out = self.cutover(["feat/never-existed"])
        self.assertIn("branch feat/never-existed: nothing to retire", out)

    def test_no_branch_is_retired_when_the_fetch_never_succeeded(self):
        name = self.land_branch()
        self.git("remote", "remove", "origin")
        out = self.cutover([name])
        self.assertIn("branch retirement: SKIPPED", out)
        self.assertIn(name, self.branches())

    def test_a_dirty_tree_refuses_the_fast_forward_but_still_retires(self):
        """Retirement touches no working tree, so a dirty tree does not stop it."""
        name = self.land_branch()
        self.write("seed.txt", "concurrent edit\n")
        out = self.cutover([name])
        self.assertIn("CUTOVER REFUSED", out)
        self.assertIn(f"branch {name}: DELETED locally", out)


class ForcedDeletionBanTests(unittest.TestCase):
    """A test that fails if anyone ever adds `-D` or `--force` to this module."""

    def test_the_only_deletion_command_is_git_branch_dash_d(self):
        self.assertEqual(merge_stack.branch_delete_argv("feat/x"),
                         ["branch", "-d", "feat/x"])

    def test_no_forcing_flag_is_spelled_anywhere_in_the_module(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)}
        for banned in ("-D", "--force", "--delete --force", "-f -d", "-df"):
            self.assertNotIn(
                banned, literals,
                f"{banned!r} appears as a string literal in merge_stack.py. "
                "This repo bans forced branch deletion outright: `-d` makes git "
                "prove containment before deleting, and every way of making git "
                "skip that proof works by removing the evidence it consults.")

    def test_update_ref_d_is_not_used_either(self):
        """Plumbing with no safety check at all is strictly more forcing."""
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)}
        self.assertNotIn("update-ref", literals)
        self.assertNotIn("--unset-upstream", literals)


class CutoverWiringTests(GhTestCase):
    """How `main()` calls the cutover — and when it must not."""

    def test_a_dry_run_never_touches_git(self):
        fake = FakeGh(pulls={41: plain(41)})
        code, out = self.run_main(["--repo", REPO, "41"], fake)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.git.calls, [])
        self.assertIn("cutover runs only under --execute", out)

    def test_no_cutover_skips_the_whole_step(self):
        fake = FakeGh(
            pulls={41: plain(41)},
            responses={"pr merge 41": (0, "", ""),
                       "pulls/41/merge": (0, "", "")})
        code, out = self.run_main(
            ["--repo", REPO, "--execute", "--no-cutover", "41", *FAST], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("#41 MERGED", out)
        self.assertIn("SKIPPED (--no-cutover)", out)
        self.assertEqual(self.git.calls, [])

    def test_the_cutover_runs_after_an_ordinary_merge(self):
        fake = FakeGh(
            pulls={41: dict(plain(41), headRefName="feat/x")},
            responses={"pr merge 41": (0, "", ""),
                       "pulls/41/merge": (0, "", "")})
        code, out = self.run_main(
            ["--repo", REPO, "--execute", "41", *FAST], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("Post-merge cutover:", out)
        self.assertTrue(self.git.ran("rev-parse --git-dir --git-common-dir"))

    def test_a_pr_with_no_head_ref_name_still_cuts_over(self):
        fake = FakeGh(
            pulls={41: plain(41)},
            responses={"pr merge 41": (0, "", ""),
                       "pulls/41/merge": (0, "", "")})
        code, out = self.run_main(
            ["--repo", REPO, "--execute", "41", *FAST], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("no head branch name in the classification payload", out)


class CutoverNeverFailsTheMergeTests(CutoverTestCase):
    """A refused cutover must never report a merged PR as un-merged."""

    def _fake_gh(self):
        return FakeGh(
            pulls={41: dict(plain(41), headRefName="feat/x")},
            responses={"pr merge 41": (0, "", ""),
                       "pulls/41/merge": (0, "", "")})

    def _run(self, argv, fake):
        original_gh, original_git = merge_stack._run_gh, merge_stack._run_git
        merge_stack._run_gh = fake
        merge_stack._run_git = REAL_RUN_GIT
        self.addCleanup(lambda: setattr(merge_stack, "_run_gh", original_gh))
        self.addCleanup(lambda: setattr(merge_stack, "_run_git", original_git))
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = merge_stack.main(argv)
        return code, buffer.getvalue()

    def test_a_dirty_tree_refusal_leaves_the_merge_reported_as_merged(self):
        self.advance_origin("upstream commit")
        self.write("seed.txt", "a concurrent session is editing this\n")
        before = self.sha()
        code, out = self._run(
            ["--repo", REPO, "--execute", "--cutover-root", str(self.main),
             "41", *FAST], self._fake_gh())
        self.assertEqual(code, 0, out)
        self.assertIn("#41 MERGED (confirmed by GET /pulls/41/merge -> 204).",
                      out)
        self.assertIn("All named pull requests merged and independently "
                      "confirmed.", out)
        self.assertIn("CUTOVER REFUSED", out)
        self.assertIn("receipt: main ", out)
        self.assertNotIn("REFUSED --", out.split("CUTOVER REFUSED")[0])
        self.assertEqual(self.sha(), before)

    def test_a_clean_tree_cuts_over_from_main_and_receipts_it(self):
        before = self.sha()
        expected = self.advance_origin("upstream commit")
        code, out = self._run(
            ["--repo", REPO, "--execute", "--cutover-root", str(self.main),
             "41", *FAST], self._fake_gh())
        self.assertEqual(code, 0, out)
        self.assertIn(f"receipt: main {before[:12]}..{expected[:12]}, 1 commits",
                      out)
        self.assertEqual(self.sha(), expected)


class WorktreeParsingTests(unittest.TestCase):
    def test_branch_detached_and_bare_entries_are_all_read(self):
        entries = merge_stack.parse_worktrees(
            "worktree /repo\n"
            "HEAD abc\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /repo/wt/one\n"
            "HEAD def\n"
            "detached\n"
            "\n"
            "worktree /bare\n"
            "bare\n")
        self.assertEqual([entry["path"] for entry in entries],
                         ["/repo", "/repo/wt/one", "/bare"])
        self.assertEqual(entries[0]["branch"], "main")
        self.assertIsNone(entries[1]["branch"])
        self.assertTrue(entries[1]["detached"])
        self.assertTrue(entries[2]["bare"])
        self.assertEqual(merge_stack.worktree_holding(entries, "main"), "/repo")
        self.assertIsNone(merge_stack.worktree_holding(entries, "nope"))


if __name__ == "__main__":
    unittest.main()
