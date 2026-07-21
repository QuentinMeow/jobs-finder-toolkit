"""Tests for handoff.py — the search -> drafting folder bridge.

NO network: the JD is fetched from local ``file://`` fixtures, and the metadata
carry-over / validation runs entirely on synthetic search rows for a fictional
company. One test subprocesses the application-tracker's ``--check-metadata`` to
prove a fresh handoff folder validates unmodified (subprocess is allowed here).

Run with:
    .venv/bin/python -m unittest discover -s .agents/skills/job-search/scripts/tests
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# Make the sibling script (and its _vendor/) importable.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import handoff  # noqa: E402
from job_metadata import validate_meta  # noqa: E402

import yaml  # noqa: E402

# .agents/skills/job-search/scripts/tests/ -> repo root is five parents up.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_STATUS_PY = (
    _REPO_ROOT / ".agents" / "skills" / "application-tracker" / "scripts" / "status.py"
)

# A fictional posting page — no real names/employers (public repo).
JD_PAGE = """<!doctype html>
<html><body>
  <h1>Senior Platform Engineer</h1>
  <p>Nimbus Robotics builds autonomous warehouse robots. You will design and
     operate the Kubernetes platform every product team ships on.</p>
  <h2>Requirements</h2>
  <ul><li>5+ years operating production distributed systems</li></ul>
  <h2>Benefits</h2>
  <p>We sponsor H-1B transfers. Compensation is $190k-$230k base plus equity.</p>
</body></html>
"""


def _row(**overrides):
    """A complete, pipeline-shaped search row (JobPosting.to_dict()) to mutate."""
    row = {
        "source": "greenhouse",
        "company": "Nimbus Robotics",
        "title": "Senior Platform Engineer",
        "url": "",
        "location": "Remote (US)",
        "remote": "remote",
        "posted_at": "2026-07-15T00:00:00+00:00",
        "description": "We sponsor H-1B transfers. $190k-$230k base.",
        "age_days": 5.0,
        "visa_label": "yes",
        "visa_hits": ["sponsor h-1b"],
        "workplace": "remote",
        "sponsorship": "likely",
        "job_level": {"normalized": "senior", "min": 5.0, "max": 5.8,
                      "confidence": "medium", "source": "title"},
        "required_yoe": {"min": 5, "max": None, "confidence": "high",
                         "source": "job_description"},
        "salary_range": {"min": 190000, "max": 230000, "confidence": "high",
                         "source": "job_description"},
        "score": 88.5,
        "reasons": ["visa: sponsorship stated"],
    }
    row.update(overrides)
    return row


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.root = self.tmp / "apps"
        # A local JD fixture served over file:// so no test touches the network.
        self.jd_url = (self.tmp / "jd.html").as_uri()
        (self.tmp / "jd.html").write_text(JD_PAGE, encoding="utf-8")

    # -- helpers ---------------------------------------------------------- #
    def _write_json(self, rows) -> Path:
        path = self.tmp / "search.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        return path

    def _run(self, rows, select, *extra):
        """Run handoff.main; return (code, folder_path_or_None, stdout, stderr)."""
        json_path = self._write_json(rows)
        argv = ["--json", str(json_path), "--select", select,
                "--applications-root", str(self.root), *extra]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = handoff.main(argv)
        stdout = out.getvalue()
        # Stdout contract: line 1 is the folder path, line 2 the validation status.
        # Hard errors (bad selector, refuse-overwrite) print nothing to stdout.
        folder = None
        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("meta.yaml:"):
                folder = Path(stripped)
                break
        return code, folder, stdout, err.getvalue()

    def _run_all(self, rows, *extra):
        json_path = self._write_json(rows)
        report_path = self.tmp / "bulk-report.json"
        argv = [
            "--json", str(json_path), "--all",
            "--applications-root", str(self.root),
            "--report", str(report_path), *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = handoff.main(argv)
        report = json.loads(report_path.read_text()) if report_path.exists() else None
        return code, report, out.getvalue(), err.getvalue()

    def _tracker_check(self) -> dict:
        """Subprocess the tracker's --check-metadata over the drafted folder."""
        config_yaml = self.tmp / "config.yaml"
        config_yaml.write_text(
            f"paths:\n  applications_root: {json.dumps(str(self.root))}\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["JOBHUNT_CONFIG"] = str(config_yaml)
        proc = subprocess.run(
            [sys.executable, str(_STATUS_PY),
             "--check-metadata", "--statuses", "drafted", "--json"],
            capture_output=True, text=True, env=env,
        )
        return {"returncode": proc.returncode,
                "data": json.loads(proc.stdout), "stderr": proc.stderr}

    # -- tests ------------------------------------------------------------ #
    def test_happy_path_folder_meta_and_jd(self):
        code, folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        self.assertIsNotNone(folder)
        # Folder follows the <company>-<role>-<YYYYMMDD> convention under 6_drafted.
        self.assertTrue(folder.is_dir())
        self.assertEqual(folder.parent.name, "6_drafted")
        self.assertRegex(folder.name, r"^nimbus-robotics-senior-platform-engineer-\d{8}$")
        # JD saved verbatim under source/ with the JD-<title>.md name.
        jd = folder / "source" / "JD-senior-platform-engineer.md"
        self.assertTrue(jd.is_file())
        self.assertIn("# Senior Platform Engineer", jd.read_text(encoding="utf-8"))

    def test_meta_passes_vendored_validation_and_carries_facts(self):
        _code, folder, _out, _err = self._run([_row(url=self.jd_url)], "rank 1")
        meta = yaml.safe_load((folder / "meta.yaml").read_text())
        self.assertEqual(validate_meta(meta, app_dir=folder), [])
        # Every structured fact from the row is carried under the schema names.
        self.assertEqual(meta["company"], "Nimbus Robotics")
        self.assertEqual(meta["channel"], "greenhouse")           # row source
        job = meta["jobs"][0]
        self.assertEqual(job["role"], "Senior Platform Engineer")
        self.assertEqual(job["jd_file"], "JD-senior-platform-engineer.md")
        self.assertEqual(job["location"], "Remote (US)")
        self.assertEqual(job["url"], self.jd_url)
        self.assertEqual(job["posted_date"], "2026-07-15")        # date part only
        self.assertEqual(job["workplace"], "remote")
        self.assertEqual(job["sponsorship"], "likely")
        self.assertEqual(job["job_level"]["normalized"], "senior")
        self.assertEqual(job["required_yoe"]["min"], 5)
        self.assertEqual(job["salary_range"]["max"], 230000)

    def test_scaffold_emits_schema_v4_and_status_drafted(self):
        _code, folder, _out, _err = self._run([_row(url=self.jd_url)], "rank 1")
        meta = yaml.safe_load((folder / "meta.yaml").read_text())
        self.assertEqual(meta["job_metadata_schema_version"], 4)
        # Handoff always creates a fresh DRAFTED application.
        self.assertEqual(meta["jobs"][0]["status"], "drafted")

    def test_fresh_folder_passes_tracker_check_metadata(self):
        code, folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        result = self._tracker_check()
        self.assertEqual(result["returncode"], 0, result["stderr"])
        rows = result["data"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["valid"], rows[0]["errors"])
        self.assertEqual(rows[0]["slug"], folder.name)

    def test_select_by_rank_picks_the_ranked_row(self):
        rows = [
            _row(company="Alpha Systems", title="Staff Backend Engineer", url=self.jd_url),
            _row(company="Nimbus Robotics", title="Senior Platform Engineer", url=self.jd_url),
        ]
        _code, folder, _out, err = self._run(rows, "rank 2", "--skip-jd-fetch")
        self.assertIsNotNone(folder, err)
        self.assertTrue(folder.name.startswith("nimbus-robotics-senior-platform-engineer-"))
        # A bare integer is also accepted as a rank.
        code1, folder1, _o, _e = self._run(rows, "1", "--skip-jd-fetch")
        self.assertTrue(folder1.name.startswith("alpha-systems-staff-backend-engineer-"))

    def test_select_by_company_title(self):
        rows = [
            _row(company="Alpha Systems", title="Staff Backend Engineer", url=self.jd_url),
            _row(company="Nimbus Robotics", title="Senior Platform Engineer", url=self.jd_url),
        ]
        _code, folder, _out, err = self._run(
            rows, "Nimbus Robotics/Senior Platform Engineer", "--skip-jd-fetch")
        self.assertIsNotNone(folder, err)
        self.assertTrue(folder.name.startswith("nimbus-robotics-senior-platform-engineer-"))

    def test_missing_required_field_diagnostics(self):
        row = _row(url=self.jd_url)
        del row["job_level"]
        del row["required_yoe"]
        code, folder, stdout, err = self._run([row], "rank 1")
        self.assertEqual(code, 1)
        self.assertIn("INVALID", stdout)
        # The folder is still scaffolded; validation lists the gaps for enrichment.
        self.assertTrue(folder.is_dir())
        self.assertIn("job_level", err)
        self.assertIn("required_yoe", err)
        self.assertIn("enrich-metadata", err)
        meta = yaml.safe_load((folder / "meta.yaml").read_text())
        self.assertNotEqual(validate_meta(meta, app_dir=folder), [])

    def test_refuse_overwrite(self):
        rows = [_row(url=self.jd_url)]
        code1, folder, _out, err1 = self._run(rows, "rank 1")
        self.assertEqual(code1, 0, err1)
        sentinel = folder / "meta.yaml"
        original = sentinel.read_bytes()
        # A second handoff for the same company/role/date must refuse.
        code2, _folder2, _out2, err2 = self._run(rows, "rank 1")
        self.assertEqual(code2, 2)
        self.assertIn("refusing to overwrite", err2)
        self.assertEqual(sentinel.read_bytes(), original)   # untouched

    def test_bulk_handoff_skips_live_duplicate_and_creates_new_role(self):
        existing = _row(url=self.jd_url)
        code1, _folder, _out, err1 = self._run([existing], "rank 1")
        self.assertEqual(code1, 0, err1)
        second_url = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [
            existing,
            _row(title="Platform Engineer", url=second_url),
        ]
        code, report, stdout, err = self._run_all(rows)
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["duplicate"], 1)
        self.assertEqual(report["counts"]["created"], 1)
        self.assertIn("Bulk handoff:", stdout)
        self.assertEqual(
            len(list((self.root / "6_drafted").glob("*/meta.yaml"))), 2)

    def test_bulk_all_reports_location_mismatch_and_exits_nonzero(self):
        # --all must combine the location gate with bulk handoff: a mismatch row
        # is a distinct, auditable outcome and makes the whole bulk run non-zero,
        # while a clean row is still created in the same pass.
        self._pin_policy(metro=("springfield",))
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [
            _row(company="Alpha Systems", title="Staff Backend Engineer",
                 url=self.jd_url, location="Austin, TX (Hybrid)", remote="hybrid"),
            _row(company="Nimbus Robotics", title="Senior Platform Engineer",
                 url=url2, location="Remote (US)", remote="remote"),
        ]
        code, report, stdout, err = self._run_all(rows)
        self.assertEqual(code, 1, err)
        self.assertEqual(report["counts"]["location_mismatch"], 1)
        self.assertEqual(report["counts"]["created"], 1)
        statuses = {row["status"] for row in report["rows"]}
        self.assertIn("location_mismatch", statuses)
        self.assertIn("created", statuses)
        # The mismatch folder is left on disk for review (both folders present).
        self.assertEqual(
            len(list((self.root / "6_drafted").glob("*/meta.yaml"))), 2)
        self.assertIn("location_mismatch", stdout)

    def test_allow_location_mismatch_applies_to_bulk_all(self):
        # With the override, a would-be mismatch is created (warned, not blocked).
        self._pin_policy(metro=("springfield",))
        rows = [_row(company="Alpha Systems", title="Staff Backend Engineer",
                     url=self.jd_url, location="Austin, TX (Hybrid)",
                     remote="hybrid")]
        code, report, _stdout, err = self._run_all(rows, "--allow-location-mismatch")
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["created"], 1)
        self.assertEqual(report["counts"]["location_mismatch"], 0)

    def test_jd_fetch_failure_still_scaffolds_and_exits_nonzero(self):
        # A URL that cannot be fetched: the folder is scaffolded, exit is non-zero.
        bad_url = (self.tmp / "does-not-exist.html").as_uri()
        code, folder, stdout, err = self._run([_row(url=bad_url)], "rank 1")
        self.assertEqual(code, 1)
        self.assertTrue(folder.is_dir())
        self.assertTrue((folder / "meta.yaml").is_file())
        self.assertFalse((folder / "source" / "JD-senior-platform-engineer.md").exists())
        self.assertIn("save", err.lower())

    def test_rank_out_of_range_and_bad_selector(self):
        rows = [_row(url=self.jd_url)]
        code, _folder, _out, err = self._run(rows, "rank 5", "--skip-jd-fetch")
        self.assertEqual(code, 2)
        self.assertIn("out of range", err)
        code2, _f2, _o2, err2 = self._run(rows, "NotAPair", "--skip-jd-fetch")
        self.assertEqual(code2, 2)
        self.assertIn("neither a rank", err2)

    # -- location policy gate --------------------------------------------- #
    def _pin_policy(self, *, metro=("springfield",), allow_us_remote=True,
                    us_only=True):
        """Point config discovery at a temp config with a known location policy.

        handoff's location gate reads ``config.location_policy()``; pinning it makes
        every location verdict deterministic regardless of any real/example config
        that discovery would otherwise walk up to find.
        """
        import config  # vendored (same module handoff's gate imports)

        cfg = self.tmp / "policy-config.yaml"
        cfg.write_text(
            "location_policy:\n"
            f"  metro: [{', '.join(metro)}]\n"
            f"  allow_us_remote: {'true' if allow_us_remote else 'false'}\n"
            f"  us_only: {'true' if us_only else 'false'}\n",
            encoding="utf-8",
        )
        prev = os.environ.get("JOBHUNT_CONFIG")
        os.environ["JOBHUNT_CONFIG"] = str(cfg)
        config._load.cache_clear()

        def _restore():
            if prev is None:
                os.environ.pop("JOBHUNT_CONFIG", None)
            else:
                os.environ["JOBHUNT_CONFIG"] = prev
            config._load.cache_clear()

        self.addCleanup(_restore)

    def test_location_mismatch_blocks_and_leaves_folder(self):
        # A hybrid role in a non-preferred metro (the benchmark mis-handoff): the
        # gate flags it, keeps the folder on disk, and exits non-zero (3).
        self._pin_policy(metro=("springfield",))
        row = _row(url=self.jd_url, location="Austin, TX (Hybrid)", remote="hybrid")
        code, folder, stdout, err = self._run([row], "rank 1")
        self.assertEqual(code, 3, err)
        # Folder is NOT deleted — left for the agent to inspect / override / remove.
        self.assertTrue(folder.is_dir())
        self.assertTrue((folder / "meta.yaml").is_file())
        # Verdict + offending location string + a remedy hint, all on stderr.
        self.assertIn("MISMATCH", err)
        self.assertIn("other_us", err)
        self.assertIn("Austin", err)
        self.assertIn("--allow-location-mismatch", err)
        self.assertIn("delete the folder", err.lower())
        # Stdout keeps its two-line contract (folder + meta status only).
        self.assertNotIn("MISMATCH", stdout)

    def test_location_mismatch_foreign_blocks(self):
        self._pin_policy(metro=("springfield",))
        row = _row(url=self.jd_url, location="London, United Kingdom", remote="")
        code, folder, _out, err = self._run([row], "rank 1")
        self.assertEqual(code, 3, err)
        self.assertTrue(folder.is_dir())
        self.assertIn("foreign", err)
        self.assertIn("London", err)

    def test_allow_location_mismatch_override_proceeds(self):
        # With the override flag a mismatch is acknowledged but no longer blocks;
        # the exit code then reflects only meta/JD completeness (here: clean -> 0).
        self._pin_policy(metro=("springfield",))
        row = _row(url=self.jd_url, location="Austin, TX (Hybrid)", remote="hybrid")
        code, folder, _out, err = self._run(
            [row], "rank 1", "--allow-location-mismatch")
        self.assertEqual(code, 0, err)
        self.assertTrue(folder.is_dir())
        self.assertIn("MISMATCH", err)                      # still reported
        self.assertIn("--allow-location-mismatch set", err)  # override acknowledged

    def test_location_match_metro_confirmation(self):
        # A preferred-metro posting matches -> one confirmation line, exit 0.
        self._pin_policy(metro=("austin",))
        row = _row(url=self.jd_url, location="Austin, TX", remote="")
        code, folder, _out, err = self._run([row], "rank 1")
        self.assertEqual(code, 0, err)
        self.assertIn("location OK", err)
        self.assertIn("metro", err)
        self.assertNotIn("MISMATCH", err)

    def test_location_match_us_remote_confirmation(self):
        # US-remote is a match under the default allow_us_remote policy.
        self._pin_policy(metro=("springfield",))
        code, folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        self.assertIn("location OK", err)
        self.assertIn("us_remote", err)

    def test_location_unknown_is_review_not_block(self):
        # An unrecognized location is surfaced for review but does NOT block
        # (mirrors the tracker's review-vs-mismatch split).
        self._pin_policy(metro=("springfield",))
        row = _row(url=self.jd_url, location="Mars Colony", remote="")
        code, folder, _out, err = self._run([row], "rank 1")
        self.assertEqual(code, 0, err)
        self.assertTrue(folder.is_dir())
        self.assertIn("NOT classifiable", err)
        self.assertNotIn("MISMATCH", err)


if __name__ == "__main__":
    unittest.main()
