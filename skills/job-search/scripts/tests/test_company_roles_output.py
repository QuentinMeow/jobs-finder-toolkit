"""The single-company re-check must expose the gate's three-valued outcome.

`assess_location` answers `match` / `no_match` / `review`. When this script
collapsed that to a bool, a `review` posting — the gate saying "the fields do not
let me judge, read this one" — printed as a flat `no` and carried no `decision`
key in `--json`, so a consumer could not tell a rejection from an unread posting.
That is how a live board hid a genuinely remote role behind its "Hybrid" location
tag.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests

No network: `fetch_company` is replaced with hand-built postings.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import company_roles  # noqa: E402
from common import JobPosting  # noqa: E402

_POLICY = {
    "metro": ["springfield", "fairview"],
    "allow_us_remote": True,
    "us_only": True,
    "require_match": True,
}

_REMOTE_JD = (
    "About the team\n\n"
    "This is a fully remote role. You may live anywhere you are authorized\n"
    "to work.\n\n"
    "Available Locations: Remote - United States\n"
)


def _posting(title, location, remote="unknown", description=""):
    return JobPosting(
        source="greenhouse",
        company="Example Board Co",
        title=title,
        url=f"https://example.test/jobs/{title.lower().replace(' ', '-')}",
        location=location,
        remote=remote,
        description=description,
    )


# One posting per decision the gate can reach.
_BOARD = [
    _posting("Platform Engineer", "Springfield, ST"),                # match
    _posting("Reliability Engineer", "London, United Kingdom"),      # no_match
    _posting("Compute Engineer", "In-Office"),                       # review
]


class CompanyRolesVerdictExposureTests(unittest.TestCase):
    def setUp(self):
        self._fetch = company_roles.fetch_company
        self._policy = company_roles._location_policy
        company_roles.fetch_company = lambda entry: list(_BOARD)
        company_roles._location_policy = lambda: dict(_POLICY)
        self.addCleanup(self._restore)

    def _restore(self):
        company_roles.fetch_company = self._fetch
        company_roles._location_policy = self._policy

    def _run(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = company_roles.main()
        return code, buf.getvalue()

    def _main(self, *argv):
        old = sys.argv
        sys.argv = ["company_roles.py", "--ats", "greenhouse",
                    "--token", "example", *argv]
        try:
            return self._run()
        finally:
            sys.argv = old

    def test_gather_carries_the_three_valued_decision(self):
        rows = {r["title"]: r for r in company_roles.gather({"name": "X"})}
        self.assertEqual(rows["Platform Engineer"]["decision"], "match")
        self.assertEqual(rows["Reliability Engineer"]["decision"], "no_match")
        self.assertEqual(rows["Compute Engineer"]["decision"], "review")
        # The narrow bool is False for BOTH non-matches, which is exactly why the
        # decision key has to be there.
        self.assertFalse(rows["Compute Engineer"]["match"])
        self.assertFalse(rows["Reliability Engineer"]["match"])

    def test_json_exposes_decision_workplace_and_review_reasons(self):
        code, out = self._main("--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["matches"], 1)
        self.assertEqual(payload["review"], 1)
        review = [r for r in payload["roles"] if r["decision"] == "review"]
        self.assertEqual(len(review), 1)
        row = review[0]
        for key in ("decision", "workplace", "confidence", "evidence",
                    "review_reasons"):
            self.assertIn(key, row)
        self.assertIn("workplace_tag_without_geography", row["review_reasons"])

    def test_table_labels_review_distinctly_from_a_rejection(self):
        code, out = self._main()
        self.assertEqual(code, 0)
        lines = [ln for ln in out.splitlines() if ln.startswith(("MATCH", "REVIEW", "no "))]
        flags = {ln.split()[1]: ln.split()[0] for ln in lines}
        self.assertEqual(flags["metro"], "MATCH")
        self.assertEqual(flags["foreign"], "no")
        self.assertEqual(flags["unknown"], "REVIEW")
        self.assertIn("workplace_tag_without_geography", out)

    def test_match_only_keeps_review_and_drops_definite_non_matches(self):
        code, out = self._main("--match-only", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        shown = {r["title"]: r["decision"] for r in payload["roles"]}
        self.assertEqual(shown,
                         {"Platform Engineer": "match",
                          "Compute Engineer": "review"})

    def test_bare_hybrid_tag_with_a_remote_jd_is_reported_as_a_match(self):
        # End-to-end shape of the live false negative: the board's location field
        # says "Hybrid", the JD says fully remote.
        company_roles.fetch_company = lambda entry: [
            _posting("Data Platform Engineer", "Hybrid", remote="hybrid",
                     description=_REMOTE_JD)]
        code, out = self._main("--match-only", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["matches"], 1)
        self.assertEqual(payload["roles"][0]["decision"], "match")
        self.assertEqual(payload["roles"][0]["workplace"], "remote")


if __name__ == "__main__":
    unittest.main()
