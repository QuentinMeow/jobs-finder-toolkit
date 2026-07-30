"""Skip-logic identity tests: company-name variants must not escape the skips.

Regression for the 2026-07-22 gap where an aggregator's longer legal-name variant
("Acme Ltd.") escaped both the company-search-log recently-searched skip and the
applications-log already-considered skip because the log rows stored the shorter
registry name ("Acme"). Both skips now resolve every company through the registry's
match keys (name/alias/token + suffix-variant comparable forms), so the variant is
recognized as the SAME employer regardless of which source supplied the string.

Also covers what the identity gap's original tests could not see. Every case here
used to write a log row with a BLANK url, so ``load_considered``'s ``(company,
role)`` key was the only branch ever exercised and the suite could not tell a
correct reader from one that derived the URL key INSTEAD of the pair key. The
``PairKey`` cases below make the log row URL-bearing, which is the shape that fails
if the two independent keys are ever collapsed into url-else-pair.

No network / no candidate data: a fictional registry + temp-dir skip logs (the
already-considered one is the append-only JSONL).

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import search_jobs  # noqa: E402
from common import JobPosting  # noqa: E402
from registry import Registry  # noqa: E402

TODAY = date(2026, 7, 22)


def _posting(company: str, title: str, url: str = "") -> JobPosting:
    return JobPosting(source="jobicy", company=company, title=title, url=url)


def _reg() -> Registry:
    # "Acme" is a polled registry entry; aggregators report it as "Acme Ltd.".
    return Registry([
        {"name": "Acme", "ats": "greenhouse", "token": "acme",
         "tags": ["ai-native"]},
    ])


class _LogFixture:
    """Write the two skip-logs into a temp dir and point their accessors at them.

    Patches the accessors rather than a directory helper. The helper this replaced
    searched for *a directory containing a log*, which meant a fixture could satisfy
    it by accident; these name the two files directly, so a test that forgets to
    write one gets a missing path rather than a plausible-looking empty answer.

    The already-considered log is the append-only JSONL: one JSON object per line,
    one line per EVENT, folded last-wins by ``skip_log.read_postings``. Events are
    written as raw lines rather than through ``skip_log.append_event`` so these
    tests exercise the READER against the file format, not the reader against its
    own writer.
    """

    def __init__(self, test: unittest.TestCase):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._orig = (search_jobs._applications_jsonl, search_jobs._company_search_log)
        search_jobs._applications_jsonl = (  # type: ignore[assignment]
            lambda: self.dir / "applications-log.jsonl")
        search_jobs._company_search_log = (  # type: ignore[assignment]
            lambda: self.dir / "company-search-log.yaml")
        test.addCleanup(self._restore)

    def _restore(self):
        (search_jobs._applications_jsonl,  # type: ignore[assignment]
         search_jobs._company_search_log) = self._orig
        self._tmp.cleanup()

    def write_search_log(self, name: str, day: date = TODAY):
        (self.dir / "company-search-log.yaml").write_text(
            "skip_within_days: 7\n"
            "companies:\n"
            f"  - name: {name!r}\n"
            f"    last_successful_search: '{day.isoformat()}'\n"
            "    outcome: created\n"
        )

    def append_application_event(self, **row):
        """Append ONE skip-log event line (the log is append-only; never rewritten)."""
        event = {"company": "", "slug": "", "date": "2026-07-16",
                 "status": "applied", "role": "", "url": "",
                 "recorded": "2026-07-16T09:00:00Z", "source": "sync"}
        event.update(row)
        with (self.dir / "applications-log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def write_applications_log(self, company: str, role: str, url: str = ""):
        self.append_application_event(company=company, role=role, url=url)


class RecentlySearchedVariantTests(unittest.TestCase):
    def _fires(self, logged_name: str, incoming_company: str) -> bool:
        fx = _LogFixture(self)
        fx.write_search_log(logged_name)
        reg = _reg()
        skip_days, token_dates = search_jobs.load_company_search_log(
            profile=None, registry=reg)
        return search_jobs.is_recently_searched(
            _posting(incoming_company, "Backend Engineer"),
            token_dates, skip_days, TODAY, reg)

    def test_short_log_name_skips_longer_aggregator_variant(self):
        self.assertTrue(self._fires("Acme", "Acme Ltd."))

    def test_longer_log_name_skips_shorter_variant(self):  # symmetry
        self.assertTrue(self._fires("Acme Ltd.", "Acme"))

    def test_exact_name_still_skips(self):
        self.assertTrue(self._fires("Acme", "Acme"))

    def test_unrelated_company_is_not_skipped(self):
        self.assertFalse(self._fires("Acme", "Beacon Systems"))

    def test_aggregator_only_company_variant_skips(self):
        # Neither string is in the registry; comparable fallback still links them.
        self.assertTrue(self._fires("Globex", "Globex Technologies"))


class AlreadyConsideredVariantTests(unittest.TestCase):
    def _fires(self, logged_company: str, incoming_company: str,
               role: str = "Backend Engineer", logged_url: str = "",
               incoming_url: str = "") -> bool:
        fx = _LogFixture(self)
        fx.write_applications_log(logged_company, "Backend Engineer", logged_url)
        reg = _reg()
        urls, pairs = search_jobs.load_considered(reg)
        return search_jobs.already_considered(
            _posting(incoming_company, role, incoming_url), urls, pairs, reg)

    def test_short_log_name_skips_longer_aggregator_variant(self):
        self.assertTrue(self._fires("Acme", "Acme Ltd."))

    def test_longer_log_name_skips_shorter_variant(self):  # symmetry
        self.assertTrue(self._fires("Acme Ltd.", "Acme"))

    def test_aggregator_only_company_variant_skips(self):
        self.assertTrue(self._fires("Globex", "Globex Technologies"))

    def test_different_role_at_same_company_still_surfaces(self):
        # Only the exact (company, role) pair is suppressed; a new role surfaces.
        self.assertFalse(self._fires("Acme", "Acme Ltd.", role="ML Engineer"))

    def test_unrelated_company_is_not_considered(self):
        self.assertFalse(self._fires("Acme", "Beacon Systems"))

    # -- the pair key must survive a row that ALSO has a URL ---------------- #
    #
    # Every assertion above takes the (company, role) branch only because the
    # fixture row's URL is blank, so on its own this class cannot tell a working
    # ``load_considered`` from one that derived the URL key INSTEAD of the pair key
    # (url-else-pair rather than two independent ``if``s). In the real log the vast
    # majority of rows carry a URL, so that mistake would silently drop the pair
    # skip for nearly every posting and re-surface roles already applied to. These
    # two tests make the log row URL-bearing, which is the only shape that fails if
    # the two keys are ever collapsed into one branch.

    def test_pair_skip_still_fires_when_the_logged_row_has_a_url(self):
        # Logged WITH a URL; the incoming posting carries no URL at all, so only the
        # (company, role) key can produce a skip.
        self.assertTrue(self._fires(
            "Acme", "Acme Ltd.",
            logged_url="https://boards.example.com/acme/jobs/1001"))

    def test_pair_skip_fires_for_a_different_url_at_the_same_company_and_role(self):
        # The same role re-posted under a NEW URL (an ATS re-list): the URL key
        # cannot match, so the pair key is the only thing standing between the
        # owner and a duplicate draft.
        self.assertTrue(self._fires(
            "Acme", "Acme Ltd.",
            logged_url="https://boards.example.com/acme/jobs/1001",
            incoming_url="https://jobs.example.net/acme/backend-engineer"))

    def test_url_skip_fires_for_the_same_url_at_an_unrelated_company_string(self):
        # The other independent key: an identical URL skips even when the company
        # strings share no registry match key at all.
        url = "https://boards.example.com/acme/jobs/1001"
        self.assertTrue(self._fires(
            "Acme", "Beacon Systems", role="Site Reliability Engineer",
            logged_url=url, incoming_url=url))


class FoldedLogShapeTests(unittest.TestCase):
    """The reader sees ONE row per posting, at its LAST status, in file order."""

    def test_later_event_supersedes_earlier_one_for_the_same_posting(self):
        fx = _LogFixture(self)
        url = "https://boards.example.com/acme/jobs/1001"
        fx.append_application_event(company="Acme", role="Backend Engineer",
                                    url=url, status="drafted")
        fx.append_application_event(company="Acme", role="Backend Engineer",
                                    url=url, status="applied")
        fx.append_application_event(company="Acme", role="Backend Engineer",
                                    url=url, status="rejected")
        urls, pairs = search_jobs.load_considered(_reg())
        # Three events, one posting: the skip sets do not triple.
        self.assertEqual(urls, {url})
        self.assertIn(("acme", "backend engineer"), pairs)

    def test_a_posting_whose_folder_is_gone_still_skips(self):
        # The whole point of the append-only log: nothing regenerates it from the
        # folders, so a deleted application cannot un-skip its posting.
        fx = _LogFixture(self)
        fx.append_application_event(company="Acme", role="Backend Engineer",
                                    url="https://boards.example.com/acme/jobs/1001",
                                    status="rejected")
        reg = _reg()
        urls, pairs = search_jobs.load_considered(reg)
        self.assertTrue(search_jobs.already_considered(
            _posting("Acme", "Backend Engineer",
                     "https://boards.example.com/acme/jobs/1001"),
            urls, pairs, reg))

    def test_missing_log_is_an_empty_skip_not_an_error(self):
        _LogFixture(self)                      # patches the accessor, writes nothing
        # stderr is swallowed because the ambient applications root has folders, so the
        # missing-log warning fires here too. It is asserted on in MissingLogWarningTests.
        with redirect_stderr(io.StringIO()):
            urls, pairs = search_jobs.load_considered(_reg())
        self.assertEqual((urls, pairs), (set(), set()))


class MissingLogWarningTests(unittest.TestCase):
    """A search with no skip-log skips NOTHING and otherwise looks entirely normal.

    That is the silent fail-open ``profile_dir()`` was removed for, and it is also the
    state a half-finished migration leaves behind: the append-only log is seeded once
    with ``--backfill-log``, and until it is, every posting the owner already applied
    to comes back as fresh. So it has to say so — but only when there is something to
    skip, or a fresh checkout warns on every search.
    """

    def _load_with_apps_root(self, root: Path) -> str:
        _LogFixture(self)                      # accessor points at a file that is absent
        orig = search_jobs.applications_root
        search_jobs.applications_root = lambda: root  # type: ignore[assignment]
        self.addCleanup(lambda: setattr(search_jobs, "applications_root", orig))
        err = io.StringIO()
        with redirect_stderr(err):
            search_jobs.load_considered(_reg())
        return err.getvalue()

    def test_warns_when_applications_exist_but_the_log_does_not(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "3_rejected" / "example-co-eng-20260101").mkdir(parents=True)
            message = self._load_with_apps_root(root)
        self.assertIn("no applications skip-log", message)
        self.assertIn("--backfill-log", message)

    def test_silent_on_a_fresh_checkout_with_no_applications(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "3_rejected").mkdir(parents=True)   # status dirs, no applications
            message = self._load_with_apps_root(root)
        self.assertEqual(message, "")

    def test_silent_when_the_applications_root_does_not_exist(self):
        with TemporaryDirectory() as td:
            message = self._load_with_apps_root(Path(td) / "absent")
        self.assertEqual(message, "")


if __name__ == "__main__":
    unittest.main()
