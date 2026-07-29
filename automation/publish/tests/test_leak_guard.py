"""Fixture-based tests for the publish leak guard + allowlist exporter.

Run with:
    .venv/bin/python -m unittest discover automation/publish/tests

NOTE ON THIS FILE'S OWN CONTENT: the exporter ships ``automation/publish/`` (tests
included) and the leak guard scans it. So every "real-looking" PII fixture value
below is assembled from split string fragments (``"415" + "-826-" + "1234"``) —
the literal never appears contiguously in this source, so this test module itself
stays guard-clean while the runtime fixture files it writes still trip the guard.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make the sibling modules importable (automation/publish/).
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

    def test_templates_markdown_schema_passes_path_check(self):
        # Root templates/ carries the tracked process-file schemas (markdown).
        reasons = check_public.find_path_denylist_violations(
            ["templates/queue/decision.md", "templates/README.md"])
        self.assertEqual(reasons, [])

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
                "skills/secretskill/SKILL.md":
                    "---\nname: secretskill\nvisibility: private\n---\nbody\n",
                "skills/secretskill/notes.md": "private\n",
            }
            tracked = _write_tree(root, files)
            result = check_public.scan(root=root, tracked=tracked, tokens=[])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["private_skill_tracked"])

    def test_public_skill_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = {
                "skills/openskill/SKILL.md":
                    "---\nname: openskill\nvisibility: public\n---\nbody\n",
                "skills/openskill/notes.md": "public\n",
            }
            tracked = _write_tree(root, files)
            result = check_public.scan(root=root, tracked=tracked, tokens=[])
        self.assertTrue(result["ok"], result["violations"])


class ReferencesPrivateTests(unittest.TestCase):
    def test_references_private_flagged_by_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = {"skills/job-search/references_private/notes.md": "x\n"}
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


class _ExampleConfigStub:
    """Stands in for automation/shared/config.py resolving to the EXAMPLE config.

    That is the state a fresh clone / a wrong cwd / a missing overlay lands in, and
    the one where ``_identity_tokens`` deliberately returns nothing.
    """

    EXAMPLE_CONFIG = Path("/nonexistent-checkout/config.example.yaml")
    CONFIG_FILENAME = "config.yaml"
    ENV_VAR = "JOBHUNT_CONFIG"

    @staticmethod
    def config_path() -> Path:
        return Path("/nonexistent-checkout/config.example.yaml")

    @staticmethod
    def candidate_name() -> str:
        return "Jordan Rivers"

    @staticmethod
    def contact_line() -> str:
        return "jordan.rivers@example.com"


class ArmingTests(unittest.TestCase):
    """The guard must refuse to run when it cannot see the real identity.

    Gating on the UNION of token sources is the bug: private/leak_tokens.txt keeps
    the union non-empty (employers, school) while the name/email/handles — the
    things a leak actually looks like — are absent.
    """

    def setUp(self):
        self._saved_env = os.environ.pop(check_public.TOKENS_ENV_VAR, None)

    def tearDown(self):
        os.environ.pop(check_public.TOKENS_ENV_VAR, None)
        if self._saved_env is not None:
            os.environ[check_public.TOKENS_ENV_VAR] = self._saved_env

    def test_example_config_yields_zero_identity_tokens(self):
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=_ExampleConfigStub):
            self.assertEqual(check_public.identity_tokens(), set())

    def test_supplementary_tokens_alone_never_arm_the_guard(self):
        # The exact fail-open shape: a non-empty leak-token file, zero identity.
        with tempfile.TemporaryDirectory() as td:
            leak_file = Path(td) / "leak_tokens.txt"
            leak_file.write_text("# comment\nAcmeRobotics\nStateUniversity\n",
                                 encoding="utf-8")
            with mock.patch.object(check_public, "LEAK_TOKENS_FILES", [leak_file]), \
                 mock.patch.object(check_public, "_load_shared_config",
                                   return_value=_ExampleConfigStub):
                self.assertEqual(check_public.identity_tokens(), set())
                self.assertEqual(check_public.supplementary_tokens(),
                                 {"AcmeRobotics", "StateUniversity"})
                # The union is non-empty — which is why the union cannot be the gate.
                self.assertTrue(check_public.personal_tokens())

    def test_env_var_arms_the_guard(self):
        os.environ[check_public.TOKENS_ENV_VAR] = "RealName,realname@corp.example"
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=_ExampleConfigStub):
            self.assertIn("RealName", check_public.identity_tokens())

    def test_unarmed_report_names_the_config_it_looked_for(self):
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=_ExampleConfigStub):
            text = "\n".join(check_public.unarmed_report())
        self.assertIn("config.yaml", text)
        self.assertIn("JOBHUNT_CONFIG", text)
        self.assertIn("config.example.yaml", text)
        self.assertIn(check_public.TOKENS_ENV_VAR, text)


class ArmingCLITests(unittest.TestCase):
    """End-to-end: the CLI exits non-zero when config discovery finds no identity."""

    def _run(self, extra_args: list[str]) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop(check_public.TOKENS_ENV_VAR, None)
        # Force discovery onto the tracked example config: that is the "found
        # nothing real" state, reached in a fresh clone or a fork CI run.
        env["JOBHUNT_CONFIG"] = str(REPO_ROOT / "config.example.yaml")
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "automation/publish/check_public.py"),
             *extra_args],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env,
        )

    def test_unarmed_run_exits_nonzero(self):
        proc = self._run([])
        self.assertEqual(proc.returncode, check_public.EXIT_UNARMED, proc.stdout)
        self.assertIn("UNARMED", proc.stdout)
        self.assertNotIn("OK: no public-repo leaks detected", proc.stdout)

    def test_allow_unarmed_still_passes_on_the_clean_tree(self):
        proc = self._run(["--allow-unarmed"])
        self.assertEqual(proc.returncode, check_public.EXIT_OK,
                         proc.stdout + proc.stderr)
        self.assertIn("UNARMED", proc.stderr)
        self.assertIn("Safe to publish", proc.stdout)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )


class StagedIndexTests(unittest.TestCase):
    """``--staged`` scans the INDEX, so unstaged edits neither hide nor cause a fail."""

    def _repo(self, td: str) -> Path:
        repo = Path(td) / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        return repo

    def test_staged_token_is_caught(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "notes.md").write_text("hello SuperSecretSlug\n", encoding="utf-8")
            _git(repo, "add", "notes.md")
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])

    def test_unstaged_edit_is_not_scanned(self):
        # The worktree carries the token; the INDEX does not. Committing what is
        # staged is safe, so the guard must pass.
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "notes.md").write_text("clean\n", encoding="utf-8")
            _git(repo, "add", "notes.md")
            (repo / "notes.md").write_text("hello SuperSecretSlug\n", encoding="utf-8")
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertTrue(result["ok"], result["violations"])

    def test_committed_file_edited_only_in_worktree_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "notes.md").write_text("clean\n", encoding="utf-8")
            _git(repo, "add", "notes.md")
            _git(repo, "commit", "-qm", "init")
            (repo / "notes.md").write_text("hello SuperSecretSlug\n", encoding="utf-8")
            (repo / "other.md").write_text("also clean\n", encoding="utf-8")
            _git(repo, "add", "other.md")
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(result["tracked_file_count"], 1)

    def test_staged_private_overlay_path_is_caught(self):
        # ``git add -f private/`` (trailing slash) stages with exit 0 and no output.
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / ".gitignore").write_text("private/\n", encoding="utf-8")
            (repo / "private").mkdir()
            (repo / "private" / "profile.md").write_text("real data\n", encoding="utf-8")
            _git(repo, "add", ".gitignore")
            _git(repo, "add", "-f", "private/")
            result = check_public.scan_staged(repo, tokens=[])
        self.assertFalse(result["ok"])
        self.assertEqual([v["path"] for v in result["violations"]["personal_overlay"]],
                         ["private/profile.md"])

    def test_staged_private_product_tree_is_caught_on_path_alone(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "applications").mkdir()
            (repo / "applications" / "notes.md").write_text("x\n", encoding="utf-8")
            _git(repo, "add", "applications/notes.md")
            result = check_public.scan_staged(repo, tokens=[])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["path_denylist"])

    def test_staged_deletion_is_not_a_finding(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "notes.md").write_text("clean\n", encoding="utf-8")
            _git(repo, "add", "notes.md")
            _git(repo, "commit", "-qm", "init")
            _git(repo, "rm", "-q", "notes.md")
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(result["tracked_file_count"], 0)

    def test_empty_index_scan_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertTrue(result["ok"], result["violations"])

    def test_staged_symlink_target_is_scanned_as_text(self):
        # An overlay symlink's blob IS its target path; that path names private data.
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            os.symlink("../private/skills/coding-interview", repo / "link")
            _git(repo, "add", "link")
            result = check_public.scan_staged(repo, tokens=["coding-interview"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])


class RealTreeStructuralTests(unittest.TestCase):
    """Scan the REAL tracked tree, not a synthetic fixture built from the same literals.

    The synthetic fixtures in the classes above pass whether or not the detector
    still matches the tree that actually ships, so a rename of a private root can
    leave them green with the detector dead. These assert against ``git ls-files``.
    """

    @classmethod
    def setUpClass(cls):
        if not (REPO_ROOT / ".git").exists():
            raise unittest.SkipTest("not a git checkout")
        cls.tracked = check_public.git_tracked_files()

    def test_tracked_tree_has_no_structural_violations(self):
        self.assertEqual(check_public.find_personal_overlay_violations(self.tracked), [])
        self.assertEqual(check_public.find_references_private_violations(self.tracked), [])
        self.assertEqual(check_public.find_path_denylist_violations(self.tracked), [])
        self.assertEqual(
            check_public.find_private_skill_violations(REPO_ROOT, self.tracked), [])

    def test_every_root_anchored_gitignore_product_rule_is_denied(self):
        """A private root that is git-ignored must ALSO be path-denied.

        ``.gitignore`` is the other place a private root at the public root is
        named. If a rename adds ``/store/`` there but not to ``_DENY_TREES``, the
        only thing standing between that tree and a publish is a glob that
        ``git add -f`` overrides — this test fails instead.
        """
        # Root-anchored ignore rules that are scratch/build output rather than a
        # private PRODUCT tree. Add here (with a reason) only after checking the
        # tree is genuinely not personal data.
        NON_PRODUCT_ROOTS: set[str] = set()
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        rules = [ln.strip() for ln in text.splitlines()
                 if ln.strip().startswith("/") and ln.strip().endswith("/")]
        self.assertTrue(rules, "expected root-anchored private-product rules in .gitignore")
        for rule in rules:
            rel = rule.lstrip("/")
            if rel in NON_PRODUCT_ROOTS:
                continue
            probe = rel + "probe.md"
            denied = bool(check_public.find_path_denylist_violations([probe])
                          or check_public.find_personal_overlay_violations([probe]))
            self.assertTrue(denied, f".gitignore rule '{rule}' is not covered by "
                                    "_DENY_TREES / PERSONAL_OVERLAY_PREFIXES")

    def test_deny_trees_are_append_only(self):
        """Historical private-root names are never retired, only added to.

        A rename (``data/``->``store/``, ``interviews/``->``me/``+``companies/``,
        ``job-search-profiles/``->``market/searches/``) must ADD the new name and
        KEEP the old one: a stale checkout or an old branch can still put the
        historical tree at the public root.
        """
        required = {
            "applications/", "interviews/", ".agents/inputs/",
            "skills/coding-interview/", "skills/coding-interview-cleanup/",
            "data/", "job-search-profiles/",
            "store/", "me/", "companies/", "market/",
        }
        labels = {label for _, label in check_public._DENY_TREES}
        self.assertEqual(required - labels, set(),
                         "a private root name was REMOVED from _DENY_TREES")
        for label in sorted(required):
            probe = label + "probe.md"
            self.assertTrue(check_public.find_path_denylist_violations([probe]),
                            f"{label} is listed but does not match {probe}")

    def test_public_roots_are_not_denied(self):
        """The denylist must not shadow a legitimate public root."""
        for rel in sorted({p.split("/")[0] for p in self.tracked if "/" in p}):
            probe = f"{rel}/probe.md"
            self.assertEqual(check_public.find_path_denylist_violations([probe]), [],
                             f"public root '{rel}/' is path-denied")


class ExporterEndToEndTests(unittest.TestCase):
    """Run the real exporter, then assert the export is clean end-to-end."""

    # A token that ARMS the exporter's own gate without naming anybody: it
    # matches no path and no file content, so the guard still leans on structural
    # / path checks — the same "clean example tree stays green" path this test
    # always exercised.
    PROBE_TOKEN = "zz-exporter-e2e-probe-token"

    def setUp(self):
        # Deterministic AND armed. ``export()`` now refuses to run with zero
        # identity tokens (an unarmed final guard would call any tree safe to
        # publish), so simply popping the env var passes only in a maintainer
        # checkout that has a real config.yaml. CI has neither a config.yaml nor
        # the token secret, so popping it turned this repo's own CI red.
        # Forwarding a token that names nobody keeps the assertion identical in
        # every checkout.
        os.environ[check_public.TOKENS_ENV_VAR] = self.PROBE_TOKEN
        self.addCleanup(lambda: os.environ.pop(check_public.TOKENS_ENV_VAR, None))

    def test_export_passes_guard_and_excludes_private_trees(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            rc = export_public.export(dest, git_init=False, force=False)
            self.assertEqual(rc, 0, "exporter+guard must pass on the clean example tree")

            copied = [p.relative_to(dest).as_posix()
                      for p in dest.rglob("*")
                      if p.is_file() and ".git/" not in p.relative_to(dest).as_posix()]

            # No private product trees leaked into the manifest.
            for bad in ("applications/", "interviews/",
                        ".agents/inputs/", "skills/coding-interview/",
                        "skills/coding-interview-cleanup/"):
                offenders = [c for c in copied if c.startswith(bad)]
                self.assertEqual(offenders, [], f"{bad} leaked: {offenders}")

            # references_private is pruned; the private skill is never copied.
            self.assertFalse([c for c in copied if "references_private" in c])
            self.assertFalse((dest / "skills/coding-interview").exists())
            self.assertFalse((dest / "skills/coding-interview-cleanup").exists())

            # meta.yaml only under examples/; no stray docx/pdf outside examples/.
            for c in copied:
                if Path(c).name == "meta.yaml":
                    self.assertTrue(c.startswith("examples/"), c)
                if Path(c).suffix.lower() in (".docx", ".pdf"):
                    self.assertTrue(c.startswith("examples/"), c)

            # The public .gitignore anchors the overlay mount + private trees.
            gitignore = (dest / ".gitignore").read_text()
            for needle in ("private/", "/applications/",
                           "/interviews/", "/skills/coding-interview/",
                           "/skills/coding-interview-cleanup/"):
                self.assertIn(needle, gitignore)

            # And a fresh directory-tree scan of the export is clean, too.
            scan_result = check_public.scan(root=dest, tokens=[])
            self.assertTrue(scan_result["ok"], scan_result["violations"])


if __name__ == "__main__":
    unittest.main()
