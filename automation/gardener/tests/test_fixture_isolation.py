"""Standing guard: no test in this folder may read the owner's private overlay.

``test_skill_drift.py::test_run_is_report_only_and_exits_zero`` used to call
``skill_drift.run()`` with no ``JOBHUNT_CONFIG`` pin. On a maintainer checkout the
ambient ``config.yaml`` resolves every accessor into ``private/``, so a bare
``unittest discover`` read the owner's real baseline and profile and printed a report
about them to stdout — into CI logs and into any terminal that ran the suite. CI never
saw it, because CI has no overlay mounted; that is exactly what made it survive.

Reviewing the one test that did it fixes one test. This module is the guard for the
*class*: it re-runs the rest of this folder's suite in a subprocess, under a
``sys.addaudithook`` recorder, with ``JOBHUNT_CONFIG`` deliberately UNSET — the
hazardous condition — and fails if any file under ``<repo-root>/private/`` was opened.
A new test that forgets its fixture pin trips it too.

The recorder is proved live by a canary that plants a read inside a scratch "guarded"
tree and asserts it is caught. Without that, this file would pass vacuously in a
checkout with no overlay (CI, any contributor clone) and nobody would notice it had
stopped working.

Cost: the child is a second full run of this folder's suite, so the folder takes about
twice as long as it did. That is the price of proving the property by execution rather
than by reading the source.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/gardener/tests \
        -t automation/gardener/tests
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parents[2]
OVERLAY = REPO_ROOT / "private"

# Set on the subprocess so the child skips this module instead of spawning its own child.
CHILD_ENV = "JOBHUNT_GARDENER_ISOLATION_CHILD"
_IS_CHILD = os.environ.get(CHILD_ENV) == "1"

# Written to a temp file and run as ``python _audit_driver.py <tests> <guarded> <report>``.
# It installs an audit hook, runs a unittest discovery over <tests>, and writes every
# path it saw opened under <guarded> to <report> as JSON.
_DRIVER = r'''
import io, json, os.path, sys, unittest

TESTS, GUARDED, REPORT = sys.argv[1], sys.argv[2], sys.argv[3]
GUARDED_PREFIX = os.path.join(os.path.abspath(GUARDED), "")
_touched = set()

# Every audit event whose FIRST argument is a filesystem path we care about. os.stat is
# not audited by CPython, so a mere existence check is invisible here: this records
# reads of CONTENT, which is the leak that matters.
_PATH_EVENTS = ("open", "os.listdir", "os.scandir", "glob.glob", "glob.glob/2",
                "pathlib.Path.glob", "os.remove", "os.rename", "os.mkdir")


def _hook(event, args):
    # Must never raise: an exception here aborts the audited call, not just the hook.
    try:
        if event not in _PATH_EVENTS or not args:
            return
        target = args[0]
        if isinstance(target, int):        # open() on an existing fd
            return
        if isinstance(target, bytes):
            target = os.fsdecode(target)
        elif not isinstance(target, str):
            target = str(target)
        # abspath is pure string work plus getcwd(); it opens nothing, so it cannot
        # re-enter this hook.
        if os.path.abspath(target).startswith(GUARDED_PREFIX):
            _touched.add(target)
    except Exception:
        pass


sys.addaudithook(_hook)

sys.path.insert(0, TESTS)
suite = unittest.defaultTestLoader.discover(TESTS, top_level_dir=TESTS)
buf = io.StringIO()
result = unittest.TextTestRunner(stream=buf, verbosity=0).run(suite)
with open(REPORT, "w", encoding="utf-8") as fh:
    json.dump({"touched": sorted(_touched),
               "ok": result.wasSuccessful(),
               "ran": result.testsRun,
               "report": buf.getvalue()[-4000:]}, fh)
'''


def _run_guarded(tests_dir: Path, guarded: Path) -> dict:
    """Run ``tests_dir``'s suite in a child that records reads under ``guarded``."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        driver = tmp / "_audit_driver.py"
        driver.write_text(_DRIVER, encoding="utf-8")
        report = tmp / "report.json"
        env = dict(os.environ)
        env[CHILD_ENV] = "1"
        # The whole point: reproduce the hazardous condition. An inherited pin would
        # make this guard prove nothing.
        env.pop("JOBHUNT_CONFIG", None)
        proc = subprocess.run(
            [sys.executable, str(driver), str(tests_dir), str(guarded), str(report)],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=900)
        if not report.exists():
            raise AssertionError(
                f"audit driver produced no report (exit {proc.returncode}).\n"
                f"stdout tail:\n{proc.stdout[-2000:]}\nstderr tail:\n{proc.stderr[-2000:]}")
        return json.loads(report.read_text(encoding="utf-8"))


@unittest.skipIf(_IS_CHILD, "child run of the isolation guard — would recurse")
class FixtureIsolationTests(unittest.TestCase):

    def test_the_recorder_catches_a_read_under_the_guarded_tree(self):
        """Canary: without this, a checkout with no overlay passes vacuously forever."""
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t).resolve()
            guarded = tmp / "guarded"
            guarded.mkdir()
            (guarded / "secret.txt").write_text("owner data\n", encoding="utf-8")
            fake_tests = tmp / "tests"
            fake_tests.mkdir()
            (fake_tests / "test_canary.py").write_text(textwrap.dedent(f"""\
                import unittest
                from pathlib import Path

                class T(unittest.TestCase):
                    def test_reads_the_guarded_file(self):
                        text = Path({str(guarded / "secret.txt")!r}).read_text()
                        self.assertIn("owner", text)
                """), encoding="utf-8")
            res = _run_guarded(fake_tests, guarded)
        self.assertEqual(res["ran"], 1)
        self.assertTrue(res["ok"], res["report"])
        self.assertEqual([Path(p).name for p in res["touched"]], ["secret.txt"])

    def test_no_test_in_this_folder_reads_the_private_overlay(self):
        res = _run_guarded(TESTS_DIR, OVERLAY)
        self.assertGreater(res["ran"], 1, "the child discovered no tests")
        self.assertTrue(res["ok"], f"the child suite itself failed:\n{res['report']}")
        self.assertEqual(
            res["touched"], [],
            "a test in automation/gardener/tests read the owner's private overlay "
            "with no JOBHUNT_CONFIG pin. Pin the config at a fixture (see "
            "test_skill_drift._pinned_config) and assert the resolved paths.")


if __name__ == "__main__":
    unittest.main()
