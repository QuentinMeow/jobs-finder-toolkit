"""Regression tests for the exporter's own arming refusal (``export()`` in
``export_public.py``).

This mirrors ``check_public.py``'s "fail closed when unarmed" behavior one layer
up: ``export()`` calls ``check_public.identity_tokens()`` FIRST, before touching
``--dest`` at all, so an unarmed checkout never gets as far as deleting an
existing destination (the ``--force`` + ``shutil.rmtree`` path) or creating a new
one. The regression this guards against: the arming check used to sit AFTER the
``--force`` rmtree, so an unarmed export could silently wipe an existing
destination before refusing.

Run with:
    .venv/bin/python -m unittest discover automation/publish/tests
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling modules importable (automation/publish/).
_PUBLISH_DIR = Path(__file__).resolve().parents[1]
if str(_PUBLISH_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISH_DIR))

import check_public  # noqa: E402

REPO_ROOT = check_public.REPO_ROOT
EXPORTER = REPO_ROOT / "automation/publish/export_public.py"

# The specific arming-refusal text, distinct from anything the leak guard itself
# prints (``check_public.py`` says "UNARMED"; the exporter's own gate says this).
REFUSAL_NEEDLE = "the leak guard is UNARMED in this checkout"


class ExportArmingCLITests(unittest.TestCase):
    """End-to-end (subprocess) coverage of the exporter's own arming gate."""

    def _run(self, extra_args: list[str], armed: bool = False) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop(check_public.TOKENS_ENV_VAR, None)
        # Force config discovery onto the tracked EXAMPLE config: zero identity
        # tokens from that channel, exactly like a fresh clone / fork CI run.
        env["JOBHUNT_CONFIG"] = str(REPO_ROOT / "config.example.yaml")
        if armed:
            env[check_public.TOKENS_ENV_VAR] = "ZZTESTTOKEN"
        return subprocess.run(
            [sys.executable, str(EXPORTER), *extra_args],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env,
        )

    def test_unarmed_export_exits_nonzero_and_does_not_create_dest(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            proc = self._run(["--dest", str(dest)])

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn(REFUSAL_NEEDLE, proc.stderr)
            self.assertFalse(dest.exists(),
                             "unarmed export must refuse BEFORE creating --dest")

    def test_unarmed_force_export_refuses_before_rmtree_and_preserves_sentinel(self):
        # The regression that matters: the arming check used to sit AFTER the
        # --force rmtree, so an unarmed --force export could wipe an existing
        # destination before refusing. Plant a sentinel and prove it survives.
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            dest.mkdir()
            sentinel = dest / "sentinel.txt"
            sentinel.write_text("do not delete me\n", encoding="utf-8")

            proc = self._run(["--dest", str(dest), "--force"])

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn(REFUSAL_NEEDLE, proc.stderr)
            self.assertTrue(sentinel.exists(),
                            "refusal must happen BEFORE shutil.rmtree(dest)")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not delete me\n")

    def test_armed_export_does_not_trip_the_arming_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            proc = self._run(["--dest", str(dest)], armed=True)

            # Not asserting the whole export succeeds (rc may be nonzero for
            # unrelated reasons, e.g. the forwarded guard run) — only that the
            # arming refusal specifically did not fire.
            self.assertNotIn(REFUSAL_NEEDLE, proc.stderr, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
