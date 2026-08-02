"""End-to-end tests for the append-only skip-log writers in `status.py`.

Covers `--sync-log` (now a union-only upsert that cannot truncate),
`--backfill-log`, `--forget-log`, and the event append that `--update-job` makes
at the moment of the status write.

The property every one of these exists to protect: **a row in the log whose
application folder is gone is left alone.** The old `--sync-log` rewrote the file
from a folder scan, so deleting a rejected application deleted its row and
job-search re-surfaced the posting as fresh.

status.py resolves its applications root from config at import time, so each case
runs it as a subprocess with JOBHUNT_CONFIG pointed at a throwaway config +
applications tree — no private overlay is ever reachable, and every company, slug
and URL below is fictional.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/application-tracker/scripts/tests \
        -t skills/application-tracker/scripts/tests
"""
from __future__ import annotations

import os
import shutil
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

import skip_log  # noqa: E402

STATUS_DIRS = {
    "drafted": "6_drafted",
    "applied": "5_applied",
    "in_progress": "4_in_progress",
    "rejected": "3_rejected",
    "ignored": "2_ignored",
}

COMPANY = "Example Corp"
OTHER_COMPANY = "Northwind Labs"
URL_A = "https://jobs.example.test/postings/1001?src=board"
URL_B = "https://jobs.example.test/postings/1002?src=board"
URL_GHOST = "https://jobs.northwind.test/postings/77"


def _progress(status: str) -> dict:
    """A valid progress summary for the given coarse status (v5 coupling)."""
    if status == "drafted":
        return {"phase": "application_prep", "state": "action_required"}
    if status == "applied":
        return {"phase": "application_review", "state": "waiting_employer"}
    if status in ("rejected", "ignored"):
        return {"phase": "recruiter_screen", "state": "closed"}
    return {"phase": "recruiter_screen", "state": "unknown"}


def _job(role: str, status: str, jd_file: str, url: str) -> dict:
    """A fully valid schema-v6 posting (fictional data)."""
    return {
        "role": role,
        "jd_file": jd_file,
        "url": url,
        "status": status,
        "progress": _progress(status),
        "workplace": "remote",
        "sponsorship": "unknown",
        "job_level": {"normalized": "senior", "min": 5.0, "max": 5.8,
                      "confidence": "low", "source": "title"},
        "required_yoe": {"min": 5, "max": None, "confidence": "high",
                         "source": "job_description"},
        "salary_range": None,
    }


class SkipLogWriterTests(unittest.TestCase):
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
        # candidate_dir() rides applications_root, so both logs land in the temp
        # tree. Asserted explicitly in test_config_isolation_keeps_both_logs_in_tmp.
        self.jsonl = self.apps / "0_profile" / "applications-log.jsonl"
        self.yaml_log = self.apps / "0_profile" / "applications-log.yaml"

    # -- fixture helpers --------------------------------------------------- #
    def _place(self, status_label: str, slug: str, jobs: list[dict],
               *, company: str = COMPANY, research_date: str = "2026-07-16") -> Path:
        app = self.apps / STATUS_DIRS[status_label] / slug
        (app / "source").mkdir(parents=True)
        for job in jobs:
            jd = job.get("jd_file")
            if jd:
                (app / "source" / jd).write_text("Fictional JD.", encoding="utf-8")
        meta = {
            "job_metadata_schema_version": 6,
            "company": company,
            "research_date": research_date,
            "jobs": jobs,
        }
        (app / "meta.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
        return app

    def _remove(self, status_label: str, slug: str) -> None:
        """Delete an application folder the way the owner would."""
        shutil.rmtree(self.apps / STATUS_DIRS[status_label] / slug)

    def _run(self, *args):
        env = dict(os.environ, JOBHUNT_CONFIG=str(self.config))
        return subprocess.run(
            [sys.executable, str(STATUS), *args],
            capture_output=True, text=True, env=env)

    def _sync(self):
        proc = self._run("--sync-log")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def _events(self) -> list[dict]:
        return skip_log.read_events(self.jsonl)

    def _fold(self) -> dict:
        return skip_log.fold(self.jsonl)

    def _folded(self, url: str) -> dict | None:
        return self._fold().get(skip_log.fold_key({"url": url}))

    # -- isolation --------------------------------------------------------- #
    _PROBE = (
        "import sys; sys.path.insert(0, sys.argv[1]); import config; "
        "print(config.applications_jsonl_path()); "
        "print(config.applications_log_path()); "
        "print(config.applications_root())"
    )

    def test_config_isolation_keeps_every_written_path_in_tmp(self):
        """Nothing these writers touch can resolve outside the temp tree.

        Guards the reason the suite drives a subprocess at all: an append-only log
        is not self-healing, so a single contaminated line written into a real
        skip-log would silently suppress a real posting forever.
        """
        env = dict(os.environ, JOBHUNT_CONFIG=str(self.config))
        probe = subprocess.run(
            [sys.executable, "-c", self._PROBE, str(SCRIPTS / "_vendor")],
            capture_output=True, text=True, env=env)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        paths = probe.stdout.strip().splitlines()
        self.assertEqual(len(paths), 3, probe.stdout)
        for line in paths:
            self.assertTrue(line.startswith(str(self.root)),
                            f"{line} escaped the temp tree {self.root}")

    # -- --sync-log -------------------------------------------------------- #
    def test_second_sync_with_no_changes_appends_nothing(self):
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._sync()
        self.assertEqual(len(self._events()), 1)
        proc = self._sync()
        self.assertEqual(len(self._events()), 1)
        self.assertIn("No posting changes", proc.stdout)

    def test_status_change_appends_exactly_one_event(self):
        slug = "example-corp-backend-20260716"
        self._place("drafted", slug,
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._sync()
        self.assertEqual(self._folded(URL_A)["status"], "drafted")

        # The owner moved the folder and edited the per-job status by hand.
        self._remove("drafted", slug)
        self._place("applied", slug,
                    [_job("Backend Engineer", "applied", "JD-backend.md", URL_A)])
        proc = self._sync()
        self.assertEqual(len(self._events()), 2)
        self.assertIn("Appended 1 posting event", proc.stdout)
        self.assertEqual(self._folded(URL_A)["status"], "applied")

    def test_deleted_folder_does_not_remove_its_row(self):
        """The whole phase in one test: an append-only log outlives its folder."""
        self._place("rejected", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "rejected", "JD-backend.md", URL_A)])
        self._place("drafted", "northwind-labs-platform-20260716",
                    [_job("Platform Engineer", "drafted", "JD-platform.md", URL_B)],
                    company=OTHER_COMPANY)
        self._sync()
        self.assertEqual(len(self._fold()), 2)

        self._remove("rejected", "example-corp-backend-20260716")
        proc = self._sync()
        self.assertEqual(len(self._events()), 2, "sync appended for a deletion")
        self.assertIn("No posting changes", proc.stdout)
        survivor = self._folded(URL_A)
        self.assertIsNotNone(survivor, "the deleted folder's row was truncated away")
        self.assertEqual(survivor["status"], "rejected")

    def test_two_folder_rows_sharing_a_url_do_not_ping_pong(self):
        """A re-application (same URL, new slug + date) must converge, not alternate.

        Both rows fold to one key, so if both reached the append loop at least one
        would differ from whatever the fold currently held and append on EVERY
        run, forever. They are collapsed last-wins instead.
        """
        self._place("rejected", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "rejected", "JD-backend.md", URL_A)],
                    research_date="2026-07-16")
        self._place("drafted", "example-corp-backend-20260801",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)],
                    research_date="2026-08-01")
        self._sync()
        first = len(self._events())
        self.assertEqual(first, 1, "colliding rows were not collapsed")
        # Last-wins keeps the fresher re-application, not the row it superseded.
        self.assertEqual(self._folded(URL_A)["slug"], "example-corp-backend-20260801")

        proc = self._sync()
        self.assertEqual(len(self._events()), first,
                         "a second sync appended again — the log ping-pongs")
        self.assertIn("No posting changes", proc.stdout)

    def test_sync_never_writes_the_yaml_log(self):
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._sync()
        self.assertFalse(self.yaml_log.exists(),
                         "--sync-log recreated the retired YAML projection")

        # And it leaves an existing one byte-for-byte alone.
        self.yaml_log.parent.mkdir(parents=True, exist_ok=True)
        self.yaml_log.write_text("postings: []\n", encoding="utf-8")
        before = self.yaml_log.read_bytes()
        self._remove("drafted", "example-corp-backend-20260716")
        self._sync()
        self.assertEqual(self.yaml_log.read_bytes(), before)

    # -- --backfill-log ---------------------------------------------------- #
    def _write_yaml_log(self, postings: list[dict]) -> None:
        self.yaml_log.parent.mkdir(parents=True, exist_ok=True)
        self.yaml_log.write_text(
            yaml.safe_dump({"count": len(postings), "postings": postings},
                           sort_keys=False), encoding="utf-8")

    def test_backfill_unions_yaml_and_folders_with_the_folder_winning(self):
        # A row whose folder the owner already deleted, plus a stale copy of a row
        # that still has a folder.
        self._write_yaml_log([
            {"company": OTHER_COMPANY, "slug": "northwind-labs-data-20260601",
             "date": "2026-06-01", "status": "rejected", "role": "Data Engineer",
             "url": URL_GHOST},
            {"company": COMPANY, "slug": "example-corp-backend-20260716",
             "date": "2026-07-16", "status": "drafted", "role": "Backend Engineer",
             "url": URL_A},
        ])
        self._place("applied", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "applied", "JD-backend.md", URL_A)])

        proc = self._run("--backfill-log")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("appended 2 event(s)", proc.stdout)
        self.assertIn("the fold now holds 2 posting(s)", proc.stdout)
        # The old YAML is named and left in place for the owner to remove.
        self.assertIn(str(self.yaml_log), proc.stdout)
        self.assertTrue(self.yaml_log.exists())

        fold = self._fold()
        self.assertEqual(len(fold), 2)
        # YAML-only row survives (it is exactly what the union is for) ...
        self.assertEqual(self._folded(URL_GHOST)["role"], "Data Engineer")
        # ... and the folder wins the key both sources carry.
        self.assertEqual(self._folded(URL_A)["status"], "applied")
        self.assertTrue(all(e["source"] == "backfill" for e in self._events()))

    def test_backfill_refuses_a_second_seed_and_names_force(self):
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self.assertEqual(self._run("--backfill-log").returncode, 0)
        events = len(self._events())

        refused = self._run("--backfill-log")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--force", refused.stderr)
        self.assertEqual(len(self._events()), events, "the refusal still wrote")

    def test_backfill_force_appends_a_fresh_generation(self):
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self.assertEqual(self._run("--backfill-log").returncode, 0)
        self.assertEqual(len(self._events()), 1)

        forced = self._run("--backfill-log", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        # A re-seed is just another append: nothing was deleted, the fold is the
        # same size, and the later line wins.
        self.assertEqual(len(self._events()), 2)
        self.assertEqual(len(self._fold()), 1)

    def test_force_without_backfill_is_rejected(self):
        proc = self._run("--force")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--backfill-log", proc.stderr)

    # -- --forget-log ------------------------------------------------------ #
    def test_forget_log_drops_a_url_key_and_prints_the_row(self):
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._place("drafted", "northwind-labs-platform-20260716",
                    [_job("Platform Engineer", "drafted", "JD-platform.md", URL_B)],
                    company=OTHER_COMPANY)
        self._sync()
        self.assertEqual(len(self._fold()), 2)
        # The real shape of an un-skip: the folder is already gone, which is what
        # leaves the row un-repairable by any other means.
        self._remove("drafted", "example-corp-backend-20260716")

        proc = self._run("--forget-log", URL_A)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Dropping from the skip-log", proc.stdout)
        self.assertIn("Backend Engineer", proc.stdout)

        fold = self._fold()
        self.assertEqual(len(fold), 1)
        self.assertIsNone(self._folded(URL_A))
        self.assertIsNotNone(self._folded(URL_B))
        # The repair is an append, never a deletion.
        self.assertEqual(len(self._events()), 3)
        self.assertTrue(self._events()[-1]["forget"])

    def test_forget_log_drops_a_company_role_key(self):
        # A posting with no URL folds to the (company, role) pair — exactly the
        # rows whose folders get deleted, so the pair branch has to work.
        self._place("rejected", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "rejected", "JD-backend.md", "")])
        self._sync()
        self.assertEqual(len(self._fold()), 1)
        self._remove("rejected", "example-corp-backend-20260716")

        proc = self._run("--forget-log", COMPANY, "Backend Engineer")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self._fold()), 0)

    def test_forget_log_refuses_while_a_live_folder_still_backs_the_key(self):
        """Otherwise the tombstone prints success and the next --sync-log reverts it.

        --sync-log rebuilds every row from the folders, so forgetting a posting whose
        folder is still there is undone within one command — silently, because both
        commands report success. A live folder is live evidence the posting was
        handled, so the thing to fix is the folder.
        """
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._sync()
        before = len(self._events())

        proc = self._run("--forget-log", URL_A)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("still backed by a live application folder", proc.stderr)
        self.assertIn("example-corp-backend-20260716", proc.stderr)
        self.assertEqual(len(self._events()), before, "the refusal still appended")
        self.assertEqual(len(self._fold()), 1)

    def test_a_forgotten_posting_is_not_resurrected_by_a_force_reseed(self):
        """--force re-seeds from the retired YAML, which still holds the forgotten row.

        The YAML is never updated after the migration, so without honouring tombstones
        a fresh generation reverses every --forget-log the owner ever ran, and reports
        only that it seeded N events.
        """
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._sync()
        # The retired YAML keeps the row even after the folder and the fold lose it.
        self.yaml_log.write_text(yaml.safe_dump({"postings": [{
            "company": COMPANY, "slug": "example-corp-backend-20260716",
            "date": "2026-07-16", "status": "drafted",
            "role": "Backend Engineer", "url": URL_A}]}), encoding="utf-8")
        self._remove("drafted", "example-corp-backend-20260716")
        self.assertEqual(self._run("--forget-log", URL_A).returncode, 0)
        self.assertEqual(len(self._fold()), 0)

        forced = self._run("--backfill-log", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertIn("tombstone", forced.stdout)
        self.assertEqual(len(self._fold()), 0, "the re-seed resurrected an un-skip")

    def test_forget_log_refuses_an_absent_key(self):
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._sync()
        before = len(self._events())

        proc = self._run("--forget-log", "https://jobs.example.test/postings/9999")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("refusing to append a tombstone", proc.stderr)
        self.assertEqual(len(self._events()), before, "the refusal still appended")
        self.assertEqual(len(self._fold()), 1)

    def test_forget_log_by_pair_on_a_url_bearing_row_refuses_with_near_misses(self):
        """A URL-bearing row is keyed by its URL; the pair form must not silently pass."""
        self._place("drafted", "example-corp-backend-20260716",
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._sync()

        proc = self._run("--forget-log", COMPANY, "Backend Engineer")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Closest folded rows", proc.stderr)
        self.assertIn("Backend Engineer", proc.stderr)
        self.assertIn("addressed by that URL", proc.stderr)
        self.assertEqual(len(self._fold()), 1)

    # -- --update / --update-job ------------------------------------------- #
    def test_update_job_appends_the_event(self):
        slug = "example-corp-backend-20260716"
        self._place("drafted", slug,
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        proc = self._run("--update-job", slug, "backend", "applied")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Recorded 1 posting event", proc.stdout)

        self.assertEqual(len(self._events()), 1)
        row = self._folded(URL_A)
        self.assertEqual(row["status"], "applied")
        self.assertEqual(row["slug"], slug)
        self.assertEqual(self._events()[0]["source"], "update")

        # A later sync sees no change: both writers build rows the same way.
        proc = self._sync()
        self.assertEqual(len(self._events()), 1)
        self.assertIn("No posting changes", proc.stdout)

    def test_update_appends_one_event_per_posting(self):
        slug = "example-corp-multi-20260716"
        self._place("drafted", slug, [
            _job("Backend Engineer", "drafted", "JD-backend.md", URL_A),
            _job("Platform Engineer", "drafted", "JD-platform.md", URL_B),
        ])
        proc = self._run("--update", slug, "applied")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Recorded 2 posting event", proc.stdout)
        self.assertEqual(len(self._fold()), 2)
        for url in (URL_A, URL_B):
            self.assertEqual(self._folded(url)["status"], "applied")

    def test_update_to_the_same_status_appends_nothing_the_second_time(self):
        slug = "example-corp-backend-20260716"
        self._place("drafted", slug,
                    [_job("Backend Engineer", "drafted", "JD-backend.md", URL_A)])
        self._run("--update", slug, "applied")
        self.assertEqual(len(self._events()), 1)
        proc = self._run("--update", slug, "applied")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self._events()), 1)


if __name__ == "__main__":
    unittest.main()
