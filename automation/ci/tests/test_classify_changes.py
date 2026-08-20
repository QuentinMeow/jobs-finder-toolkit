from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "classify_changes.py"
SPEC = importlib.util.spec_from_file_location("classify_changes", SCRIPT)
CLASSIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CLASSIFIER
SPEC.loader.exec_module(CLASSIFIER)


def changed(*records):
    return tuple(CLASSIFIER.Change(status, tuple(path.encode() for path in paths))
                 for status, paths in records)


class ParseNameStatusTests(unittest.TestCase):
    def test_parses_regular_copy_and_rename_records(self):
        result = CLASSIFIER.parse_name_status(
            b"M\0README.md\0R091\0old.md\0new.md\0C100\0a.py\0b.py\0"
        )
        self.assertEqual([entry.status for entry in result], ["M", "R091", "C100"])
        self.assertEqual(result[1].paths, (b"old.md", b"new.md"))

    def test_zero_diff_is_valid(self):
        self.assertEqual(CLASSIFIER.parse_name_status(b""), ())

    def test_rejects_unterminated_output(self):
        with self.assertRaisesRegex(CLASSIFIER.ClassificationError, "NUL-terminated"):
            CLASSIFIER.parse_name_status(b"M\0README.md")

    def test_rejects_unknown_or_malformed_statuses(self):
        bad = (
            b"Q\0path\0",
            b"R101\0a\0b\0",
            b"Rxx\0a\0b\0",
            b"M\0",
            b"M\0\0",
            b"R100\0only-one\0",
            b"\xff\0path\0",
        )
        for output in bad:
            with self.subTest(output=output):
                with self.assertRaises(CLASSIFIER.ClassificationError):
                    CLASSIFIER.parse_name_status(output)


class ClassificationTests(unittest.TestCase):
    def assertFocused(self, records, expected):
        result = CLASSIFIER.classify(changed(*records))
        self.assertFalse(result.full)
        self.assertEqual(result.lanes, expected)

    def test_docs_and_process_only_select_no_long_lanes(self):
        self.assertFocused(
            (("M", ("docs/handbook/README.md",)),
             ("A", ("tasks/0_backlog/task/task.md",)),
             ("M", ("skills/job-search/SKILL.md",))),
            (),
        )

    def test_docs_process_and_review_ledger_select_no_long_lanes(self):
        self.assertFocused(
            (("M", ("docs/handbook/README.md",)),
             ("A", ("history/conversations/session/handover.md",)),
             ("M", ("automation/publish/review_ledger.yaml",))),
            (),
        )

    def test_other_publish_paths_still_select_publish(self):
        self.assertFocused(
            (("M", ("automation/publish/review_gate.py",)),),
            ("publish",),
        )

    def test_each_owned_lane(self):
        cases = {
            "maintenance": "automation/reconcile/tests/test_reconcile.py",
            "render": "examples/me/applications/6_drafted/example/source/tailored.yaml",
            "resume": "skills/resume-writer/scripts/tests/test_resume_schema.py",
            "shared": "automation/store/validate_store.py",
            "job-search": "skills/job-search/scripts/search.py",
            "applications": "skills/application-tracker/scripts/status.py",
            "publish": "automation/publish/tests/test_leak_guard.py",
        }
        for lane, path in cases.items():
            with self.subTest(lane=lane):
                result = CLASSIFIER.classify(changed(("M", (path,))))
                self.assertFalse(result.full)
                self.assertIn(lane, result.lanes)

    def test_cutover_tooling_selects_maintenance(self):
        # The cutover tools are maintenance tooling with their own unit suite
        # (run_gates' tests-cutover gate, in the maintenance lane). Without this
        # rule they fall through to the full-fallback and every cutover edit
        # runs every long lane.
        self.assertFocused(
            (("M", ("automation/cutover/validate_cutover.py",)),
             ("A", ("automation/cutover/tests/test_verify_copy.py",))),
            ("maintenance",),
        )

    def test_workspace_status_tooling_selects_maintenance(self):
        self.assertFocused(
            (("M", ("automation/workspace/status.py",)),
             ("A", ("automation/workspace/tests/test_status.py",))),
            ("maintenance",),
        )

    def test_resume_implementation_selects_render_and_resume(self):
        self.assertFocused(
            (("M", ("skills/resume-writer/scripts/render.py",)),),
            ("render", "resume"),
        )

    def test_multiple_owned_paths_union_lanes_in_stable_order(self):
        self.assertFocused(
            (("M", ("automation/publish/check_public.py",)),
             ("M", ("skills/job-search/scripts/search.py",)),
             ("M", ("automation/gardener/verify_links.py",))),
            ("maintenance", "job-search", "publish"),
        )

    def test_unknown_workflow_dependency_config_shared_and_classifier_are_full(self):
        paths = (
            "mystery/new.py",
            ".github/workflows/ci.yml",
            "requirements.txt",
            "config.example.yaml",
            "automation/shared/config.py",
            "automation/ci/classify_changes.py",
            "automation/vendoring/sync_vendored.py",
        )
        for path in paths:
            with self.subTest(path=path):
                result = CLASSIFIER.classify(changed(("M", (path,))))
                self.assertTrue(result.full)
                self.assertEqual(result.lanes, CLASSIFIER.LANES)
                self.assertIn(path, result.reason)

    def test_non_utf8_path_falls_back_with_an_encodable_reason(self):
        result = CLASSIFIER.classify(
            (CLASSIFIER.Change("M", (b"mystery/\xff.py",)),)
        )
        self.assertTrue(result.full)
        encoded = result.reason.encode("utf-8")
        self.assertIn(b"mystery/", encoded)

    def test_non_inert_delete_and_rename_are_full(self):
        cases = (
            ("D", ("skills/job-search/scripts/search.py",)),
            ("R100", ("docs/old.md", "skills/job-search/scripts/search.py")),
            ("R100", ("skills/job-search/scripts/old.py", "docs/new.md")),
        )
        for record in cases:
            with self.subTest(record=record):
                self.assertTrue(CLASSIFIER.classify(changed(record)).full)

    def test_inert_delete_and_rename_remain_focused(self):
        self.assertFocused(
            (("D", ("docs/obsolete.md",)),
             ("R100", ("history/old.md", "history/new.md"))),
            (),
        )

    def test_unmerged_statuses_are_full(self):
        for status in ("T", "U", "X", "B"):
            with self.subTest(status=status):
                self.assertTrue(
                    CLASSIFIER.classify(changed((status, ("docs/file.md",)))).full
                )

    def test_copy_classifies_destination_without_treating_source_as_removed(self):
        self.assertFocused(
            (("C100", ("unknown/source.py", "automation/store/copy.py")),),
            ("shared",),
        )

    def test_zero_diff_selects_no_lanes(self):
        result = CLASSIFIER.classify(())
        self.assertFalse(result.full)
        self.assertEqual(result.lanes, ())
        self.assertIn("no changes", result.reason)


class RangeAndOutputTests(unittest.TestCase):
    def test_git_uses_exact_rename_aware_nul_command(self):
        completed = subprocess.CompletedProcess([], 0, b"M\0README.md\0", b"")
        with mock.patch.object(CLASSIFIER.subprocess, "run", return_value=completed) as run:
            result = CLASSIFIER.git_changes(Path("/repo"), "base", "head")
        self.assertEqual(result[0].paths, (b"README.md",))
        self.assertEqual(
            run.call_args.args[0],
            ["git", "diff", "--name-status", "-z", "-M", "base", "head", "--"],
        )

    def test_git_and_parse_errors_fail_closed_to_all_lanes(self):
        failures = (
            subprocess.CompletedProcess([], 128, b"", b"bad revision\nsecond line"),
            subprocess.CompletedProcess([], 0, b"M\0unterminated", b""),
        )
        for completed in failures:
            with self.subTest(returncode=completed.returncode):
                with mock.patch.object(CLASSIFIER.subprocess, "run", return_value=completed):
                    result = CLASSIFIER.classify_range(Path("/repo"), "base", "head")
                self.assertTrue(result.full)
                self.assertEqual(result.lanes, CLASSIFIER.LANES)
                self.assertIn("fail-closed", result.reason)
                self.assertNotIn("\n", result.reason)

    def test_matrix_is_valid_github_include_matrix(self):
        result = CLASSIFIER.classify(changed(("M", ("automation/store/validate_store.py",))))
        outputs = CLASSIFIER.github_outputs(result)
        self.assertEqual(json.loads(outputs["matrix"]), {"include": [{"lane": "shared"}]})
        self.assertEqual(
            json.loads(outputs["test_matrix"]),
            {"include": [{"lane": "shared"}]},
        )
        self.assertEqual(json.loads(outputs["test_lanes"]), ["shared"])
        self.assertEqual(json.loads(outputs["pdf_lanes"]), [])
        self.assertEqual(outputs["full"], "false")

    def test_pdf_lanes_share_one_hosted_job(self):
        outputs = CLASSIFIER.github_outputs(CLASSIFIER.full_classification("full"))
        self.assertEqual(json.loads(outputs["pdf_lanes"]), ["render", "resume"])
        self.assertEqual(
            [entry["lane"] for entry in json.loads(outputs["test_matrix"])["include"]],
            ["maintenance", "shared", "job-search", "applications", "publish"],
        )
        self.assertNotIn("render", json.loads(outputs["test_lanes"]))
        self.assertNotIn("resume", json.loads(outputs["test_lanes"]))

    def test_force_full_emits_all_lanes_without_invoking_git(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            with mock.patch.object(
                CLASSIFIER, "git_changes", side_effect=AssertionError("Git was invoked")
            ):
                with mock.patch("builtins.print"):
                    exit_code = CLASSIFIER.main(
                        ["--force-full", "push to main", "--github-output", str(output)]
                    )
            output_text = output.read_text()
        self.assertEqual(exit_code, 0)
        self.assertIn("full<<__CI_CLASSIFIER_OUTPUT__\ntrue\n", output_text)
        self.assertIn("forced full matrix: push to main", output_text)
        self.assertEqual(
            json.loads(CLASSIFIER.github_outputs(
                CLASSIFIER.full_classification("forced")
            )["matrix"]),
            {"include": [{"lane": lane} for lane in CLASSIFIER.LANES]},
        )

    def test_range_arguments_are_required_together_and_exclude_force_full(self):
        invalid = (
            [],
            ["--base", "base"],
            ["--head", "head"],
            ["--force-full", "reason", "--base", "base", "--head", "head"],
            ["--force-full", "   "],
        )
        for argv in invalid:
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        CLASSIFIER.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_github_output_delimiter_escapes_newlines_and_delimiter_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            CLASSIFIER.write_github_outputs(
                output,
                {"reason": "first\n__CI_CLASSIFIER_OUTPUT__\nlast", "percent": "100%"},
            )
            text = output.read_text()
        self.assertIn("reason<<__CI_CLASSIFIER_OUTPUT___\n", text)
        self.assertIn("first\n__CI_CLASSIFIER_OUTPUT__\nlast\n", text)
        self.assertIn("percent<<__CI_CLASSIFIER_OUTPUT__\n100%\n", text)

    def test_cli_on_real_git_range_writes_summary_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            (repo / "README.md").write_text("before\n")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            (repo / "README.md").write_text("after\n")
            subprocess.run(["git", "-C", str(repo), "commit", "-qam", "head"], check=True)
            head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            output = repo / "outputs"
            run = subprocess.run(
                [sys.executable, str(SCRIPT), "--repository", str(repo), "--base", base,
                 "--head", head, "--github-output", str(output)],
                text=True, capture_output=True, check=False,
            )
            output_text = output.read_text()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("long-running lanes: none", run.stdout)
        self.assertIn('"include":[]', output_text)


if __name__ == "__main__":
    unittest.main()
