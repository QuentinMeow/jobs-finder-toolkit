"""Tests for the setup preflight (automation/check_python.py).

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/hooks/tests -t automation/hooks/tests

Lives beside the overlay-hook tests because this suite is where the repo's
top-level SETUP tooling is covered (``test_overlay_hooks.py`` imports
``automation/bootstrap_overlay.py`` the same way).

The load-bearing test here is ``test_source_parses_as_python_37``: the preflight
is executed BY the interpreter it is judging, so a syntax error in it is not a
report — it is a traceback that hides the diagnosis. ``ast.parse`` with
``feature_version=(3, 7)`` rejects walrus / ``match`` / 3.8+ f-string syntax on
any modern interpreter, so the rule is enforced in CI without needing an ancient
Python on the runner.
"""
from __future__ import annotations

import ast
import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "automation/check_python.py"


def _module():
    sys.path.insert(0, str(REPO_ROOT / "automation"))
    import check_python  # noqa: E402

    return check_python


class TestPreflightSyntaxFloor(unittest.TestCase):
    def test_source_parses_as_python_37(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        # Raises SyntaxError on any syntax newer than 3.7 — which is the point:
        # a 3.7 box must get the message, not a crash.
        ast.parse(source, filename=str(SCRIPT), feature_version=(3, 7))

    def test_declares_no_type_annotations(self) -> None:
        """``X | None`` is a 3.10 runtime error; the simplest rule is: none at all."""
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        annotated = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.AnnAssign, ast.arg)) and getattr(
                node, "annotation", None) is not None
        ]
        self.assertEqual(annotated, [], "check_python.py must stay annotation-free")

    def test_imports_only_the_always_available_stdlib(self) -> None:
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        self.assertLessEqual(modules, {"sys", "shutil"}, modules)


class TestPreflightBehavior(unittest.TestCase):
    def test_passes_on_the_repo_venv(self) -> None:
        """The interpreter running the suite is by definition new enough."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: Python", result.stdout)

    def test_minimum_matches_the_documented_floor(self) -> None:
        self.assertEqual(_module().MINIMUM, (3, 11))

    def test_failure_report_names_a_found_interpreter(self) -> None:
        report = _module().failure_report(["python3.13"])
        self.assertIn("python3.13 -m venv .venv", report)
        self.assertIn("python-jobspy", report)

    def test_failure_report_without_a_candidate_says_how_to_install_one(self) -> None:
        report = _module().failure_report([])
        self.assertIn("was found on PATH", report)
        self.assertIn("brew install python@3.13", report)
        self.assertIn("uv venv", report)

    def test_exits_non_zero_when_the_interpreter_is_too_old(self) -> None:
        """Simulate an old interpreter by raising the floor above this one."""
        check_python = _module()
        original = check_python.MINIMUM
        self.addCleanup(setattr, check_python, "MINIMUM", original)
        check_python.MINIMUM = (99, 0)
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            self.assertEqual(check_python.main(), 1)
        self.assertIn("needs Python 99.0+", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
