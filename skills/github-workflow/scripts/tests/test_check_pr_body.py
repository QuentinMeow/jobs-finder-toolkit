"""Tests for `check_pr_body.py` — the human-facing PR-description format checker.

Run with (from the repo root):
    .venv/bin/python -m unittest discover skills/github-workflow/scripts/tests

The module is loaded from its absolute path rather than imported by name: a
skill's `scripts/` is not a package on `sys.path`, and nothing here may reach
repo-root Python (`handbook/skills-and-vendoring.md`).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check_pr_body.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_pr_body", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_pr_body = _load()


GOOD_BODY = textwrap.dedent("""\
    ## What changes for you

    ### Renaming an export

    **Before.** `export.py` wrote `out.csv` and overwrote any file already there,
    so a second run silently replaced the first run's output.

    **After.** It writes `out-<date>.csv` and refuses to overwrite an existing
    file.

    **What you'll notice.** Old scripts that read `out.csv` by name stop finding
    it; point them at the dated name. Reruns now leave one file per day in the
    directory, so you will have to clean it out yourself.

    ## What & why

    The overwrite was reported twice. Dating the file is the smallest fix that
    keeps both runs.

    ## Verification

    ```
    $ python -m unittest discover tests
    OK
    ```
    """)


class CheckFunctionTests(unittest.TestCase):
    def test_good_body_passes(self):
        self.assertEqual(check_pr_body.check(GOOD_BODY), [])

    def test_first_section_must_be_human_facing(self):
        body = GOOD_BODY.replace("## What changes for you", "## Summary", 1)
        findings = check_pr_body.check(body)
        self.assertTrue(findings, "a body opening with `## Summary` must fail")
        self.assertTrue(
            any("human-facing section" in message for _, message in findings),
            findings,
        )

    def test_missing_before_and_after_fails(self):
        body = textwrap.dedent("""\
            ## What changes for you

            The exporter now writes a dated filename.

            ## What & why

            Two people hit the overwrite.
            """)
        findings = check_pr_body.check(body)
        messages = [message for _, message in findings]
        self.assertTrue(any("`**Before.**`" in m for m in messages), messages)
        self.assertTrue(any("`**After.**`" in m for m in messages), messages)

    def test_missing_after_alone_fails(self):
        body = GOOD_BODY.replace("**After.**", "Now", 1)
        messages = [message for _, message in check_pr_body.check(body)]
        self.assertTrue(any("`**After.**`" in m for m in messages), messages)
        self.assertFalse(any("`**Before.**`" in m for m in messages), messages)

    def test_marketing_word_is_flagged(self):
        body = GOOD_BODY.replace(
            "It writes `out-<date>.csv`",
            "It leverages a robust naming scheme and writes `out-<date>.csv`",
            1,
        )
        messages = [message for _, message in check_pr_body.check(body)]
        self.assertTrue(any("'leverages'" in m for m in messages), messages)
        self.assertTrue(any("'robust'" in m for m in messages), messages)

    def test_hyphenated_marketing_word_is_flagged(self):
        body = GOOD_BODY + "\nThis is a cutting-edge change.\n"
        messages = [message for _, message in check_pr_body.check(body)]
        self.assertTrue(any("cutting-edge" in m for m in messages), messages)

    def test_inline_code_is_exempt(self):
        """A body may NAME a banned word by backticking it."""
        body = GOOD_BODY + "\nThe checker rejects a word like `seamless`.\n"
        self.assertEqual(check_pr_body.check(body), [])

    def test_marketing_word_outside_backticks_still_flagged_on_same_line(self):
        body = GOOD_BODY + "\nA robust fix, unlike `seamless` prose.\n"
        messages = [message for _, message in check_pr_body.check(body)]
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("'robust'", messages[0])

    def test_code_fences_are_exempt(self):
        body = GOOD_BODY + textwrap.dedent("""\

            ```
            WARNING: robust_mode is deprecated
            ## Summary of run
            ```
            """)
        self.assertEqual(check_pr_body.check(body), [])

    def test_no_heading_at_all_fails(self):
        findings = check_pr_body.check("Just a sentence about the change.\n")
        self.assertTrue(any("no `##` heading" in m for _, m in findings), findings)


class CliTests(unittest.TestCase):
    def _run(self, argv, stdin=""):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv],
            input=stdin, capture_output=True, text=True,
        )

    def test_reads_from_stdin(self):
        result = self._run([], stdin=GOOD_BODY)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)

    def test_stdin_failure_reports_findings_and_exits_1(self):
        result = self._run([], stdin=GOOD_BODY.replace(
            "## What changes for you", "## Summary", 1))
        self.assertEqual(result.returncode, 1)
        self.assertIn("human-facing section", result.stderr)

    def test_reads_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.md"
            path.write_text(GOOD_BODY, encoding="utf-8")
            result = self._run([str(path)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_input_exits_2(self):
        result = self._run([], stdin="   \n")
        self.assertEqual(result.returncode, 2)

    def test_missing_file_exits_2(self):
        result = self._run(["/nonexistent/pr-body.md"])
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
