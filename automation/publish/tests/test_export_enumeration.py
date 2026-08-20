"""Tests for WHAT the allowlist exporter enumerates, and what the export owes CI.

Two regressions are pinned here:

  * ``_copy_tree`` used ``os.walk``, so any UNTRACKED file sitting inside an
    allowlisted directory was exported — scratch files, scraped JDs, and the
    owner's git-ignored personal job-search profile symlinks. The exporter now
    enumerates through ``git ls-files``, so only TRACKED files can ship.
  * An allowlisted path that resolved to nothing was skipped in SILENCE, so a
    renamed or misspelled entry shipped zero files and said so nowhere. It is now
    a warning, and a refusal under ``--strict`` (raised BEFORE ``--force`` touches
    the destination).

The third block walks every ``.github/workflows/*.yml`` file for the paths CI
invokes and asserts every one of them exists in a FRESH export — the exported
repo's CI used to be red before it started because a workflow invoked a path the
export did not contain.

Run with:
    .venv/bin/python -m unittest discover automation/publish/tests
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling modules importable (automation/publish/).
_PUBLISH_DIR = Path(__file__).resolve().parents[1]
if str(_PUBLISH_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISH_DIR))

import check_public  # noqa: E402
import export_public  # noqa: E402
import sync_skill_manifests as ssm  # noqa: E402

REPO_ROOT = check_public.REPO_ROOT
CI_WORKFLOWS = tuple(sorted((REPO_ROOT / ".github/workflows").glob("*.yml")))

# A token that arms the guard without naming anybody. ``export()`` refuses to run
# unarmed (an unarmed final guard would report any tree "safe to publish"), and
# these tests must behave identically in a maintainer checkout and in a
# config-less CI checkout.
PROBE_TOKEN = "zz-export-enumeration-probe-token"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


class GitEnumerationTests(unittest.TestCase):
    """Only TRACKED files under an allowlisted directory are exported."""

    def _mini_repo(self, root: Path) -> None:
        (root / "public_tree").mkdir()
        (root / "public_tree/tracked.md").write_text("tracked\n", encoding="utf-8")
        (root / "public_tree/untracked.md").write_text("untracked\n", encoding="utf-8")
        (root / "public_tree/nested").mkdir()
        (root / "public_tree/nested/tracked.txt").write_text("nested\n", encoding="utf-8")
        _git(root, "init")
        _git(root, "add", "public_tree/tracked.md", "public_tree/nested/tracked.txt")

    def _patch_root(self, root: Path) -> None:
        original = export_public.REPO_ROOT
        export_public.REPO_ROOT = root
        self.addCleanup(lambda: setattr(export_public, "REPO_ROOT", original))

    def test_untracked_file_in_an_allowlisted_dir_is_not_exported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            root.mkdir()
            self._mini_repo(root)
            self._patch_root(root)

            dest = Path(td) / "dest"
            copied: list[str] = []
            skipped: list[tuple[str, str]] = []
            tracked = export_public.tracked_files()
            export_public._copy_tree("public_tree", dest, copied, skipped, [], tracked)

            self.assertEqual(sorted(copied),
                             ["public_tree/nested/tracked.txt", "public_tree/tracked.md"])
            self.assertFalse((dest / "public_tree/untracked.md").exists())

            # The regression this replaces: os.walk DID see the untracked file.
            walked = {str(Path(dirpath, f).relative_to(root))
                      for dirpath, _dirs, files in os.walk(root / "public_tree")
                      for f in files}
            self.assertIn("public_tree/untracked.md", walked)

    def test_tracked_but_deleted_worktree_file_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"
            root.mkdir()
            self._mini_repo(root)
            (root / "public_tree/tracked.md").unlink()
            self._patch_root(root)

            dest = Path(td) / "dest"
            copied: list[str] = []
            skipped: list[tuple[str, str]] = []
            export_public._copy_tree("public_tree", dest, copied, skipped, [],
                                     export_public.tracked_files())
            self.assertEqual(copied, ["public_tree/nested/tracked.txt"])
            self.assertEqual(skipped, [("public_tree/tracked.md",
                                        "tracked but missing from the worktree")])

    def test_live_export_carries_no_untracked_file(self):
        """Every file in the real export is a tracked path (or a generated one)."""
        tracked = set(export_public.tracked_files())
        export = _shared_export()
        # The two files the exporter WRITES rather than copies. The marker records
        # that this directory is a disposable export target (so a later --force may
        # replace it); it is excluded from the export's git history, which is what
        # test_export_destination.py asserts.
        generated = {".gitignore", export_public.EXPORT_MARKER_NAME}
        offenders = []
        for path in export.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(export).as_posix()
            if rel.startswith(".git/") or rel in generated:
                continue
            if rel not in tracked:
                offenders.append(rel)
        self.assertEqual(offenders, [], f"untracked paths in the export: {offenders}")

    def test_personal_profile_allowlist_still_applies(self):
        """PROFILES_DIR filenames are personal tokens; the denylist must survive.

        Git enumeration already excludes them (they are untracked overlay
        symlinks), but the per-file rule is defense in depth and must not have
        been dropped along with ``os.walk``.
        """
        for name in ("someone-default.yaml", "someone.md"):
            rel = f"{export_public.PROFILES_DIR}/{name}"
            self.assertEqual(export_public._deny_reason(rel, []), "personal-profile", rel)
        for name in sorted(export_public.PUBLIC_PROFILE_FILES):
            rel = f"{export_public.PROFILES_DIR}/{name}"
            self.assertIsNone(export_public._deny_reason(rel, []), rel)


class PreflightTests(unittest.TestCase):
    """A missing allowlisted path warns, and refuses under --strict."""

    def _patch_dirs(self, extra: list[str]) -> None:
        original = list(export_public.ALLOWLIST_DIRS)
        export_public.ALLOWLIST_DIRS = original + extra
        self.addCleanup(lambda: setattr(export_public, "ALLOWLIST_DIRS", original))

    def test_clean_allowlist_produces_no_warnings(self):
        self.assertEqual(export_public.preflight(export_public.tracked_files()), [])

    def test_missing_directory_is_reported(self):
        self._patch_dirs(["automation/renamed-away"])
        warnings = export_public.preflight(export_public.tracked_files())
        self.assertEqual(warnings,
                         ["allowlisted directory does not exist: automation/renamed-away"])

    def test_untracked_directory_is_reported(self):
        """A directory that exists but holds nothing tracked ships nothing."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "empty_tree").mkdir()
            _git(root, "init")
            original = export_public.REPO_ROOT
            export_public.REPO_ROOT = root
            self.addCleanup(lambda: setattr(export_public, "REPO_ROOT", original))
            original_dirs = list(export_public.ALLOWLIST_DIRS)
            original_files = list(export_public.ALLOWLIST_FILES)
            export_public.ALLOWLIST_DIRS = ["empty_tree"]
            export_public.ALLOWLIST_FILES = []
            self.addCleanup(lambda: setattr(export_public, "ALLOWLIST_DIRS", original_dirs))
            self.addCleanup(lambda: setattr(export_public, "ALLOWLIST_FILES", original_files))

            warnings = export_public.preflight(export_public.tracked_files())
            self.assertEqual(warnings,
                             ["allowlisted directory holds no tracked files: empty_tree"])

    def test_missing_file_is_reported(self):
        original = list(export_public.ALLOWLIST_FILES)
        export_public.ALLOWLIST_FILES = original + ["NOT_A_REAL_FILE.md"]
        self.addCleanup(lambda: setattr(export_public, "ALLOWLIST_FILES", original))
        warnings = export_public.preflight(export_public.tracked_files())
        self.assertEqual(
            warnings,
            ["allowlisted file contributes nothing: NOT_A_REAL_FILE.md (does not exist)"])

    def test_strict_refuses_and_never_touches_the_destination(self):
        self._patch_dirs(["automation/renamed-away"])
        os.environ[check_public.TOKENS_ENV_VAR] = PROBE_TOKEN
        self.addCleanup(lambda: os.environ.pop(check_public.TOKENS_ENV_VAR, None))
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            dest.mkdir()
            (dest / "sentinel.txt").write_text("must survive a strict refusal\n",
                                               encoding="utf-8")
            rc = export_public.export(dest, git_init=False, force=True, strict=True)
            self.assertEqual(rc, 2)
            # --force did NOT get as far as rmtree'ing the destination.
            self.assertTrue((dest / "sentinel.txt").is_file())

    def test_non_strict_warns_but_still_exports(self):
        self._patch_dirs(["automation/renamed-away"])
        os.environ[check_public.TOKENS_ENV_VAR] = PROBE_TOKEN
        self.addCleanup(lambda: os.environ.pop(check_public.TOKENS_ENV_VAR, None))
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            rc = export_public.export(dest, git_init=False, force=False)
            self.assertEqual(rc, 0)
            self.assertTrue((dest / "AGENTS.md").is_file())


# ── one shared export for the read-only assertions below ─────────────────────

_EXPORT_DIR: tempfile.TemporaryDirectory | None = None
_EXPORT_PATH: Path | None = None


def _shared_export() -> Path:
    """Run the real exporter ONCE per process; return the exported tree."""
    global _EXPORT_DIR, _EXPORT_PATH
    if _EXPORT_PATH is not None:
        return _EXPORT_PATH
    _EXPORT_DIR = tempfile.TemporaryDirectory(prefix="export-ci-paths-")
    dest = Path(_EXPORT_DIR.name) / "export"
    previous = os.environ.get(check_public.TOKENS_ENV_VAR)
    os.environ[check_public.TOKENS_ENV_VAR] = PROBE_TOKEN
    try:
        rc = export_public.export(dest, git_init=False, force=False, strict=True)
    finally:
        if previous is None:
            os.environ.pop(check_public.TOKENS_ENV_VAR, None)
        else:
            os.environ[check_public.TOKENS_ENV_VAR] = previous
    if rc != 0:
        raise AssertionError(f"export failed (exit {rc}) — see the manifest above")
    _EXPORT_PATH = dest
    return dest


def tearDownModule() -> None:
    global _EXPORT_DIR, _EXPORT_PATH
    if _EXPORT_DIR is not None:
        _EXPORT_DIR.cleanup()
    _EXPORT_DIR = None
    _EXPORT_PATH = None


# ── workflow path extraction ─────────────────────────────────────────────────

_RUN_RE = re.compile(r"^(\s*)run:\s*(.*)$")


def _run_blocks(text: str) -> list[str]:
    """Every ``run:`` block body in a GitHub workflow (block or inline scalar)."""
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        m = _RUN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        indent, inline = m.group(1), m.group(2).strip()
        body: list[str] = []
        if inline and inline not in ("|", "|-", "|+", ">", ">-", ">+"):
            body.append(inline)
        i += 1
        while i < len(lines):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) <= len(indent):
                break
            body.append(line)
            i += 1
        blocks.append("\n".join(body))
    return blocks


def _tokens(block: str) -> list[str]:
    block = block.replace("\\\n", " ")
    try:
        return shlex.split(block, comments=False)
    except ValueError:
        return block.split()


def _candidate_paths(text: str, roots: set[str]) -> list[str]:
    """Repo paths a workflow's ``run:`` blocks reference.

    A token counts only when its FIRST path segment is a real top-level entry of
    the source repo — that keeps ``sudo``/``apt-get``/``libreoffice-writer`` and
    prose inside an ``echo`` out without an ad-hoc blocklist.
    """
    found: list[str] = []
    for block in _run_blocks(text):
        for token in _tokens(block):
            if "=" in token and not token.startswith("-"):
                token = token.rsplit("=", 1)[1]
            token = token.strip("\"'").rstrip("/")
            if token.startswith("$PWD/"):
                token = token[len("$PWD/"):]
            if not token or token.startswith(("-", "$", "/")) or "::" in token or "@" in token:
                continue
            if token.split("/", 1)[0] not in roots:
                continue
            if token not in found:
                found.append(token)
    return found


def _invocation_targets(text: str) -> list[str]:
    """The high-precision set: ``python <script.py>`` and ``discover [-s|-t] <dir>``."""
    targets: list[str] = []
    for block in _run_blocks(text):
        tokens = _tokens(block)
        for idx, token in enumerate(tokens):
            token = token.strip("\"'").rstrip("/")
            if token.endswith(".py") and "/" in token:
                targets.append(token)
            elif token == "discover":
                rest = [t.strip("\"'").rstrip("/") for t in tokens[idx + 1:]]
                explicit = False
                while rest and rest[0] in ("-s", "-t", "-p"):
                    if len(rest) > 1:
                        if rest[0] != "-p":
                            targets.append(rest[1])
                        explicit = True
                    rest = rest[2:]
                # ``discover <dir>`` only when no -s/-t named the start directory;
                # otherwise the next token is the NEXT command in the block.
                if not explicit and rest and not rest[0].startswith("-"):
                    targets.append(rest[0])
    return sorted(set(targets))


class CIPathsExistInExportTests(unittest.TestCase):
    """Every path the exported repo's CI invokes must exist in the export."""

    @classmethod
    def setUpClass(cls):
        cls.export = _shared_export()
        cls.text = "\n".join(path.read_text(encoding="utf-8")
                             for path in CI_WORKFLOWS)
        cls.roots = {p.name for p in REPO_ROOT.iterdir()}
        cls.candidates = _candidate_paths(cls.text, cls.roots)
        cls.targets = _invocation_targets(cls.text)

    def test_the_parser_actually_found_something(self):
        """A parser that extracts nothing would make every assertion vacuous."""
        self.assertGreaterEqual(len(self.candidates), 5, self.candidates)
        self.assertGreaterEqual(len(self.targets), 5, self.targets)
        self.assertIn("automation/ci/classify_changes.py", self.targets)
        self.assertIn("automation/gates/run_gates.py", self.targets)
        self.assertIn("skills/github-workflow/scripts/check_pr_body.py", self.targets)

    def test_every_invocation_target_exists_in_the_source(self):
        missing = [t for t in self.targets if not list(REPO_ROOT.glob(t))]
        self.assertEqual(missing, [],
                         f"GitHub workflows invoke paths that do not exist: {missing}")

    def test_every_ci_path_exists_in_the_export(self):
        missing = [c for c in self.candidates if not list(self.export.glob(c))]
        self.assertEqual(
            missing, [],
            "GitHub workflows invoke paths the export does not ship (add them to "
            f"ALLOWLIST_DIRS/ALLOWLIST_FILES): {missing}")

    def test_requirements_and_example_config_ship(self):
        self.assertTrue((self.export / "requirements.txt").is_file())
        self.assertTrue((self.export / "config.example.yaml").is_file())

    def test_workspace_dashboard_and_its_tests_ship(self):
        self.assertTrue((self.export / "automation/workspace/status.py").is_file())
        self.assertTrue(
            (self.export / "automation/workspace/tests/test_status.py").is_file()
        )

    def test_store_validator_runs_against_the_exported_example_store(self):
        proc = subprocess.run(
            [sys.executable, "automation/store/validate_store.py", "examples/store",
             "--check-fixture-size"],
            cwd=self.export, capture_output=True, text=True,
            env={**os.environ,
                 "PYTHONDONTWRITEBYTECODE": "1",  # leave the export tree pristine
                 "JOBHUNT_CONFIG": str(self.export / "config.example.yaml")},
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_reconciler_passes_inside_the_export(self):
        proc = subprocess.run(
            [sys.executable, "automation/reconcile/reconcile.py", "--check"],
            cwd=self.export, capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_verify_links_passes_inside_the_export(self):
        """CI step 2b-ii, run where it actually has to hold.

        ``ci.yml`` says both process-layer steps are written without
        ``--require-roots`` so the published mirror stays green. That was true of the
        reconciler and false of this one: a markdown link resolves against its own
        directory with NO absent-root allowance (a backticked path has one), so a
        handbook page linking into ``memory/`` — which the export never ships — broke
        here and nowhere else. The maintainer checkout cannot see it, which is why the
        assertion has to run against a real export.
        """
        proc = subprocess.run(
            [sys.executable, "automation/gardener/verify_links.py"],
            cwd=self.export, capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class ExportedSkillTreeTests(unittest.TestCase):
    """The export ships exactly the skills the frontmatter declares public."""

    @classmethod
    def setUpClass(cls):
        cls.export = _shared_export()

    def test_every_public_skill_ships(self):
        public = ssm.public_skills(REPO_ROOT)
        self.assertIn("search-recall-audit", public)  # the skill that never shipped
        for skill in public:
            self.assertTrue((self.export / "skills" / skill / "SKILL.md").is_file(), skill)
        self.assertEqual(sorted(p.name for p in (self.export / "skills").iterdir()),
                         sorted(public))

    def test_symlink_trees_match_the_public_skills(self):
        public = sorted(ssm.public_skills(REPO_ROOT))
        for host in ssm.SYMLINK_HOSTS:
            base = self.export / host
            self.assertEqual(sorted(p.name for p in base.iterdir()), public, host)
            for skill in public:
                self.assertEqual(os.readlink(base / skill),
                                 f"{ssm.SYMLINK_TARGET_PREFIX}{skill}")

    def test_exported_manifests_are_self_consistent(self):
        self.assertEqual(ssm.findings(self.export), [])

    def test_no_private_skill_ships(self):
        for skill in ssm.private_skills(REPO_ROOT):
            self.assertFalse((self.export / "skills" / skill).exists(), skill)


if __name__ == "__main__":
    unittest.main()
