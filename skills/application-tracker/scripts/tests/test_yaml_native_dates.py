"""`status.py` against a `meta.yaml` that spells a date the way YAML allows.

`yaml.safe_load` resolves an UNQUOTED `research_date: 2026-07-02` to a
`datetime.date`, not a `str`. The file is valid YAML and says exactly the right
day, but that one application's `date` then has a different TYPE from every
other application's (theirs comes from the slug parse, or from a quoted value),
and two consumers assume `str`:

* `print_table` sorts on `date`, so a fleet with one such row died with
  `TypeError: '<' not supported between instances of 'datetime.date' and 'str'`
  after printing its header (a fleet of exactly ONE such row never compares, so
  it printed the literal `<10` in the Date column instead — `date.__format__`
  hands a non-empty format spec to `strftime`);
* `build_created_search_entries` calls `.strip()` on it, so `--sync-log` died
  with `AttributeError` — *after* it had already appended to the append-only
  skip-log.

The last file also pins the ordering itself: nothing permanent may be written
before every fallible step of a command has run.

status.py resolves its applications root from config at import time, so each case
runs it as a subprocess with JOBHUNT_CONFIG pointed at a throwaway config +
applications tree. No private overlay is reachable and every company, slug and
URL below is fictional.

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

STATUS = Path(__file__).resolve().parents[1] / "status.py"

# One meta.yaml with the date UNQUOTED, one with it quoted. Two applications,
# not one: `sorted` never invokes the comparison on a single-element list, so a
# one-row fleet hid the TypeError behind a wrong-looking cell.
UNQUOTED_META = """\
company: Globex
research_date: 2026-07-02
jobs:
  - role: Backend Engineer
    status: drafted
    location: "Springfield, ST"
    url: "https://boards.example.test/globex/backend"
"""
QUOTED_META = """\
company: Initech
research_date: "2026-06-15"
jobs:
  - role: Frontend Engineer
    status: drafted
    location: "Fairview, ST"
    url: "https://boards.example.test/initech/frontend"
"""


class YamlNativeDateTests(unittest.TestCase):
    def _tree(self, tmp: str) -> Path:
        """A two-application tree; the Globex meta.yaml leaves its date unquoted."""
        root = Path(tmp)
        drafted = root / "apps" / "6_drafted"
        for slug, meta in (
            ("globex-backend-engineer-20260702", UNQUOTED_META),
            ("initech-frontend-engineer-20260615", QUOTED_META),
        ):
            (drafted / slug).mkdir(parents=True)
            (drafted / slug / "meta.yaml").write_text(meta, encoding="utf-8")
        (root / "config.yaml").write_text(textwrap.dedent(f"""\
            paths:
              applications_root: "{(root / 'apps').as_posix()}"
            """), encoding="utf-8")
        return root

    def _run(self, root: Path, *args: str):
        env = dict(os.environ, JOBHUNT_CONFIG=str(root / "config.yaml"))
        return subprocess.run(
            [sys.executable, str(STATUS), *args],
            capture_output=True, text=True, env=env)

    def test_default_table_renders_an_unquoted_research_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp)
            proc = self._run(root)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("2026-07-02", proc.stdout)
            # `<10` is what `date.__format__("<10")` produces: the column's width
            # spec reaching `strftime` verbatim. Its absence is the whole point.
            self.assertNotIn("<10", proc.stdout)

    def test_sync_log_completes_with_an_unquoted_research_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp)
            proc = self._run(root, "--sync-log")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)
            search_log = (root / "apps" / "0_profile"
                          / "company-search-log.yaml").read_text()
            self.assertIn("2026-07-02", search_log)
            self.assertIn("2026-06-15", search_log)

    def test_a_failure_after_the_scan_leaves_the_skip_log_untouched(self):
        """The ordering, pinned independently of any one crash.

        `--sync-log` used to append to the append-only skip-log and only then
        build the company search log, so every failure in the second half landed
        after a write nothing can take back. An unparseable company search log
        reaches that window without a crash at all — `_load_company_search_log_raw`
        deliberately exits rather than rewriting a file it could not read.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(tmp)
            profile = root / "apps" / "0_profile"
            profile.mkdir(parents=True, exist_ok=True)
            (profile / "company-search-log.yaml").write_text(
                "companies: [\nthis is not: valid: yaml\n", encoding="utf-8")
            proc = self._run(root, "--sync-log")
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(
                (profile / "applications-log.jsonl").exists(),
                "the append-only skip-log must not be written by a run that "
                "then fails: nothing regenerates it and a wrong row is repaired "
                "only by appending a --forget-log tombstone",
            )


if __name__ == "__main__":
    unittest.main()
