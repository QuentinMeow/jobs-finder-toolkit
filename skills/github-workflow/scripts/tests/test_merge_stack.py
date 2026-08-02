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

import importlib.util
import io
import json
import subprocess
import sys
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

REPO = "owner/name"
UUID = "3f2b1c9a-0d4e-4f6a-8b1c-2d3e4f5a6b7c"


def stacked(number, *, position=1, size=3, stack_number=88, state="OPEN",
            base="main", head="a" * 40, draft=False, mergeable="MERGEABLE"):
    return {
        "number": number, "state": state, "isDraft": draft,
        "baseRefName": base, "headRefOid": head, "mergeable": mergeable,
        "stackEntry": {"position": position,
                       "stack": {"number": stack_number, "size": size}},
    }


def plain(number, *, state="OPEN", base="main", head="b" * 40, draft=False,
          mergeable="MERGEABLE"):
    return {
        "number": number, "state": state, "isDraft": draft,
        "baseRefName": base, "headRefOid": head, "mergeable": mergeable,
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


class GhTestCase(unittest.TestCase):
    def install(self, fake):
        self._original = merge_stack._run_gh
        merge_stack._run_gh = fake
        self.addCleanup(lambda: setattr(merge_stack, "_run_gh", self._original))
        return fake

    def run_main(self, argv, fake):
        """Return (exit code, stdout AND stderr) — refusals print to stderr."""
        self.install(fake)
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
        fake = FakeGh(pulls={87: stacked(87, position=7, size=7)})
        code, out = self.run_main(["--repo", REPO, "87"], fake)
        self.assertEqual(code, 0, out)
        self.assertIn("#87", out)
        self.assertIn("#88 pos 7/7", out)
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

    def test_atomic_allows_it_on_purpose(self):
        fake, dispatch = self._fake(pulls={84: stacked(84, position=4, size=7)})
        code, out = self._run(
            fake, dispatch,
            ["--repo", REPO, "--execute", "--atomic", *FAST, "84"])
        self.assertEqual(code, 0, out)

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

    def test_an_atomic_sweep_is_reported_and_skipped(self):
        """Merging entry k lands 1..k; a PR named later can already be merged."""
        fake, dispatch = self._fake(pulls={
            87: [stacked(87, position=1, size=2)],
            86: [stacked(86, position=2, size=2),
                 stacked(86, position=2, size=2, state="MERGED")],
        })
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "87", "86"])
        self.assertEqual(code, 0, out)
        self.assertIn("swept into the same atomic merge", out)
        self.assertEqual(len(fake.ran("--method PUT")), 1)


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
            42: [plain(42, base="feat/01-parser"), plain(42, base="main"),
                 plain(42, base="main")],
        })
        code, out = self._run(fake, dispatch,
                              ["--repo", REPO, "--execute", *FAST, "41", "42"])
        self.assertEqual(code, 0, out)
        self.assertTrue(fake.ran("pr edit 42"), fake.calls)
        self.assertIn("read back and confirmed", out)

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


if __name__ == "__main__":
    unittest.main()
