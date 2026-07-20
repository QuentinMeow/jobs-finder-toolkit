"""Offline search-to-render E2E for the public multi-experience fixture."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from pypdf import PdfReader


REPO_ROOT = Path(__file__).resolve().parents[5]
FIXTURE = (
    REPO_ROOT / "examples" / "fixtures" / "resume-writer"
    / "_test_application_multi-experience"
)
HANDOFF = REPO_ROOT / ".agents" / "skills" / "job-search" / "scripts" / "handoff.py"
RENDER = REPO_ROOT / ".agents" / "skills" / "resume-writer" / "scripts" / "render.py"
STATUS = (
    REPO_ROOT / ".agents" / "skills" / "application-tracker" / "scripts" / "status.py"
)


def _has_libreoffice() -> bool:
    return bool(
        shutil.which("soffice")
        or (Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice").exists()
        or Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists()
    )


@unittest.skipUnless(_has_libreoffice(), "LibreOffice is required for PDF E2E")
class MultiExperienceApplicationE2E(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)
        self.apps = self.tmp / "applications"
        self.config = self.tmp / "config.yaml"
        self.config.write_text(
            yaml.safe_dump({
                "candidate": {
                    "name": "Jordan Rivers",
                    "contact_line": (
                        "City, ST • jordan.rivers@example.com • "
                        "linkedin.com/in/jordanrivers"
                    ),
                    "name_slug": "Jordan_Rivers",
                    "title_slug": "Software_Engineer",
                },
                "paths": {
                    "profile_md": str(FIXTURE / "profile" / "jordan-rivers.md"),
                    "baseline_yaml": str(FIXTURE / "profile" / "baseline.yaml"),
                    "reference_docx": str(
                        REPO_ROOT / "examples" / "templates" / "reference.example.docx"),
                    "applications_root": str(self.apps),
                    "discoveries_dir": str(self.apps / "1_discoveries"),
                },
                "location_policy": {
                    "metro": ["springfield", "fairview", "riverside", "lakemont"],
                    "allow_us_remote": True,
                    "us_only": True,
                },
            }, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        self.env = dict(os.environ)
        self.env["JOBHUNT_CONFIG"] = str(self.config)

    def _run(self, *command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(part) for part in command],
            cwd=REPO_ROOT,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_search_handoff_rename_render_and_validate(self):
        # Search handoff stays offline: its URL is a local synthetic HTML page.
        rows = json.loads((FIXTURE / "search" / "search-row.json").read_text())
        rows[0]["url"] = (FIXTURE / "search" / "jd-page.html").as_uri()
        search_json = self.tmp / "search-row.json"
        search_json.write_text(json.dumps(rows), encoding="utf-8")

        handoff = self._run(
            sys.executable, HANDOFF,
            "--json", search_json,
            "--select", "rank 1",
            "--applications-root", self.apps,
            "--research-date", "2026-07-20",
        )
        self.assertEqual(handoff.returncode, 0, handoff.stderr)
        generated = Path(handoff.stdout.splitlines()[0].strip())
        self.assertTrue(generated.name.startswith("nimbus-robotics-"))

        # Test products are unmistakable and remain isolated from real application roots.
        app = generated.with_name("_test_application_" + generated.name)
        generated.rename(app)
        self.assertTrue(app.name.startswith("_test_application_"))
        self.assertEqual(app.parent.resolve(), (self.apps / "6_drafted").resolve())

        seed = FIXTURE / "application"
        shutil.copy2(seed / "source" / "tailored.yaml", app / "source" / "tailored.yaml")
        bundles = list(seed.glob("*_Application_*.txt"))
        self.assertEqual(len(bundles), 1)
        shutil.copy2(bundles[0], app / bundles[0].name)

        rendered = self._run(sys.executable, RENDER, app)
        self.assertEqual(
            rendered.returncode, 0,
            f"stdout:\n{rendered.stdout}\nstderr:\n{rendered.stderr}",
        )
        self.assertIn("OK: predicted 1 page", rendered.stdout)

        manifest = yaml.safe_load(
            (FIXTURE / "expected" / "artifact-manifest.yaml").read_text())
        for relative in manifest["expected_paths"]["generated_outputs"]:
            self.assertTrue(
                (app / relative).is_file(),
                f"{relative}\nstdout:\n{rendered.stdout}\nstderr:\n{rendered.stderr}",
            )

        resume_docx = app / manifest["expected_paths"]["generated_outputs"][0]
        resume_pdf = app / manifest["expected_paths"]["generated_outputs"][1]
        cover_docx = app / manifest["expected_paths"]["generated_outputs"][2]
        cover_pdf = app / manifest["expected_paths"]["generated_outputs"][3]

        reader = PdfReader(resume_pdf)
        self.assertEqual(len(reader.pages), 1)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertLess(text.index("Northwind Systems"), text.index("Blue Lantern Labs"))
        for expected in (
                "Northwind Systems", "Blue Lantern Labs",
                "Regional deployment control plane", "Scheduling data migration"):
            self.assertIn(expected, text)
        normalized_resume = " ".join(
            text.replace("—", "-").replace("–", "-").split())
        for line in (FIXTURE / "expected" / "resume-rendered.txt").read_text().splitlines():
            normalized_line = " ".join(
                line.replace("—", "-").replace("–", "-").split())
            self.assertIn(normalized_line, normalized_resume)

        cover_reader = PdfReader(cover_pdf)
        self.assertEqual(len(cover_reader.pages), 1)
        cover_text = " ".join(
            (page.extract_text() or "") for page in cover_reader.pages)
        normalized_cover = " ".join(cover_text.split())
        for line in (FIXTURE / "expected" / "cover-letter-rendered.txt").read_text().splitlines():
            self.assertIn(" ".join(line.split()), normalized_cover)

        location = self._run(
            sys.executable, STATUS, "--check-locations", "--statuses", "drafted", "--json")
        self.assertEqual(location.returncode, 0, location.stderr)
        location_data = json.loads(location.stdout)
        self.assertEqual(len(location_data["rows"]), 1)
        self.assertTrue(location_data["rows"][0]["match"])

        metadata = self._run(
            sys.executable, STATUS, "--check-metadata", "--statuses", "drafted", "--json")
        self.assertEqual(metadata.returncode, 0, metadata.stderr)
        self.assertTrue(json.loads(metadata.stdout)["rows"][0]["valid"])


if __name__ == "__main__":
    unittest.main()
