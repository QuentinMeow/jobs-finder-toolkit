"""Tests for how a ``--profile`` value becomes a file on disk.

The candidate's own profiles used to be SYMLINKED from the private overlay into
the tracked ``skills/job-search/profiles/`` folder, which put a personal filename
at a public path — held out of git only by an ignore glob with negations that
``git add -f`` overrides. Workspace-restructure phase 4 deleted those links, so a
bare label now resolves through ``config.search_profiles_dir()`` first and the
tracked public folder second.

Two properties matter and are asserted here:
  * the overlay is searched FIRST, so a personal label still resolves and wins
    over a same-named public file;
  * a checkout with NO overlay still resolves ``example`` from the tracked
    folder — that is what a fresh public clone runs on.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import search_jobs  # noqa: E402
import validate_filter_variants  # noqa: E402

SKILL_PROFILES = _SCRIPTS.parent / "profiles"


class ProfileSearchDirsTests(unittest.TestCase):
    """Order and membership of the directories a bare label is looked up in."""

    def _with_profiles_dir(self, path: Path | None):
        """Stub ``config.search_profiles_dir``; ``None`` = no config layer."""
        original = search_jobs.config
        self.addCleanup(setattr, search_jobs, "config", original)
        if path is None:
            search_jobs.config = None
            return

        class _Stub:
            @staticmethod
            def search_profiles_dir():
                return path

        search_jobs.config = _Stub()

    def test_overlay_dir_comes_first_then_the_public_folder(self):
        with tempfile.TemporaryDirectory() as td:
            overlay = Path(td) / "job-search-profiles"
            self._with_profiles_dir(overlay)
            self.assertEqual(search_jobs.profile_search_dirs(),
                             [overlay.resolve(), SKILL_PROFILES])

    def test_public_folder_alone_without_a_config_layer(self):
        self._with_profiles_dir(None)
        self.assertEqual(search_jobs.profile_search_dirs(), [SKILL_PROFILES])

    def test_a_raising_config_does_not_take_resolution_down(self):
        class _Raising:
            @staticmethod
            def search_profiles_dir():
                raise RuntimeError("no config.yaml found")

        original = search_jobs.config
        self.addCleanup(setattr, search_jobs, "config", original)
        search_jobs.config = _Raising()
        self.assertEqual(search_jobs.profile_search_dirs(), [SKILL_PROFILES])

    def test_no_search_dir_is_inside_the_public_profiles_folder(self):
        """The overlay dir must not be a path under the tracked public folder.

        That shape is exactly the deleted symlink arrangement: a personal profile
        addressable at ``skills/job-search/profiles/<personal-name>.yaml``.
        """
        with tempfile.TemporaryDirectory() as td:
            self._with_profiles_dir(Path(td) / "job-search-profiles")
            for d in search_jobs.profile_search_dirs():
                if d == SKILL_PROFILES:
                    continue
                self.assertFalse(str(d).startswith(str(SKILL_PROFILES) + "/"), d)

    def test_a_configured_dir_inside_skills_is_refused(self):
        """With no config at all the accessor collapses onto the loader's dir.

        In a config-less public clone ``config.search_profiles_dir()`` derives
        ``skills/job-search/job-search-profiles`` — inside the PUBLIC tree.
        Honouring it would put personal profiles back at a public path, so it is
        dropped and only the tracked folder is searched.
        """
        self._with_profiles_dir(SKILL_PROFILES.parent / "job-search-profiles")
        self.assertEqual(search_jobs.profile_search_dirs(), [SKILL_PROFILES])
        # ...including the tracked folder itself.
        self._with_profiles_dir(SKILL_PROFILES)
        self.assertEqual(search_jobs.profile_search_dirs(), [SKILL_PROFILES])


class ResolveProfileTests(unittest.TestCase):
    """``resolve_profile`` and the audit tool must agree on every input."""

    def _overlay(self, td: str, *names: str) -> Path:
        overlay = (Path(td) / "job-search-profiles").resolve()
        overlay.mkdir(parents=True)
        for n in names:
            (overlay / n).write_text("titles: {}\n", encoding="utf-8")
        original = search_jobs.config
        self.addCleanup(setattr, search_jobs, "config", original)

        class _Stub:
            @staticmethod
            def search_profiles_dir():
                return overlay

        search_jobs.config = _Stub()
        return overlay

    def test_bare_label_resolves_from_the_overlay(self):
        with tempfile.TemporaryDirectory() as td:
            overlay = self._overlay(td, "mine.yaml")
            self.assertEqual(search_jobs.resolve_profile("mine"), overlay / "mine.yaml")
            self.assertEqual(validate_filter_variants._profile_path("mine"),
                             overlay / "mine.yaml")

    def test_overlay_wins_over_a_same_named_public_profile(self):
        with tempfile.TemporaryDirectory() as td:
            overlay = self._overlay(td, "example.yaml")
            self.assertEqual(search_jobs.resolve_profile("example"),
                             overlay / "example.yaml")

    def test_public_example_resolves_when_the_overlay_lacks_it(self):
        with tempfile.TemporaryDirectory() as td:
            self._overlay(td, "mine.yaml")
            self.assertEqual(search_jobs.resolve_profile("example"),
                             SKILL_PROFILES / "example.yaml")

    def test_public_example_resolves_with_no_overlay_at_all(self):
        """The fresh-public-clone case: no config layer, no overlay directory."""
        original = search_jobs.config
        self.addCleanup(setattr, search_jobs, "config", original)
        search_jobs.config = None
        self.assertEqual(search_jobs.resolve_profile("example"),
                         SKILL_PROFILES / "example.yaml")
        self.assertTrue(search_jobs.resolve_profile("example").is_file())

    def test_an_absolute_path_still_wins_outright(self):
        with tempfile.TemporaryDirectory() as td:
            self._overlay(td, "mine.yaml")
            elsewhere = Path(td) / "bench.yaml"
            elsewhere.write_text("titles: {}\n", encoding="utf-8")
            self.assertEqual(search_jobs.resolve_profile(str(elsewhere)), elsewhere)
            self.assertEqual(validate_filter_variants._profile_path(str(elsewhere)),
                             elsewhere)

    def test_unknown_label_exits_naming_every_directory_searched(self):
        with tempfile.TemporaryDirectory() as td:
            overlay = self._overlay(td, "mine.yaml")
            with self.assertRaises(SystemExit) as ctx:
                search_jobs.resolve_profile("no-such-profile")
            message = str(ctx.exception)
            self.assertIn(str(overlay), message)
            self.assertIn(str(SKILL_PROFILES), message)
            with self.assertRaises(FileNotFoundError):
                validate_filter_variants._profile_path("no-such-profile")


class PublicProfilesFolderTests(unittest.TestCase):
    """The tracked folder is entirely public — nothing personal may live there."""

    def test_only_the_generic_files_are_present(self):
        self.assertEqual(sorted(p.name for p in SKILL_PROFILES.iterdir()),
                         ["README.md", "_TEMPLATE.yaml", "example.yaml"])

    def test_it_holds_no_symlinks(self):
        self.assertEqual([p.name for p in SKILL_PROFILES.iterdir() if p.is_symlink()],
                         [])


if __name__ == "__main__":
    unittest.main()
