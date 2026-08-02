"""Tests for handoff.py — the search -> drafting folder bridge.

NO network: the JD is fetched from local ``file://`` fixtures, and the metadata
carry-over / validation runs entirely on synthetic search rows for a fictional
company. One test subprocesses the application-tracker's ``--check-metadata`` to
prove a fresh handoff folder validates unmodified (subprocess is allowed here).

Run with:
    .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests
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
from layout import slugify_label  # noqa: E402  (the cover-letter/bundle filename key)
import skip_log  # noqa: E402  (importable because handoff puts _vendor/ on the path)

import shutil  # noqa: E402
import yaml  # noqa: E402

# Test-safety (store stage 1): handoff fetches the JD via fetch_jd, which now
# captures the page to the raw store. Isolate every capture in this module to a
# throwaway data root (env beats the machine config's real store).
_PRIOR_DATA_ROOT: str | None = None
_TMP_DATA_ROOT: str | None = None


def setUpModule():
    global _PRIOR_DATA_ROOT, _TMP_DATA_ROOT
    _PRIOR_DATA_ROOT = os.environ.get("JOBHUNT_DATA_ROOT")
    _TMP_DATA_ROOT = tempfile.mkdtemp(prefix="handoff-capture-")
    os.environ["JOBHUNT_DATA_ROOT"] = _TMP_DATA_ROOT
    try:
        import capture_hooks
        capture_hooks._reset_for_tests()
    except Exception:  # noqa: BLE001
        pass


def tearDownModule():
    if _PRIOR_DATA_ROOT is None:
        os.environ.pop("JOBHUNT_DATA_ROOT", None)
    else:
        os.environ["JOBHUNT_DATA_ROOT"] = _PRIOR_DATA_ROOT
    try:
        import capture_hooks
        capture_hooks._reset_for_tests()
    except Exception:  # noqa: BLE001
        pass
    if _TMP_DATA_ROOT:
        shutil.rmtree(_TMP_DATA_ROOT, ignore_errors=True)

# skills/job-search/scripts/tests/ -> repo root is five parents up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_STATUS_PY = (
    _REPO_ROOT / "skills" / "application-tracker" / "scripts" / "status.py"
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

    def test_scaffold_emits_schema_v6_and_status_drafted(self):
        _code, folder, _out, _err = self._run([_row(url=self.jd_url)], "rank 1")
        meta = yaml.safe_load((folder / "meta.yaml").read_text())
        self.assertEqual(meta["job_metadata_schema_version"], 6)
        # Handoff always creates a fresh DRAFTED application with the
        # deterministic drafted progress summary.
        self.assertEqual(meta["jobs"][0]["status"], "drafted")
        self.assertEqual(meta["jobs"][0]["progress"],
                         {"phase": "application_prep",
                          "state": "action_required"})

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
        # Two postings, two URLs: this test scaffolds both in turn, and a shared
        # URL is one posting as far as the duplicate preflight is concerned.
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [
            _row(company="Alpha Systems", title="Staff Backend Engineer", url=self.jd_url),
            _row(company="Nimbus Robotics", title="Senior Platform Engineer", url=url2),
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

    # -- one-folder-per-company grouping ---------------------------------- #
    def _run_raw(self, rows, *argv_extra):
        """Run handoff.main with arbitrary argv; return (code, stdout, stderr)."""
        json_path = self._write_json(rows)
        argv = ["--json", str(json_path),
                "--applications-root", str(self.root), *argv_extra]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = handoff.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _drafted_metas(self) -> list[dict]:
        return [yaml.safe_load(p.read_text())
                for p in (self.root / "6_drafted").glob("*/meta.yaml")]

    def test_select_company_groups_roles_into_one_folder(self):
        # DEFAULT: a bare "Company" selector puts every role in ONE folder with a
        # multi-role jobs: list — the one-folder-per-company default.
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [
            _row(title="Senior Platform Engineer", url=self.jd_url),
            _row(title="Backend Infrastructure Engineer", url=url2),
        ]
        code, _out, err = self._run_raw(rows, "--select", "Nimbus Robotics")
        self.assertEqual(code, 0, err)
        metas = self._drafted_metas()
        self.assertEqual(len(metas), 1, "expected ONE folder for the company")
        self.assertEqual(len(metas[0]["jobs"]), 2)
        self.assertEqual({j["role"] for j in metas[0]["jobs"]},
                         {"Senior Platform Engineer", "Backend Infrastructure Engineer"})
        # Lead (highest-ranked) role drives the folder slug.
        folder = next((self.root / "6_drafted").glob("*"))
        self.assertTrue(folder.name.startswith(
            "nimbus-robotics-senior-platform-engineer-"))
        # Each posting keeps its OWN verbatim JD file.
        src = folder / "source"
        self.assertTrue((src / "JD-senior-platform-engineer.md").is_file())
        self.assertTrue((src / "JD-backend-infrastructure-engineer.md").is_file())
        self.assertIn("grouped 2", err)

    def test_all_groups_one_folder_per_company(self):
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        url3 = (self.tmp / "jd3.html").as_uri()
        (self.tmp / "jd3.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [
            _row(title="Senior Platform Engineer", url=self.jd_url),
            _row(title="Backend Infrastructure Engineer", url=url2),
            _row(company="Alpha Systems", title="Staff Backend Engineer", url=url3),
        ]
        code, report, _stdout, err = self._run_all(rows)
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["created"], 2)  # two companies -> two folders
        by_company = {m["company"]: m for m in self._drafted_metas()}
        self.assertEqual(len(by_company["Nimbus Robotics"]["jobs"]), 2)
        self.assertEqual(len(by_company["Alpha Systems"]["jobs"]), 1)

    def test_split_forces_one_folder_per_posting(self):
        # The divergent-roles escape hatch: --split keeps the old per-posting layout.
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [
            _row(title="Senior Platform Engineer", url=self.jd_url),
            _row(title="Backend Infrastructure Engineer", url=url2),
        ]
        code, report, _stdout, err = self._run_all(rows, "--split")
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["created"], 2)  # split -> two folders
        self.assertEqual(len(self._drafted_metas()), 2)
        for meta in self._drafted_metas():
            self.assertEqual(len(meta["jobs"]), 1)

    def test_rank_list_groups_same_company(self):
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        url3 = (self.tmp / "jd3.html").as_uri()
        (self.tmp / "jd3.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [
            _row(title="Senior Platform Engineer", url=self.jd_url),
            _row(title="Backend Infrastructure Engineer", url=url2),
            _row(company="Alpha Systems", title="Staff Backend Engineer", url=url3),
        ]
        code, _out, err = self._run_raw(rows, "--select", "rank 1,2")
        self.assertEqual(code, 0, err)
        metas = self._drafted_metas()
        self.assertEqual(len(metas), 1)  # ranks 1,2 are both Nimbus -> one folder
        self.assertEqual(len(metas[0]["jobs"]), 2)

    def test_group_drops_location_mismatch_posting(self):
        # A multi-role company folder keeps only postings that pass the location
        # policy; a definite mismatch is dropped (not a whole-folder block).
        self._pin_policy(metro=("springfield",))
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [
            _row(title="Senior Platform Engineer", url=self.jd_url,
                 location="Remote (US)", remote="remote"),                 # match
            _row(title="Austin Onsite Engineer", url=url2,
                 location="Austin, TX (Hybrid)", remote="hybrid"),         # mismatch
        ]
        code, _out, err = self._run_raw(rows, "--select", "Nimbus Robotics")
        self.assertEqual(code, 0, err)
        metas = self._drafted_metas()
        self.assertEqual(len(metas), 1)
        self.assertEqual(len(metas[0]["jobs"]), 1)  # the mismatch posting dropped
        self.assertEqual(metas[0]["jobs"][0]["role"], "Senior Platform Engineer")
        self.assertIn("dropping", err)

    def test_unique_jd_filename_disambiguates_collisions(self):
        used: set[str] = set()
        self.assertEqual(handoff.unique_jd_filename("Backend Engineer!", used),
                         "JD-backend-engineer.md")
        self.assertEqual(handoff.unique_jd_filename("Backend Engineer", used),
                         "JD-backend-engineer-2.md")
        self.assertEqual(handoff.unique_jd_filename("backend engineer", used),
                         "JD-backend-engineer-3.md")

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
        # A second handoff for the same posting must refuse and change nothing.
        # It now stops one step EARLIER than it used to: the duplicate preflight
        # runs on the single-posting path too, and the folder the first run left
        # is a live folder, so the refusal names the duplicate rather than the
        # slug collision. Same exit code, same untouched tree, better reason —
        # and it fires even when the second run uses a different --research-date,
        # which the slug-collision branch never caught.
        code2, _folder2, _out2, err2 = self._run(rows, "rank 1")
        self.assertEqual(code2, 2)
        self.assertIn("REFUSING to scaffold", err2)
        self.assertIn("duplicate", err2)
        self.assertEqual(sentinel.read_bytes(), original)   # untouched
        self.assertEqual(
            len(list((self.root / "6_drafted").glob("*/meta.yaml"))), 1)

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

    def test_fresh_jd_refusal_is_explicit(self):
        # Store-is-never-verification: a missing session-fresh JD is an explicit
        # refusal (non-zero exit + framing), with no override flag.
        bad_url = (self.tmp / "nope.html").as_uri()
        code, _folder, _out, err = self._run([_row(url=bad_url)], "rank 1")
        self.assertNotEqual(code, 0)
        self.assertIn("REFUSING", err)
        self.assertIn("session-fresh", err.lower())
        self.assertIn("verification", err.lower())

    def test_store_key_copied_verbatim_into_meta_and_validates(self):
        code, folder, _out, err = self._run(
            [_row(url=self.jd_url, store_key="gh-1234567")], "rank 1")
        self.assertEqual(code, 0, err)
        meta = yaml.safe_load((folder / "meta.yaml").read_text())
        self.assertEqual(meta["jobs"][0]["store_key"], "gh-1234567")
        self.assertEqual(validate_meta(meta, app_dir=folder), [])

    def test_no_store_key_field_when_absent(self):
        _code, folder, _out, _err = self._run([_row(url=self.jd_url)], "rank 1")
        meta = yaml.safe_load((folder / "meta.yaml").read_text())
        self.assertNotIn("store_key", meta["jobs"][0])

    def test_stale_last_seen_warns_fresh_is_quiet(self):
        import io as _io
        from contextlib import redirect_stderr as _rse
        prior = os.environ.get("JOBHUNT_DATA_ROOT")
        root = self.tmp / "store"
        os.environ["JOBHUNT_DATA_ROOT"] = str(root)
        try:
            idx = root / "jobs" / "index" / "postings.jsonl"
            idx.parent.mkdir(parents=True, exist_ok=True)
            from datetime import datetime, timedelta, timezone
            stale = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            fresh = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            lines = [{"_schema": 1, "built_at": stale, "note": "x"},
                     {"key": "gh-stale", "last_seen": stale, "seq": 1},
                     {"key": "gh-fresh", "last_seen": fresh, "seq": 2}]
            idx.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
            buf = _io.StringIO()
            with _rse(buf):
                handoff.warn_if_stale("gh-stale")
            self.assertIn("STALE", buf.getvalue())
            buf2 = _io.StringIO()
            with _rse(buf2):
                handoff.warn_if_stale("gh-fresh")
            self.assertEqual(buf2.getvalue(), "")
        finally:
            if prior is None:
                os.environ.pop("JOBHUNT_DATA_ROOT", None)
            else:
                os.environ["JOBHUNT_DATA_ROOT"] = prior

    # -- duplicate preflight: the applications skip-log branch ------------- #
    #
    # Nothing here existed before the log became an append-only JSONL: every other
    # test in this file leaves the log absent, so ``_posting_keys`` was only ever
    # exercised over live folders. That blind spot is exactly what would hide a
    # broken ``_applications_jsonl`` — a path that does not exist reads as "no
    # duplicates", with no error and no output to notice.

    def _seed_log(self, *events) -> Path:
        """Append skip-log events at the path --applications-root implies.

        Deliberately composed from string literals rather than from
        ``config.APPLICATIONS_JSONL_FILENAME``: the point is to pin the file the
        override must name. Build it from the same constant the code under test
        uses and the test agrees with any typo the code makes.
        """
        path = self.root / "0_profile" / "applications-log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for event in events:
                row = {"company": "", "slug": "", "date": "2026-07-16",
                       "status": "applied", "role": "", "url": "",
                       "recorded": "2026-07-16T09:00:00Z", "source": "sync"}
                row.update(event)
                fh.write(json.dumps(row) + "\n")
        return path

    def test_applications_root_override_names_the_jsonl_log(self):
        # The override composes the log path from the config module's layout
        # CONSTANTS; naming the retired .yaml there would fail open silently.
        path = handoff._applications_jsonl(self.root, str(self.root))
        self.assertEqual(path, self.root / "0_profile" / "applications-log.jsonl")

    def test_posting_keys_reads_url_and_pair_keys_from_the_log(self):
        log = self._seed_log(
            {"company": "Nimbus Robotics", "role": "Senior Platform Engineer",
             "url": "https://boards.example.com/nimbus/jobs/2001/"},
            {"company": "Alpha Systems", "role": "Staff Backend Engineer"},
        )
        urls, pairs = handoff._posting_keys(self.root, log)
        # Trailing slash stripped by _posting_keys' own rstrip (not skip_log's).
        self.assertIn("https://boards.example.com/nimbus/jobs/2001", urls)
        # BOTH keys come off every row — the URL-bearing row still yields a pair.
        self.assertIn(("nimbus robotics", "senior platform engineer"), pairs)
        self.assertIn(("alpha systems", "staff backend engineer"), pairs)

    def test_posting_keys_folds_repeated_events_for_one_posting(self):
        log = self._seed_log(
            {"company": "Nimbus Robotics", "role": "Senior Platform Engineer",
             "url": "https://boards.example.com/nimbus/jobs/2001", "status": "drafted"},
            {"company": "Nimbus Robotics", "role": "Senior Platform Engineer",
             "url": "https://boards.example.com/nimbus/jobs/2001", "status": "applied"},
        )
        urls, _pairs = handoff._posting_keys(self.root, log)
        self.assertEqual(urls, {"https://boards.example.com/nimbus/jobs/2001"})

    def test_log_row_suppresses_a_posting_under_applications_root_override(self):
        # End-to-end through --applications-root: the ONLY thing marking this row a
        # duplicate is the seeded log (no live folder exists yet). If the override
        # composed the wrong filename the log would be unreadable, the row would be
        # created, and the count assertions below would flip.
        self._seed_log({"company": "Nimbus Robotics",
                        "role": "Senior Platform Engineer",
                        "url": self.jd_url})
        code, report, _stdout, err = self._run_all([_row(url=self.jd_url)])
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["duplicate"], 1)
        self.assertEqual(report["counts"]["created"], 0)
        self.assertFalse(list((self.root / "6_drafted").glob("*/meta.yaml")))

    def test_log_row_suppresses_a_re_listed_posting_by_company_and_role(self):
        # Same role, NEW url (an ATS re-list). The URL key cannot match, so only the
        # pair key derived from a URL-bearing log row can catch it.
        self._seed_log({"company": "Nimbus Robotics",
                        "role": "Senior Platform Engineer",
                        "url": "https://boards.example.com/nimbus/jobs/2001"})
        code, report, _stdout, err = self._run_all([_row(url=self.jd_url)])
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["duplicate"], 1)
        self.assertEqual(report["counts"]["created"], 0)

    def test_unlogged_posting_is_still_created_with_a_seeded_log(self):
        # The negative control: a populated log must not suppress everything.
        self._seed_log({"company": "Alpha Systems", "role": "Staff Backend Engineer",
                        "url": "https://boards.example.com/alpha/jobs/3001"})
        code, report, _stdout, err = self._run_all([_row(url=self.jd_url)])
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["created"], 1)
        self.assertEqual(report["counts"]["duplicate"], 0)

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


class ScaffoldedCompanyKeyTests(unittest.TestCase):
    """What a freshly scaffolded ``meta.yaml`` says about ``company_key``.

    The field is written ALWAYS and EMPTY always. Three properties, and each is
    here because collapsing it into another one hides a real defect:

    * **present** — before this, the scaffold omitted the field, so a new
      application was indistinguishable from one whose key had been considered
      and rejected, and coverage decayed with nothing saying so;
    * **null, not blank** — ``null`` is UNASSIGNED to ``validate_meta``, to the
      reconciler and to ``--company-keys``; ``""`` / ``false`` / ``0`` are
      MALFORMED to all three. Writing the wrong one turns every new application
      into a finding;
    * **never resolved** — the index is the owner's and lives in the private
      overlay, so the scaffold's output must not depend on whether an overlay
      happens to be mounted.

    The three fixtures are BORROWED from ``HandoffTests`` rather than inherited:
    subclassing it would re-run its whole suite under a second name for the sake
    of a temp dir and a ``file://`` JD.
    """

    setUp = HandoffTests.setUp
    _write_json = HandoffTests._write_json
    _run = HandoffTests._run

    def _meta_text(self) -> tuple[str, dict, str]:
        code, folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        text = (folder / "meta.yaml").read_text(encoding="utf-8")
        return text, yaml.safe_load(text), err

    def test_the_field_is_present_and_empty(self):
        _text, meta, _err = self._meta_text()
        self.assertIn("company_key", meta,
                      "a scaffolded application must SAY it is unkeyed; an "
                      "absent field is indistinguishable from a considered one")
        self.assertIsNone(meta["company_key"])

    def test_the_empty_key_is_null_and_not_a_blank_string(self):
        """``""``/``false``/``0`` are MALFORMED everywhere; ``null`` is unassigned.

        Pinned on the LINE as well as on the parsed value: the two spellings of
        "no key" parse to different Python objects, and the wrong one makes every
        fresh handoff a ``validate_meta`` error, a reconciler finding and a
        ``--company-keys --strict`` failure at once.
        """
        text, meta, _err = self._meta_text()
        self.assertIsNone(meta["company_key"])
        self.assertIn("\ncompany_key: null\n", text)

    def test_the_key_line_sits_directly_under_company(self):
        """The same position the 243 migrated files use, so the two files read alike."""
        text, _meta, _err = self._meta_text()
        lines = [line for line in text.splitlines() if line.strip()]
        company_at = next(i for i, line in enumerate(lines)
                          if line.startswith("company:"))
        self.assertTrue(lines[company_at + 1].startswith("company_key:"),
                        f"company_key is not the line after company:\n{text}")

    def test_the_scaffold_still_validates(self):
        code, folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        meta = yaml.safe_load((folder / "meta.yaml").read_text(encoding="utf-8"))
        self.assertEqual(validate_meta(meta, app_dir=folder), [])

    def test_handoff_says_the_key_is_empty(self):
        """The gap is announced when it is CREATED, not only when a report is run."""
        _text, _meta, err = self._meta_text()
        self.assertIn("empty company_key", err)
        self.assertIn("status.py --company-keys", err)

    def test_handoff_never_reads_the_company_index(self):
        """The scaffold resolves nothing, with or without an overlay.

        Opportunistic resolution was considered and rejected: it would make the
        bytes of a new ``meta.yaml`` depend on whether the private overlay is
        mounted, and it would put an index reader in the module that holds four
        of the additive guard's roots. Reversing that is a decision, so it has to
        delete this test rather than slip in.
        """
        source = (_SCRIPTS_DIR / "handoff.py").read_text(encoding="utf-8")
        self.assertNotIn("company_index", source)

    def test_the_tracker_counts_it_unkeyed_and_not_malformed(self):
        """The cross-skill half: what the coverage report says about this file.

        ``--company-keys`` is the surface that reports the gap, and it must call
        a scaffolded application UNKEYED. If it called it MALFORMED instead,
        ``--strict`` would fail on every fresh handoff and the report would be
        useless the moment it mattered.
        """
        code, folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)

        config_yaml = self.tmp / "keys-config.yaml"
        config_yaml.write_text(
            f"paths:\n  applications_root: {json.dumps(str(self.root))}\n",
            encoding="utf-8")
        index = self.tmp / "_index.yaml"
        index.write_text("acme-labs:\n  display: Acme Labs\n  kind: employer\n",
                         encoding="utf-8")
        env = dict(os.environ, JOBHUNT_CONFIG=str(config_yaml),
                   JOBHUNT_COMPANY_INDEX=str(index))
        proc = subprocess.run(
            [sys.executable, str(_STATUS_PY), "--company-keys", "--strict",
             "--statuses", "drafted", "--json"],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["unkeyed"], [folder.name])
        self.assertEqual(report["malformed"], [])
        self.assertEqual(report["unresolved"], [])


class CreationTimeSkipLogTests(unittest.TestCase):
    """handoff records every posting it scaffolds, at the moment it scaffolds it.

    The window this closes: the tracker's writers cover every status TRANSITION,
    and nothing covered CREATION. So "scaffold a posting -> decide against it the
    same day -> delete the folder -> run ``--sync-log``" left the log with no
    trace of the posting at all, and the next search re-surfaced it as fresh. The
    reproduction is ``test_a_deleted_folder_no_longer_un_skips_its_posting``; the
    rest pin the properties that make the append safe to add on this path.

    Fixtures are borrowed from ``HandoffTests`` (a temp applications root, a
    ``file://`` JD) rather than inherited, so its whole suite does not re-run
    under a second name.
    """

    setUp = HandoffTests.setUp
    _write_json = HandoffTests._write_json
    _run = HandoffTests._run
    _run_all = HandoffTests._run_all
    _run_raw = HandoffTests._run_raw
    _pin_policy = HandoffTests._pin_policy

    # -- helpers ---------------------------------------------------------- #
    def _log_path(self) -> Path:
        return self.root / "0_profile" / "applications-log.jsonl"

    def _events(self) -> list[dict]:
        return skip_log.read_events(self._log_path())

    def _urls(self) -> set[str]:
        return {r["url"] for r in skip_log.read_postings(self._log_path())}

    def _sync_log(self):
        """Subprocess the tracker's ``--sync-log`` against this temp tree."""
        config_yaml = self.tmp / "sync-config.yaml"
        config_yaml.write_text(
            f"paths:\n  applications_root: {json.dumps(str(self.root))}\n",
            encoding="utf-8")
        env = dict(os.environ, JOBHUNT_CONFIG=str(config_yaml))
        return subprocess.run([sys.executable, str(_STATUS_PY), "--sync-log"],
                              capture_output=True, text=True, env=env)

    # -- the gap ---------------------------------------------------------- #
    def test_a_deleted_folder_no_longer_un_skips_its_posting(self):
        """Scaffold -> delete the folder -> --sync-log -> still skipped."""
        code, folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        self.assertIn(self.jd_url, self._urls())

        # The owner changes their mind and removes the folder before any sync.
        shutil.rmtree(folder)
        self.assertFalse(list((self.root / "6_drafted").glob("*/meta.yaml")))

        proc = self._sync_log()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # The sync scans folders and finds nothing; the row is left alone,
        # because the only write this format has is an append.
        self.assertIn(self.jd_url, self._urls())

        # The real consequence: job-search still treats the posting as handled.
        # Nothing but the log can say so now — the folder is gone.
        code, report, _stdout, err = self._run_all([_row(url=self.jd_url)])
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["duplicate"], 1)
        self.assertEqual(report["counts"]["created"], 0)

    # -- shape parity with the tracker's writer --------------------------- #
    def test_sync_log_finds_nothing_to_add_after_a_handoff(self):
        """The anti-drift assertion, made against the other writer itself.

        Both writers now flatten through ``skip_log.posting_rows``. If handoff's
        row disagreed with the tracker's in ANY of the six stored fields — a
        differently derived date, a missing slug, a per-job status read from the
        wrong place — the very next ``--sync-log`` over the same untouched folder
        would see a difference and append a second line. "Zero appended" is the
        only cheap statement of "the two writers agree".
        """
        code, _folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        before = self._events()
        self.assertEqual(len(before), 1)

        proc = self._sync_log()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No posting changes", proc.stdout)
        self.assertEqual(len(self._events()), 1)

        stored = before[0]
        self.assertEqual(stored["source"], "handoff")
        self.assertEqual(stored["company"], "Nimbus Robotics")
        self.assertEqual(stored["role"], "Senior Platform Engineer")
        self.assertEqual(stored["status"], "drafted")
        self.assertRegex(stored["slug"],
                         r"^nimbus-robotics-senior-platform-engineer-\d{8}$")
        self.assertRegex(stored["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(stored["slug"], f"nimbus-robotics-senior-platform-engineer-"
                                         f"{stored['date'].replace('-', '')}")

    def test_a_grouped_folder_records_every_posting_not_just_the_lead(self):
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [_row(url=self.jd_url),
                _row(title="Staff Platform Engineer", url=url2)]
        code, _out, err = self._run_raw(rows, "--select", "Nimbus Robotics")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self._events()), 2)
        self.assertEqual(self._urls(), {self.jd_url, url2})
        # One folder, two rows — the slug is shared, the roles are not.
        rows = skip_log.read_postings(self._log_path())
        self.assertEqual(len({r["slug"] for r in rows}), 1)
        self.assertEqual({r["role"] for r in rows},
                         {"Senior Platform Engineer", "Staff Platform Engineer"})

    # -- idempotency ------------------------------------------------------ #
    def test_a_second_run_on_the_same_posting_adds_no_second_line(self):
        code, _folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        # The second run is stopped by the duplicate preflight — the first run's
        # folder is a live folder carrying this URL — before any mkdir and so
        # before the append. (It was the refuse-to-overwrite branch that caught
        # this; the preflight now catches it first, and unlike the slug check it
        # still catches it under a different --research-date.)
        code2, _folder2, _out2, err2 = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code2, 2, err2)
        self.assertIn("REFUSING to scaffold", err2)
        self.assertEqual(len(self._events()), 1)

    def test_a_bulk_rerun_is_stopped_by_the_row_the_first_run_wrote(self):
        # The log the first run wrote is the ONLY thing that can stop the second
        # here, once the folder is gone.
        code, report, _out, err = self._run_all([_row(url=self.jd_url)])
        self.assertEqual(code, 0, err)
        self.assertEqual(report["counts"]["created"], 1)
        for folder in (self.root / "6_drafted").iterdir():
            shutil.rmtree(folder)
        code, report, _out, err = self._run_all([_row(url=self.jd_url)])
        self.assertEqual(report["counts"]["duplicate"], 1)
        self.assertEqual(len(self._events()), 1)

    # -- nothing is recorded that was not built --------------------------- #
    def test_a_group_dropped_entirely_by_the_location_gate_records_nothing(self):
        # Every posting fails the policy -> exit 3 BEFORE any mkdir. No folder,
        # so no row: the append must never claim a scaffold that does not exist.
        self._pin_policy(metro=("springfield",))
        url2 = (self.tmp / "jd2.html").as_uri()
        (self.tmp / "jd2.html").write_text(JD_PAGE, encoding="utf-8")
        rows = [_row(url=self.jd_url, location="London, United Kingdom", remote=""),
                _row(title="Staff Platform Engineer", url=url2,
                     location="Berlin, Germany", remote="")]
        code, _out, err = self._run_raw(rows, "--select", "Nimbus Robotics")
        self.assertNotEqual(code, 0)
        self.assertIn("nothing scaffolded", err)
        self.assertFalse(list((self.root / "6_drafted").glob("*")))
        self.assertFalse(self._log_path().exists())

    def test_a_row_with_no_company_records_nothing(self):
        code, _out, err = self._run_raw([_row(company="", url=self.jd_url)],
                                        "--all")
        self.assertIn("no company", err)
        self.assertFalse(self._log_path().exists())

    # -- the decided policy: a folder on disk is recorded, clean or not ---- #
    def test_a_location_mismatch_folder_is_recorded_with_the_un_skip_command(self):
        """Exit 3 leaves the folder on disk, so its posting IS recorded.

        Decided in ``message-queue/needs-human/decisions/
        handoff-records-non-clean-scaffolds.md``. Recording matches what the rest
        of the pipeline already does with these folders (``_register_row`` and the
        live-folder half of ``_posting_keys`` both ignore the exit code), and the
        alternative would drop the skip for exactly the folders MOST likely to be
        deleted. The cost is that "delete the folder" stops being a complete
        remedy, so the un-skip command is printed with its argument filled in.
        """
        self._pin_policy(metro=("springfield",))
        row = _row(url=self.jd_url, location="Austin, TX (Hybrid)", remote="hybrid")
        code, folder, stdout, err = self._run([row], "rank 1")
        self.assertEqual(code, 3, err)
        self.assertTrue(folder.is_dir())
        self.assertIn(self.jd_url, self._urls())
        self.assertIn("--forget-log", err)
        self.assertIn(self.jd_url, err.split("--forget-log", 1)[1])
        # Stdout keeps its two-line contract.
        self.assertNotIn("forget-log", stdout)
        self.assertNotIn("recorded", stdout)

    def test_a_scaffold_with_no_fresh_jd_is_recorded_with_the_un_skip_command(self):
        # --skip-jd-fetch exits 1 with the folder on disk. Same policy, same
        # remedy line — this is the case the decision file weighs explicitly.
        code, folder, _out, err = self._run(
            [_row(url=self.jd_url)], "rank 1", "--skip-jd-fetch")
        self.assertEqual(code, 1, err)
        self.assertTrue(folder.is_dir())
        self.assertIn(self.jd_url, self._urls())
        self.assertIn("--forget-log", err)

    def test_a_clean_scaffold_does_not_print_the_un_skip_command(self):
        code, _folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        self.assertIn("recorded 1 posting event", err)
        self.assertNotIn("--forget-log", err)

    # -- the path override ------------------------------------------------ #
    def test_the_append_honours_applications_root(self):
        # The write must land in the tree --applications-root names, not in
        # whatever config discovery would resolve. Composed from string literals
        # for the same reason ``_seed_log`` is: build it from the constant the
        # code uses and the test agrees with any typo the code makes.
        code, _folder, _out, err = self._run([_row(url=self.jd_url)], "rank 1")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.root / "0_profile" / "applications-log.jsonl").is_file())
        self.assertIn(str(self.root / "0_profile" / "applications-log.jsonl"), err)


class PostingIdentityTests(unittest.TestCase):
    """One identity rule for a posting: its URL, else its ``(company, title)`` pair.

    ``skip_log.fold_key`` already writes that rule down and says why the ``else``
    branch is load-bearing. handoff used to spell identity a second way — the
    posting's TITLE — in three places at once: the in-run duplicate register, the
    per-JD role label, and the folder slug. Two requisitions at one employer
    routinely share a title, so each of those three spellings collapsed two
    distinct postings into one, and every collapse exited 0.

    Fixtures are borrowed from ``HandoffTests`` (a temp applications root, a
    ``file://`` JD) rather than inherited, so its whole suite does not re-run
    under a second name.
    """

    setUp = HandoffTests.setUp
    _write_json = HandoffTests._write_json
    _run = HandoffTests._run
    _run_all = HandoffTests._run_all
    _run_raw = HandoffTests._run_raw
    _drafted_metas = HandoffTests._drafted_metas
    _seed_log = HandoffTests._seed_log
    _pin_policy = HandoffTests._pin_policy

    def _jd(self, name: str, body: str = "") -> str:
        """A distinct ``file://`` JD page; ``body`` can add a ``Location:`` line."""
        path = self.tmp / f"{name}.html"
        path.write_text(
            "<!doctype html><html><body><h1>Role</h1>"
            f"{body}<p>Nimbus Robotics builds warehouse robots.</p>"
            "</body></html>",
            encoding="utf-8",
        )
        return path.as_uri()

    # -- finding 1: the per-JD role label --------------------------------- #
    def test_two_same_title_postings_keep_one_cover_letter_each(self):
        # AGENTS.md: "One cover letter per JD — no shared/boilerplate letter."
        # The per-JD artifacts (cover letter, bundled .txt) are keyed on
        # jobs[].role, so two identical role labels collapse two JDs onto one
        # letter. Pre-fix this printed "meta.yaml: valid" and exited 0; the
        # collision only surfaced at render time.
        self._pin_policy(metro=("seattle", "springfield"))
        rows = [
            _row(title="Software Engineer", url=self._jd("req1"),
                 location="Seattle, WA"),
            _row(title="Software Engineer", url=self._jd("req2"),
                 location="Springfield, IL"),
        ]
        code, _out, err = self._run_raw(rows, "--select", "Nimbus Robotics")
        self.assertEqual(code, 0, err)
        metas = self._drafted_metas()
        self.assertEqual(len(metas), 1, "the multi-role default still makes ONE folder")
        roles = [job["role"] for job in metas[0]["jobs"]]
        self.assertEqual(len(roles), 2)
        # The cover-letter / bundle stem is slugify_label(role): two JDs, two stems.
        self.assertEqual(len({slugify_label(r) for r in roles}), 2, roles)
        # The lead posting keeps its plain title; the discriminator is the second
        # posting's own location, not a bare "-2".
        self.assertIn("Software Engineer", roles)
        self.assertTrue(any("Springfield" in r for r in roles), roles)
        # Each posting still keeps its own verbatim JD, one-to-one with its role.
        folder = next((self.root / "6_drafted").glob("*"))
        jd_files = [job["jd_file"] for job in metas[0]["jobs"]]
        self.assertEqual(len(set(jd_files)), 2)
        for name in jd_files:
            self.assertTrue((folder / "source" / name).is_file(), name)
        self.assertEqual(validate_meta(metas[0], app_dir=folder), [])

    def test_validate_meta_rejects_a_duplicate_role(self):
        # The mirror of the duplicate-jd_file assertion that already exists: a
        # duplicate role is the same defect one artifact over.
        job = {
            "role": "Software Engineer",
            "jd_file": "JD-software-engineer.md",
            "status": "drafted",
            "progress": {"phase": "application_prep", "state": "action_required"},
        }
        meta = {
            "job_metadata_schema_version": 6,
            "company": "Nimbus Robotics",
            "jobs": [dict(job), dict(job, jd_file="JD-software-engineer-2.md")],
        }
        errors = validate_meta(meta)
        self.assertTrue(
            any("role duplicates" in error for error in errors), errors)

    # -- finding 2: --split must not discard a distinct requisition -------- #
    def test_split_keeps_a_same_title_sibling_with_its_own_url(self):
        # _register_row used to add the (company, title) pair after each group,
        # so the next group's DIFFERENT requisition matched it and was dropped as
        # a "duplicate" of its own sibling — nothing scaffolded, nothing logged,
        # exit 0, and a stderr line claiming it "already exists" in a log and a
        # tree that had never seen it.
        self._pin_policy(metro=("seattle", "springfield"))
        rows = [
            _row(title="Software Engineer", url=self._jd("req1"),
                 location="Seattle, WA"),
            _row(title="Software Engineer", url=self._jd("req2"),
                 location="Springfield, IL"),
        ]
        code, report, _stdout, err = self._run_all(rows, "--split")
        self.assertEqual(report["counts"]["duplicate"], 0, err)
        self.assertEqual(report["counts"]["created"], 2, err)
        self.assertEqual(code, 0, err)
        metas = self._drafted_metas()
        self.assertEqual(len(metas), 2)
        # Both requisitions are on disk, in two folders with distinct slugs.
        self.assertEqual(len({meta["jobs"][0]["url"] for meta in metas}), 2)
        self.assertEqual(
            len({p.name for p in (self.root / "6_drafted").glob("*")}), 2)
        # And both are recorded in the append-only log.
        rows_logged = skip_log.read_postings(
            self.root / "0_profile" / "applications-log.jsonl")
        self.assertEqual(len(rows_logged), 2)

    def test_a_urlless_same_pair_row_is_still_caught_in_run(self):
        # The else branch of the identity rule: with no URL to tell them apart,
        # two same-company/same-title rows ARE one posting as far as this tool
        # can tell, and the second must still be skipped.
        rows = [_row(title="Software Engineer", url=""),
                _row(title="Software Engineer", url="")]
        code, report, _stdout, err = self._run_all(rows, "--split")
        self.assertEqual(report["counts"]["duplicate"], 1, err)
        self.assertNotEqual(code, 0, err)

    # -- finding 3: the location gate over a multi-role folder ------------- #
    def test_a_blank_location_sibling_is_judged_by_its_own_jd(self):
        # A row with no location is "review", so the multi-role pre-filter keeps
        # it; the folder rollup was then any-matches, so the sibling's Seattle
        # location made the whole folder "location OK" and the London posting
        # rode in with its JD saying so on disk, unread.
        self._pin_policy(metro=("seattle",))
        rows = [
            _row(title="Backend Engineer", location="Seattle, WA",
                 url=self._jd("us", "<p>Location: Seattle, WA</p>")),
            _row(title="Infra Engineer", location="",
                 url=self._jd("uk", "<p>Location: London, United Kingdom</p>")),
        ]
        code, _out, err = self._run_raw(rows, "--select", "Nimbus Robotics")
        # Non-zero: a multi-posting selection runs the bulk path, which collapses
        # every non-clean outcome to 1 (the single-posting path exits 3).
        self.assertNotEqual(code, 0, err)
        self.assertIn("MISMATCH", err)
        self.assertIn("Infra Engineer", err)          # the offending posting, named
        self.assertIn("London", err)
        self.assertNotIn("location OK", err)

    def test_allow_location_mismatch_still_reports_a_grouped_mismatch(self):
        # The flag's documented contract is "warn and proceed". Over a grouped
        # folder the any-matches rollup said "match", so report_location took the
        # match branch and the mismatch was never mentioned at all.
        self._pin_policy(metro=("seattle",))
        rows = [
            _row(title="Backend Engineer", location="Seattle, WA",
                 url=self._jd("us")),
            _row(title="Infra Engineer", location="London, United Kingdom",
                 url=self._jd("uk")),
        ]
        code, _out, err = self._run_raw(
            rows, "--select", "Nimbus Robotics", "--allow-location-mismatch")
        self.assertEqual(code, 0, err)
        self.assertIn("MISMATCH", err)
        self.assertIn("London", err)
        self.assertIn("--allow-location-mismatch set", err)

    # -- finding 4: the duplicate preflight on the single-posting path ----- #
    def test_a_single_select_runs_the_duplicate_preflight(self):
        # SKILL.md's first handoff example is --select "rank N", and the preflight
        # lived only in _run_groups: an already-applied posting was scaffolded a
        # SECOND time, with no warning, exit 0.
        url = self._jd("req1")
        self._seed_log({"company": "Nimbus Robotics",
                        "role": "Senior Platform Engineer",
                        "url": url, "status": "applied"})
        code, _out, err = self._run_raw([_row(url=url)], "--select", "rank 1")
        self.assertNotEqual(code, 0, err)
        self.assertFalse(list((self.root / "6_drafted").glob("*/meta.yaml")))
        self.assertIn("duplicate", err)
        # "Delete the folder" is not the undo here — nothing was created. The
        # remedy for a posting you DO want is the tombstone, argument filled in.
        self.assertIn("--forget-log", err)
        self.assertIn(url, err)

    def test_a_single_select_of_a_fresh_role_at_a_known_employer_still_works(self):
        # The negative control the preflight must not break: the pair key is
        # (company, role), not company alone.
        self._seed_log({"company": "Nimbus Robotics",
                        "role": "Staff Data Engineer",
                        "url": "https://boards.example.com/nimbus/jobs/9001"})
        code, _out, err = self._run_raw(
            [_row(url=self._jd("req1"))], "--select", "rank 1")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(list((self.root / "6_drafted").glob("*/meta.yaml"))), 1)

    # -- finding 5: --research-date is a path component -------------------- #
    def test_research_date_must_be_an_iso_date(self):
        # `2026/07/31` is an ordinary typo for the documented YYYY-MM-DD. It was
        # joined into the slug unslugified, so mkdir(parents=True) buried the
        # application two levels deeper than every tool globs, and the permanent
        # skip-log row recorded slug "31" with an empty date. Exit was 0.
        rows = [_row(url=self._jd("req1"))]
        with self.assertRaises(SystemExit) as ctx:
            self._run_raw(rows, "--select", "rank 1",
                          "--research-date", "2026/07/31")
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertFalse(list(self.root.rglob("meta.yaml")))
        self.assertFalse(list(self.root.rglob("applications-log.jsonl")))

    def test_an_application_folder_is_always_two_levels_under_the_root(self):
        # Belt and braces for every other path component that reaches the slug.
        with self.assertRaises(ValueError):
            handoff._require_folder_under_root(
                self.root / "6_drafted" / "a" / "b", self.root, "6_drafted")

    # -- finding 6: what the bulk report says about a refusal -------------- #
    def test_a_refusal_is_reported_as_refused_not_as_an_incomplete_scaffold(self):
        # Two different titles that slugify identically collide on the folder
        # slug. _run_group returns 2 having created NOTHING, but 2 fell to the
        # default "incomplete" bucket and the row carried "folder": the
        # PRE-EXISTING folder, which belongs to a different posting. An agent
        # working the report to finish the incomplete scaffolds is aimed at it.
        first = _row(title="Software Engineer, Backend", url=self._jd("req1"))
        code1, _o, err1 = self._run_raw(
            [first], "--select", "rank 1", "--research-date", "2026-07-31")
        self.assertEqual(code1, 0, err1)
        existing = next((self.root / "6_drafted").glob("*"))

        second = _row(title="Software Engineer (Backend)", url=self._jd("req2"))
        code, report, _stdout, err = self._run_all(
            [second], "--research-date", "2026-07-31")
        self.assertNotEqual(code, 0, err)
        self.assertEqual(report["counts"]["refused"], 1, report["counts"])
        self.assertEqual(report["counts"]["incomplete"], 0, report["counts"])
        row = report["rows"][0]
        self.assertEqual(row["status"], "refused")
        self.assertNotIn("folder", row)   # nothing was created; no path to offer
        self.assertEqual(row["conflicting_folder"], str(existing.resolve()))


if __name__ == "__main__":
    unittest.main()
