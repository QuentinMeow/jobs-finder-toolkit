"""Tests for the JobSpy 'enabled but not installed' fail-loud path.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests

No network: ``assemble_jobspy_tasks`` only builds deferred callables and never runs
a scrape, and ``jobspy_available()`` is exercised by patching ``sys.modules``.
"""
from __future__ import annotations

import io
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path

# Make the skill's own scripts/ (+ its _vendor/) importable, mirroring how
# search_jobs.py bootstraps itself when run directly.
_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import aggregators  # noqa: E402
import search_jobs  # noqa: E402


@contextmanager
def _patched_module(name, value):
    """Temporarily set ``sys.modules[name]`` (``None`` makes ``import name`` fail)."""
    sentinel = object()
    prev = sys.modules.get(name, sentinel)
    sys.modules[name] = value
    try:
        yield
    finally:
        if prev is sentinel:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prev


class JobspyAvailableTests(unittest.TestCase):
    def test_reports_missing_when_import_fails(self):
        # sys.modules[name] = None makes `import name` raise ImportError.
        with _patched_module("jobspy", None):
            self.assertFalse(aggregators.jobspy_available())

    def test_reports_present_when_importable(self):
        with _patched_module("jobspy", types.ModuleType("jobspy")):
            self.assertTrue(aggregators.jobspy_available())


class JobspyMissingBannerTests(unittest.TestCase):
    def test_banner_names_install_command_and_sites(self):
        banner = search_jobs._jobspy_missing_banner(["indeed", "google"])
        self.assertIn(".venv/bin/pip install python-jobspy", banner)
        self.assertIn("indeed", banner)
        self.assertIn("google", banner)
        # Prominent + multi-line.
        self.assertGreaterEqual(len(banner.splitlines()), 5)


class AssembleJobspyTasksTests(unittest.TestCase):
    def test_enabled_but_missing_emits_banner_and_continues(self):
        stream = io.StringIO()
        tasks, labels, skipped = search_jobs.assemble_jobspy_tasks(
            jobspy_on=True, stage=2, jobspy_cfg={},
            query_terms=["software engineer"], max_age=3,
            available=False, stream=stream)
        out = stream.getvalue()
        # Banner emitted, naming the exact install command...
        self.assertIn(".venv/bin/pip install python-jobspy", out)
        # ...and every skipped source (reliable Indeed/Google + stage-2 LinkedIn)...
        for site in ("indeed", "google", "linkedin"):
            self.assertIn(site, out)
        # ...and the run continues: the function returns normally (no exception),
        # with no JobSpy tasks/labels but the skipped sites recorded.
        self.assertEqual(tasks, [])
        self.assertEqual(labels, [])
        self.assertEqual(skipped, ["indeed", "google", "linkedin"])

    def test_enabled_and_present_builds_tasks_without_banner(self):
        stream = io.StringIO()
        tasks, labels, skipped = search_jobs.assemble_jobspy_tasks(
            jobspy_on=True, stage=1, jobspy_cfg={},
            query_terms=["software engineer"], max_age=3,
            available=True, stream=stream)
        self.assertEqual(stream.getvalue(), "")     # no banner when installed
        self.assertTrue(tasks)                       # deferred fetch callables built
        self.assertIn("jobspy:indeed,google", labels)
        self.assertEqual(skipped, ["indeed", "google"])

    def test_disabled_is_a_no_op(self):
        stream = io.StringIO()
        result = search_jobs.assemble_jobspy_tasks(
            jobspy_on=False, stage=2, jobspy_cfg={},
            query_terms=["x"], max_age=3,
            available=False, stream=stream)
        self.assertEqual(result, ([], [], []))
        self.assertEqual(stream.getvalue(), "")


class ReliableSitesKeyTests(unittest.TestCase):
    """The staged planner reads `reliable_sites`; the profiles taught `sites`.

    A profile asking for Indeed only through the obsolete key was ignored, so the
    run fell back to [indeed, google] and doubled its fetch volume — silently.
    """

    def _plan(self, cfg, stream):
        _, labels, _ = search_jobs.assemble_jobspy_tasks(
            jobspy_on=True, stage=1, jobspy_cfg=cfg, query_terms=["x"], max_age=3,
            available=True, stream=stream)
        return labels

    def test_the_obsolete_sites_key_is_honoured_not_ignored(self):
        stream = io.StringIO()
        self.assertEqual(self._plan({"sites": ["indeed"]}, stream),
                         ["jobspy:indeed"])

    def test_the_obsolete_key_warns_and_names_the_rename(self):
        stream = io.StringIO()
        self._plan({"sites": ["indeed"]}, stream)
        warning = stream.getvalue()
        self.assertIn("sites", warning)
        self.assertIn("reliable_sites", warning)

    def test_the_canonical_key_is_silent(self):
        stream = io.StringIO()
        self.assertEqual(self._plan({"reliable_sites": ["indeed"]}, stream),
                         ["jobspy:indeed"])
        self.assertEqual(stream.getvalue(), "")

    def test_the_canonical_key_wins_when_both_are_set(self):
        stream = io.StringIO()
        self.assertEqual(
            self._plan({"reliable_sites": ["indeed"], "sites": ["google"]}, stream),
            ["jobspy:indeed"])
        self.assertIn("IGNORING", stream.getvalue())

    def test_neither_key_falls_back_to_the_documented_default(self):
        stream = io.StringIO()
        self.assertEqual(self._plan({}, stream), ["jobspy:indeed,google"])
        self.assertEqual(stream.getvalue(), "")

    def test_the_bare_jobspy_aggregator_name_reads_the_same_key(self):
        """`build_aggregator_tasks`'s legacy path must not disagree with the planner."""
        stream = io.StringIO()
        self.assertEqual(
            aggregators.resolve_reliable_sites({"reliable_sites": ["indeed"]},
                                               stream=stream),
            ["indeed"])
        tasks = aggregators.build_aggregator_tasks(
            ["jobspy"], ["x"], "US", 3, {"reliable_sites": ["indeed"]})
        self.assertTrue(all("indeed" in label and "google" not in label
                            for label, _ in tasks), [t[0] for t in tasks])


class RequirementsTxtTests(unittest.TestCase):
    def test_requirements_lists_python_jobspy(self):
        # REPO_ROOT resolves skills/job-search -> toolkit root; requirements.txt
        # must pin the scraper dep that powers the default search path.
        req = (search_jobs.REPO_ROOT / "requirements.txt").read_text()
        self.assertIn("python-jobspy", req)


class ShippedProfileDefaultsTests(unittest.TestCase):
    def test_example_enables_stage1_jobspy_baseline(self):
        profile = search_jobs.load_yaml(
            search_jobs.SKILL_DIR / "profiles" / "example.yaml")
        self.assertTrue(profile["sources"]["jobspy"]["enabled"])
        # The canonical key the staged planner actually reads. The shipped
        # profiles taught `sites:` while the planner read `reliable_sites`, so a
        # profile narrowing its sites was ignored and Google got scraped anyway.
        self.assertEqual(profile["sources"]["jobspy"]["reliable_sites"],
                         ["indeed", "google"])
        self.assertNotIn("sites", profile["sources"]["jobspy"])


if __name__ == "__main__":
    unittest.main()
