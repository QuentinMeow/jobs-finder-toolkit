"""How `status.py` rewrites `company-search-log.yaml`.

Every `--sync-log` and every `--log-search` rewrites this file whole. The old
writer did it with a bare `Path.write_text` of a dict rebuilt from exactly three
keys, which cost two things: an interrupted write left a truncated search log, and
any top-level key the owner had added was deleted without a word.

status.py resolves the log path from config at import time, so the subprocess
cases run with JOBHUNT_CONFIG pointed at a throwaway tree; every company below is
fictional.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/application-tracker/scripts/tests \
        -t skills/application-tracker/scripts/tests
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
STATUS = SCRIPTS / "status.py"
for _p in (SCRIPTS, SCRIPTS / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

HEALTHY_META = textwrap.dedent("""\
    job_metadata_schema_version: 6
    company: Globex
    research_date: "2026-07-02"
    jobs:
      - role: Backend Engineer
        status: drafted
        location: Springfield, ST
        url: https://boards.example.test/globex/backend
    """)


class CompanySearchLogWriterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.apps = self.root / "apps"
        self.config = self.root / "config.yaml"
        self.config.write_text(textwrap.dedent(f"""\
            paths:
              applications_root: "{self.apps.as_posix()}"
            """), encoding="utf-8")
        self.search_log = self.apps / "0_profile" / "company-search-log.yaml"

    def _run(self, *args):
        env = dict(os.environ, JOBHUNT_CONFIG=str(self.config))
        return subprocess.run([sys.executable, str(STATUS), *args],
                              capture_output=True, text=True, env=env)

    def _seed_log_with_an_unknown_key(self) -> None:
        self.search_log.parent.mkdir(parents=True, exist_ok=True)
        self.search_log.write_text(textwrap.dedent("""\
            skip_within_days: 7
            owner_note: keep me
            never_search:
              - Some Corp
            companies:
              - name: Initech
                aliases: [initech]
                last_successful_search: '2026-06-01'
                outcome: no_suitable
                note: ''
            """), encoding="utf-8")

    def _doc(self) -> dict:
        return yaml.safe_load(self.search_log.read_text(encoding="utf-8"))

    # -- unknown top-level keys -------------------------------------------- #
    def test_log_search_preserves_unknown_top_level_keys(self):
        self._seed_log_with_an_unknown_key()
        proc = self._run("--log-search", "Beta Inc", "--outcome", "no_suitable")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = self._doc()
        self.assertEqual(doc["owner_note"], "keep me")
        self.assertEqual(doc["never_search"], ["Some Corp"])

    def test_sync_log_preserves_unknown_top_level_keys(self):
        self._seed_log_with_an_unknown_key()
        app = self.apps / "6_drafted" / "globex-backend-engineer-20260702"
        (app / "source").mkdir(parents=True)
        (app / "meta.yaml").write_text(HEALTHY_META, encoding="utf-8")

        proc = self._run("--sync-log")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = self._doc()
        self.assertEqual(doc["owner_note"], "keep me")
        self.assertIn("Globex", [c["name"] for c in doc["companies"]])

    def test_the_three_managed_keys_still_come_first(self):
        """A file with nothing extra keeps its familiar shape."""
        self._run("--log-search", "Beta Inc", "--outcome", "no_suitable")
        keys = list(self._doc())
        self.assertEqual(keys, ["skip_within_days", "generated", "companies"])

    def test_an_unparseable_log_is_not_replaced_with_an_empty_one(self):
        """The same "unreadable is not empty" rule, on the writer's own input.

        Every caller rewrites the file from what the loader returns, so a loader
        that swallowed the parse error would replace the owner's whole search log
        with two keys and no companies.
        """
        self.search_log.parent.mkdir(parents=True, exist_ok=True)
        broken = "skip_within_days: 7\ncompanies: [oops: unquoted: colon]\n"
        self.search_log.write_text(broken, encoding="utf-8")

        proc = self._run("--log-search", "Beta Inc", "--outcome", "no_suitable")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self.search_log.read_text(encoding="utf-8"), broken)

    # -- atomicity --------------------------------------------------------- #
    _INTERRUPT_DRIVER = textwrap.dedent("""\
        import sys
        sys.path.insert(0, sys.argv[1])
        sys.path.insert(0, sys.argv[2])
        import metadata_editor
        import status

        def boom(*args, **kwargs):
            raise OSError("interrupted")

        metadata_editor.os.replace = boom
        try:
            status.write_company_search_log({"companies": []})
        except OSError:
            sys.exit(3)
        sys.exit(0)
        """)

    def test_an_interrupted_rewrite_leaves_the_previous_log_whole(self):
        """`Path.write_text` truncates and then writes; this must do neither halfway.

        The failure is injected at the rename — the last possible moment — so the
        complete previous log must still be all that is on disk, with no temp file
        left beside it. Driven in a subprocess because status.py resolves the log
        path from config at import time.
        """
        self._seed_log_with_an_unknown_key()
        before = self.search_log.read_text(encoding="utf-8")
        env = dict(os.environ, JOBHUNT_CONFIG=str(self.config))
        proc = subprocess.run(
            [sys.executable, "-c", self._INTERRUPT_DRIVER,
             str(SCRIPTS), str(SCRIPTS / "_vendor")],
            capture_output=True, text=True, env=env)

        self.assertEqual(proc.returncode, 3,
                         f"the write should have raised\n{proc.stdout}{proc.stderr}")
        self.assertEqual(self.search_log.read_text(encoding="utf-8"), before)
        self.assertEqual(sorted(p.name for p in self.search_log.parent.iterdir()),
                         ["company-search-log.yaml"])


if __name__ == "__main__":
    unittest.main()
