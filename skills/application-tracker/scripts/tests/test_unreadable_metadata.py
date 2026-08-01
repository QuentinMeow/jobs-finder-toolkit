"""What `status.py` does with a `meta.yaml` it cannot parse.

The defect these pin: `load_application` wrapped the whole read in a bare
`except Exception: pass`, so an unparseable file was indistinguishable from an
absent one. Two consumers then answered questions they had not looked at —
`--check-locations` cleared an application whose file says `location: London, UK`,
and `--sync-log` appended a row built from the folder name into a log that is
append-only and authoritative, where only a `--forget-log` tombstone can undo it.

The invariant, in three parts:

* a gate that claims to have inspected the application FAILS on it;
* nothing DERIVES A WRITE from it;
* a read-only view still shows the rest of the pipeline.

status.py resolves its applications root and location policy from config at import
time, so every case runs it as a subprocess with JOBHUNT_CONFIG pointed at a
throwaway tree. No private overlay is reachable and every company, slug and URL
below is fictional.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/application-tracker/scripts/tests \
        -t skills/application-tracker/scripts/tests
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

import yaml

STATUS = Path(__file__).resolve().parents[1] / "status.py"

# A hand-edit break that is invisible to a human skim: the unquoted second colon
# in a value. Everything the consumers care about — the company, the London
# location, the posting URL — is present in the file and readable by eye.
CORRUPT_META = textwrap.dedent("""\
    company: Acme Labs
    research_date: "2026-07-01"
    location: London, UK
    url: https://boards.example.test/acme/ml-engineer
    notes: Referred by: someone at the meetup
    jobs:
      - role: ML Engineer
        status: drafted
        location: London, UK
        url: https://boards.example.test/acme/ml-engineer
    """)

HEALTHY_META = textwrap.dedent("""\
    job_metadata_schema_version: 5
    company: Globex
    research_date: "2026-07-02"
    jobs:
      - role: Backend Engineer
        status: drafted
        location: Springfield, ST
        url: https://boards.example.test/globex/backend
    """)

CORRUPT_SLUG = "acme-labs-ml-engineer-20260701"
HEALTHY_SLUG = "globex-backend-engineer-20260702"


class UnreadableMetadataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.apps = self.root / "apps"
        self.config = self.root / "config.yaml"
        self.config.write_text(textwrap.dedent(f"""\
            paths:
              applications_root: "{self.apps.as_posix()}"
            location_policy:
              metro: [springfield, fairview]
              allow_us_remote: true
              us_only: true
            """), encoding="utf-8")
        self.jsonl = self.apps / "0_profile" / "applications-log.jsonl"
        self.search_log = self.apps / "0_profile" / "company-search-log.yaml"

    # -- fixtures ---------------------------------------------------------- #
    def _place(self, slug: str, meta: str, *, jd: str | None = None) -> Path:
        app = self.apps / "6_drafted" / slug
        (app / "source").mkdir(parents=True)
        (app / "meta.yaml").write_text(meta, encoding="utf-8")
        if jd is not None:
            (app / "source" / "JD-role.md").write_text(jd, encoding="utf-8")
        return app

    def _place_pair(self) -> None:
        """The broken application plus a healthy sibling that must keep working."""
        self._place(CORRUPT_SLUG, CORRUPT_META)
        self._place(HEALTHY_SLUG, HEALTHY_META)

    def _run(self, *args):
        env = dict(os.environ, JOBHUNT_CONFIG=str(self.config))
        return subprocess.run([sys.executable, str(STATUS), *args],
                              capture_output=True, text=True, env=env)

    def _log_rows(self) -> list[dict]:
        if not self.jsonl.exists():
            return []
        return [json.loads(line) for line in
                self.jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]

    # -- the gate ---------------------------------------------------------- #
    def test_check_locations_fails_on_an_unreadable_meta(self):
        self._place_pair()
        proc = self._run("--check-locations", "--json")
        self.assertEqual(proc.returncode, 1,
                         "the location gate must not clear an application it "
                         f"could not read.\n{proc.stdout}\n{proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertEqual([r["slug"] for r in data["unreadable"]], [CORRUPT_SLUG])
        self.assertEqual(data["mismatches"], [])

    def test_an_unreadable_row_is_not_counted_as_review(self):
        """It is a failure, not the pre-existing "blank location" review bucket.

        The review bucket is documented as "not a policy failure" and exits 0, so
        landing there is exactly how the corrupt file used to pass.
        """
        self._place_pair()
        data = json.loads(self._run("--check-locations", "--json").stdout)
        self.assertEqual(data["review"], [])
        self.assertEqual(len(data["unreadable"]), 1)

    def test_a_matching_jd_cannot_clear_an_unreadable_application(self):
        """The nastiest shape: the fallback evidence agrees with the policy.

        With meta.yaml unreadable the location falls back to the JD file, so a JD
        naming a preferred metro made the assessment come back *matching* for a
        posting whose meta.yaml says London. Unreadable is therefore classified
        before match/mismatch/review, never after.
        """
        self._place(CORRUPT_SLUG, CORRUPT_META,
                    jd="# ML Engineer\nLocation: Springfield, ST\n")
        proc = self._run("--check-locations", "--json")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data["unreadable"]), 1)
        self.assertNotIn(CORRUPT_SLUG,
                         [r["slug"] for r in data["rows"] if r["match"]
                          and not r["meta_error"]])

    def test_check_locations_still_passes_a_clean_tree(self):
        self._place(HEALTHY_SLUG, HEALTHY_META)
        proc = self._run("--check-locations", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["unreadable"], [])

    # -- the write path ---------------------------------------------------- #
    def test_sync_log_refuses_to_derive_a_row_from_an_unreadable_meta(self):
        self._place_pair()
        proc = self._run("--sync-log")
        self.assertEqual(proc.returncode, 1,
                         f"an incomplete sync must not exit 0\n{proc.stdout}")
        rows = self._log_rows()
        self.assertEqual([r["slug"] for r in rows], [HEALTHY_SLUG],
                         "the healthy sibling is still logged; the broken one is not")
        self.assertIn(CORRUPT_SLUG, proc.stderr)

    def test_the_refused_row_is_the_one_that_would_have_been_wrong(self):
        """Name the damage the old row did, so a future edit cannot re-create it.

        `build_log` fell back to a company parsed from the folder name and an
        empty role and url, so `skip_log.fold_key` stored
        ("pair", "acme labs ml engineer", "") — and the real posting URL was
        never skipped, which is the whole purpose of the log.
        """
        self._place_pair()
        self._run("--sync-log")
        rows = self._log_rows()
        self.assertEqual(rows and [r["company"] for r in rows], ["Globex"])
        self.assertNotIn("https://boards.example.test/acme/ml-engineer",
                         [r["url"] for r in rows])
        self.assertNotIn("Acme Labs Ml Engineer", [r["company"] for r in rows])

    def test_sync_log_writes_no_company_search_row_for_an_unreadable_meta(self):
        """The slug-derived company is an invention, and it hides the real one.

        "acme-labs-ml-engineer-20260701" titles to "Acme Labs Ml Engineer": a
        company that does not exist gets a fresh successful-search date while
        "Acme Labs" gets none, so job-search skips the wrong one.
        """
        self._place_pair()
        self._run("--sync-log")
        doc = yaml.safe_load(self.search_log.read_text(encoding="utf-8"))
        names = [c["name"] for c in doc["companies"]]
        self.assertEqual(names, ["Globex"])

    def test_backfill_log_seeds_nothing_for_an_unreadable_meta(self):
        """A bad seed row is exactly as permanent as a bad sync row."""
        self._place_pair()
        proc = self._run("--backfill-log")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual([r["slug"] for r in self._log_rows()], [HEALTHY_SLUG])
        self.assertIn(CORRUPT_SLUG, proc.stderr)

    def test_a_clean_sync_still_exits_zero(self):
        self._place(HEALTHY_SLUG, HEALTHY_META)
        proc = self._run("--sync-log")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual([r["slug"] for r in self._log_rows()], [HEALTHY_SLUG])

    # -- shapes other than a scanner error --------------------------------- #
    def test_a_meta_holding_a_sequence_is_also_unreadable(self):
        """Parseable YAML, wrong document type.

        `.get` on a list raised AttributeError straight into the same bare
        `except Exception`, so this shape was swallowed by the identical path.
        """
        self._place(CORRUPT_SLUG, "- company: Acme Labs\n- role: ML Engineer\n")
        self.assertEqual(self._run("--check-locations").returncode, 1)
        self.assertEqual(self._run("--sync-log").returncode, 1)
        self.assertEqual(self._log_rows(), [])

    def test_an_unreadable_tailored_yaml_also_blocks_the_write(self):
        """The other swallowed read in the same function.

        `tailored.yaml` supplies the role only when meta.yaml supplied none, and
        `fold_key` identifies a url-less posting by (company, role) — so that role
        is part of a skip-log identity too.
        """
        app = self._place(CORRUPT_SLUG, 'company: Acme Labs\nresearch_date: "2026-07-01"\n')
        (app / "source" / "tailored.yaml").write_text(
            "title: ML Engineer: Platform\n", encoding="utf-8")
        proc = self._run("--sync-log")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual(self._log_rows(), [])

    # -- the read-only view stays survivable ------------------------------- #
    def test_the_default_table_reports_but_does_not_abort(self):
        """One broken file must not hide the other forty rows.

        The default table is a pipeline view, not a gate; --check-metadata and
        --check-locations are the gates. So this stays exit 0 and says so out loud.
        """
        self._place_pair()
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(HEALTHY_SLUG.split("-")[0].title(), proc.stdout)
        self.assertIn(CORRUPT_SLUG, proc.stdout)
        self.assertIn("Unreadable metadata (1)", proc.stdout)

    def test_json_output_carries_the_error(self):
        self._place_pair()
        proc = self._run("--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = {a["slug"]: a for a in json.loads(proc.stdout)}
        self.assertIn("meta.yaml", rows[CORRUPT_SLUG]["meta_error"])
        self.assertNotIn("meta_error", rows[HEALTHY_SLUG])


if __name__ == "__main__":
    unittest.main()
