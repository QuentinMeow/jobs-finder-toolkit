"""Item 4: render.py's pre-flight one-page estimate GATE.

render.py auto-runs estimate_layout BEFORE any LibreOffice conversion and aborts
(non-zero, nothing rendered) when the resume clearly overflows one page — but
NOT on a borderline/TIGHT resume within the ±1-line word-wrap noise band. A
--skip-estimate escape hatch bypasses the gate.

These tests drive the real render.py CLI as a subprocess (with --no-pdf so no
LibreOffice is needed) and self-validate each fixture's estimate band up front so
they stay correct if the calibrated constants shift.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[5]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import estimate_layout  # noqa: E402

REFERENCE = REPO_ROOT / "examples" / "templates" / "reference.example.docx"
CONFIG = REPO_ROOT / "config.example.yaml"
RENDER = SCRIPTS / "render.py"
EXAMPLE_TAILORED = (REPO_ROOT / "examples" / "applications" / "6_drafted"
                    / "example-corp-senior-software-engineer" / "source" / "tailored.yaml")

SHORT = "Improved reliability of a fictional service used across the test fleet."
LONG = ("Built a deterministic fictional control plane that improved reliability "
        "and cut deploy time for every internal test client across many regions here.")


def _employer(company, *, bullets=None, projects=None):
    return {
        "company": company,
        "role": "Software Engineer",
        "dates": "2020 - Present",
        "location": "Remote (US)",
        "bullets": bullets if bullets is not None else [LONG],
        "projects": projects or [],
    }


def _resume(employers, summary_count=3):
    return {
        "name": "Jordan Rivers",
        "contact_line": "City, ST - jordan.rivers@example.com",
        "summary_bullets": [LONG] * summary_count,
        "education_line": "B.S. Computer Science, Example University, 2020",
        "skills": [{"label": "Programming Languages", "items": "Python, Go, Rust"}],
        "employers": employers,
    }


def _project(i, n_bullets=4):
    return {"title": f"Synthetic Project {i}", "bullets": [LONG] * n_bullets}


def _est_total(data):
    m = estimate_layout.read_template_metrics(REFERENCE)
    p = estimate_layout.derived_params(m)
    e = estimate_layout.estimate(data, p)
    noise_line = p["pitch_body"] + estimate_layout.BULLET_AFTER_PT
    return e["total_pt"], e["budget_pt"], noise_line


class RenderEstimateGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "source").mkdir()
        self.assertTrue(REFERENCE.exists(), "reference template missing")

    def _write(self, data):
        (self.tmp / "source" / "tailored.yaml").write_text(
            yaml.safe_dump(data), encoding="utf-8")

    def _write_raw(self, text):
        (self.tmp / "source" / "tailored.yaml").write_text(text, encoding="utf-8")

    def _render(self, *extra):
        env = os.environ.copy()
        env["JOBHUNT_CONFIG"] = str(CONFIG)
        return subprocess.run(
            [sys.executable, str(RENDER), str(self.tmp),
             "--reference", str(REFERENCE), "--no-cover-letter", *extra],
            capture_output=True, text=True, env=env)

    def _docx_count(self):
        return len(list((self.tmp / "source").glob("*.docx")))

    # ── fixtures with asserted bands ──────────────────────────────────────
    def test_clear_overflow_fixture_is_actually_a_clear_overflow(self):
        data = _resume([_employer("Example Systems",
                                  projects=[_project(i) for i in range(5)])])
        total, budget, noise = _est_total(data)
        self.assertGreater(total - budget, noise,
                           f"fixture must be a CLEAR overflow (est {total:.0f}, "
                           f"budget {budget:.0f}, noise {noise:.1f})")

    def test_within_margin_fixture_is_under_budget(self):
        data = _resume([_employer("Example Systems",
                                  projects=[_project(0, n_bullets=1),
                                            _project(1, n_bullets=1)])])
        total, budget, _ = _est_total(data)
        self.assertLess(total, budget - 15,
                        f"fixture must be comfortably under budget (est {total:.0f})")

    # ── gate behavior ─────────────────────────────────────────────────────
    def test_clear_overflow_aborts_before_conversion(self):
        data = _resume([_employer("Example Systems",
                                  projects=[_project(i) for i in range(5)])])
        self._write(data)
        res = self._render("--no-pdf", "--skip-checks")
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("Aborting before render", res.stderr)
        self.assertIn("2-page", res.stderr)
        self.assertIn("Trim guidance", res.stderr)
        # Nothing was rendered — the DOCX cycle never ran.
        self.assertEqual(self._docx_count(), 0, "no DOCX should exist after abort")

    def test_within_margin_renders_without_abort(self):
        data = _resume([_employer("Example Systems",
                                  projects=[_project(0, n_bullets=1),
                                            _project(1, n_bullets=1)])])
        self._write(data)
        res = self._render("--no-pdf", "--skip-checks")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Aborting before render", res.stderr)
        self.assertEqual(self._docx_count(), 1, "resume DOCX should be produced")

    def test_borderline_example_is_not_aborted(self):
        # The shipped example estimates a few pt over the 734pt budget yet is a
        # valid 1 page — the exact ±1-line-noise case the gate must NOT abort.
        self.assertTrue(EXAMPLE_TAILORED.exists())
        raw = EXAMPLE_TAILORED.read_text(encoding="utf-8")
        total, budget, noise = _est_total(yaml.safe_load(raw))
        self.assertGreater(total, budget, "sanity: example is a (borderline) OVERFLOW")
        self.assertLessEqual(total - budget, noise, "example must be within the noise band")
        self._write_raw(raw)
        res = self._render("--no-pdf", "--skip-checks")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Aborting before render", res.stderr)
        self.assertEqual(self._docx_count(), 1)

    def test_skip_estimate_bypasses_abort_on_clear_overflow(self):
        data = _resume([_employer("Example Systems",
                                  projects=[_project(i) for i in range(5)])])
        self._write(data)
        res = self._render("--skip-estimate", "--no-pdf", "--skip-checks")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Aborting before render", res.stderr)
        self.assertEqual(self._docx_count(), 1, "DOCX should render under --skip-estimate")


if __name__ == "__main__":
    unittest.main()
