"""The overlay blacklist actually reaches the search preflight (item 0.8).

The live ``private/job-search/blacklist.yaml`` is ``companies: []``, so every
existing test passes whether the overlay blacklist is loaded or not — a broken
path built "no blacklist" and nothing observable changed. These tests therefore
PLANT a real blacklist row in a temp overlay and assert the filter pipeline drops
the posting, plus the negative control (same posting, no overlay → kept).

No candidate data: a fictional overlay tree pointed at by ``$JOBHUNT_CONFIG``.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import registry  # noqa: E402
import search_jobs  # noqa: E402
from _vendor import config as vendored_config  # noqa: E402  (the copy registry uses)
from common import JobPosting  # noqa: E402

NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)

BLACKLIST_YAML = """\
companies:
  - name: Fictional Skip Corp
    aliases: [FSC]
    blacklist: Fictional row planted by the test suite.
"""


@contextmanager
def _overlay(*, blacklist: bool):
    """A temp checkout whose config points applications_root into an overlay."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        (root / "private" / "applications" / "0_profile").mkdir(parents=True)
        if blacklist:
            (root / "private" / "job-search").mkdir(parents=True)
            (root / "private" / "job-search" / "blacklist.yaml").write_text(
                BLACKLIST_YAML, encoding="utf-8")
        cfg = root / "config.yaml"
        cfg.write_text('paths:\n  applications_root: "private/applications"\n',
                       encoding="utf-8")
        saved = os.environ.get(vendored_config.ENV_VAR)
        os.environ[vendored_config.ENV_VAR] = str(cfg)
        vendored_config._load.cache_clear()
        try:
            yield root
        finally:
            if saved is None:
                os.environ.pop(vendored_config.ENV_VAR, None)
            else:
                os.environ[vendored_config.ENV_VAR] = saved
            vendored_config._load.cache_clear()


def _posting() -> JobPosting:
    return JobPosting(
        source="jobicy",
        company="Fictional Skip Corp",
        title="Senior Software Engineer, Platform",
        url="https://example.test/jobs/1",
        location="Remote, United States",
        description="Build platform services.",
    )


def _ctx() -> dict:
    return {
        "considered_urls": set(), "considered_pairs": set(),
        "skip_days": 0, "search_tokens": [],
        "ignore_search_log": True, "ai_native_keys": set(),
    }


def _run_preflight(reg) -> tuple[list, dict]:
    return search_jobs.filter_score_rank(
        [_posting()], {}, _ctx(), max_age=None, top_k=40, max_per_company=10,
        sponsor_index=None, company_levels={}, registry=reg, now=NOW)


class OverlayBlacklistTests(unittest.TestCase):
    def test_planted_overlay_row_is_honoured_by_the_search_preflight(self):
        with _overlay(blacklist=True):
            reg = registry.load_registry()
            blocked, reason = reg.is_blacklisted("Fictional Skip Corp")
            self.assertTrue(blocked)
            self.assertEqual(reason, "Fictional row planted by the test suite.")
            # The alias resolves through the registry's match keys too.
            self.assertTrue(reg.is_blacklisted("fsc")[0])

            kept, counts = _run_preflight(reg)
            self.assertEqual(counts["n_blacklisted"], 1)
            self.assertEqual(kept, [])
            self.assertEqual(counts["n_review"], 0)

    def test_negative_control_same_posting_is_kept_without_the_overlay_row(self):
        # Proves the assertion above is caused by the planted row and not by an
        # unrelated gate: identical posting, overlay present but no blacklist file.
        with _overlay(blacklist=False):
            with redirect_stderr(io.StringIO()):
                reg = registry.load_registry()
            self.assertFalse(reg.is_blacklisted("Fictional Skip Corp")[0])
            kept, counts = _run_preflight(reg)
            self.assertEqual(counts["n_blacklisted"], 0)
            self.assertEqual(len(kept) + counts["n_review"], 1)

    def test_missing_blacklist_under_a_mounted_overlay_is_reported(self):
        err = io.StringIO()
        with _overlay(blacklist=False):
            with redirect_stderr(err):
                registry.load_registry()
        self.assertIn("no overlay blacklist", err.getvalue())
        self.assertIn("blacklist.yaml", err.getvalue())

    def test_no_overlay_means_no_notice(self):
        # A fresh public clone has no blacklist by design — staying silent there is
        # what keeps the notice meaningful when it does fire.
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "applications").mkdir()
            cfg = root / "config.yaml"
            cfg.write_text('paths:\n  applications_root: "applications"\n',
                           encoding="utf-8")
            saved = os.environ.get(vendored_config.ENV_VAR)
            os.environ[vendored_config.ENV_VAR] = str(cfg)
            vendored_config._load.cache_clear()
            try:
                with redirect_stderr(err):
                    registry.load_registry()
            finally:
                if saved is None:
                    os.environ.pop(vendored_config.ENV_VAR, None)
                else:
                    os.environ[vendored_config.ENV_VAR] = saved
                vendored_config._load.cache_clear()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
