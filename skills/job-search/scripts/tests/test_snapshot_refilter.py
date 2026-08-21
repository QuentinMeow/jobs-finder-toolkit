"""Tests for the fetch-snapshot cache and the --refilter re-run path.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests

NO network: every test operates on synthetic postings + the shipped example profile;
--refilter never fetches, and the fetch path is exercised only through
``snapshot.write_snapshot`` (a pure serializer).
"""
from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
import types
import unittest
from collections import Counter
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

        with TemporaryDirectory() as tmp:
            # The direct call has to reproduce every input main() feeds the renderer
            # — including the pre-dedupe unique count and the review artifact's
            # stable pointer path — or this test compares two different questions.
            pipeline_input = copy.deepcopy(postings)
            kept, counts = search_jobs.filter_score_rank(
                pipeline_input, profile, ctx, max_age=max_age, top_k=top_k,
                max_per_company=max_per_company, sponsor_index=None,
                company_levels=company_levels, registry=registry, now=fetched_at)
            meta = search_jobs.build_meta(
                profile, args_ns, stage=1, n_companies=5,
                aggregators=["jobicy", "themuse"], n_raw=len(postings),
                counts=counts, max_age=max_age, max_per_company=max_per_company,
                errors=[], now=fetched_at,
                n_raw_unique=len(search_jobs.dedupe(pipeline_input)))
            md_direct = search_jobs.render_markdown(
                kept, profile, meta,
                review_path=Path(tmp) / "example-filter-review.json",
                review_postings=counts.get("review_postings", []))
            self.assertEqual(len(kept), 3)   # sanity: 3 survive, 2 filtered

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


class DiscoveriesRunIdentityTests(unittest.TestCase):
    """Two runs of one profile on one day must leave two reports, not one.

    The default discoveries name is fixed per (day, profile), and the refilter path
    dates the report by the SNAPSHOT's fetch time — so refiltering yesterday's
    snapshot today used to rewrite yesterday's report in the owner's tree.
    """

    def test_a_second_run_does_not_overwrite_the_first_report(self):
        fetched_at = datetime.now(timezone.utc) - timedelta(days=1)
        postings = _synthetic_postings(fetched_at)
        original_dir = search_jobs.discoveries_dir
        with TemporaryDirectory() as tmp:
            disc = Path(tmp) / "1_discoveries"
            disc.mkdir(parents=True, exist_ok=True)
            search_jobs.discoveries_dir = lambda: disc
            try:
                snap_path, _ = snapshot.write_snapshot(
                    Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
                    source_selection={"n_companies": 0, "aggregators": [],
                                      "max_age_days_at_fetch": None},
                    postings=postings, errors=[])
                base = ["--profile", "example", "--cache-dir", tmp,
                        "--refilter", str(snap_path), "--allow-stale",
                        "--sponsor-index", str(Path(tmp) / "none.json")]
                self.assertEqual(_run_main([*base, "--top-k", "3"])[0], 0)
                first = sorted(p.name for p in disc.iterdir())
                self.assertEqual(_run_main([*base, "--top-k", "1"])[0], 0)
                second = sorted(p.name for p in disc.iterdir())
            finally:
                search_jobs.discoveries_dir = original_dir

            pointer = f"{fetched_at.strftime('%Y%m%d')}-example.md"
            self.assertIn(pointer, first)          # the path docs/habits name
            self.assertEqual(len(first), 2)        # + this run's own copy
            # Run 2 adds its own file and never removes run 1's.
            self.assertEqual(len(second), 3)
            self.assertTrue(set(first) <= set(second))
            run_files = [n for n in second if n != pointer]
            bodies = {(disc / n).read_text() for n in run_files}
            self.assertEqual(len(bodies), 2)       # two different answers, both kept
            # Count the SHORTLIST table only. The report also renders a
            # `## Manual review` preview whose rows carry the same link marker,
            # so a whole-body count cannot say which table a row came from.
            def shortlist_rows(body):
                return body.split("## Manual review")[0].count("| [link](")

            rows = sorted(shortlist_rows(body) for body in bodies)
            self.assertEqual(rows, [1, 3])         # --top-k 1 and --top-k 3 survive
            # The pointer holds the newest run (--top-k 1).
            self.assertEqual(shortlist_rows((disc / pointer).read_text()), 1)

    def test_an_explicit_out_path_is_still_written_verbatim(self):
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        with TemporaryDirectory() as tmp:
            snap_path, _ = snapshot.write_snapshot(
                Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
                source_selection={"n_companies": 0, "aggregators": [],
                                  "max_age_days_at_fetch": None},
                postings=_synthetic_postings(fetched_at), errors=[])
            out_md = Path(tmp) / "exact.md"
            code, _out, _err = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path), "--out", str(out_md),
                "--sponsor-index", str(Path(tmp) / "none.json")])
            self.assertEqual(code, 0)
            self.assertTrue(out_md.is_file())
            self.assertEqual([p.name for p in Path(tmp).glob("*.md")], ["exact.md"])

    def test_the_review_artifact_is_written_even_with_no_review_rows(self):
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        with TemporaryDirectory() as tmp:
            snap_path, _ = snapshot.write_snapshot(
                Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
                source_selection={"n_companies": 0, "aggregators": [],
                                  "max_age_days_at_fetch": None},
                postings=_synthetic_postings(fetched_at), errors=[])
            code, _out, _err = _run_main([
                "--profile", "example", "--cache-dir", tmp,
                "--refilter", str(snap_path), "--out", str(Path(tmp) / "x.md"),
                "--sponsor-index", str(Path(tmp) / "none.json")])
            self.assertEqual(code, 0)
            pointer = Path(tmp) / "example-filter-review.json"
            self.assertTrue(pointer.is_file())
            payload = json.loads(pointer.read_text())
            self.assertEqual(payload["count"], len(payload["postings"]))
            self.assertEqual(payload["snapshot"], str(snap_path))
            # Both lanes: the bounded review list and the cap's overflow, each with
            # one run file plus its stable pointer.
            overflow = Path(tmp) / "example-filter-review-overflow.json"
            self.assertTrue(overflow.is_file())
            self.assertEqual(json.loads(overflow.read_text())["kind"],
                             "filter-review-overflow")
            runs = [p.name for p in Path(tmp).glob("example-filter-review-2*.json")]
            over_runs = [p.name for p in
                         Path(tmp).glob("example-filter-review-overflow-2*.json")]
            self.assertEqual(len(runs), 1)
            self.assertEqual(len(over_runs), 1)


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

    def test_an_abbreviated_fetch_flag_is_rejected_too(self):
        # argparse accepts any unambiguous PREFIX, so a guard that matches raw
        # sys.argv text disagrees with the namespace it is protecting. The
        # refilter branch never consults args.company_tags / args.no_companies,
        # so the run silently returns the WHOLE snapshot as though the selector
        # had been applied.
        for flag, canonical in ((["--company-tag", "ai-lab"], "--company-tags"),
                                (["--no-compan"], "--no-companies"),
                                (["--company-batch", "b1"], "--company-batches")):
            with self.subTest(flag=flag[0]), TemporaryDirectory() as tmp:
                snap_path = self._snapshot(tmp)
                code, _out, _err = _run_main([
                    "--profile", "example", "--cache-dir", tmp,
                    "--refilter", str(snap_path), *flag])
                self.assertIsInstance(code, str)
                self.assertIn("Fresh fetch required", code)
                self.assertIn(canonical, code)

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


class SearchJsonAuditabilityTests(unittest.TestCase):
    """An emitted row must be auditable from the row, and joinable to its run.

    ``to_dict`` clips ``description`` to 400 characters, and a JD's deciding clause
    — excluded states, clearance, "no sponsorship", a 10+ YOE line — routinely sits
    past that cut. A row that shows the clipped text without labelling it, and
    without naming where the whole text lives, invites a novice to trust a
    classification they cannot check.
    """

    LATE = "This role is not open to residents of Washington state."

    def _long_jd(self):
        jd = ("Northwind Robotics is hiring. Python, Kubernetes, AWS, distributed "
              "systems, microservices, rest api, postgres. " + "filler. " * 45
              + self.LATE)
        assert jd.index(self.LATE) > 400          # decisive clause past the clip
        return jd

    def _run(self, tmp, snap_path, *extra, default_out=False):
        """One refilter with --json-out; ``default_out`` exercises discoveries/."""
        out_json = Path(tmp) / f"m{len(list(Path(tmp).glob('m*.json')))}.json"
        out_flags = [] if default_out else ["--out", str(Path(tmp) / "m.md")]
        code, out, _err = _run_main([
            "--profile", "example", "--cache-dir", tmp,
            "--refilter", str(snap_path), *out_flags,
            "--json-out", str(out_json), "--allow-stale",
            "--sponsor-index", str(Path(tmp) / "none.json"), *extra])
        self.assertEqual(code, 0)
        return json.loads(out_json.read_text()), out

    def _snapshot(self, tmp, postings, fetched_at):
        snap_path, _ = snapshot.write_snapshot(
            Path(tmp), profile="example", stage=1, fetched_at=fetched_at,
            source_selection={"n_companies": 0, "aggregators": [],
                              "max_age_days_at_fetch": None},
            postings=postings, errors=[])
        return snap_path

    def test_a_clipped_row_names_and_locates_its_untruncated_jd(self):
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        jd = self._long_jd()
        target = _posting("Northwind Robotics", "Senior Backend Engineer",
                          "San Francisco, CA", "remote",
                          fetched_at - timedelta(days=1), jd)
        raw = [*_synthetic_postings(fetched_at), target]
        with TemporaryDirectory() as tmp:
            snap_path = self._snapshot(tmp, raw, fetched_at)
            rows, _out = self._run(tmp, snap_path)
            row = next(r for r in rows if r["url"] == target.url)

            # The row says the text is a preview, and how much is missing.
            self.assertTrue(row["description_is_preview"])
            self.assertEqual(row["description_full_chars"], len(jd))
            self.assertNotIn(self.LATE, row["description"])

            # …and it resolves: the named snapshot row IS this posting, in full.
            self.assertEqual(row["source_snapshot"], str(snap_path))
            self.assertEqual(row["source_snapshot_row"], raw.index(target))
            snap_row = json.loads(snap_path.read_text())["postings"][
                row["source_snapshot_row"]]
            self.assertEqual(snap_row["url"], target.url)
            self.assertEqual(snap_row["description"], jd)
            self.assertIn(self.LATE, snap_row["description"])

    def test_the_emitted_command_prints_the_full_jd(self):
        # The locator is only worth as much as the retrieval a novice can run.
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        jd = self._long_jd()
        target = _posting("Northwind Robotics", "Senior Backend Engineer",
                          "San Francisco, CA", "remote",
                          fetched_at - timedelta(days=1), jd)
        with TemporaryDirectory() as tmp:
            snap_path = self._snapshot(tmp, [target], fetched_at)
            rows, _out = self._run(tmp, snap_path)
            command = rows[0]["full_description_command"]
            proc = subprocess.run(command, shell=True, capture_output=True,
                                  text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), jd)
            self.assertIn(self.LATE, proc.stdout)

    def test_an_untruncated_row_is_not_labelled_a_preview(self):
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        with TemporaryDirectory() as tmp:
            snap_path = self._snapshot(tmp, _synthetic_postings(fetched_at),
                                       fetched_at)
            rows, _out = self._run(tmp, snap_path)
            self.assertTrue(rows)
            for row in rows:                       # every fixture JD is short
                self.assertFalse(row["description_is_preview"])
                self.assertIsNone(row["full_description_command"])
                self.assertEqual(row["description_full_chars"],
                                 len(row["description"]))

    def test_the_locator_separates_rows_that_share_one_url(self):
        # Generic aggregator URLs (RemoteOK) are shared by several postings, so a
        # URL is not a locator; the snapshot row index is.
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        jd = self._long_jd()
        shared = "https://remoteok.com/remote-dev-jobs"
        first = _posting("Northwind Robotics", "Senior Backend Engineer",
                         "San Francisco, CA", "remote",
                         fetched_at - timedelta(days=1), jd)
        second = _posting("Cobalt Systems", "Platform Engineer", "New York, NY",
                          "remote", fetched_at - timedelta(days=1), jd + " Second.")
        first.url = second.url = shared
        with TemporaryDirectory() as tmp:
            snap_path = self._snapshot(tmp, [first, second], fetched_at)
            rows, _out = self._run(tmp, snap_path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(sorted(r["source_snapshot_row"] for r in rows), [0, 1])
            body = json.loads(snap_path.read_text())["postings"]
            for row in rows:
                self.assertEqual(body[row["source_snapshot_row"]]["company"],
                                 row["company"])

    def test_two_runs_over_one_snapshot_are_distinct_and_joinable(self):
        # #244: refiltering with different arguments must leave two comparable
        # results, each machine row naming the run that produced it.
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        original_dir = search_jobs.discoveries_dir
        with TemporaryDirectory() as tmp:
            disc = Path(tmp) / "1_discoveries"
            disc.mkdir(parents=True, exist_ok=True)
            search_jobs.discoveries_dir = lambda: disc
            try:
                snap_path = self._snapshot(tmp, _synthetic_postings(fetched_at),
                                           fetched_at)
                first, _out = self._run(tmp, snap_path, "--top-k", "3",
                                        default_out=True)
                second, _out = self._run(tmp, snap_path, "--top-k", "1",
                                         default_out=True)
            finally:
                search_jobs.discoveries_dir = original_dir

            run_a = {r["run_id"] for r in first}
            run_b = {r["run_id"] for r in second}
            self.assertEqual(len(run_a), 1)
            self.assertEqual(len(run_b), 1)
            self.assertTrue(run_a.isdisjoint(run_b))   # two runs, two identities
            # Both results are joinable back to the one snapshot they replayed…
            self.assertEqual({r["source_snapshot"] for r in [*first, *second]},
                             {str(snap_path)})
            # …and each run id names that run's own surviving report + review file.
            names = [p.name for p in disc.iterdir()]
            for run_id in (*run_a, *run_b):
                self.assertIn(f"{run_id}-example.md", names)
                self.assertTrue(
                    (Path(tmp) / f"example-filter-review-{run_id}.json").is_file())
            self.assertEqual(len(first), 3)            # the differing arguments
            self.assertEqual(len(second), 1)           # produced differing results

    def test_review_rows_locate_their_full_jd_and_name_their_run(self):
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        jd = self._long_jd()
        # jobspy source + an uncertain location keeps the row in the review lane.
        review_me = _posting("Review Systems", "Senior Backend Engineer",
                             "Austin, TX", "remote",
                             fetched_at - timedelta(days=1), jd)
        review_me.source = "jobspy:indeed"
        with TemporaryDirectory() as tmp:
            snap_path = self._snapshot(tmp, [review_me], fetched_at)
            _rows, _out = self._run(tmp, snap_path)
            payload = json.loads(
                (Path(tmp) / "example-filter-review.json").read_text())
            self.assertEqual(payload["count"], 1)
            self.assertIsNotNone(payload["run_id"])    # the pointer copy self-IDs
            self.assertTrue(
                (Path(tmp) /
                 f"example-filter-review-{payload['run_id']}.json").is_file())
            row = payload["postings"][0]
            self.assertTrue(row["description_truncated"])
            self.assertEqual(row["description_full_chars"], len(jd))
            self.assertEqual(row["source_snapshot_row"], 0)
            self.assertEqual(
                json.loads(snap_path.read_text())["postings"][0]["description"], jd)
            # The artifact carries the retrieval command, not just a snapshot name.
            self.assertIn("source_snapshot_row", payload["instruction"])
            self.assertIn(str(snap_path), payload["instruction"])

    def test_fetch_and_replay_agree_on_every_rows_provenance(self):
        """The replay contract: a no-change refilter reproduces the fetch's rows.

        ``run_tasks`` is stubbed (no network) and the post-fetch store build is
        forced off, so this compares exactly what the two code paths emit for the
        same postings — the comparison #284 found broken, where the fetch carried
        store identity and the replay of its own snapshot did not.
        """
        fetched_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        raw = [*_synthetic_postings(fetched_at),
               _posting("Northwind Robotics", "Senior Backend Engineer",
                        "San Francisco, CA", "remote",
                        fetched_at - timedelta(days=1), self._long_jd())]
        fake_map = {"https://x.test/1": "gh-1"}
        orig_tasks = search_jobs.run_tasks
        orig_build = search_jobs.run_post_fetch_store_build
        orig_replay = search_jobs.read_store_status_for_replay
        with TemporaryDirectory() as tmp:
            try:
                search_jobs.run_tasks = (
                    lambda tasks, workers=12: (copy.deepcopy(raw), [], Counter()))
                # Containment: a test never builds or reads a real store.
                search_jobs.run_post_fetch_store_build = lambda: (None, dict(fake_map))
                fetch_rows, _out = self._run_fetch(tmp)
                snap_path = next(Path(tmp).glob("example-stage1-latest.json"))
                search_jobs.run_post_fetch_store_build = lambda: (_ for _ in ()).throw(
                    AssertionError("a refilter must never build the store"))
                search_jobs.read_store_status_for_replay = lambda: (None, dict(fake_map))
                replay_rows, _out = self._run(tmp, snap_path)
            finally:
                search_jobs.run_tasks = orig_tasks
                search_jobs.run_post_fetch_store_build = orig_build
                search_jobs.read_store_status_for_replay = orig_replay

            compared = ("url", "store_key", "source_snapshot_row",
                        "description_is_preview", "description_full_chars")
            self.assertTrue(fetch_rows)
            self.assertEqual([{k: r[k] for k in compared} for r in fetch_rows],
                             [{k: r[k] for k in compared} for r in replay_rows])
            # The run id is the one field that MUST differ: two runs, two answers.
            self.assertNotEqual({r["run_id"] for r in fetch_rows},
                                {r["run_id"] for r in replay_rows})

    def _run_fetch(self, tmp):
        out_json = Path(tmp) / "fetch.json"
        code, out, _err = _run_main([
            # Company tasks are built from the local registry and never run:
            # run_tasks is stubbed, so nothing reaches the network.
            "--profile", "example", "--cache-dir", tmp,
            "--no-aggregators", "--no-jobspy", "--out", str(Path(tmp) / "f.md"),
            "--json-out", str(out_json),
            "--sponsor-index", str(Path(tmp) / "none.json")])
        self.assertEqual(code, 0)
        return json.loads(out_json.read_text()), out

    def test_the_json_payload_is_still_a_bare_list_of_rows(self):
        # handoff.py consumes --json-out as a list; provenance rides on the rows.
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        with TemporaryDirectory() as tmp:
            snap_path = self._snapshot(tmp, _synthetic_postings(fetched_at),
                                       fetched_at)
            rows, _out = self._run(tmp, snap_path)
            self.assertIsInstance(rows, list)
            self.assertTrue(all(isinstance(r, dict) for r in rows))
            import handoff
            self.assertEqual(len(handoff.load_rows(
                next(Path(tmp).glob("m0.json")))), len(rows))


class SnapshotPointerRobustnessTests(unittest.TestCase):
    """One torn pointer must not take out `--refilter latest` for the profile."""

    def _write(self, tmp, stage, minutes_ago):
        fetched_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        return snapshot.write_snapshot(
            Path(tmp), profile="example", stage=stage, fetched_at=fetched_at,
            source_selection={"n_companies": 0, "aggregators": []},
            postings=_synthetic_postings(fetched_at), errors=[])

    def test_a_truncated_pointer_is_skipped_not_fatal(self):
        with TemporaryDirectory() as tmp:
            _snap1, good = self._write(tmp, 1, 10)
            _snap2, torn = self._write(tmp, 2, 5)
            torn.write_text(torn.read_text()[:200])   # crash / full disk mid-copy
            resolved = snapshot.resolve_snapshot_path(Path(tmp), "example", "latest")
            self.assertEqual(resolved, good)

    def test_every_pointer_unreadable_is_a_clear_error(self):
        with TemporaryDirectory() as tmp:
            _snap, torn = self._write(tmp, 1, 5)
            torn.write_text("{")
            with self.assertRaises(FileNotFoundError) as ctx:
                snapshot.resolve_snapshot_path(Path(tmp), "example", "latest")
            self.assertIn("unreadable", str(ctx.exception))

    def test_a_leftover_write_temp_is_never_resolved_as_a_pointer(self):
        # The atomic write stages `<name>.tmp-*`; a crash between staging and
        # os.replace leaves one behind, and it must not join the pointer glob.
        with TemporaryDirectory() as tmp:
            _snap, good = self._write(tmp, 1, 10)
            (Path(tmp) / "example-stage2-latest.json.tmp-abc").write_text("{")
            self.assertEqual(
                snapshot.resolve_snapshot_path(Path(tmp), "example", "latest"), good)


if __name__ == "__main__":
    unittest.main()
