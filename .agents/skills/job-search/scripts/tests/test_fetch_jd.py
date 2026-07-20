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


if __name__ == "__main__":
    unittest.main()
