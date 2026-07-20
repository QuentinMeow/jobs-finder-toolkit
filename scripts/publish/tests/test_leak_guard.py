"""Fixture-based tests for the publish leak guard + allowlist exporter.

Run with:
    .venv/bin/python -m unittest discover scripts/publish/tests

NOTE ON THIS FILE'S OWN CONTENT: the exporter ships ``scripts/publish/`` (tests
included) and the leak guard scans it. So every "real-looking" PII fixture value
below is assembled from split string fragments (``"415" + "-826-" + "1234"``) —
the literal never appears contiguously in this source, so this test module itself
stays guard-clean while the runtime fixture files it writes still trip the guard.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling modules importable (scripts/publish/).
_PUBLISH_DIR = Path(__file__).resolve().parents[1]
if str(_PUBLISH_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISH_DIR))

import check_public  # noqa: E402
import export_public  # noqa: E402

REPO_ROOT = check_public.REPO_ROOT


def _write_tree(root: Path, files: dict) -> list[str]:
    """Write ``{relpath: str|bytes}`` under ``root``; return the sorted rel paths."""
    for rel, content in files.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            dest.write_text(content, encoding="utf-8")
    return sorted(files)


# PII fixtures, assembled so this source stays guard-clean (see module docstring).
REAL_EMAIL = "dana.harrison" + "@" + "acme-robotics" + ".io"
EXAMPLE_EMAIL = "casey" + "@" + "example" + ".com"
REAL_PHONE = "415" + "-826-" + "1234"
FICTIONAL_PHONE = "212" + "-555-" + "0142"
REAL_HOME = "/Users/" + "danaharrison" + "/notes/resume.md"
PLACEHOLDER_HOME = "/Users/" + "you" + "/notes/resume.md"
REAL_LINKEDIN = "linkedin.com/in/" + "dana-harrison-42"
PLACEHOLDER_LINKEDIN = "linkedin.com/in/" + "jordanrivers"


class StructuralPIITests(unittest.TestCase):
    """Structural PII must be caught with ZERO identity tokens active."""

    def _scan(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            return check_public.scan(root=root, tracked=tracked, tokens=[])

    def _kinds(self, result: dict) -> set:
        return {v["kind"] for v in result["violations"]["structural_pii"]}

    def test_real_domain_email_fails_with_zero_tokens(self):
        result = self._scan({"notes.md": f"reach me at {REAL_EMAIL} anytime"})
        self.assertFalse(result["ok"])
        self.assertIn("email", self._kinds(result))

    def test_example_domain_email_passes(self):
        result = self._scan({"notes.md": f"placeholder {EXAMPLE_EMAIL} in docs"})
        self.assertTrue(result["ok"], result["violations"])

    def test_us_phone_fails(self):
        result = self._scan({"notes.md": f"call {REAL_PHONE} today"})
        self.assertFalse(result["ok"])
        self.assertIn("phone", self._kinds(result))

    def test_fictional_555_phone_passes(self):
        result = self._scan({"notes.md": f"call {FICTIONAL_PHONE} (fake)"})
        self.assertTrue(result["ok"], result["violations"])

    def test_home_path_fails(self):
        result = self._scan({"notes.md": f"see {REAL_HOME}"})
        self.assertFalse(result["ok"])
        self.assertIn("home_path", self._kinds(result))

    def test_placeholder_home_path_passes(self):
        result = self._scan({"notes.md": f"see {PLACEHOLDER_HOME}"})
        self.assertTrue(result["ok"], result["violations"])

    def test_linkedin_handle_fails(self):
        result = self._scan({"notes.md": f"profile {REAL_LINKEDIN}"})
        self.assertFalse(result["ok"])
        self.assertIn("linkedin", self._kinds(result))

    def test_placeholder_linkedin_passes(self):
        result = self._scan({"notes.md": f"profile {PLACEHOLDER_LINKEDIN}"})
        self.assertTrue(result["ok"], result["violations"])


class PathDenylistTests(unittest.TestCase):
    """Private product trees / stray binaries must fail on path alone."""

    def _scan(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            return check_public.scan(root=root, tracked=tracked, tokens=[])

    def _reasons(self, result: dict) -> list:
        return [v["reason"] for v in result["violations"]["path_denylist"]]

    def test_tracked_meta_yaml_fails(self):
        result = self._scan({"meta.yaml": "role: x\n"})
        self.assertFalse(result["ok"])
        self.assertTrue(any("meta.yaml" in r for r in self._reasons(result)))

    def test_meta_yaml_under_examples_passes(self):
        result = self._scan({"examples/app/meta.yaml": "role: x\n"})
        self.assertTrue(result["ok"], result["violations"])

    def test_applications_tree_fails(self):
        result = self._scan({"applications/foo/notes.md": "hi\n"})
        self.assertFalse(result["ok"])
        self.assertTrue(any("applications/" in r for r in self._reasons(result)))

    def test_interviews_tree_fails(self):
        result = self._scan({"interviews/foo.md": "hi\n"})
        self.assertFalse(result["ok"])

    def test_agents_inputs_tree_fails(self):
        result = self._scan({".agents/inputs/master-resume/x.md": "hi\n"})
        self.assertFalse(result["ok"])

    def test_docx_outside_examples_fails(self):
        # A minimal non-zip .docx: also exercises the fail-closed path, but the
        # path denylist alone is enough to fail it.
        result = self._scan({"reports/resume.docx": b"not a real docx"})
        self.assertFalse(result["ok"])
        self.assertTrue(any("binary-outside-examples" in r or "docx" in r
                            for r in self._reasons(result)))

    def test_templates_nonexample_fails(self):
        result = self._scan({"templates/resume/reference.docx": b"x"})
        self.assertFalse(result["ok"])

    def test_templates_example_named_passes_path_check(self):
        # A real (zip) example docx would pass; here we only assert the PATH check
        # does not flag an example-named template.
        reasons = check_public.find_path_denylist_violations(
            ["templates/resume/reference.example.docx"])
        self.assertEqual(reasons, [])


class FailClosedBinaryTests(unittest.TestCase):
    def _scan(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            return check_public.scan(root=root, tracked=tracked, tokens=[])

    def test_unscannable_image_fails(self):
        result = self._scan({"docs/screenshot.png": b"\x89PNG\r\n\x1a\n not-real"})
        self.assertFalse(result["ok"])
        self.assertIn("docs/screenshot.png", result["unscanned_binaries"])

    def test_example_binary_is_exempt(self):
        # An unextractable image under examples/ is intentionally shipped.
        result = self._scan({"examples/img/shot.png": b"\x89PNG\r\n not-real"})
        self.assertTrue(result["ok"], result["violations"])


class TokenTests(unittest.TestCase):
    def test_planted_token_denied_by_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"a.txt": "hello SuperSecretSlug world\n"})
            result = check_public.scan(root=root, tracked=tracked,
                                       tokens=["SuperSecretSlug"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])

    def test_planted_token_denied_by_exporter_denylist(self):
        # A file whose CONTENT trips a token must be excluded by the exporter.
        reason = export_public._deny_reason("config.example.yaml", ["Rivers"])
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith("token"))

    def test_clean_file_not_denied_by_exporter(self):
        self.assertIsNone(
            export_public._deny_reason("config.example.yaml", ["ZZZ-absent-token"]))


class PrivateSkillTests(unittest.TestCase):
    def test_private_skill_with_tracked_files_flags(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = {
                ".agents/skills/secretskill/SKILL.md":
                    "---\nname: secretskill\nvisibility: private\n---\nbody\n",
                ".agents/skills/secretskill/notes.md": "private\n",
            }
            tracked = _write_tree(root, files)
            result = check_public.scan(root=root, tracked=tracked, tokens=[])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["private_skill_tracked"])

    def test_public_skill_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = {
                ".agents/skills/openskill/SKILL.md":
                    "---\nname: openskill\nvisibility: public\n---\nbody\n",
                ".agents/skills/openskill/notes.md": "public\n",
            }
            tracked = _write_tree(root, files)
            result = check_public.scan(root=root, tracked=tracked, tokens=[])
        self.assertTrue(result["ok"], result["violations"])


class ReferencesPrivateTests(unittest.TestCase):
    def test_references_private_flagged_by_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = {".agents/skills/job-search/references_private/notes.md": "x\n"}
            tracked = _write_tree(root, files)
            result = check_public.scan(root=root, tracked=tracked, tokens=[])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["references_private"])

    def test_references_private_pruned_by_exporter(self):
        self.assertEqual(
            export_public._deny_reason("x/references_private/y.md", []),
            "references_private")

    def test_env_tokens_ignore_comment_lines(self):
        # The env var may be populated verbatim from private/leak_tokens.txt
        # (e.g. a CI secret), so '#' comment lines must not become tokens.
        os.environ[check_public.TOKENS_ENV_VAR] = (
            "# employer, school, extra handles\nRealToken\n#\n , SecondToken,\n")
        try:
            toks = check_public.personal_tokens()
        finally:
            os.environ.pop(check_public.TOKENS_ENV_VAR, None)
        self.assertIn("RealToken", toks)
        self.assertIn("SecondToken", toks)
        self.assertNotIn("school", toks)
        self.assertNotIn("extra handles", toks)
        self.assertFalse([t for t in toks if t.startswith("#")])


class ExporterEndToEndTests(unittest.TestCase):
    """Run the real exporter, then assert the export is clean end-to-end."""

    def setUp(self):
        # Deterministic: no forwarded tokens, so the guard leans on structural /
        # path checks — exactly the "clean example tree stays green" path.
        os.environ.pop(check_public.TOKENS_ENV_VAR, None)

    def test_export_passes_guard_and_excludes_private_trees(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            rc = export_public.export(dest, git_init=False, force=False)
            self.assertEqual(rc, 0, "exporter+guard must pass on the clean example tree")

            copied = [p.relative_to(dest).as_posix()
                      for p in dest.rglob("*")
                      if p.is_file() and ".git/" not in p.relative_to(dest).as_posix()]

            # No private product trees leaked into the manifest.
            for bad in ("applications/", "interviews/", "templates/",
                        ".agents/inputs/", ".agents/skills/coding-interview/"):
                offenders = [c for c in copied if c.startswith(bad)]
                self.assertEqual(offenders, [], f"{bad} leaked: {offenders}")

            # references_private is pruned; the private skill is never copied.
            self.assertFalse([c for c in copied if "references_private" in c])
            self.assertFalse((dest / ".agents/skills/coding-interview").exists())

            # meta.yaml only under examples/; no stray docx/pdf outside examples/.
            for c in copied:
                if Path(c).name == "meta.yaml":
                    self.assertTrue(c.startswith("examples/"), c)
                if Path(c).suffix.lower() in (".docx", ".pdf"):
                    self.assertTrue(c.startswith("examples/"), c)

            # The public .gitignore anchors the overlay mount + private trees.
            gitignore = (dest / ".gitignore").read_text()
            for needle in ("private/", "/applications/",
                           "/interviews/", "/.agents/skills/coding-interview/"):
                self.assertIn(needle, gitignore)

            # And a fresh directory-tree scan of the export is clean, too.
            scan_result = check_public.scan(root=dest, tokens=[])
            self.assertTrue(scan_result["ok"], scan_result["violations"])


if __name__ == "__main__":
    unittest.main()
