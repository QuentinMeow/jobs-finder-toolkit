"""End-to-end tests for `status.py --update` / `--update-job` (schema v4).

status.py resolves its applications root from config at import time, so each case
runs it as a subprocess with JOBHUNT_CONFIG pointed at a throwaway config +
applications tree (no private overlay, fictional data only).

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s .agents/skills/application-tracker/scripts/tests \
        -t .agents/skills/application-tracker/scripts/tests
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path

import yaml

STATUS = Path(__file__).resolve().parents[1] / "status.py"

STATUS_DIRS = {
    "drafted": "6_drafted",
    "applied": "5_applied",
    "in_progress": "4_in_progress",
    "rejected": "3_rejected",
    "ignored": "2_ignored",
}


def _job(role: str, status: str, jd_file: str) -> dict:
    """A fully valid schema-v4 posting (fictional data)."""
    return {
        "role": role,
        "jd_file": jd_file,
        "status": status,
        "workplace": "remote",
        "sponsorship": "unknown",
        "job_level": {"normalized": "senior", "min": 5.0, "max": 5.8,
                      "confidence": "low", "source": "title"},
        "required_yoe": {"min": 5, "max": None, "confidence": "high",
                         "source": "job_description"},
        "salary_range": None,
    }


class StatusTransitionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.apps = self.root / "apps"
        (self.root / "config.yaml").write_text(textwrap.dedent(f"""\
            paths:
              applications_root: "{self.apps.as_posix()}"
            """), encoding="utf-8")

    def _place(self, status_label: str, slug: str, jobs: list[dict],
               *, version: int = 4) -> Path:
        app = self.apps / STATUS_DIRS[status_label] / slug
        (app / "source").mkdir(parents=True)
        for job in jobs:
            jd = job.get("jd_file")
            if jd:
                (app / "source" / jd).write_text("Fictional JD.", encoding="utf-8")
        meta = {
            "job_metadata_schema_version": version,
            "company": "Example Corp",
            "research_date": "2026-07-20",
            "jobs": jobs,
        }
        (app / "meta.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
        return app

    def _run(self, *args):
        env = dict(os.environ, JOBHUNT_CONFIG=str(self.root / "config.yaml"))
        return subprocess.run(
            [sys.executable, str(STATUS), *args],
            capture_output=True, text=True, env=env)

    def _find(self, slug: str) -> tuple[str, Path] | None:
        for label, folder in STATUS_DIRS.items():
            app = self.apps / folder / slug
            if app.is_dir():
                return label, app
        return None

    def _meta(self, app: Path) -> dict:
        return yaml.safe_load((app / "meta.yaml").read_text())

    # -- --update ---------------------------------------------------------- #
    def test_update_sets_all_job_statuses_stamps_date_and_moves(self):
        slug = "example-corp-multi-20260720"
        self._place("drafted", slug, [
            _job("Backend Engineer", "drafted", "JD-backend.md"),
            _job("Platform Engineer", "drafted", "JD-platform.md"),
        ])
        proc = self._run("--update", slug, "applied")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        label, app = self._find(slug)
        self.assertEqual(label, "applied")  # folder moved 6_drafted -> 5_applied
        meta = self._meta(app)
        today = date.today().isoformat()
        for job in meta["jobs"]:
            self.assertEqual(job["status"], "applied")
            self.assertEqual(job["status_date"], today)

    def test_update_refuses_non_v4_meta_without_moving(self):
        slug = "example-corp-legacy-20260720"
        self._place("drafted", slug,
                    [{"role": "Legacy", "jd_file": "JD-legacy.md"}], version=3)
        proc = self._run("--update", slug, "applied")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("schema v4", proc.stderr)
        self.assertEqual(self._find(slug)[0], "drafted")  # not moved

    # -- --update-job ------------------------------------------------------ #
    def test_update_job_by_role_substring_moves_on_rollup(self):
        slug = "example-corp-multi-20260720"
        self._place("applied", slug, [
            _job("Backend Engineer", "applied", "JD-backend.md"),
            _job("Platform Engineer", "applied", "JD-platform.md"),
        ])
        proc = self._run("--update-job", slug, "platform", "in_progress")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        label, app = self._find(slug)
        # in_progress outranks applied, so the whole app moves to 4_in_progress.
        self.assertEqual(label, "in_progress")
        meta = self._meta(app)
        self.assertEqual(meta["jobs"][0]["status"], "applied")     # untouched
        self.assertEqual(meta["jobs"][1]["status"], "in_progress")
        self.assertEqual(meta["jobs"][1]["status_date"], date.today().isoformat())

    def test_update_job_by_index(self):
        slug = "example-corp-multi-20260720"
        self._place("applied", slug, [
            _job("Backend Engineer", "applied", "JD-backend.md"),
            _job("Platform Engineer", "applied", "JD-platform.md"),
        ])
        proc = self._run("--update-job", slug, "1", "rejected")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        label, app = self._find(slug)
        # One rejected, one applied -> applied still wins; folder stays 5_applied.
        self.assertEqual(label, "applied")
        meta = self._meta(app)
        self.assertEqual(meta["jobs"][0]["status"], "rejected")

    def test_update_job_rollup_downgrade_moves_folder(self):
        slug = "example-corp-multi-20260720"
        self._place("in_progress", slug, [
            _job("Backend Engineer", "rejected", "JD-backend.md"),
            _job("Platform Engineer", "in_progress", "JD-platform.md"),
        ])
        # Reject the sole in_progress role -> everything rejected -> move to 3_rejected.
        proc = self._run("--update-job", slug, "platform", "rejected")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._find(slug)[0], "rejected")

    def test_update_job_ambiguous_role_lists_candidates_and_fails(self):
        slug = "example-corp-multi-20260720"
        self._place("applied", slug, [
            _job("Senior Backend Engineer", "applied", "JD-backend.md"),
            _job("Senior Platform Engineer", "applied", "JD-platform.md"),
        ])
        proc = self._run("--update-job", slug, "engineer", "rejected")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("matches 2 postings", proc.stderr)
        self.assertIn("Senior Backend Engineer", proc.stderr)
        self.assertEqual(self._find(slug)[0], "applied")  # nothing moved

    def test_update_job_stage_only_keep_requires_stage(self):
        slug = "example-corp-solo-20260720"
        self._place("in_progress", slug,
                    [_job("Backend Engineer", "in_progress", "JD-backend.md")])
        missing = self._run("--update-job", slug, "backend", "keep")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("--stage", missing.stderr)

        proc = self._run("--update-job", slug, "backend", "keep",
                         "--stage", "onsite scheduled")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        label, app = self._find(slug)
        self.assertEqual(label, "in_progress")  # status unchanged, no move
        meta = self._meta(app)
        self.assertEqual(meta["jobs"][0]["stage"], "onsite scheduled")
        self.assertEqual(meta["jobs"][0]["status"], "in_progress")

    def test_update_job_status_change_with_stage(self):
        slug = "example-corp-solo-20260720"
        self._place("applied", slug,
                    [_job("Backend Engineer", "applied", "JD-backend.md")])
        proc = self._run("--update-job", slug, "backend", "in_progress",
                         "--stage", "recruiter screen")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        label, app = self._find(slug)
        self.assertEqual(label, "in_progress")
        meta = self._meta(app)
        self.assertEqual(meta["jobs"][0]["status"], "in_progress")
        self.assertEqual(meta["jobs"][0]["stage"], "recruiter screen")


if __name__ == "__main__":
    unittest.main()
