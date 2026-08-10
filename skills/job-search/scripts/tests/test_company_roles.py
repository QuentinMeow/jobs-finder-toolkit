"""Tests for company_roles.py --jd: the ATS-API JD-recovery path and its digest.

NO network: a RECORDED Ashby board payload is fed to ``sources.http_get_full``, so
``fetch_company`` builds real ``JobPosting`` objects through the real parser — the
same path a live board takes, minus the socket. Fictional postings only
(Jordan-Rivers universe).

Run with:
    .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# Make the sibling scripts importable (skills/job-search/scripts/).
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import company_roles  # noqa: E402
import fetch_jd  # noqa: E402
import sources  # noqa: E402
from common import HttpResult  # noqa: E402

# Test-safety: fetching a board captures it to the raw store, and the machine
# config.yaml points data_root at the REAL private store — isolate every capture in
# this module to a throwaway data root (env beats config).
_PRIOR_DATA_ROOT: str | None = None
_TMP_DATA_ROOT: str | None = None


def setUpModule():
    global _PRIOR_DATA_ROOT, _TMP_DATA_ROOT
    _PRIOR_DATA_ROOT = os.environ.get("JOBHUNT_DATA_ROOT")
    _TMP_DATA_ROOT = tempfile.mkdtemp(prefix="companyroles-capture-")
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


# --------------------------------------------------------------------------- #
# Recorded Ashby payload. The long description carries ONE line per field the
# pipeline parses out of a JD body, buried in enough filler prose to exceed the
# digest threshold — exactly the ~5-8 KB JS-rendered shape this path recovers.
# --------------------------------------------------------------------------- #

_FILLER = (
    "You will design, build and operate large-scale services, partner with product "
    "engineers across the company, and own your systems end to end in production. "
)

LONG_JD = (
    "Senior Platform Engineer\n"
    "\n"
    "Location: Seattle, WA (Hybrid)\n"
    "This is a hybrid role: three days a week in the Seattle office.\n"
    "\n"
    "## About the role\n"
    + _FILLER * 18 + "\n"
    "\n"
    "## Requirements\n"
    "- 9+ years of professional software engineering experience is required.\n"
    "- Strong Python and Go.\n"
    + "".join(f"- Responsibility {i}: {_FILLER}\n" for i in range(12)) +
    "\n"
    "## Compensation\n"
    "The base salary range for this role is $195,000 - $265,000 per year.\n"
    "\n"
    "## Work authorization\n"
    "We are unable to sponsor or take over sponsorship of an employment visa at "
    "this time.\n"
)

SHORT_JD = (
    "Data Analyst\n"
    "\n"
    "Location: Remote (US)\n"
    "We analyze product metrics for the growth team.\n"
    "3 years of SQL experience.\n"
)

ASHBY_BOARD = {
    "apiVersion": "1",
    "jobs": [
        {
            "id": "ax-long",
            "title": "Senior Platform Engineer",
            "location": "Seattle, WA",
            "jobUrl": "https://jobs.ashbyhq.com/examplecorp/ax-long",
            "descriptionPlain": LONG_JD,
            "publishedAt": "2026-07-11T00:00:00Z",
            "isListed": True,
            "workplaceType": "Hybrid",
            "secondaryLocations": [],
        },
        {
            "id": "ax-short",
            "title": "Data Analyst",
            "location": "Remote (US)",
            "jobUrl": "https://jobs.ashbyhq.com/examplecorp/ax-short",
            "descriptionPlain": SHORT_JD,
            "publishedAt": "2026-07-12T00:00:00Z",
            "isListed": True,
            "workplaceType": "Remote",
            "secondaryLocations": [],
        },
        {
            "id": "ax-eng-2",
            "title": "Staff Platform Engineer",
            "location": "Seattle, WA",
            "jobUrl": "https://jobs.ashbyhq.com/examplecorp/ax-eng-2",
            "descriptionPlain": LONG_JD,
            "publishedAt": "2026-07-13T00:00:00Z",
            "isListed": True,
            "workplaceType": "Hybrid",
            "secondaryLocations": [],
        },
    ],
}

ENTRY = {"name": "ExampleCorp", "ats": "ashby", "token": "examplecorp"}


def _result(body: bytes) -> HttpResult:
    return HttpResult(url="https://example.test/x", status=200, body=body,
                      headers={"content-type": "application/json"}, duration_ms=1,
                      ok=True, error=None, method="GET",
                      content_type="application/json")


class _RecordedBoard(unittest.TestCase):
    """Serves the recorded Ashby payload to every fetch in this module."""

    def setUp(self):
        self._prior_get = sources.http_get_full
        body = json.dumps(ASHBY_BOARD).encode()
        sources.http_get_full = lambda *a, **k: _result(body)
        self.addCleanup(lambda: setattr(sources, "http_get_full", self._prior_get))
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # The mode hint is config-dependent; pin it off unless a test asks for it.
        self._prior_saving = company_roles._token_saving
        company_roles._token_saving = lambda: False
        self.addCleanup(
            lambda: setattr(company_roles, "_token_saving", self._prior_saving))

    def _dump(self, needle, **kwargs) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = company_roles.dump_jd(ENTRY, needle, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def _posting(self, needle):
        return next(p for p in sources.fetch_company(ENTRY)
                    if needle.lower() in p.title.lower())


class NoFlagRegressionTests(_RecordedBoard):
    """Without --digest/--out, stdout is byte-identical to the pre-flag behavior."""

    def test_full_mode_stdout_is_byte_identical(self):
        code, stdout, stderr = self._dump("Senior Platform")
        self.assertEqual(code, 0)
        p = self._posting("Senior Platform")
        # `_verdict` returns a LocationAssessment, not the (category, matched)
        # tuple this test was first written against: the verdict line now carries
        # the three-valued decision and its review reasons, because collapsing
        # `review` to `no` was hiding roles.
        a = company_roles._verdict(p)
        reasons = f" [{', '.join(a.review_reasons)}]" if a.review_reasons else ""
        expected = (
            f"===== {p.title} =====\n"
            f"Location: {p.location}\n"
            f"Remote: {p.remote}\n"
            f"LocationVerdict: {a.category} / {a.workplace} "
            f"({a.decision}){reasons}\n"
            f"Posted: {p.posted_at.date().isoformat()}\n"
            f"URL: {p.url}\n"
            "\n"
            f"{p.description}\n"
            "\n"
        )
        self.assertEqual(stdout, expected)
        self.assertEqual(stderr, "")
        # No digest artifact anywhere on the default path.
        self.assertNotIn("DIGEST", stdout)

    def test_full_mode_emits_the_whole_description(self):
        _code, stdout, _err = self._dump("Senior Platform")
        self.assertIn("Responsibility 11", stdout)
        self.assertGreater(len(stdout.encode()), company_roles._DIGEST_MIN_BYTES)

    def test_no_match_still_exits_one(self):
        code, stdout, stderr = self._dump("Quantum Blacksmith")
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("no posting title contains", stderr)


class DigestFidelityTests(_RecordedBoard):
    """Every field the pipeline parses out of a JD body survives the digest."""

    def _digest_stdout(self) -> str:
        _code, stdout, _err = self._dump("Senior Platform", digest=True)
        return stdout

    def test_digest_carries_title_and_level(self):
        # job_metadata.classify_level -> meta.yaml job_level
        d = self._digest_stdout()
        self.assertIn("TITLE: Senior Platform Engineer", d)
        self.assertIn("LEVEL (job_metadata.classify_level on title): senior", d)

    def test_digest_titles_the_posting_not_the_jd_body(self):
        # ax-eng-2 is titled "Staff Platform Engineer" on the board but reuses a
        # description whose first line reads "Senior Platform Engineer". The board
        # title is the authoritative one and drives the level read; the body's is
        # kept on its own line rather than dropped.
        _code, d, _err = self._dump("Staff Platform", digest=True)
        self.assertIn("TITLE: Staff Platform Engineer", d)
        self.assertIn("LEVEL (job_metadata.classify_level on title): staff", d)
        self.assertIn("TITLE (derived from the JD body): Senior Platform Engineer", d)

    def test_digest_carries_required_yoe(self):
        # extract_required_yoe_details -> meta.yaml required_yoe; a high-confidence
        # minimum over the profile cap is a HARD drop in assess_required_yoe.
        d = self._digest_stdout()
        self.assertIn("REQUIRED YOE", d)
        self.assertIn("min=9", d)
        self.assertIn("confidence: high", d)
        self.assertIn("9+ years of professional software engineering experience", d)

    def test_digest_carries_location_and_workplace(self):
        # extract_jd_locations (status.py --check-locations) + classify_workplace
        d = self._digest_stdout()
        self.assertIn("Seattle, WA (Hybrid)", d)
        self.assertIn("three days a week in the Seattle office", d)

    def test_digest_carries_sponsorship(self):
        # classify_sponsorship -> meta.yaml sponsorship (and the search-time gate)
        d = self._digest_stdout()
        self.assertIn("unable to sponsor or take over sponsorship of an employment "
                      "visa", d)
        # LOCATOR, not a verdict.
        self.assertNotIn("unlikely", d)

    def test_digest_carries_compensation(self):
        # extract_salary_range -> meta.yaml salary_range
        d = self._digest_stdout()
        self.assertIn("PARSED SALARY", d)
        self.assertIn("195000-265000 USD/year", d)
        self.assertIn("The base salary range for this role is $195,000 - $265,000 "
                      "per year.", d)

    def test_compensation_terms_match_on_word_boundaries_only(self):
        # "ote" (on-target earnings) is a SUBSTRING of "Remote" — the workplace lines
        # must not be dragged into the compensation section.
        d = self._digest_stdout()
        comp = d.split("COMPENSATION SENTENCES")[1]
        self.assertNotIn("hybrid role", comp)
        self.assertNotIn("Seattle office", comp)

    def test_digest_drops_the_prose_and_says_so(self):
        # The honest cost: responsibilities/benefits prose is NOT in the digest, and
        # the digest says where the complete text is.
        d = self._digest_stdout()
        self.assertNotIn("Responsibility 11", d)
        self.assertIn("open the JD above and read it verbatim", d)
        self.assertIn("still required for handoff, drafting, and the honesty gates", d)

    def test_digest_matches_fetch_jd_for_the_same_text(self):
        # ONE builder, one format: the ATS-API path prints exactly what the page path
        # prints for the same JD text.
        d = self._digest_stdout()
        p = self._posting("Senior Platform")
        expected = fetch_jd.build_digest(
            p.description, jd_path=company_roles._NOT_SAVED,
            byte_count=len(p.description.encode()), title=p.title)
        self.assertIn(expected, d)


class DigestVisibilityTests(_RecordedBoard):
    """A consumer can always tell a digested dump from a complete one."""

    def test_digest_is_labeled_on_the_posting_header(self):
        _code, stdout, _err = self._dump("Senior Platform", digest=True)
        self.assertIn("[DIGEST: gate locator, NOT the full JD]", stdout.splitlines()[0])

    def test_digest_without_out_says_the_verbatim_jd_was_not_saved(self):
        _code, stdout, _err = self._dump("Senior Platform", digest=True)
        self.assertIn("NOT SAVED — re-run with --out", stdout)

    def test_digest_tail_points_at_the_saved_file_when_out_is_given(self):
        dest = self.tmp / "source" / "JD-Senior-Platform-Engineer.md"
        _code, stdout, _err = self._dump("Senior Platform", digest=True, out=dest)
        self.assertIn(f"VERBATIM JD SAVED: {dest}", stdout)
        self.assertIn(f"JD (verbatim, full): {dest}", stdout)
        self.assertNotIn("NOT SAVED", stdout)


class ShortJdPassthroughTests(_RecordedBoard):
    """A JD under the digest threshold is passed through untouched."""

    def test_short_jd_is_printed_verbatim_with_a_stated_reason(self):
        _code, stdout, _err = self._dump("Data Analyst", digest=True)
        p = self._posting("Data Analyst")
        self.assertLess(len(p.description.encode()), company_roles._DIGEST_MIN_BYTES)
        self.assertIn(p.description, stdout)          # verbatim, untouched
        self.assertNotIn("JD DIGEST", stdout)         # no locator built
        self.assertIn("a digest of it would not be smaller", stdout)

    def test_short_jd_header_is_not_labeled_a_digest(self):
        _code, stdout, _err = self._dump("Data Analyst", digest=True)
        self.assertEqual(stdout.splitlines()[0], "===== Data Analyst =====")

    def test_dense_jd_over_the_threshold_still_passes_through_when_measured_bigger(self):
        # A JD over the size threshold whose body is ALL gate signal (requirements
        # and pay lines, no prose) digests larger than itself. The measured check
        # catches it and prints the JD verbatim rather than a bigger "summary".
        dense = "Senior Platform Engineer\nLocation: Austin, TX (Hybrid)\n" + "\n".join(
            f"- Track {i}: at least {i + 2} years of experience; the base salary "
            f"range is ${100 + i},000 - ${200 + i},000 per year." for i in range(30))
        board = json.loads(json.dumps(ASHBY_BOARD))
        board["jobs"][0]["descriptionPlain"] = dense
        body = json.dumps(board).encode()
        sources.http_get_full = lambda *a, **k: _result(body)

        self.assertGreater(len(dense.encode()), company_roles._DIGEST_MIN_BYTES)
        _code, stdout, _err = self._dump("Senior Platform", digest=True)
        self.assertIn("is not smaller than this", stdout)
        self.assertIn(dense, stdout)             # verbatim, untouched
        self.assertNotIn("JD DIGEST", stdout)
        self.assertNotIn("[DIGEST:", stdout)


class OutFlagTests(_RecordedBoard):
    def test_out_writes_the_verbatim_jd_and_suppresses_the_body(self):
        dest = self.tmp / "source" / "JD-Senior-Platform-Engineer.md"
        code, stdout, _err = self._dump("Senior Platform", out=dest)
        self.assertEqual(code, 0)
        p = self._posting("Senior Platform")
        self.assertEqual(dest.read_text(encoding="utf-8"), p.description)
        self.assertIn(f"VERBATIM JD SAVED: {dest} "
                      f"({len(p.description.encode())} bytes)", stdout)
        # The body never travels through stdout — that is the point of --out.
        self.assertNotIn("Responsibility 11", stdout)

    def test_out_refuses_an_ambiguous_multi_hit_selection(self):
        dest = self.tmp / "JD.md"
        code, stdout, stderr = self._dump("Platform Engineer", out=dest)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("2 postings match", stderr)
        self.assertIn("Narrow --jd", stderr)
        self.assertFalse(dest.exists())

    def test_multi_hit_digest_without_out_is_allowed(self):
        code, stdout, _err = self._dump("Platform Engineer", digest=True)
        self.assertEqual(code, 0)
        self.assertEqual(stdout.count("JD DIGEST"), 2)

    def test_out_plus_short_jd_keeps_the_file_and_skips_the_body(self):
        # The passthrough path must not re-print a JD that --out already saved.
        dest = self.tmp / "JD-Data-Analyst.md"
        code, stdout, _err = self._dump("Data Analyst", digest=True, out=dest)
        self.assertEqual(code, 0)
        p = self._posting("Data Analyst")
        self.assertEqual(dest.read_text(encoding="utf-8"), p.description)
        self.assertIn("no digest built", stdout)
        self.assertNotIn("We analyze product metrics", stdout)


class DigestFailureTests(_RecordedBoard):
    def test_a_broken_digest_never_costs_the_recovery(self):
        # A digest is a best-effort add-on: if the builder raises, the verbatim JD
        # is still delivered (fetch_jd._emit_digest holds the same line).
        def _boom(*_a, **_k):
            raise RuntimeError("classifier import failed")

        prior = company_roles.build_digest
        company_roles.build_digest = _boom
        self.addCleanup(lambda: setattr(company_roles, "build_digest", prior))
        code, stdout, _err = self._dump("Senior Platform", digest=True)
        self.assertEqual(code, 0)
        self.assertIn("could not build the digest (classifier import failed)", stdout)
        self.assertIn("Responsibility 11", stdout)   # full JD delivered anyway


class ModeHintTests(_RecordedBoard):
    """generation_mode nudges the caller on stderr; it never changes stdout."""

    def test_token_saving_hint_goes_to_stderr_only(self):
        company_roles._token_saving = lambda: True
        _code, stdout, stderr = self._dump("Senior Platform")
        self.assertIn("--digest", stderr)
        self.assertIn("token_saving", stderr)
        self.assertNotIn("tip —", stdout)

    def test_full_mode_stdout_is_identical_with_and_without_the_hint(self):
        _code, quiet, _err = self._dump("Senior Platform")
        company_roles._token_saving = lambda: True
        _code, loud, _err = self._dump("Senior Platform")
        self.assertEqual(quiet, loud)

    def test_no_hint_when_the_dump_is_small(self):
        company_roles._token_saving = lambda: True
        _code, _stdout, stderr = self._dump("Data Analyst")
        self.assertEqual(stderr, "")

    def test_no_hint_when_the_digest_is_already_in_use(self):
        company_roles._token_saving = lambda: True
        _code, _stdout, stderr = self._dump("Senior Platform", digest=True)
        self.assertEqual(stderr, "")


class ReductionTests(_RecordedBoard):
    def test_digest_is_materially_smaller_than_the_full_dump(self):
        _code, full, _err = self._dump("Senior Platform")
        _code, digested, _err = self._dump("Senior Platform", digest=True)
        self.assertLess(len(digested.encode()), len(full.encode()) // 2)


class EmptyDescriptionOutTests(_RecordedBoard):
    """A failed detail fetch must never truncate an already-recovered JD.

    ``--out`` wrote ``p.description or ""`` unconditionally. The documented
    recovery recipe points it at ``source/JD-<role>.md`` inside an application
    folder — owner-owned product content — and the natural response to a partial
    outage is to re-run it. So the second run overwrote a JD the first run had
    recovered with ZERO bytes and printed ``VERBATIM JD SAVED … (0 bytes)`` at
    rc 0.
    """

    def _serve_without_a_description(self):
        board = json.loads(json.dumps(ASHBY_BOARD))
        for job in board["jobs"]:
            if job["id"] == "ax-short":       # the Data Analyst posting
                job["descriptionPlain"] = ""
        body = json.dumps(board).encode()
        sources.http_get_full = lambda *a, **k: _result(body)

    def test_an_existing_jd_survives_a_posting_that_came_back_empty(self):
        self._serve_without_a_description()
        dest = self.tmp / "source" / "JD-Data-Analyst.md"
        dest.parent.mkdir(parents=True)
        recovered = "A JD an earlier run recovered.\n"
        dest.write_text(recovered, encoding="utf-8")
        code, stdout, stderr = self._dump("Data Analyst", out=dest)
        self.assertEqual(code, 1)
        self.assertEqual(dest.read_text(encoding="utf-8"), recovered)
        self.assertIn("refusing to write", stderr)
        self.assertNotIn("VERBATIM JD SAVED", stdout)

    def test_nothing_at_all_is_created_when_the_target_is_new(self):
        self._serve_without_a_description()
        dest = self.tmp / "fresh" / "JD-Data-Analyst.md"
        code, _stdout, _stderr = self._dump("Data Analyst", out=dest)
        self.assertEqual(code, 1)
        self.assertFalse(dest.exists())
        self.assertFalse(dest.parent.exists(), "the parent dir was created anyway")

    def test_a_posting_that_still_has_its_jd_is_unaffected(self):
        self._serve_without_a_description()
        dest = self.tmp / "JD-Senior-Platform-Engineer.md"
        code, _stdout, _stderr = self._dump("Senior Platform", out=dest)
        self.assertEqual(code, 0)
        self.assertTrue(dest.read_text(encoding="utf-8").strip())

    def test_the_stdout_path_still_reports_the_sentinel_at_rc_zero(self):
        # Only the WRITE is refused: printing "(no description returned…)" costs
        # nothing and is the existing contract.
        self._serve_without_a_description()
        code, stdout, _stderr = self._dump("Data Analyst")
        self.assertEqual(code, 0)
        self.assertIn(company_roles._NO_DESCRIPTION, stdout)


if __name__ == "__main__":
    unittest.main()
