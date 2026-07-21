import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SEARCH_SCRIPTS = REPO_ROOT / ".agents" / "skills" / "job-search" / "scripts"
SEARCH_VENDOR = SEARCH_SCRIPTS / "_vendor"
for path in (SEARCH_SCRIPTS, SEARCH_VENDOR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from aggregators import _provided_range  # noqa: E402
from common import JobPosting  # noqa: E402
from job_metadata import validate_meta  # noqa: E402
from scoring import experience_ok, parse_min_required_years, score_posting  # noqa: E402
from search_jobs import enrich_posting_metadata  # noqa: E402


class SearchJobMetadataTests(unittest.TestCase):
    def test_hard_filter_uses_only_high_confidence_general_yoe(self):
        contextual = JobPosting(
            source="test",
            company="Acme",
            title="Software Engineer",
            url="https://example.test/contextual",
            description="Requires 8+ years of experience with Kubernetes.",
        )
        required = JobPosting(
            source="test",
            company="Acme",
            title="Software Engineer",
            url="https://example.test/required",
            description="Requires at least 8 years of professional experience.",
        )
        profile = {"max_years_experience": 6}
        self.assertIsNone(parse_min_required_years(contextual.description))
        self.assertTrue(experience_ok(contextual, profile))
        self.assertIsNone(parse_min_required_years(
            "8+ years working with Kubernetes in production."
        ))
        self.assertFalse(experience_ok(required, profile))

    def test_yoe_score_penalty_uses_same_high_confidence_threshold(self):
        profile = {
            "years_experience": 5,
            "seniority": {"yoe_fit_weight": 2},
        }
        contextual = JobPosting(
            source="test", company="Acme", title="Software Engineer",
            url="https://example.test/contextual",
            required_yoe={"min": 8, "confidence": "medium"},
        )
        required = JobPosting(
            source="test", company="Acme", title="Software Engineer",
            url="https://example.test/required",
            required_yoe={"min": 8, "confidence": "high"},
        )
        score_posting(contextual, profile)
        score_posting(required, profile)
        self.assertEqual(contextual.score, 0)
        self.assertEqual(required.score, -6)

    def test_aggregator_rejects_malformed_or_ambiguous_ranges(self):
        invalid = (
            _provided_range(-1, 10, currency="USD", period="year"),
            _provided_range(math.nan, 10, currency="USD", period="year"),
            _provided_range(20, 10, currency="USD", period="year"),
            _provided_range(10, 20, currency=None, period="year"),
            _provided_range(10, 20, currency="USD", period=None),
            _provided_range(10, 20, currency="US", period="year"),
            _provided_range(10, 20, currency="USD", period="mixed"),
        )
        self.assertEqual(invalid, (None,) * len(invalid))

    def test_search_to_metadata_to_schema_v4_validation(self):
        posting = JobPosting(
            source="test",
            company="Acme",
            title="Senior Software Engineer",
            url="https://example.test/jobs/1",
            location="Remote (US)",
            description=(
                "Requires at least 5 years of professional experience. "
                "The annual base salary range is USD $150,000-$200,000 per year."
            ),
            salary_range=_provided_range(
                140000,
                190000,
                currency="USD",
                period="year",
                source="licensed_api",
            ),
        )
        enrich_posting_metadata(posting, {})
        meta = {
            "job_metadata_schema_version": 4,
            "company": posting.company,
            "jobs": [{
                "role": posting.title,
                "jd_file": "JD-senior-software-engineer.md",
                "status": "drafted",
                "workplace": posting.workplace,
                "sponsorship": posting.sponsorship,
                "job_level": posting.job_level,
                "required_yoe": posting.required_yoe,
                "salary_range": posting.salary_range,
            }],
        }
        self.assertEqual(validate_meta(meta), [])
        self.assertEqual(posting.salary_range["source"], "job_description")
        self.assertEqual(posting.workplace, "remote")


if __name__ == "__main__":
    unittest.main()
