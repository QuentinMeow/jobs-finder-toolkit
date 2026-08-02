"""`store_refilter.py`'s command line: `--help` answers, no store is a sentence.

The sibling `UnconfiguredStoreTests` in `test_field_fidelity.py` fixed exactly this
shape for `field_fidelity.py` — "every store-reading command tracebacked out of
``pathlib`` where no store is configured". `store_refilter.py` is the other
store-reading command in this folder and the pass missed it, so under the shipped
example config (every fresh clone, and CI) it still died seven frames deep in
``pathlib/_local.py``::

    TypeError: argument should be a str or an os.PathLike object …, not 'NoneType'

`config.data_root()` returns None BY DESIGN when the store is unconfigured, and its
docstring promises that "the query/validate tools print a clear 'store not
configured' message".

Compounding it, the entire scan sat under a bare ``if __name__ == "__main__":`` with
no argparse at all, so ``--help`` — the one thing you reach for when a command
misbehaves — took the same traceback. A ``--help`` that crashes is not a help.

Exit 0, not 2: this follows the store's own `validate_store.py` / `gc_store.py`,
which print "nothing to validate" / "nothing to garbage-collect" and exit 0.
`field_fidelity.py` deliberately exits 2 instead and says why in a comment — it is
ASKED for a verdict and has none. `store_refilter` is asked to re-filter what is
stored; with no store there is nothing stored, which is a complete answer, and it
returns no verdict a caller could misread.

Isolation: every subprocess pins ``JOBHUNT_CONFIG`` at the tracked example config
and clears ``JOBHUNT_DATA_ROOT``, so no probe reads the owner's config, store or
applications tree, and the refusal path reaches neither.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/search-recall-audit/tests \
        -t automation/search-recall-audit/tests
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

AUDIT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
REFILTER = AUDIT_DIR / "store_refilter.py"

if str(AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(AUDIT_DIR))

import store_refilter  # noqa: E402  (import stays side-effect-free: no scan, no
#                                     private path, no local/ output)


class UnconfiguredStoreCliTests(unittest.TestCase):

    def _run(self, *argv: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["JOBHUNT_CONFIG"] = str(REPO_ROOT / "config.example.yaml")
        env.pop("JOBHUNT_DATA_ROOT", None)
        return subprocess.run([sys.executable, str(REFILTER), *argv],
                              cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=300, env=env)

    def test_help_answers_instead_of_crashing(self):
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0,
                         f"--help exited {proc.returncode}:\n{proc.stderr}")
        self.assertIn("usage", proc.stdout.lower(), proc.stdout)

    def test_an_unknown_flag_is_rejected_by_argparse(self):
        """Proves there is a real parser, not a docstring that mentions one."""
        proc = self._run("--no-such-flag")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("unrecognized arguments", proc.stderr)

    def test_no_store_is_a_sentence_naming_what_to_configure(self):
        proc = self._run()
        message = proc.stdout + proc.stderr
        self.assertNotIn("Traceback", message, message)
        self.assertEqual(proc.returncode, 0, message)
        self.assertIn("store not configured", message)
        self.assertIn("paths.data_root", message)
        self.assertIn("JOBHUNT_DATA_ROOT", message)

    def test_the_guard_runs_before_anything_is_created_or_loaded(self):
        """Order, asserted on the source: ``OUT`` lives in the real repo tree.

        There is no flag that redirects it, so a dynamic "wrote nothing" probe
        would have to inspect (or clear) a folder that may hold the owner's last
        real audit. The property is nonetheless exact and worth pinning: refusing
        AFTER ``OUT.mkdir`` leaves a reader of ``local/field_fidelity_audit/``
        unable to tell a real run from one that never happened, and refusing after
        ``load_registry()`` resolves the overlay blacklist for a run that is about
        to do nothing.
        """
        main = next(node for node in ast.parse(REFILTER.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.If)
                    and ast.unparse(node.test) == "__name__ == '__main__'")
        steps = [ast.unparse(stmt) for stmt in main.body]
        guard = next((i for i, s in enumerate(steps) if "store not configured" in s), None)
        self.assertIsNotNone(guard, "the scan carries no unconfigured-store guard")
        for effect in ("OUT.mkdir", "load_registry(", "resolve_profile("):
            with self.subTest(effect=effect):
                at = next((i for i, s in enumerate(steps) if effect in s), None)
                self.assertIsNotNone(at, f"{effect} is no longer a step of the scan")
                self.assertLess(guard, at,
                                f"the store guard runs after {effect}, so a refusal "
                                f"still has side effects")


if __name__ == "__main__":
    unittest.main()
