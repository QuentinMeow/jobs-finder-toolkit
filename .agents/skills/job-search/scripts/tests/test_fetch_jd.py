"""Tests for fetch_jd.py — extraction quality, idempotency, --force, errors.

NO network: the extractor is exercised directly on local HTML fixtures, and the
CLI is driven against ``file://`` URLs pointing at fixtures written to a temp dir.

Run with:
    .venv/bin/python -m unittest discover -s .agents/skills/job-search/scripts/tests
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# Make the sibling script importable (.agents/skills/job-search/scripts/).
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import fetch_jd  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures — a fictional "Nimbus Robotics" posting; no real names/employers.
# --------------------------------------------------------------------------- #

# Representative ATS-style page: real JD wrapped in nav/script/style/header/
# footer/form chrome, plus a cookie banner and a "similar jobs" list of noise.
ATS_PAGE = """<!doctype html>
<html lang="en">
<head>
  <title>Nimbus Robotics — Careers</title>
  <style>.hero { color: #123; } body { font: 14px sans-serif; }</style>
  <script>window.dataLayer = []; console.log("NOISE_ANALYTICS_TAG");</script>
</head>
<body>
  <header>
    <a href="/">Nimbus Robotics</a>
    <nav>
      <a href="/jobs">NOISE_NAV_ALL_JOBS</a>
      <a href="/login">NOISE_NAV_SIGN_IN</a>
    </nav>
  </header>

  <main>
    <article class="posting">
      <h1>Senior Platform Engineer</h1>
      <p>Nimbus Robotics builds autonomous warehouse robots. You will design and
         operate the Kubernetes platform every product team ships on.</p>

      <h2>Responsibilities</h2>
      <ul>
        <li>Build and maintain multi-tenant Kubernetes clusters</li>
        <li>Own the CI/CD pipeline and developer self-service tooling</li>
        <li>Mentor engineers on reliability and on-call practice</li>
      </ul>

      <h2>Requirements</h2>
      <ul>
        <li>5+ years operating production distributed systems</li>
        <li>Deep experience with Kubernetes, Terraform, and observability</li>
      </ul>

      <h2>Benefits</h2>
      <p>We sponsor H-1B transfers and support green-card processing after one
         year. Compensation is $190k-$230k base plus equity.</p>
    </article>

    <form action="/apply" method="post">
      <label>NOISE_FORM_EMAIL<input type="email" name="email"></label>
      <button type="submit">NOISE_FORM_APPLY_NOW</button>
    </form>
  </main>

  <footer>
    <p>NOISE_FOOTER_COPYRIGHT Nimbus Robotics. All rights reserved.</p>
    <script>trackFooter("NOISE_FOOTER_SCRIPT");</script>
  </footer>
</body>
</html>
"""

# Minimal valid page: a heading + one short paragraph. Its extracted text is
# well under the tiny-extraction threshold, so the CLI should warn yet still save.
MINIMAL_PAGE = """<!doctype html>
<html><body>
  <h1>Backend Engineer</h1>
  <p>Join our small team building payments infrastructure.</p>
</body></html>
"""

# Empty-content page: only chrome/script — nothing readable survives extraction.
EMPTY_PAGE = """<!doctype html>
<html>
<head><title>Loading…</title><script>boot();</script></head>
<body>
  <nav><a href="/">Home</a></nav>
  <div id="root"></div>
  <script>renderApp("NOISE_ONLY_JS");</script>
</body>
</html>
"""


def _run_cli(argv):
    """Run fetch_jd.main(argv); return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fetch_jd.main(argv)
    return code, out.getvalue(), err.getvalue()


class ExtractorTests(unittest.TestCase):
    def test_strips_chrome(self):
        text = fetch_jd.extract_readable_text(ATS_PAGE)
        for noise in (
            "NOISE_ANALYTICS_TAG", "NOISE_NAV_ALL_JOBS", "NOISE_NAV_SIGN_IN",
            "NOISE_FORM_EMAIL", "NOISE_FORM_APPLY_NOW", "NOISE_FOOTER_COPYRIGHT",
            "NOISE_FOOTER_SCRIPT", "console.log", "dataLayer", "color: #123",
        ):
            self.assertNotIn(noise, text, f"chrome/script leaked: {noise!r}")
        # Catch-all: no chrome marker of any kind survives extraction.
        self.assertNotIn("NOISE_", text)

    def test_keeps_jd_text_verbatim(self):
        text = fetch_jd.extract_readable_text(ATS_PAGE)
        # Paragraph wording survives exactly (whitespace re-flowed, words verbatim).
        self.assertIn(
            "You will design and operate the Kubernetes platform every product "
            "team ships on.", text)
        self.assertIn(
            "We sponsor H-1B transfers and support green-card processing after "
            "one year. Compensation is $190k-$230k base plus equity.", text)

    def test_preserves_heading_and_bullet_structure(self):
        text = fetch_jd.extract_readable_text(ATS_PAGE)
        self.assertIn("# Senior Platform Engineer", text)
        self.assertIn("## Responsibilities", text)
        self.assertIn("## Requirements", text)
        self.assertIn("- Build and maintain multi-tenant Kubernetes clusters", text)
        self.assertIn("- Mentor engineers on reliability and on-call practice", text)
        # Heading precedes its bullets in reading order.
        self.assertLess(text.index("## Responsibilities"),
                        text.index("- Build and maintain"))

    def test_empty_page_yields_no_text(self):
        self.assertEqual(fetch_jd.extract_readable_text(EMPTY_PAGE).strip(), "")


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _fixture_url(self, name: str, html: str) -> str:
        path = self.tmp / name
        path.write_text(html, encoding="utf-8")
        return path.as_uri()

    def test_saves_and_reports_bytes(self):
        url = self._fixture_url("ats.html", ATS_PAGE)
        out = self.tmp / "JD-senior-platform-engineer.md"
        code, stdout, stderr = _run_cli([url, "--out", str(out)])
        self.assertEqual(code, 0, stderr)
        self.assertTrue(out.exists())
        self.assertIn(str(out), stdout)
        self.assertIn(f"({out.stat().st_size} bytes)", stdout)
        self.assertNotIn("warning", stderr)      # ATS page is well over the floor
        self.assertIn("Senior Platform Engineer", out.read_text(encoding="utf-8"))

    def test_creates_parent_dirs(self):
        url = self._fixture_url("ats.html", ATS_PAGE)
        out = self.tmp / "source" / "nested" / "JD.md"
        code, _stdout, stderr = _run_cli([url, "--out", str(out)])
        self.assertEqual(code, 0, stderr)
        self.assertTrue(out.exists())

    def test_idempotent_keeps_existing_without_fetching(self):
        out = self.tmp / "JD.md"
        out.write_text("SENTINEL — do not overwrite\n", encoding="utf-8")
        # A URL that would ERROR if fetched proves the fetch path is never taken.
        bad_url = (self.tmp / "does-not-exist.html").as_uri()
        code, stdout, stderr = _run_cli([bad_url, "--out", str(out)])
        self.assertEqual(code, 0, stderr)
        self.assertIn("[kept existing]", stdout)
        self.assertEqual(out.read_text(encoding="utf-8"),
                         "SENTINEL — do not overwrite\n")

    def test_force_overwrites(self):
        out = self.tmp / "JD.md"
        out.write_text("STALE CONTENT\n", encoding="utf-8")
        url = self._fixture_url("ats.html", ATS_PAGE)
        code, stdout, stderr = _run_cli([url, "--out", str(out), "--force"])
        self.assertEqual(code, 0, stderr)
        self.assertNotIn("[kept existing]", stdout)
        body = out.read_text(encoding="utf-8")
        self.assertNotIn("STALE CONTENT", body)
        self.assertIn("Senior Platform Engineer", body)

    def test_tiny_extraction_warns_but_saves(self):
        url = self._fixture_url("minimal.html", MINIMAL_PAGE)
        out = self.tmp / "JD.md"
        code, stdout, stderr = _run_cli([url, "--out", str(out)])
        self.assertEqual(code, 0, stderr)
        self.assertTrue(out.exists())
        self.assertIn(str(out), stdout)
        self.assertIn("warning", stderr.lower())
        self.assertIn("javascript", stderr.lower())
        # Real content still saved verbatim.
        self.assertIn("Backend Engineer", out.read_text(encoding="utf-8"))

    def test_empty_extraction_errors_without_writing(self):
        url = self._fixture_url("empty.html", EMPTY_PAGE)
        out = self.tmp / "JD.md"
        code, _stdout, stderr = _run_cli([url, "--out", str(out)])
        self.assertNotEqual(code, 0)
        self.assertFalse(out.exists())
        self.assertIn("no readable text", stderr.lower())

    def test_fetch_failure_exits_nonzero(self):
        bad_url = (self.tmp / "missing.html").as_uri()
        out = self.tmp / "JD.md"
        code, _stdout, stderr = _run_cli([bad_url, "--out", str(out)])
        self.assertNotEqual(code, 0)
        self.assertFalse(out.exists())
        self.assertIn("could not fetch", stderr.lower())


# --------------------------------------------------------------------------- #
# Digest builder — constructed saved-JD texts (the digest works on the saved
# markdown, so it is exercised directly, no fetch). Fictional postings only.
# --------------------------------------------------------------------------- #

# Remote role with an explicit sponsorship DENIAL whose sentence still contains
# the word "sponsorship" (the LESSONS false-positive case).
JD_REMOTE_DENIAL = """# Senior Backend Engineer

## About the role
- Location: Remote (US)
We are a fully remote team building payments infrastructure.

## Requirements
- 5+ years of backend experience.
- You must be authorized to work in the United States; we are unable to sponsor \
visas or provide visa sponsorship for this position.
"""

# Hybrid role in a preferred metro (Springfield is a config.example metro) with an
# explicit green-card / H-1B OFFER.
JD_HYBRID_METRO = """# Machine Learning Engineer II

Our headquarters are in Springfield. This is a hybrid role: 3 days a week in the \
Springfield office, 2 remote.

Location: Springfield, ST (Hybrid)

## What we offer
We happily sponsor H-1B transfers and support the green card process for strong \
candidates. Relocation assistance is available.
"""

# Foreign-city role: the city is in the TITLE, on-site, requires relocation, with a
# denial phrased ONLY via a job_metadata phrase-list entry not in the keyword regex.
JD_FOREIGN_TITLE = """# Staff Software Engineer, London

Location: London, United Kingdom

You will join our on-site team in London; this role requires relocation to the UK.

## Eligibility
This role is open to permanent resident only applicants — gc only.
"""

# No workplace and no visa signals at all — placeholders must fire.
JD_NO_SIGNALS = """# Data Analyst

## About
We analyze product metrics and build dashboards for the growth team.

## Requirements
- 3 years of SQL and Python.
"""


class DigestBuilderTests(unittest.TestCase):
    def _digest(self, text: str, *, path="/apps/6_drafted/x/source/JD-role.md") -> str:
        data = text.encode("utf-8")
        return fetch_jd.build_digest(text, jd_path=path, byte_count=len(data))

    def test_remote_denial(self):
        d = self._digest(JD_REMOTE_DENIAL)
        # (a) title + level
        self.assertIn("TITLE: Senior Backend Engineer", d)
        self.assertIn("LEVEL", d)
        self.assertIn("senior", d)  # classify_level on the title
        # (b) parsed location + workplace signal line
        self.assertIn("Remote (US)", d)
        self.assertIn("fully remote team", d)  # the remote-signal line, located
        # (c) the DENIAL sentence, verbatim (not paraphrased, not classified)
        self.assertIn(
            "we are unable to sponsor visas or provide visa sponsorship for this "
            "position.", d)
        # LOCATOR, not a verdict: the classifier's likely/unlikely words never appear.
        self.assertNotIn("unlikely", d)
        self.assertNotIn("likely", d)
        # (d) escape-hatch tail
        self.assertIn("/apps/6_drafted/x/source/JD-role.md", d)
        self.assertIn(f"{len(JD_REMOTE_DENIAL.encode())} bytes", d)
        self.assertIn("open the JD", d)

    def test_hybrid_metro(self):
        d = self._digest(JD_HYBRID_METRO)
        self.assertIn("TITLE: Machine Learning Engineer II", d)
        self.assertIn("mid", d)  # "Engineer II" -> mid
        # parsed hybrid location + the hybrid signal line
        self.assertIn("Springfield, ST (Hybrid)", d)
        self.assertIn("hybrid role", d)
        # the OFFER sentence, located verbatim
        self.assertIn("We happily sponsor H-1B transfers and support the green card "
                      "process for strong candidates.", d)
        # sentence-scoped: the unrelated trailing offer clause is not merged into the
        # visa bullet (Relocation is a workplace signal, not a sponsorship sentence).
        visa_block = d.split("VISA/SPONSORSHIP SENTENCES")[1]
        self.assertNotIn("Relocation assistance is available", visa_block)

    def test_foreign_city_title(self):
        d = self._digest(JD_FOREIGN_TITLE)
        self.assertIn("TITLE: Staff Software Engineer, London", d)
        self.assertIn("staff", d)  # classify_level on the title
        self.assertIn("London, United Kingdom", d)  # parsed foreign location
        self.assertIn("relocation to the UK", d)     # on-site/relocation signal line
        # Denial phrased ONLY via reused phrase-list entries ("permanent resident
        # only" / "gc only") — no keyword-regex stem — must still be located, proving
        # the classify_sponsorship phrase lists are reused, not just the keyword net.
        self.assertIn("gc only", d.lower())

    def test_no_signals_shows_placeholders(self):
        d = self._digest(JD_NO_SIGNALS)
        self.assertIn("TITLE: Data Analyst", d)
        self.assertIn("no workplace/location keyword", d)
        self.assertIn("no visa/sponsorship sentence found", d)

    def test_digest_is_compact_vs_full_jd(self):
        # A long JD (repeated prose + many bullets) still yields a small, roughly
        # constant-size digest: it extracts signal lines, not the whole body.
        filler = ("You will build and operate large-scale services that serve many "
                  "requests per second, working across the stack. ")
        big = (
            "# Senior Platform Engineer\n"
            "Location: San Francisco, CA (Hybrid)\n\n"
            + "## About\n" + filler * 40 + "\n\n"
            + "## Responsibilities\n"
            + "\n".join(f"- Duty {i}: {filler}" for i in range(40)) + "\n\n"
            + "We are unable to provide visa sponsorship for this role.\n"
        )
        data = big.encode("utf-8")
        d = fetch_jd.build_digest(big, jd_path="/x/JD.md", byte_count=len(data))
        self.assertLess(len(d.encode("utf-8")), len(data) // 2)
        self.assertLess(len(d.encode("utf-8")), 3000)  # ~1-2 KB target, bounded
        # Both gate signals still present despite the surrounding bulk.
        self.assertIn("San Francisco, CA (Hybrid)", d)
        self.assertIn("unable to provide visa sponsorship", d)


class DigestCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_no_flag_stdout_is_exactly_the_path_line(self):
        # Regression: without --digest, stdout is byte-identical to before — exactly
        # the "path (N bytes)\n" line, no digest anywhere, on stdout or stderr.
        url = (self.tmp / "ats.html").as_uri()
        (self.tmp / "ats.html").write_text(ATS_PAGE, encoding="utf-8")
        out = self.tmp / "JD.md"
        code, stdout, stderr = _run_cli([url, "--out", str(out)])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, f"{out} ({out.stat().st_size} bytes)\n")
        self.assertNotIn("DIGEST", stdout + stderr)

    def test_digest_flag_appends_digest_after_base_line(self):
        url = (self.tmp / "ats.html").as_uri()
        (self.tmp / "ats.html").write_text(ATS_PAGE, encoding="utf-8")
        out = self.tmp / "JD.md"
        code, stdout, _stderr = _run_cli([url, "--out", str(out), "--digest"])
        self.assertEqual(code, 0)
        # The first stdout line is the unchanged base "path (N bytes)" line.
        self.assertEqual(stdout.splitlines()[0], f"{out} ({out.stat().st_size} bytes)")
        self.assertIn("JD DIGEST", stdout)
        # ATS_PAGE carries a sponsorship offer sentence — it must be located.
        self.assertIn("We sponsor H-1B transfers", stdout)

    def test_digest_from_kept_existing_file_without_refetch(self):
        # The common flow: handoff.py already saved the JD; --digest on the existing
        # file emits the digest without re-fetching (a URL that would ERROR proves it).
        out = self.tmp / "JD.md"
        out.write_text(JD_REMOTE_DENIAL, encoding="utf-8")
        bad_url = (self.tmp / "does-not-exist.html").as_uri()
        code, stdout, _stderr = _run_cli([bad_url, "--out", str(out), "--digest"])
        self.assertEqual(code, 0)
        self.assertIn("[kept existing]", stdout.splitlines()[0])
        self.assertIn("JD DIGEST", stdout)
        self.assertIn("Remote (US)", stdout)


if __name__ == "__main__":
    unittest.main()
