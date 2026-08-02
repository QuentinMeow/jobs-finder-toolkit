"""Tests for `check_pr_body.py` — the human-facing PR-description format checker.

Run with (from the repo root):
    .venv/bin/python -m unittest discover skills/github-workflow/scripts/tests

The module is loaded from its absolute path rather than imported by name: a
skill's `scripts/` is not a package on `sys.path`, and nothing here may reach
repo-root Python (`docs/handbook/skills-and-vendoring.md`).
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


SKILL_EDIT = ["skills/job-search/SKILL.md", "automation/shared/config.py"]
NO_SKILL_EDIT = ["automation/shared/config.py", "docs/handbook/repo-map.md"]

# The checklist item in .github/pull_request_template.md quotes the skip line's
# FORM inside backticks and keeps writing after it. Quoting a form is not
# discharging a gate, so this text must never satisfy the property.
TEMPLATE_CHECKLIST_LINE = (
    "- [ ] If any `skills/*/SKILL.md` / `LESSONS.md` / `reference.md` changed: per "
    "the risk-based gate, either ran that skill's canaries in "
    "`evals/canaries/<skill>.yaml` and pasted results below, or recorded a one-line "
    "skip rationale (`Eval gate: skipped — <intention + size>`) — see "
    "`evals/README.md`\n"
)

# The same checklist item after the template was rewritten to name all three
# forms. It quotes TWO of them, and mentions `tasks/0_backlog/` in the same
# breath — so a PR that happens to add a backlog item for its own reasons must
# still not be discharged by the unfilled template text.
TEMPLATE_CHECKLIST_LINE_THREE_FORMS = (
    "- [ ] If any `skills/*/SKILL.md` / `LESSONS.md` / `reference.md` changed: "
    "discharge the risk-based eval gate in this body — CI's `pr-body` job blocks "
    "on it. Exactly one of: that skill's canary results from "
    "`evals/canaries/<skill>.yaml` pasted below (or the `evals/results/` record "
    "named); `Eval gate: skipped — <intention + size>` with the rationale actually "
    "written out; `Eval gate: debt — <why not now>` plus a `tasks/0_backlog/` item "
    "named here and added by this same diff. The bracketed placeholders are not "
    "rationales — see `evals/README.md`\n"
)

# The checklist item once the `stack` form joined it. It quotes a fourth form whose
# whole content is a NAMED tip — so the quoted placeholder (`tip: <#PR or branch>`)
# must not read as a naming.
TEMPLATE_CHECKLIST_LINE_FOUR_FORMS = (
    "- [ ] If any `skills/*/SKILL.md` / `LESSONS.md` / `reference.md` changed: "
    "discharge the risk-based eval gate in this body — CI's `pr-body` job blocks "
    "on it. Exactly one of: that skill's canary results from "
    "`evals/canaries/<skill>.yaml` pasted below (or the `evals/results/` record "
    "named); `Eval gate: skipped — <intention + size>` with the rationale actually "
    "written out; `Eval gate: stack — <why this one is intermediate>; "
    "tip: <#PR or branch>` when this is an intermediate PR of a stack and the run "
    "happens once at the named tip; `Eval gate: debt — <why not now>` plus a "
    "`tasks/0_backlog/` item named here and added by this same diff. The bracketed "
    "placeholders are not rationales — see `evals/README.md`\n"
)

# The tracked template itself. An unfilled template must discharge nothing, and the
# constants above are only a copy of it — this is the file CI's `pr-body` job meets.
TRACKED_TEMPLATE = (Path(__file__).resolve().parents[4]
                    / ".github" / "pull_request_template.md")


class EvalGateTests(unittest.TestCase):
    """Property 4 — a harness edit must discharge the risk-based eval gate."""

    def test_inert_without_a_diff(self):
        """A body checked on its own is checked for the three format properties."""
        self.assertEqual(check_pr_body.check(GOOD_BODY), [])
        self.assertEqual(check_pr_body.check(GOOD_BODY + "\nEval gate: nothing\n"), [])

    def test_diff_without_skill_instruction_files_does_not_trigger(self):
        self.assertEqual(check_pr_body.check(GOOD_BODY, NO_SKILL_EDIT), [])

    def test_skill_edit_with_no_discharge_fails(self):
        findings = check_pr_body.check(GOOD_BODY, SKILL_EDIT)
        self.assertEqual(len(findings), 1, findings)
        location, message = findings[0]
        self.assertEqual(location, "eval gate")
        self.assertIn("skills/job-search/SKILL.md", message)

    def test_named_eval_record_discharges(self):
        body = GOOD_BODY + "\nCanaries ran: `evals/results/job-search-abc1234-20260801.md`.\n"
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_ran_line_with_a_result_discharges(self):
        body = GOOD_BODY + "\nEval gate: ran — job-search canaries, 4 of 4 PASS, no\nregression.\n"
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_bare_ran_line_without_evidence_fails(self):
        body = GOOD_BODY + "\nEval gate: ran\n"
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("does not say what ran" in m for m in messages), messages)

    def test_written_skip_rationale_discharges(self):
        body = GOOD_BODY + ("\nEval gate: skipped — one path corrected to match the "
                            "script's real flag; no step semantics changed.\n")
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_placeholder_skip_rationale_fails(self):
        body = GOOD_BODY + "\nEval gate: skipped — <intention + size>\n"
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("template placeholder" in m for m in messages), messages)

    def test_template_checklist_line_is_not_a_discharge(self):
        body = GOOD_BODY + "\n" + TEMPLATE_CHECKLIST_LINE
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(messages, "the unfilled template must not discharge")
        self.assertTrue(any("inline code span" in m for m in messages), messages)

    def test_three_form_template_line_is_not_a_discharge(self):
        body = GOOD_BODY + "\n" + TEMPLATE_CHECKLIST_LINE_THREE_FORMS
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(messages, "the unfilled template must not discharge")

    def test_three_form_template_line_does_not_ride_an_unrelated_backlog_item(self):
        """Its quoted `debt` form + its mention of the backlog folder must not pair up."""
        body = GOOD_BODY + "\n" + TEMPLATE_CHECKLIST_LINE_THREE_FORMS
        changed = SKILL_EDIT + ["tasks/0_backlog/2026-08-01-something-unrelated/task.md"]
        self.assertTrue(check_pr_body.check(body, changed),
                        "quoted template text must not discharge via a backlog item "
                        "the PR added for its own reasons")

    def test_four_form_template_line_is_not_a_discharge(self):
        body = GOOD_BODY + "\n" + TEMPLATE_CHECKLIST_LINE_FOUR_FORMS
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(messages, "the unfilled template must not discharge")

    @unittest.skipUnless(TRACKED_TEMPLATE.is_file(),
                         f"{TRACKED_TEMPLATE} is not in this checkout")
    def test_the_tracked_pr_template_discharges_nothing(self):
        """The file CI actually meets, unfilled, must fail the gate."""
        body = TRACKED_TEMPLATE.read_text(encoding="utf-8")
        self.assertTrue(check_pr_body.check_eval_gate(body, SKILL_EDIT),
                        "an unfilled .github/pull_request_template.md must not "
                        "discharge the eval gate")

    def test_inline_code_inside_a_rationale_is_not_truncation(self):
        """The reported defect: a code span mid-sentence swallowed the rationale.

        The line was read only as far as the first backtick — two words — and the
        finding then reported an empty rationale at an author who had written one.
        """
        body = GOOD_BODY + ("\nEval gate: ran — the four `github-workflow` canaries, "
                            "4/4 pass\n")
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_inline_code_inside_a_skip_rationale_is_not_truncation(self):
        body = GOOD_BODY + ("\nEval gate: skipped — corrected the `--strict` flag "
                            "name in one line; no step semantics changed.\n")
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_a_rationale_written_only_in_code_says_why_it_failed(self):
        body = GOOD_BODY + "\nEval gate: skipped — `a typo in one path`\n"
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("read as a quotation" in m for m in messages), messages)

    def test_a_fully_quoted_eval_line_says_why_it_failed(self):
        body = GOOD_BODY + "\nSee `Eval gate: skipped — a real rationale` for the form.\n"
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("inline code span" in m for m in messages), messages)

    def test_debt_with_a_backlog_item_in_the_same_diff_discharges(self):
        body = GOOD_BODY + ("\nEval gate: debt — canaries cost a full session at this "
                            "batch size; filed\n"
                            "`tasks/0_backlog/2026-08-01-run-job-search-canaries/task.md`.\n")
        changed = SKILL_EDIT + ["tasks/0_backlog/2026-08-01-run-job-search-canaries/task.md"]
        self.assertEqual(check_pr_body.check(body, changed), [])

    def test_debt_may_name_the_task_folder(self):
        body = GOOD_BODY + ("\nEval gate: debt — filed "
                            "tasks/0_backlog/2026-08-01-run-job-search-canaries\n")
        changed = SKILL_EDIT + ["tasks/0_backlog/2026-08-01-run-job-search-canaries/task.md"]
        self.assertEqual(check_pr_body.check(body, changed), [])

    def test_debt_whose_backlog_item_is_not_in_the_diff_fails(self):
        """Tracked debt means the item lands with the PR that owes it."""
        body = GOOD_BODY + ("\nEval gate: debt — filed "
                            "`tasks/0_backlog/2026-08-01-run-job-search-canaries/task.md`.\n")
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("adds nothing under it" in m for m in messages), messages)

    def test_debt_naming_no_item_fails(self):
        body = GOOD_BODY + "\nEval gate: debt — will run these later.\n"
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("names no `tasks/0_backlog/` item" in m for m in messages),
                        messages)

    def test_a_near_prefix_backlog_path_does_not_count(self):
        body = GOOD_BODY + "\nEval gate: debt — filed tasks/0_backlog/2026-08-01-run\n"
        changed = SKILL_EDIT + ["tasks/0_backlog/2026-08-01-runner-unrelated/task.md"]
        messages = [m for _, m in check_pr_body.check(body, changed)]
        self.assertTrue(any("adds nothing under it" in m for m in messages), messages)

    def test_stack_form_naming_a_pr_number_discharges(self):
        body = GOOD_BODY + ("\nEval gate: stack — intermediate PR of a four-branch "
                            "stack; the job-search canaries run once at the tip: "
                            "#137\n")
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_stack_form_naming_a_branch_discharges(self):
        body = GOOD_BODY + ("\nEval gate: stack — intermediate; tip: "
                            "feat/04-jd-renderer runs them\n")
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_stack_tip_in_backticks_discharges(self):
        """A branch name is an identifier — code spans are where people put those."""
        body = GOOD_BODY + ("\nEval gate: stack — intermediate PR; tip: "
                            "`feat/04-jd-renderer`.\n")
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_stack_form_accepts_a_pull_request_url(self):
        body = GOOD_BODY + ("\nEval gate: stack — tip: "
                            "https://github.com/o/r/pull/137\n")
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_bare_stack_line_without_a_tip_fails(self):
        """"It's a stack" is a form every PR can type — it commits to nobody."""
        for text in ("Eval gate: stack",
                     "Eval gate: stack — this is an intermediate PR in a stack and "
                     "the canaries run at the tip"):
            with self.subTest(text=text):
                messages = [m for _, m in
                            check_pr_body.check(GOOD_BODY + "\n" + text + "\n",
                                                SKILL_EDIT)]
                self.assertTrue(any("names no tip" in m for m in messages), messages)

    def test_stack_form_with_a_placeholder_tip_fails(self):
        body = GOOD_BODY + "\nEval gate: stack — intermediate; tip: <#PR or branch>\n"
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("names no tip" in m for m in messages), messages)

    def test_a_file_path_is_not_a_stack_tip(self):
        """`the tip runs them, see evals/README.md` names a document, not a tip."""
        body = GOOD_BODY + ("\nEval gate: stack — intermediate; tip: "
                            "evals/README.md explains it\n")
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("names no tip" in m for m in messages), messages)

    def test_the_tip_must_be_named_on_the_verdict_line(self):
        """A `#137` elsewhere in the body is some other PR, not a promise."""
        body = GOOD_BODY + ("\nEval gate: stack — intermediate PR, canaries at the "
                            "tip.\n\nThis one follows on from #137.\n")
        messages = [m for _, m in check_pr_body.check(body, SKILL_EDIT)]
        self.assertTrue(any("names no tip" in m for m in messages), messages)

    def test_stack_template_line_is_not_a_discharge(self):
        """The template quotes the form AND its placeholder tip; neither discharges."""
        quoted = ("- [ ] `Eval gate: stack — <why this one is intermediate>; "
                  "tip: <#PR or branch>` when this is an intermediate PR\n")
        messages = [m for _, m in
                    check_pr_body.check(GOOD_BODY + "\n" + quoted, SKILL_EDIT)]
        self.assertTrue(messages, "quoting the stack form must not discharge")
        self.assertTrue(any("inline code span" in m for m in messages), messages)

    def test_lessons_and_reference_files_also_trigger(self):
        for path in ("skills/job-search/LESSONS.md", "skills/job-search/reference.md"):
            with self.subTest(path=path):
                self.assertTrue(check_pr_body.check(GOOD_BODY, [path]))

    def test_a_skill_script_or_canary_file_does_not_trigger(self):
        for path in ("skills/job-search/scripts/search.py",
                     "evals/canaries/job-search.yaml",
                     "skills/job-search/agents-references/notes.md"):
            with self.subTest(path=path):
                self.assertEqual(check_pr_body.check(GOOD_BODY, [path]), [])

    def test_discharge_inside_a_fence_still_counts(self):
        """Pasted results are evidence; the fence exemption protects prose checks."""
        body = GOOD_BODY + textwrap.dedent("""\

            ```
            Eval gate: ran — job-search canaries, 4 of 4 PASS
            ```
            """)
        self.assertEqual(check_pr_body.check(body, SKILL_EDIT), [])

    def test_format_findings_and_the_eval_finding_are_both_reported(self):
        body = GOOD_BODY.replace("## What changes for you", "## Summary", 1)
        findings = check_pr_body.check(body, SKILL_EDIT)
        locations = [location for location, _ in findings]
        self.assertIn("eval gate", locations)
        self.assertTrue(any(location != "eval gate" for location in locations),
                        findings)


class CliTests(unittest.TestCase):
    def _run(self, argv, stdin=""):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv],
            input=stdin, capture_output=True, text=True,
        )

    def _changed_files(self, tmp, paths, name="changed.txt"):
        path = Path(tmp) / name
        path.write_text("\n".join(paths) + "\n", encoding="utf-8")
        return str(path)

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

    def test_eval_gate_only_needs_changed_files(self):
        result = self._run(["--eval-gate-only"], stdin=GOOD_BODY)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--changed-files", result.stderr)

    def test_missing_changed_files_list_exits_2(self):
        result = self._run(["--changed-files", "/nonexistent/changed.txt"],
                           stdin=GOOD_BODY)
        self.assertEqual(result.returncode, 2)

    def test_eval_gate_only_ignores_the_format_properties(self):
        """CI gates the eval gate alone — a `## Summary` opener is not its business."""
        with tempfile.TemporaryDirectory() as tmp:
            changed = self._changed_files(tmp, NO_SKILL_EDIT)
            result = self._run(["--changed-files", changed, "--eval-gate-only"],
                               stdin="## Summary\n\nA body in the wrong shape.\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_eval_gate_only_fails_an_undischarged_skill_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed = self._changed_files(tmp, SKILL_EDIT)
            result = self._run(["--changed-files", changed, "--eval-gate-only"],
                               stdin=GOOD_BODY)
        self.assertEqual(result.returncode, 1)
        self.assertIn("eval gate", result.stderr)

    def test_empty_body_with_a_diff_is_a_verdict_not_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = self._changed_files(tmp, SKILL_EDIT, "skill.txt")
            other = self._changed_files(tmp, NO_SKILL_EDIT, "other.txt")
            failing = self._run(["--changed-files", skill, "--eval-gate-only"],
                                stdin="   \n")
            passing = self._run(["--changed-files", other, "--eval-gate-only"],
                                stdin="   \n")
        self.assertEqual(failing.returncode, 1, failing.stderr)
        self.assertEqual(passing.returncode, 0, passing.stderr)


if __name__ == "__main__":
    unittest.main()
