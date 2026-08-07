"""Regression: a render that inspected no PDF may never report plain success.

``AGENTS.md`` lists the one-page PDF among the mandatory hard gates. Before this
suite, ``render.py --no-pdf`` (and any machine with no DOCX->PDF converter, where
``pdf_convert.docx_to_pdf`` returns ``None``) called
``check.run_checks(yaml_path, None)``; both branches of that function's PDF block
were guarded on ``pdf_path is not None``, so with ``None`` **nothing was printed
at all** and the run ended on an unqualified ``all checks passed``, exit 0 — over
a PDF no gate had opened.

The standard these tests hold the gate to is the review gate's: a check that
could not inspect its input says ``NOT INSPECTED``, loudly, and the summary is
never an unqualified success. The two ways to have no PDF are deliberately NOT
equivalent — ``--no-pdf`` is a declared DOCX-only draft (WARN, exit 0) while a
missing converter is an environment failure on a run that asked for the full
pipeline (FAIL, exit 1).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check  # noqa: E402

CONFIG = REPO_ROOT / "config.example.yaml"
RENDER = SCRIPTS / "render.py"
REFERENCE = (REPO_ROOT / "examples" / "me" / "career" / "resume"
             / "reference.example.docx")
EXAMPLE_APP = (REPO_ROOT / "examples" / "me" / "applications" / "6_drafted"
               / "example-corp-senior-software-engineer")
# Passed explicitly so these tests never resolve the config layer (which on a
# maintainer checkout points at the private overlay).
BASELINE = (REPO_ROOT / "examples" / "me" / "career" / "resume"
            / "baseline.example.yaml")
PROFILE = REPO_ROOT / "examples" / "me" / "career" / "profile.example.md"

# The exact string a fully-inspected run prints. Asserting its ABSENCE is the
# point of this file: a partially-run gate set must not be able to emit it.
UNQUALIFIED_SUCCESS = "all checks passed"


def _run_checks(pdf_path, *, pdf_required: bool) -> tuple[bool, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        ok = check.run_checks(EXAMPLE_APP / "source" / "tailored.yaml", pdf_path,
                              BASELINE, PROFILE, pdf_required=pdf_required)
    return ok, out.getvalue()


class UninspectedPdfIsReportedTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(EXAMPLE_APP.is_dir(), "shipped example application missing")

    def test_no_pdf_at_all_fails_when_the_pipeline_asked_for_one(self):
        """The missing-LibreOffice case: an environment failure, not a skip."""
        ok, text = _run_checks(None, pdf_required=True)
        self.assertFalse(ok, text)
        self.assertIn("PDF NOT INSPECTED", text)
        self.assertNotIn(UNQUALIFIED_SUCCESS, text)
        # The message must name the remedy, both halves of it.
        self.assertIn("LibreOffice", text)
        self.assertIn("--no-pdf", text)

    def test_no_pdf_at_all_warns_but_passes_when_opted_out(self):
        """``--no-pdf`` is a legitimate declared intent, so it stays exit 0."""
        ok, text = _run_checks(None, pdf_required=False)
        self.assertTrue(ok, text)
        self.assertIn("PDF NOT INSPECTED", text)
        self.assertIn("WARN:", text)
        self.assertNotIn("FAIL:", text)
        # Passing is fine; claiming everything was checked is not.
        self.assertNotIn(UNQUALIFIED_SUCCESS, text)
        self.assertIn("NOT RUN", text)

    def test_every_pdf_gate_is_named_in_the_not_inspected_message(self):
        """The operator learns WHICH gates went unrun, not just that some did."""
        _, text = _run_checks(None, pdf_required=False)
        for gate in check.PDF_GATE_NAMES:
            self.assertIn(gate, text, f"gate {gate!r} missing from the NOT INSPECTED report")

    def test_a_missing_pdf_file_is_reported_the_same_way(self):
        """The standalone path (a concrete path that does not exist) warned but
        still printed an unqualified success summary. It no longer can."""
        ok, text = _run_checks(EXAMPLE_APP / "does-not-exist.pdf", pdf_required=False)
        self.assertTrue(ok, text)
        self.assertIn("PDF NOT INSPECTED", text)
        self.assertNotIn(UNQUALIFIED_SUCCESS, text)

    def test_a_real_pdf_still_reports_plain_success(self):
        """Guard against over-correction: the happy path must be unchanged.

        The fixture is found by globbing, NOT by composing
        ``check.resume_stem('')``: that stem comes from whichever config the
        developer has mounted, so on a maintainer checkout it names the owner's
        real resume and the shipped example — written for the fictional example
        candidate — looks missing. CI has no config and passed either way, so
        the test was green everywhere except the one machine that matters.

        ``config.resume_stem()`` is ``<name>_<title>_Resume`` by construction,
        so the suffix is stable across every identity; the cover letter in the
        same folder is ``*_Cover_Letter*`` and does not collide.
        """
        pdfs = sorted(EXAMPLE_APP.glob("*_Resume.pdf"))
        self.assertEqual(
            len(pdfs), 1,
            f"expected exactly one shipped example resume PDF in {EXAMPLE_APP}, found {pdfs}",
        )
        pdf = pdfs[0]
        ok, text = _run_checks(pdf, pdf_required=True)
        self.assertTrue(ok, text)
        self.assertIn(UNQUALIFIED_SUCCESS, text)
        self.assertNotIn("NOT INSPECTED", text)


class RenderCliTests(unittest.TestCase):
    """Drives the real CLI, because the defect lived in what render.py PASSED."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = self.tmp / EXAMPLE_APP.name
        shutil.copytree(EXAMPLE_APP, self.app)
        # Remove the shipped PDFs: --no-pdf renders none, and a leftover copy
        # would let the gates run and hide the very state under test.
        for pdf in self.app.glob("*.pdf"):
            pdf.unlink()

    def _render(self, *extra):
        env = os.environ.copy()
        env["JOBHUNT_CONFIG"] = str(CONFIG)
        return subprocess.run(
            [sys.executable, str(RENDER), str(self.app),
             "--reference", str(REFERENCE), *extra],
            capture_output=True, text=True, env=env)

    def test_render_with_no_pdf_does_not_claim_the_pdf_gates_passed(self):
        res = self._render("--no-pdf")
        combined = res.stdout + res.stderr
        # Deliberate opt-out: the render is allowed to succeed ...
        self.assertEqual(res.returncode, 0, combined)
        # ... but it must not say the PDF was checked.
        self.assertNotIn(UNQUALIFIED_SUCCESS, combined)
        self.assertIn("PDF NOT INSPECTED", combined)
        self.assertIn("NOT RUN", combined)
        self.assertFalse(list(self.app.glob("*.pdf")),
                         "--no-pdf must not produce a PDF")


if __name__ == "__main__":
    unittest.main()
