"""Direct coverage for config discovery + the derived-path accessors.

Two things are pinned here:

1. **Discovery no longer fails open.** Falling back to the tracked fictional
   example config is fine for a fresh public clone (loudly, once), but it is a
   REFUSAL when a ``private/`` overlay is mounted — real data on disk plus a tool
   silently pointed at "Jordan Rivers" is the failure mode item 0.3 exists to
   close. A malformed config raises instead of degrading to every default.

2. **Every accessor's default equals the literal it replaced.** These accessors
   were extracted from literals spread across ~10 scripts; the story bank is the
   dangerous one — ``build_tailoring_card.py`` and the gardener's
   ``card_staleness.py`` computed it independently, and a divergence yields a
   tailoring card with zero stories and a still-valid sha256.

Every test builds its own temp tree and patches the module's own location, so
nothing here can reach (or depend on) the maintainer's real config or overlay.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/shared/tests
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import textwrap
import unittest
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from unittest import mock

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import config  # noqa: E402

_ENV_KEYS = (config.ENV_VAR, config.REQUIRE_REAL_CONFIG_ENV_VAR)


@contextmanager
def _clean_env(**overrides: str):
    """Run with the config env vars cleared (then optionally set) and no cache."""
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update(overrides)
    config._load.cache_clear()
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config._load.cache_clear()


@contextmanager
def _fake_checkout(*, overlay: bool, example_text: str = "candidate:\n  name: x\n"):
    """A temp git checkout with no config.yaml, standing in for the real repo.

    ``config._HERE`` / ``REPO_ROOT`` / ``EXAMPLE_CONFIG`` are patched onto the temp
    tree and the cwd is moved inside it, so discovery cannot reach the real
    repository's ``config.yaml`` (which would otherwise be found by the walk up
    from the module's own directory).
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / "checkout"
        here = root / "automation" / "shared"
        here.mkdir(parents=True)
        (root / ".git").mkdir()
        if overlay:
            (root / config.OVERLAY_DIRNAME).mkdir()
        example = root / "config.example.yaml"
        example.write_text(example_text, encoding="utf-8")
        workdir = root / "skills" / "job-search"
        workdir.mkdir(parents=True)
        cwd = Path.cwd()
        os.chdir(workdir)
        try:
            with mock.patch.object(config, "_HERE", here), \
                 mock.patch.object(config, "REPO_ROOT", root), \
                 mock.patch.object(config, "EXAMPLE_CONFIG", example):
                yield root
        finally:
            os.chdir(cwd)


@contextmanager
def _active_config(body: str, *, subdir: str = ""):
    """Point ``$JOBHUNT_CONFIG`` at a temp config.yaml holding ``body``."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp).resolve()
        base = tmp / subdir if subdir else tmp
        base.mkdir(parents=True, exist_ok=True)
        cfg = base / config.CONFIG_FILENAME
        cfg.write_text(textwrap.dedent(body), encoding="utf-8")
        with _clean_env(**{config.ENV_VAR: str(cfg)}):
            yield cfg


class DiscoveryRefusalTests(unittest.TestCase):
    """Item 0.3: the example fallback must never be silent, and must sometimes fail."""

    def test_raises_when_an_overlay_is_mounted_and_no_real_config_exists(self):
        with _fake_checkout(overlay=True), _clean_env():
            with self.assertRaises(config.ConfigNotFound) as ctx:
                config.config_path()
        message = str(ctx.exception)
        self.assertIn(config.OVERLAY_DIRNAME, message)      # names what it found
        self.assertIn(config.CONFIG_FILENAME, message)      # names what it wanted
        self.assertIn(config.ENV_VAR, message)              # names the way out

    def test_falls_back_to_the_example_with_a_stderr_notice_when_no_overlay(self):
        err = io.StringIO()
        with _fake_checkout(overlay=False) as root, _clean_env():
            with redirect_stderr(err):
                path = config.config_path()
                config.config_path()          # cached: the notice fires ONCE
            self.assertEqual(path, root / "config.example.yaml")
        self.assertEqual(err.getvalue().count("fictional example persona"), 1)

    def test_require_real_config_raises_even_without_an_overlay(self):
        with _fake_checkout(overlay=False), \
                _clean_env(**{config.REQUIRE_REAL_CONFIG_ENV_VAR: "1"}):
            with self.assertRaises(config.ConfigNotFound) as ctx:
                config.config_path()
        self.assertIn(config.REQUIRE_REAL_CONFIG_ENV_VAR, str(ctx.exception))

    def test_explicit_env_config_is_honoured_silently_even_with_an_overlay(self):
        err = io.StringIO()
        with _fake_checkout(overlay=True) as root:
            real = root / "elsewhere.yaml"
            real.write_text("candidate:\n  name: Real\n", encoding="utf-8")
            with _clean_env(**{config.ENV_VAR: str(real)}), redirect_stderr(err):
                self.assertEqual(config.config_path(), real)
                self.assertEqual(config.candidate_name(), "Real")
        self.assertEqual(err.getvalue(), "")

    def test_walk_stops_at_the_git_boundary_and_searches_the_boundary_itself(self):
        # A worktree's .git is a FILE. The parent checkout's config.yaml sits one
        # level above it and must NOT be reached (known-issues/
        # worktree-config-discovery-escape.md); the worktree's own config IS found.
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "parent"
            (parent / ".git").mkdir(parents=True)
            (parent / config.CONFIG_FILENAME).write_text(
                "candidate:\n  name: Parent\n", encoding="utf-8")
            worktree = parent / "worktrees" / "feature"
            (worktree / "sub").mkdir(parents=True)
            (worktree / ".git").write_text("gitdir: ../../.git/worktrees/feature\n",
                                           encoding="utf-8")

            found, boundary = config._search_up(worktree / "sub")
            self.assertIsNone(found)                  # parent's config NOT reached
            self.assertEqual(boundary, worktree)

            (worktree / config.CONFIG_FILENAME).write_text(
                "candidate:\n  name: Worktree\n", encoding="utf-8")
            found, boundary = config._search_up(worktree / "sub")
            self.assertEqual(found, worktree / config.CONFIG_FILENAME)


class MalformedConfigTests(unittest.TestCase):
    def test_yaml_syntax_error_raises_instead_of_yielding_an_empty_config(self):
        with _active_config("candidate:\n  name: \"unclosed\n   - [\n"):
            with self.assertRaises(config.ConfigError) as ctx:
                config.candidate_name()
            self.assertIn("not valid YAML", str(ctx.exception))

    def test_non_mapping_top_level_raises(self):
        with _active_config("- just\n- a\n- list\n"):
            with self.assertRaises(config.ConfigError):
                config.candidate_name()

    def test_empty_config_is_still_fine(self):
        with _active_config("\n"):
            self.assertEqual(config.candidate_name(), "")


class AccessorDefaultTests(unittest.TestCase):
    """Each default must equal the literal it replaced, byte for byte."""

    CONFIG = 'paths:\n  applications_root: "private/applications"\n'

    def test_defaults_match_the_literals_they_replaced(self):
        with _active_config(self.CONFIG) as cfg:
            base = cfg.parent
            apps = base / "private" / "applications"
            overlay = base / "private"
            self.assertEqual(config.applications_root(), apps)

            # overlay_root(): the applications_root().parent idiom (registry.py,
            # build_tailoring_card.py, card_staleness.py).
            self.assertEqual(config.overlay_root(), apps.parent)
            self.assertEqual(config.overlay_root(), overlay)

            # candidate_dir(): applications_root() / "0_profile" (status.py:152,
            # compact_logs.py, self_measure.py, search_jobs.py, audit.py, ...).
            self.assertEqual(config.candidate_dir(), apps / "0_profile")

            self.assertEqual(config.tailoring_card_path(),
                             apps / "0_profile" / "tailoring-card.md")
            self.assertEqual(config.applications_log_path(),
                             apps / "0_profile" / "applications-log.yaml")
            self.assertEqual(config.company_search_log_path(),
                             apps / "0_profile" / "company-search-log.yaml")
            self.assertEqual(config.calendar_path(),
                             apps / "0_profile" / "calendar.md")

            # registry.py's _overlay_blacklist_paths() built exactly this.
            self.assertEqual(config.blacklist_path(),
                             overlay / "job-search" / "blacklist.yaml")

            self.assertEqual(config.search_profiles_dir(),
                             overlay / "job-search-profiles")
            self.assertEqual(config.skill_references_dir("job-search"),
                             overlay / "skills" / "references_private" / "job-search")
            self.assertEqual(config.companies_root(), overlay / "companies")

    def test_story_bank_matches_both_independent_derivations(self):
        # The trap: build_tailoring_card.py and card_staleness.py each computed
        # ``config.applications_root().parent / "interviews/behavioral/story-bank"``.
        # If the accessor answers anything else, the card is built from an empty
        # directory and stamped with a sha256 that the staleness check agrees with —
        # a card with zero stories that never reports itself stale.
        with _active_config(self.CONFIG):
            legacy = (config.applications_root().parent
                      / "interviews" / "behavioral" / "story-bank")
            self.assertEqual(config.story_bank_path(), legacy)

    def test_story_bank_does_not_require_the_directory_to_exist(self):
        with _active_config(self.CONFIG):
            path = config.story_bank_path()
            self.assertFalse(path.exists())
            self.assertFalse(path.is_dir())     # callers degrade gracefully

    def test_every_accessor_resolves_relative_to_the_config_file_directory(self):
        # Not the cwd, and not the repo root: a config in a subdirectory must move
        # every derived path with it.
        with _active_config(self.CONFIG, subdir="nested/deeper") as cfg:
            base = cfg.parent
            for name, path in (
                ("applications_root", config.applications_root()),
                ("overlay_root", config.overlay_root()),
                ("candidate_dir", config.candidate_dir()),
                ("tailoring_card_path", config.tailoring_card_path()),
                ("applications_log_path", config.applications_log_path()),
                ("company_search_log_path", config.company_search_log_path()),
                ("calendar_path", config.calendar_path()),
                ("blacklist_path", config.blacklist_path()),
                ("story_bank_path", config.story_bank_path()),
                ("search_profiles_dir", config.search_profiles_dir()),
                ("skill_references_dir", config.skill_references_dir("job-search")),
                ("companies_root", config.companies_root()),
            ):
                with self.subTest(accessor=name):
                    self.assertTrue(path.is_absolute())
                    self.assertEqual(path.relative_to(base).parts[0], "private")


class AccessorOverrideTests(unittest.TestCase):
    """Every accessor's config key wins over the derivation."""

    OVERRIDES = """\
        paths:
          applications_root: "apps"
          overlay_root: "elsewhere"
          candidate_dir: "apps/candidate"
          calendar_md: "apps/candidate/cal.md"
          blacklist_yaml: "elsewhere/skips.yaml"
          story_bank_dir: "elsewhere/stories"
          search_profiles_dir: "elsewhere/profiles"
          skill_references_root: "elsewhere/refs"
          companies_root: "elsewhere/co"
    """

    def test_configured_keys_win(self):
        with _active_config(self.OVERRIDES) as cfg:
            base = cfg.parent
            self.assertEqual(config.overlay_root(), base / "elsewhere")
            self.assertEqual(config.candidate_dir(), base / "apps" / "candidate")
            # Derived-from-candidate_dir paths follow the override.
            self.assertEqual(config.tailoring_card_path(),
                             base / "apps" / "candidate" / "tailoring-card.md")
            self.assertEqual(config.applications_log_path(),
                             base / "apps" / "candidate" / "applications-log.yaml")
            self.assertEqual(config.calendar_path(),
                             base / "apps" / "candidate" / "cal.md")
            self.assertEqual(config.blacklist_path(), base / "elsewhere" / "skips.yaml")
            self.assertEqual(config.story_bank_path(), base / "elsewhere" / "stories")
            self.assertEqual(config.search_profiles_dir(),
                             base / "elsewhere" / "profiles")
            self.assertEqual(config.skill_references_dir("resume-writer"),
                             base / "elsewhere" / "refs" / "resume-writer")
            self.assertEqual(config.companies_root(), base / "elsewhere" / "co")

    def test_absolute_configured_paths_are_used_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = Path(tmp).resolve()
            body = f'paths:\n  overlay_root: "{resolved.as_posix()}"\n'
            with _active_config(body):
                self.assertEqual(config.overlay_root(), resolved)


class OverlayMountedTests(unittest.TestCase):
    """The signal registry.py uses to decide whether a missing blacklist is news."""

    def test_false_when_the_overlay_root_collapses_onto_the_config_dir(self):
        # A fresh public clone: applications/ at the repo root, so overlay_root()
        # derives to the config dir itself. Nothing is mounted.
        with _active_config('paths:\n  applications_root: "applications"\n'):
            self.assertFalse(config.overlay_mounted())

    def test_false_when_the_overlay_root_does_not_exist(self):
        with _active_config('paths:\n  applications_root: "private/applications"\n'):
            self.assertFalse(config.overlay_mounted())

    def test_true_when_a_distinct_overlay_directory_exists(self):
        with _active_config('paths:\n  applications_root: "private/applications"\n') as cfg:
            (cfg.parent / "private").mkdir()
            self.assertTrue(config.overlay_mounted())


class RepoRootResolutionTests(unittest.TestCase):
    """``REPO_ROOT`` must name the REPO root in every copy of this module.

    ``sync_vendored.py`` mirrors this file byte-identically into four skills at
    ``skills/<skill>/scripts/_vendor/config.py`` — FOUR levels below the repo root
    where the canonical copy is two. Counting parents therefore resolved to
    ``skills/<skill>/`` in each vendored copy, making ``EXAMPLE_CONFIG`` a path that
    cannot exist: the example fallback loaded nothing, and every "am I on the
    fictional persona?" comparison against that constant answered a constant.
    """

    REPO_ROOT = SHARED_DIR.parents[1]
    COPIES = (
        "automation/shared/config.py",
        "skills/resume-writer/scripts/_vendor/config.py",
        "skills/application-tracker/scripts/_vendor/config.py",
        "skills/job-search/scripts/_vendor/config.py",
        "skills/email-assistant/scripts/_vendor/config.py",
    )

    def _load_copy(self, rel: str):
        """Import one copy of config.py under its own module name."""
        path = self.REPO_ROOT / rel
        self.assertTrue(path.is_file(), f"{rel} is missing")
        name = "_probe_" + rel.replace("/", "_")[:-3]
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
        return module

    def test_every_copy_resolves_the_same_repo_root(self):
        for rel in self.COPIES:
            with self.subTest(copy=rel):
                self.assertEqual(self._load_copy(rel).REPO_ROOT, self.REPO_ROOT)

    def test_every_copy_points_example_config_at_a_real_file(self):
        for rel in self.COPIES:
            with self.subTest(copy=rel):
                example = self._load_copy(rel).EXAMPLE_CONFIG
                self.assertTrue(example.is_file(), f"{rel}: {example} does not exist")


class RepoRootMarkerTests(unittest.TestCase):
    """The marker precedence in ``_repo_root``: ``.git``, then the example, then here.

    The last case is a skill folder unpacked outside any project. Answering with the
    module's own directory keeps the search inside the unpacked artifact — walking
    on up could hit an unrelated ``/private`` (a real directory on macOS) and refuse
    the fallback, or adopt a stranger's ``config.example.yaml``.
    """

    def _tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve() / "proj"
        (root / "skills" / "s" / "scripts" / "_vendor").mkdir(parents=True)
        return root

    def test_git_marker_wins(self):
        root = self._tree()
        (root / ".git").mkdir()
        # A nearer example config must NOT outrank the repository boundary.
        (root / "skills" / "s" / config.EXAMPLE_CONFIG_FILENAME).touch()
        here = root / "skills" / "s" / "scripts" / "_vendor"
        self.assertEqual(config._repo_root(here), root)

    def test_git_file_marker_of_a_worktree_is_honoured(self):
        root = self._tree()
        (root / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        self.assertEqual(config._repo_root(root / "skills" / "s"), root)

    def test_example_config_marks_the_root_of_a_git_less_export(self):
        root = self._tree()
        (root / config.EXAMPLE_CONFIG_FILENAME).touch()
        here = root / "skills" / "s" / "scripts" / "_vendor"
        self.assertEqual(config._repo_root(here), root)

    def test_falls_back_to_the_modules_own_directory_with_no_marker(self):
        here = self._tree() / "skills" / "s" / "scripts" / "_vendor"
        self.assertEqual(config._repo_root(here), here)


if __name__ == "__main__":
    unittest.main()
