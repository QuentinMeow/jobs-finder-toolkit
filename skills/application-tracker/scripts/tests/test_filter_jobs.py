"""Tests for `filter_jobs.py` — posting-granularity filtering across status folders.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/application-tracker/scripts/tests \
        -p "test_filter*"

filter_jobs.py reads its applications root from config at runtime, so each case builds
a throwaway v5 fixture tree in a tmp dir and runs the script as a subprocess with
JOBHUNT_CONFIG pointed at a matching config.yaml (no private overlay, fictional
companies only). Mirrors test_check_locations.py's harness.
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

SCRIPT = Path(__file__).resolve().parents[1] / "filter_jobs.py"

# Status label -> on-disk folder (the stable contract from _vendor/layout.py).
STATUS_DIRS = {
    "drafted": "6_drafted",
    "applied": "5_applied",
    "in_progress": "4_in_progress",
    "rejected": "3_rejected",
    "ignored": "2_ignored",
}


# ── fixture builders ──────────────────────────────────────────
def _job(role, *, status=None, level=None, salary=None, yoe=None, posted=None,
         workplace=None, sponsorship=None, fit=None, progress=None, location=None,
         status_date=None, url=None, jd_file=None):
    """Build a v5 `jobs:` entry. level/salary/yoe are (min, max) tuples or None.

    A tuple with a None member (e.g. (5.0, None)) exercises the null-bound handling.
    """
    j = {"role": role}
    for key, val in (("status", status), ("status_date", status_date),
                     ("progress", progress), ("location", location),
                     ("workplace", workplace), ("sponsorship", sponsorship),
                     ("fit", fit), ("url", url), ("jd_file", jd_file),
                     ("posted_date", posted)):
        if val is not None:
            j[key] = val
    j["job_level"] = ({"normalized": "senior", "min": level[0], "max": level[1],
                       "confidence": "low", "source": "title"} if level else None)
    j["required_yoe"] = ({"min": yoe[0], "max": yoe[1], "confidence": "high",
                          "source": "job_description"} if yoe else None)
    j["salary_range"] = ({"min": salary[0], "max": salary[1], "confidence": "high",
                          "source": "job_description"} if salary else None)
    return j


def _meta(company, jobs, *, version=5, research_date="2026-07-15",
          channel="cold", **extra):
    m = {"job_metadata_schema_version": version, "company": company,
         "research_date": research_date, "channel": channel, "jobs": jobs}
    m.update(extra)
    return m


class FilterJobsTests(unittest.TestCase):
    # ── harness ────────────────────────────────────────────────
    def _write_tree(self, tree: dict) -> Path:
        """Materialize {label: {slug: meta_dict}} and return the config.yaml path."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        root = Path(tmp)
        apps = root / "apps"
        for label, slugs in tree.items():
            folder = apps / STATUS_DIRS[label]
            for slug, meta in slugs.items():
                app = folder / slug
                app.mkdir(parents=True)
                (app / "meta.yaml").write_text(
                    yaml.safe_dump(meta, default_flow_style=False, sort_keys=False),
                    encoding="utf-8")
        cfg = root / "config.yaml"
        cfg.write_text(textwrap.dedent(f"""\
            paths:
              applications_root: "{apps.as_posix()}"
            """), encoding="utf-8")
        return cfg

    def _run(self, cfg: Path, *args):
        env = dict(os.environ, JOBHUNT_CONFIG=str(cfg))
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, env=env)
        return proc.returncode, proc.stdout, proc.stderr

    def _run_tree(self, tree: dict, *args):
        return self._run(self._write_tree(tree), *args)

    def _count(self, tree, *args) -> int:
        rc, out, _ = self._run_tree(tree, "--count", *args)
        self.assertEqual(rc, 0)
        return int(out.strip())

    def _json(self, tree, *args):
        rc, out, _ = self._run_tree(tree, "--json", *args)
        self.assertEqual(rc, 0)
        return json.loads(out)

    # ── per-job status filtering across folders ────────────────
    def test_status_filter_uses_per_job_status_not_folder(self):
        # One app in the 5_applied folder holds a mixed pair of postings: one still
        # 'applied', one already 'rejected'. The per-job status must win over folder.
        tree = {
            "drafted": {"nimbus-draft": _meta(
                "Nimbus Data", [_job("Backend Engineer", status="drafted")])},
            "applied": {"meridian-mix": _meta("Meridian Systems", [
                _job("Platform Engineer", status="applied"),
                _job("Data Engineer", status="rejected"),
            ])},
            "in_progress": {"aurora-live": _meta(
                "Aurora Dynamics", [_job("SRE", status="in_progress")])},
        }
        self.assertEqual(self._count(tree, "--status", "applied"), 1)
        self.assertEqual(self._count(tree, "--status", "rejected"), 1)
        # OR-list across statuses.
        self.assertEqual(self._count(tree, "--status", "applied,in_progress"), 2)
        # The rejected posting lives physically in 5_applied yet filters as rejected.
        recs = self._json(tree, "--status", "rejected")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["role"], "Data Engineer")
        self.assertEqual(recs[0]["folder_status"], "applied")
        self.assertEqual(recs[0]["status"], "rejected")

    # ── structured progress filtering (schema v5) ──────────────
    def test_phase_and_progress_state_filters(self):
        tree = {"in_progress": {
            "aurora-screen": _meta("Aurora Dynamics", [_job(
                "SRE", status="in_progress",
                progress={"phase": "recruiter_screen",
                          "state": "booking_required"})]),
            "cobalt-loop": _meta("Cobalt Works", [_job(
                "Backend", status="in_progress",
                progress={"phase": "interview_loop",
                          "state": "scheduled"})]),
            "nimbus-loop": _meta("Nimbus Data", [_job(
                "Platform", status="in_progress",
                progress={"phase": "interview_loop",
                          "state": "awaiting_schedule"})]),
        }}
        # Phase membership, OR within the comma list.
        self.assertEqual(self._count(tree, "--phase", "interview_loop"), 2)
        self.assertEqual(
            self._count(tree, "--phase", "recruiter_screen,interview_loop"), 3)
        # Progress-state membership.
        recs = self._json(tree, "--progress-state", "booking_required")
        self.assertEqual([r["company"] for r in recs], ["Aurora Dynamics"])
        # AND across phase + state narrows to one.
        self.assertEqual(
            self._count(tree, "--phase", "interview_loop",
                        "--progress-state", "scheduled"), 1)
        # A job with no progress mapping fails an active progress filter.
        bare = {"in_progress": {"bare": _meta("Bare Corp", [
            _job("X", status="in_progress")])}}
        self.assertEqual(self._count(bare, "--progress-state", "scheduled"), 0)

    # ── multi-role app -> multiple rows ────────────────────────
    def test_multi_role_app_produces_one_row_per_job(self):
        tree = {"applied": {"cobalt-two": _meta("Cobalt Works", [
            _job("Backend Engineer", status="applied"),
            _job("Frontend Engineer", status="applied"),
            _job("ML Engineer", status="rejected"),
        ])}}
        self.assertEqual(self._count(tree), 3)
        roles = sorted(r["role"] for r in self._json(tree))
        self.assertEqual(roles, ["Backend Engineer", "Frontend Engineer",
                                 "ML Engineer"])

    # ── substring OR-lists ─────────────────────────────────────
    def test_substring_or_lists(self):
        tree = {"drafted": {
            "aurora": _meta("Aurora Dynamics",
                            [_job("Backend Engineer", status="drafted")]),
            "cobalt": _meta("Cobalt Works",
                            [_job("Platform Engineer", status="drafted")]),
            "nimbus": _meta("Nimbus Data",
                            [_job("Frontend Engineer", status="drafted")]),
        }}
        # company OR (case-insensitive substring).
        self.assertEqual(self._count(tree, "--company", "aurora,cobalt"), 2)
        # role OR.
        self.assertEqual(self._count(tree, "--role", "backend,frontend"), 2)
        # AND across two flags narrows to one.
        self.assertEqual(
            self._count(tree, "--company", "aurora,cobalt", "--role", "backend"), 1)

    # ── level overlap edges ────────────────────────────────────
    def test_level_overlap_edges(self):
        tree = {"drafted": {
            "high": _meta("Riverstone Labs",
                          [_job("Staff Eng", status="drafted", level=(5.0, 5.7))]),
            "low": _meta("Meridian Systems",
                         [_job("Junior Eng", status="drafted", level=(3.0, 3.5))]),
            "openmin": _meta("Aurora Dynamics",
                             [_job("Senior Eng", status="drafted", level=(5.0, None))]),
            "nolevel": _meta("Cobalt Works",
                             [_job("Mystery Eng", status="drafted")]),
        }}
        # 5.5 falls inside [5.0, 5.7] -> match high; low excluded; open-min matches
        # (5.0..inf); no-level excluded because a level filter is active.
        recs = self._json(tree, "--min-level", "5.5")
        self.assertEqual(sorted(r["company"] for r in recs),
                         ["Aurora Dynamics", "Riverstone Labs"])
        # max-level 4.0: only the low envelope [3.0,3.5] overlaps; open-min [5.0,inf]
        # excluded (min 5.0 > 4.0); no-level excluded.
        recs = self._json(tree, "--max-level", "4.0")
        self.assertEqual([r["company"] for r in recs], ["Meridian Systems"])
        # A no-numeric-level posting is always dropped once any level filter is used.
        self.assertEqual(self._count(tree, "--min-level", "0.0"), 3)

    # ── salary + yoe null handling ─────────────────────────────
    def test_salary_null_handling(self):
        tree = {"drafted": {
            "hasmax": _meta("Riverstone Labs", [_job(
                "A", status="drafted", salary=(185000, 240000))]),
            "minonly": _meta("Meridian Systems", [_job(
                "B", status="drafted", salary=(180000, None))]),
            "nosalary": _meta("Aurora Dynamics", [_job("C", status="drafted")]),
        }}
        # >=200k: hasmax (max 240k) qualifies; min-only (180k) does not; null excluded.
        recs = self._json(tree, "--min-salary", "200000")
        self.assertEqual([r["company"] for r in recs], ["Riverstone Labs"])
        # >=150k: hasmax + min-only (uses its min); null still excluded.
        self.assertEqual(self._count(tree, "--min-salary", "150000"), 2)

    def test_yoe_null_handling(self):
        tree = {"drafted": {
            "seven": _meta("Riverstone Labs", [_job(
                "A", status="drafted", yoe=(7, None))]),
            "three": _meta("Meridian Systems", [_job(
                "B", status="drafted", yoe=(3, 6))]),
            "noyoe": _meta("Aurora Dynamics", [_job("C", status="drafted")]),
        }}
        # max-yoe 6: min 7 excluded; min 3 kept; unknown requirement passes.
        recs = self._json(tree, "--max-yoe", "6")
        self.assertEqual(sorted(r["company"] for r in recs),
                         ["Aurora Dynamics", "Meridian Systems"])

    # ── posted-after exclusion ─────────────────────────────────
    def test_posted_after_excludes_missing_and_older(self):
        tree = {"drafted": {
            "recent": _meta("Riverstone Labs", [_job(
                "A", status="drafted", posted="2026-07-10")]),
            "old": _meta("Meridian Systems", [_job(
                "B", status="drafted", posted="2026-06-01")]),
            "undated": _meta("Aurora Dynamics", [_job("C", status="drafted")]),
        }}
        recs = self._json(tree, "--posted-after", "2026-07-01")
        self.assertEqual([r["company"] for r in recs], ["Riverstone Labs"])

    # ── sort + limit ───────────────────────────────────────────
    def test_sort_date_then_limit(self):
        tree = {"applied": {
            "a": _meta("Aurora Dynamics", [_job(
                "A", status="applied", posted="2026-07-01")]),
            "b": _meta("Cobalt Works", [_job(
                "B", status="applied", posted="2026-07-20")]),
            "c": _meta("Meridian Systems", [_job(
                "C", status="applied", posted="2026-07-10")]),
        }}
        recs = self._json(tree, "--sort", "date", "--limit", "2")
        # Newest first, capped at 2: 07-20 then 07-10.
        self.assertEqual([r["company"] for r in recs],
                         ["Cobalt Works", "Meridian Systems"])

    def test_sort_salary_max_desc_nulls_last(self):
        tree = {"drafted": {
            "hi": _meta("Riverstone Labs", [_job(
                "A", status="drafted", salary=(200000, 300000))]),
            "mid": _meta("Meridian Systems", [_job(
                "B", status="drafted", salary=(150000, 190000))]),
            "none": _meta("Aurora Dynamics", [_job("C", status="drafted")]),
        }}
        recs = self._json(tree, "--sort", "salary")
        self.assertEqual([r["company"] for r in recs],
                         ["Riverstone Labs", "Meridian Systems", "Aurora Dynamics"])

    # ── --json shape ───────────────────────────────────────────
    def test_json_record_shape(self):
        tree = {"in_progress": {"aurora": _meta("Aurora Dynamics", [_job(
            "Senior Platform Engineer", status="in_progress", status_date="2026-07-18",
            progress={"phase": "interview_loop", "state": "awaiting_schedule",
                      "label": "onsite"},
            location="Remote (US)", workplace="remote",
            sponsorship="unknown", fit="strong", level=(5.0, 5.7),
            yoe=(5, None), salary=(185000, 240000), url="https://example.test/job",
            jd_file="JD-senior-platform-engineer.md")])}}
        recs = self._json(tree)
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        expected_keys = {
            "status", "folder_status", "company", "role", "location", "workplace",
            "sponsorship", "fit", "job_level", "required_yoe", "salary_range",
            "posted_date", "research_date", "channel", "phase", "progress_state",
            "progress_label", "status_date", "url", "jd_file", "slug",
            "schema_version",
        }
        self.assertEqual(set(rec.keys()), expected_keys)
        # No internal helper keys leak into JSON.
        self.assertFalse(any(k.startswith("_") for k in rec))
        self.assertEqual(rec["status"], "in_progress")
        self.assertEqual(rec["phase"], "interview_loop")
        self.assertEqual(rec["progress_state"], "awaiting_schedule")
        self.assertEqual(rec["progress_label"], "onsite")
        self.assertEqual(rec["status_date"], "2026-07-18")
        self.assertEqual(rec["url"], "https://example.test/job")
        self.assertEqual(rec["jd_file"], "JD-senior-platform-engineer.md")
        self.assertEqual(rec["required_yoe"]["min"], 5)
        self.assertIsNone(rec["required_yoe"]["max"])
        self.assertEqual(rec["job_level"]["max"], 5.7)
        self.assertEqual(rec["slug"], "aurora")

    # ── --count ────────────────────────────────────────────────
    def test_count_outputs_bare_number(self):
        tree = {"applied": {"cobalt": _meta("Cobalt Works", [
            _job("A", status="applied"), _job("B", status="applied")])}}
        rc, out, _ = self._run_tree(tree, "--count")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "2")

    # ── default table renders ──────────────────────────────────
    def test_default_table_renders(self):
        tree = {"applied": {"cobalt": _meta("Cobalt Works", [_job(
            "Backend Engineer", status="applied", level=(5.0, 5.7),
            salary=(185000, 240000))])}}
        rc, out, _ = self._run_tree(tree)
        self.assertEqual(rc, 0)
        for token in ("STATUS", "COMPANY", "LEVEL", "SALARY",
                      "Cobalt Works", "5.0–5.7", "185–240k", "1 job"):
            self.assertIn(token, out)

    # ── non-v5 warning on stderr (still included best-effort) ───
    def test_non_v5_warns_on_stderr_and_reads_v5_fields_only(self):
        # A pre-v5 flat file (top-level role, no jobs: list) warns and yields no
        # rows; a non-v5 file WITH a jobs: list warns but its entries still list
        # best-effort, with no per-job status and no legacy-shape translation.
        flat = {
            "job_metadata_schema_version": 2,
            "company": "Legacy Systems",
            "research_date": "2026-06-30",
            "source": "cold",
            "role": "Senior Software Engineer",
            "location": "Remote (US)",
        }
        listed = {
            "job_metadata_schema_version": 3,
            "company": "Halfway Corp",
            "research_date": "2026-06-30",
            "source": "cold",              # pre-v4 name for `channel`: NOT translated
            "jobs": [{"role": "Platform Engineer", "location": "Remote (US)"}],
        }
        tree = {"applied": {"legacy-flat": flat, "legacy-listed": listed}}
        rc, out, err = self._run_tree(tree, "--json")
        self.assertEqual(rc, 0)
        self.assertIn("job_metadata_schema_version", err)
        self.assertIn("expected 5", err)
        recs = json.loads(out)
        # Only the jobs:-list entry survives; the flat file contributes nothing.
        self.assertEqual([r["role"] for r in recs], ["Platform Engineer"])
        self.assertEqual(recs[0]["folder_status"], "applied")
        self.assertEqual(recs[0]["status"], "")   # no per-job status in the file
        self.assertEqual(recs[0]["channel"], "")  # legacy `source` is not translated

    # ── empty result contract ──────────────────────────────────
    def test_empty_result_table_exits_zero_with_stderr_note(self):
        tree = {"drafted": {"nimbus": _meta("Nimbus Data",
                                            [_job("A", status="drafted")])}}
        rc, out, err = self._run_tree(tree, "--company", "no-such-company")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "")
        self.assertIn("no matching jobs", err)

    def test_empty_result_count_is_zero(self):
        tree = {"drafted": {"nimbus": _meta("Nimbus Data",
                                            [_job("A", status="drafted")])}}
        rc, out, _ = self._run_tree(tree, "--company", "nope", "--count")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "0")


if __name__ == "__main__":
    unittest.main()
