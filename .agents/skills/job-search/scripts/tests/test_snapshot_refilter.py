"""Tests for the fetch-snapshot cache and the --refilter re-run path.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s .agents/skills/job-search/scripts/tests \
        -t .agents/skills/job-search/scripts/tests

NO network: every test operates on synthetic postings + the shipped example profile;
--refilter never fetches, and the fetch path is exercised only through
``snapshot.write_snapshot`` (a pure serializer).
"""
from __future__ import annotations

import copy
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

# Make the skill's own scripts/ (+ its _vendor/) importable, mirroring how
# search_jobs.py bootstraps itself when run directly.
_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import search_jobs  # noqa: E402
import snapshot  # noqa: E402
from common import JobPosting  # noqa: E402
from registry import load_registry  # noqa: E402

EXAMPLE = str(_SCRIPTS.parent / "profiles" / "example.yaml")


def _posting(company, title, location, remote, posted_at, description):
    return JobPosting(
        source="board", company=company, title=title,
        url=f"https://{company.split()[0].lower()}.example/jobs/{abs(hash(title)) % 1000}",
        location=location, remote=remote, posted_at=posted_at, description=description)


def _synthetic_postings(fetched_at):
    """Five pre-filter postings: 3 survive the example profile, 2 are filtered.

    Company names are deliberately fictitious so no real registry blacklist / levels /
    sponsor-index entry perturbs scoring (Jordan Rivers is the repo's only persona).
    """
    return [
        _posting("Northwind Robotics", "Senior Backend Engineer",
                 "San Francisco, CA", "remote", fetched_at - timedelta(days=1),
                 "Python, Kubernetes, AWS, distributed systems, microservices, api."),
        _posting("Cobalt Systems", "Platform Engineer",
                 "New York, NY", "hybrid", fetched_at - timedelta(days=2),
                 "Go, Docker, Terraform, gRPC, backend, rest api, postgres."),
        _posting("Marlin Data", "Distributed Systems Engineer",
                 "Austin, TX", "onsite", fetched_at - timedelta(days=5),
                 "Java, Kafka, distributed systems, aws, observability."),
        _posting("Zephyr Cloud", "Engineering Manager",         # title exclude: manager
                 "Seattle, WA", "onsite", fetched_at - timedelta(days=1),
                 "Lead a backend team; python, kubernetes."),
        _posting("Foreign Ltd", "Software Engineer",            # location: foreign, us_only
                 "London, United Kingdom", "onsite", fetched_at - timedelta(days=1),
                 "Python backend engineer, distributed systems."),
    ]


def _effective_params(profile: dict):
    """max_age / top_k / max_per_company exactly as main() derives them (no CLI flags)."""
    max_age = profile.get("max_age_days")
    top_k = profile.get("top_k", 40)
    max_per_company = (profile.get("diversity", {}) or {}).get("max_per_company", 3)
    return max_age, top_k, max_per_company


def _run_main(argv):
    """Invoke search_jobs.main() with argv; return (code, stdout, stderr).

    ``code`` is 0 on success or the SystemExit payload (str message / int) on exit.
    """
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["search_jobs.py", *argv]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = search_jobs.main()
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


class SnapshotRoundTripTests(unittest.TestCase):
    def test_posting_round_trip_preserves_full_description(self):
        long_desc = "Backend engineer. " + ("x" * 5000)   # > to_dict()'s 400-char clip
        posted = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
        p = _posting("Northwind Robotics", "Senior Backend Engineer",
                     "San Francisco, CA", "remote", posted, long_desc)
        p.salary_range = {"min": 180000, "max": 220000}

        restored = snapshot.posting_from_dict(snapshot.posting_to_dict(p))

        self.assertEqual(restored.description, long_desc)     # untruncated
        self.assertEqual(restored.posted_at, posted)          # aware UTC preserved
        self.assertEqual(restored.company, p.company)
        self.assertEqual(restored.salary_range, p.salary_range)
        self.assertNotEqual(len(long_desc), len(p.to_dict()["description"]))  # to_dict clips

    def test_write_snapshot_creates_file_and_latest_pointer(self):
        fetched_at = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
        postings = _synthetic_postings(fetched_at)
        with TemporaryDirectory() as tmp:
            snap_path, latest = snapshot.write_snapshot(
                Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
                source_selection={"n_companies": 5, "aggregators": ["jobicy"]},
                postings=postings, errors=[])
            self.assertTrue(snap_path.exists())
            self.assertTrue(latest.exists())
            self.assertEqual(latest.name, "example-stage1-latest.json")
            loaded = snapshot.load_snapshot(snap_path)
            self.assertEqual(loaded["n_postings"], 5)
            self.assertEqual(len(loaded["postings"]), 5)
            self.assertEqual(loaded["profile"], "example")
            # `latest` resolves to the same snapshot content.
            resolved = snapshot.resolve_snapshot_path(Path(tmp), "example", "latest")
            self.assertEqual(
                snapshot.load_snapshot(resolved)["fetched_at"], loaded["fetched_at"])


class RefilterEquivalenceTests(unittest.TestCase):
    """Same snapshot + same flags => byte-identical report to the in-process run."""

    def test_refilter_matches_direct_pipeline(self):
        fetched_at = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
        postings = _synthetic_postings(fetched_at)
        profile = search_jobs.load_yaml(EXAMPLE)
        max_age, top_k, max_per_company = _effective_params(profile)
        registry = load_registry()
        # company_levels loaded exactly as main() would, so both paths agree.
        company_levels = {}
        if search_jobs.config is not None:
            try:
                company_levels = search_jobs.load_company_levels(
                    search_jobs.config.company_levels_path())
            except Exception:  # noqa: BLE001
                company_levels = {}

        args_ns = types.SimpleNamespace(
            profile="example", include_considered=False,
            search_log_skip_days=None, include_recent=False)
        ctx = search_jobs.build_filter_context(profile, registry, args_ns)
        kept, counts = search_jobs.filter_score_rank(
            copy.deepcopy(postings), profile, ctx, max_age=max_age, top_k=top_k,
            max_per_company=max_per_company, sponsor_index=None,
            company_levels=company_levels, registry=registry, now=fetched_at)
        meta = search_jobs.build_meta(
            profile, args_ns, stage=1, n_companies=5,
            aggregators=["jobicy", "themuse"], n_raw=len(postings), counts=counts,
            max_age=max_age, max_per_company=max_per_company, errors=[], now=fetched_at)
        md_direct = search_jobs.render_markdown(kept, profile, meta)
        self.assertEqual(len(kept), 3)   # sanity: 3 survive, 2 filtered

        with TemporaryDirectory() as tmp:
            snap_path, _ = snapshot.write_snapshot(
                Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
                source_selection={
                    "n_companies": 5, "aggregators": ["jobicy", "themuse"],
                    "max_age_days_at_fetch": max_age, "no_companies": False,
                    "jobspy_on": False},
                postings=copy.deepcopy(postings), errors=[])
            out_md = Path(tmp) / "refiltered.md"
            code, _stdout, _stderr = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path), "--out", str(out_md),
                "--allow-stale", "--sponsor-index", str(Path(tmp) / "none.json")])
            self.assertEqual(code, 0)
            md_refilter = out_md.read_text()

        self.assertEqual(md_direct, md_refilter)   # byte-identical

    def test_refilter_anchors_age_to_fetch_time_not_now(self):
        # fetched_at fixed far from wall-clock; a wall-clock anchor would show a
        # huge age instead of the true 2.0d for the 2-days-before posting.
        fetched_at = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
        postings = _synthetic_postings(fetched_at)
        with TemporaryDirectory() as tmp:
            snap_path, _ = snapshot.write_snapshot(
                Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
                source_selection={"n_companies": 0, "aggregators": [],
                                  "max_age_days_at_fetch": None},
                postings=postings, errors=[])
            out_md = Path(tmp) / "aged.md"
            code, _stdout, _stderr = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path), "--out", str(out_md), "--allow-stale",
                "--sponsor-index", str(Path(tmp) / "none.json")])
            self.assertEqual(code, 0)
            md = out_md.read_text()
        # Cobalt Systems was posted exactly 2 days before the snapshot fetch.
        self.assertIn("2.0d", md)
        self.assertIn("Cobalt Systems", md)

    def test_uncertain_location_is_preserved_in_review_queue(self):
        fetched_at = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
        posting = _posting(
            "Review Systems", "Senior Backend Engineer", "Austin, TX",
            "remote", fetched_at - timedelta(days=1),
            "Python, Kubernetes, distributed systems.",
        )
        posting.source = "jobspy:indeed"
        profile = search_jobs.load_yaml(EXAMPLE)
        registry = load_registry()
        args_ns = types.SimpleNamespace(
            profile="example", include_considered=True,
            search_log_skip_days=None, include_recent=True)
        ctx = search_jobs.build_filter_context(profile, registry, args_ns)
        kept, counts = search_jobs.filter_score_rank(
            [posting], profile, ctx, max_age=None, top_k=40,
            max_per_company=3, sponsor_index=None, company_levels={},
            registry=registry, now=fetched_at)
        self.assertEqual(kept, [])
        self.assertEqual(counts["n_review"], 1)
        self.assertEqual(counts["review_postings"][0].company, "Review Systems")


class RefilterTTLTests(unittest.TestCase):
    def _write(self, tmp, *, hours_old):
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=hours_old)
        snap_path, _ = snapshot.write_snapshot(
            Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
            source_selection={"n_companies": 0, "aggregators": [],
                              "max_age_days_at_fetch": None},
            postings=_synthetic_postings(fetched_at), errors=[])
        return snap_path

    def test_stale_snapshot_is_refused(self):
        with TemporaryDirectory() as tmp:
            snap_path = self._write(tmp, hours_old=7)          # > 6h TTL
            out_md = Path(tmp) / "o.md"
            code, _out, err = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path), "--out", str(out_md)])
            self.assertIsInstance(code, str)                   # sys.exit(message)
            self.assertIn("older than", code)
            self.assertIn("--allow-stale", code)
            self.assertFalse(out_md.exists())                  # bailed before writing
            self.assertIn("age", err)                          # age printed to stderr

    def test_stale_snapshot_allowed_with_flag(self):
        with TemporaryDirectory() as tmp:
            snap_path = self._write(tmp, hours_old=7)
            out_md = Path(tmp) / "o.md"
            code, _out, _err = _run_main([
                "--profile", "example", "--cache-dir", tmp, "--allow-stale",
                "--refilter", str(snap_path), "--out", str(out_md),
                "--sponsor-index", str(Path(tmp) / "none.json")])
            self.assertEqual(code, 0)
            self.assertTrue(out_md.exists())

    def test_fresh_snapshot_within_ttl_is_accepted(self):
        with TemporaryDirectory() as tmp:
            snap_path = self._write(tmp, hours_old=1)          # < 6h TTL
            out_md = Path(tmp) / "o.md"
            code, _out, err = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path), "--out", str(out_md),
                "--sponsor-index", str(Path(tmp) / "none.json")])
            self.assertEqual(code, 0)
            self.assertIn("age", err)                          # age always printed


class RefilterFetchFlagRejectionTests(unittest.TestCase):
    def _snapshot(self, tmp):
        fetched_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        snap_path, _ = snapshot.write_snapshot(
            Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
            source_selection={"n_companies": 0, "aggregators": [],
                              "max_age_days_at_fetch": None},
            postings=_synthetic_postings(fetched_at), errors=[])
        return snap_path

    def test_fetch_affecting_flag_is_rejected(self):
        for flag in (["--stage", "2"], ["--no-companies"], ["--no-jobspy"],
                     ["--jobspy"], ["--aggregators", "jobicy"],
                     ["--no-aggregators"],
                     ["--company-tags", "ai-lab"],
                     ["--company-batches", "ai-expansion-01"]):
            with self.subTest(flag=flag[0]), TemporaryDirectory() as tmp:
                snap_path = self._snapshot(tmp)
                code, _out, _err = _run_main([
                    "--profile", "example", "--cache-dir", tmp,
                    "--refilter", str(snap_path), *flag])
                self.assertIsInstance(code, str)
                self.assertIn("Fresh fetch required", code)
                self.assertIn(flag[0], code)

    def test_filter_flags_are_allowed(self):
        # Date/top-k/all-matches/visa are FILTER flags: refilter accepts them.
        with TemporaryDirectory() as tmp:
            snap_path = self._snapshot(tmp)
            out_md = Path(tmp) / "o.md"
            code, _out, _err = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path), "--max-age-days", "7", "--top-k", "10",
                "--all-matches",
                "--visa-policy", "exclude_negative", "--out", str(out_md),
                "--sponsor-index", str(Path(tmp) / "none.json")])
            self.assertEqual(code, 0)
            self.assertTrue(out_md.exists())

    def test_require_positive_activates_gate_for_generic_profile(self):
        with TemporaryDirectory() as tmp:
            snap_path = self._snapshot(tmp)
            out_md = Path(tmp) / "o.md"
            out_json = Path(tmp) / "o.json"
            code, _out, _err = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path),
                "--visa-policy", "require_positive",
                "--out", str(out_md), "--json-out", str(out_json),
                "--sponsor-index", str(Path(tmp) / "none.json")])
            self.assertEqual(code, 0)
            # Synthetic rows state no positive sponsorship language. The explicit
            # CLI policy therefore keeps none even though example.needs_sponsorship=false.
            self.assertEqual(json.loads(out_json.read_text()), [])

    def test_profile_mismatch_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fetched_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            snap_path, _ = snapshot.write_snapshot(
                Path(tmp), profile="someone-else", stage=1, fetched_at=fetched_at,
                source_selection={"n_companies": 0, "aggregators": []},
                postings=_synthetic_postings(fetched_at), errors=[])
            code, _out, _err = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path)])
            self.assertIsInstance(code, str)
            self.assertIn("Fresh fetch required", code)
            self.assertIn("someone-else", code)


if __name__ == "__main__":
    unittest.main()
