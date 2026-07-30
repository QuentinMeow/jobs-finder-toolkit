"""The two search-recall-audit readers of the applications skip-log.

``audit.build_coverage`` builds the coverage index the sampling step shows an AI
judge; ``store_refilter.build_covered`` decides which stored postings count as
"already handled". Both read the append-only skip-log, and both were wrong in
different ways before this suite existed:

* ``build_coverage`` read a YAML list that carried one row per posting. The
  append-only log carries one row per EVENT, so an unfolded read would list a
  posting once per status change and could report a superseded status.
* ``build_covered`` read ``log["applications"]`` / ``log["entries"]`` — keys the
  applications log has never had (its only writer emits ``{generated, count,
  postings}``). Both lookups returned ``[]`` on every run, so the log contributed
  nothing and "covered" silently meant "still has a live folder".

Isolation: every test pins ``JOBHUNT_CONFIG`` at a temp config whose
``applications_root`` is a temp dir, and asserts the resolved skip-log path is
inside it — the candidate's real tree is never read. Companies and URLs are
fictional.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/search-recall-audit/tests \
        -t automation/search-recall-audit/tests
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

AUDIT_DIR = Path(__file__).resolve().parents[1]
if str(AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(AUDIT_DIR))

import audit  # noqa: E402
import store_refilter  # noqa: E402  (import must be side-effect-free: no scan, no
#                                     private path, no local/ output)


def _event(**row) -> str:
    event = {"company": "", "slug": "", "date": "2026-07-16", "status": "drafted",
             "role": "", "url": "", "recorded": "2026-07-16T09:00:00Z",
             "source": "sync"}
    event.update(row)
    return json.dumps(event)


class _Tree:
    """A temp applications tree with a seeded skip-log, pinned via JOBHUNT_CONFIG."""

    def __init__(self, test: unittest.TestCase, *events: str):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.apps_root = base / "apps"
        (self.apps_root / "0_profile").mkdir(parents=True)
        self.log = self.apps_root / "0_profile" / "applications-log.jsonl"
        self.log.write_text("".join(e + "\n" for e in events), encoding="utf-8")

        cfg = base / "config.yaml"
        cfg.write_text(
            "paths:\n"
            f"  applications_root: {json.dumps(str(self.apps_root))}\n",
            encoding="utf-8",
        )
        self._prev = os.environ.get("JOBHUNT_CONFIG")
        os.environ["JOBHUNT_CONFIG"] = str(cfg)
        audit.config._load.cache_clear()
        test.addCleanup(self._restore)

    def _restore(self):
        if self._prev is None:
            os.environ.pop("JOBHUNT_CONFIG", None)
        else:
            os.environ["JOBHUNT_CONFIG"] = self._prev
        audit.config._load.cache_clear()
        self._tmp.cleanup()


class BuildCoverageTests(unittest.TestCase):
    def test_fixture_isolation_keeps_every_path_inside_the_temp_tree(self):
        tree = _Tree(self)
        self.assertEqual(Path(audit.config.applications_jsonl_path()), tree.log)
        self.assertEqual(Path(audit.config.applications_root()), tree.apps_root)

    def test_repeated_events_fold_to_one_entry_at_the_last_status(self):
        url = "https://boards.example.com/nimbus/jobs/2001"
        tree = _Tree(
            self,
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   slug="nimbus-robotics-senior-platform-engineer-20260716",
                   url=url, status="drafted"),
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   slug="nimbus-robotics-senior-platform-engineer-20260716",
                   url=url, status="applied"),
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   slug="nimbus-robotics-senior-platform-engineer-20260716",
                   url=url, status="rejected"),
        )
        self.assertTrue(tree.log.is_file())
        cov = audit.build_coverage()
        # Three events, one posting: the coverage list does not triple...
        self.assertEqual(len(cov["log"]), 1)
        # ...and reports the LAST status, not the first one it happened to read.
        self.assertEqual(cov["log"][0]["status"], "rejected")
        self.assertEqual(cov["log"][0]["company"], "Nimbus Robotics")
        self.assertEqual(cov["canon_urls"], [audit.canon(url)])
        self.assertIn("nimbus robotics", cov["companies"])

    def test_distinct_postings_are_all_covered(self):
        _Tree(
            self,
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url="https://boards.example.com/nimbus/jobs/2001"),
            _event(company="Alpha Systems", role="Staff Backend Engineer",
                   url="https://boards.example.com/alpha/jobs/3001"),
        )
        cov = audit.build_coverage()
        self.assertEqual(len(cov["log"]), 2)
        self.assertEqual(len(cov["canon_urls"]), 2)

    def test_missing_log_yields_an_empty_coverage_index(self):
        tree = _Tree(self)
        tree.log.unlink()
        cov = audit.build_coverage()
        self.assertEqual(cov["log"], [])
        self.assertEqual(cov["canon_urls"], [])


class BuildCoveredTests(unittest.TestCase):
    """Regression guard for the log branch that read keys which never existed."""

    def test_seeded_log_produces_a_non_empty_covered_set(self):
        tree = _Tree(
            self,
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url="https://boards.example.com/nimbus/jobs/2001"),
        )
        urls, pairs = store_refilter.build_covered(tree.log, tree.apps_root)
        # No application folder exists in this tree, so a non-empty result can ONLY
        # have come from the log — which is precisely what used to be empty.
        self.assertTrue(urls, "the log contributed no covered URLs")
        self.assertEqual(urls, {"https://boards.example.com/nimbus/jobs/2001"})
        self.assertEqual(pairs, {("nimbus robotics", "senior platform engineer")})

    def test_covered_urls_go_through_this_module_s_canon(self):
        # ``canon`` strips the fragment (``skip_log.norm_url`` deliberately does
        # not) and lowercases; the store side of the comparison is canon'd the same
        # way, so both sides must agree.
        tree = _Tree(
            self,
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url="https://Boards.Example.com/nimbus/jobs/2001/#apply"),
        )
        urls, _pairs = store_refilter.build_covered(tree.log, tree.apps_root)
        self.assertEqual(urls, {"https://boards.example.com/nimbus/jobs/2001"})

    def test_repeated_events_fold_before_covering(self):
        url = "https://boards.example.com/nimbus/jobs/2001"
        tree = _Tree(
            self,
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url=url, status="drafted"),
            _event(company="Nimbus Robotics", role="Senior Platform Engineer",
                   url=url, status="rejected"),
        )
        urls, pairs = store_refilter.build_covered(tree.log, tree.apps_root)
        self.assertEqual(urls, {url})
        self.assertEqual(len(pairs), 1)

    def test_live_folders_still_contribute(self):
        tree = _Tree(self)
        folder = tree.apps_root / "6_drafted" / "alpha-systems-staff-backend-engineer-20260716"
        folder.mkdir(parents=True)
        (folder / "meta.yaml").write_text(
            "company: Alpha Systems\n"
            "jobs:\n"
            "  - role: Staff Backend Engineer\n"
            "    url: https://boards.example.com/alpha/jobs/3001\n",
            encoding="utf-8",
        )
        urls, pairs = store_refilter.build_covered(tree.log, tree.apps_root)
        self.assertIn("https://boards.example.com/alpha/jobs/3001", urls)
        self.assertIn(("alpha systems", "staff backend engineer"), pairs)

    def test_missing_log_is_not_an_error(self):
        tree = _Tree(self)
        tree.log.unlink()
        self.assertEqual(store_refilter.build_covered(tree.log, tree.apps_root),
                         (set(), set()))


if __name__ == "__main__":
    unittest.main()
