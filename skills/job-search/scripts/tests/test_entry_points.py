"""Every runnable script in this skill answers ``--help`` instead of crashing.

``build_sponsor_index.py`` — documented as runnable in three places — died at
IMPORT time on every invocation, ``--help`` included::

    ModuleNotFoundError: No module named 'job_metadata'

It was the only entry point here with no ``sys.path`` bootstrap for
``scripts/_vendor``, so its ``from scoring import ...`` reached ``scoring.py``,
which reaches the vendored ``job_metadata`` — and nothing had put ``_vendor/`` on
the path. Nothing caught it: the module is imported by no test and by no other
script, so it is invisible to ``compileall`` (syntax only) and to every unit suite.

A ``--help`` sweep is the cheapest thing that would have. It costs one subprocess
per entry point, needs no fixtures, no network and no store, and it fails the same
way for the whole family of "the CLI cannot even start" defects: a bad import, a
missing vendored module, a module-level path resolution that explodes.

Which scripts count: exactly those with a top-level ``if __name__ == "__main__":``
block. That is the file's own claim to be runnable, so the set cannot drift out of
date the way a hand-kept list does. Library modules without one (``scoring.py``,
``visa.py``, ``common.py`` …) are deliberately excluded — they are imported, never
executed, and their direct ``python scoring.py`` failure says nothing about the
skill.

Isolation: each subprocess runs with ``JOBHUNT_CONFIG`` pinned at the tracked
example config and ``JOBHUNT_DATA_ROOT`` cleared, so no probe reads the owner's
config, store or applications tree. ``--help`` exits inside argparse, before any
command does work, so nothing is fetched and nothing is written.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _is_entry_point(path: Path) -> bool:
    """True when the module guards a top-level ``if __name__ == "__main__":``.

    Parsed, not grepped: a match inside a docstring or a comment would enrol a
    library module and make this suite fail for a reason that is not a defect.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # compileall owns that failure; do not double-report it
        return False
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name) and test.left.id == "__name__"
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == "__main__"):
            return True
    return False


def entry_points() -> list[Path]:
    return sorted(p for p in _SCRIPTS.glob("*.py") if _is_entry_point(p))


class EntryPointHelpTests(unittest.TestCase):

    def _help(self, script: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["JOBHUNT_CONFIG"] = str(_REPO_ROOT / "config.example.yaml")
        env.pop("JOBHUNT_DATA_ROOT", None)
        env.pop("JOBHUNT_REQUIRE_REAL_CONFIG", None)
        return subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=_REPO_ROOT, capture_output=True, text=True, env=env, timeout=120)

    def test_the_sweep_actually_found_the_entry_points(self):
        """A discovery bug would make every assertion below vacuously true."""
        names = {p.name for p in entry_points()}
        self.assertGreaterEqual(len(names), 8, sorted(names))
        self.assertIn("search_jobs.py", names)
        self.assertIn("build_sponsor_index.py", names)
        # Library modules must NOT be swept: they are imported, never run.
        self.assertNotIn("scoring.py", names)
        self.assertNotIn("common.py", names)

    def test_every_entry_point_answers_help(self):
        for script in entry_points():
            with self.subTest(script=script.name):
                proc = self._help(script)
                self.assertEqual(
                    proc.returncode, 0,
                    f"{script.name} --help exited {proc.returncode}; a documented "
                    f"entry point that cannot start is broken for every flag, not "
                    f"just this one:\n{proc.stdout}\n{proc.stderr}")
                self.assertIn("usage", proc.stdout.lower(), proc.stdout)


if __name__ == "__main__":
    unittest.main()
