import math
import sys
import tempfile
import unittest
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from job_metadata import (  # noqa: E402
    APPLICATION_SCHEMA_VERSION,
    STATUS_VALUES,
    analyze_job_metadata,
    classify_level,
    classify_sponsorship,
    classify_workplace,
    derive_status,
    extract_required_yoe,
    extract_required_yoe_details,
    extract_salary_range,
    load_company_levels,
    pick_candidate,
    validate_meta,
)


def _valid_job(**overrides) -> dict:
    """A schema-v4 jobs entry that passes validation, with optional overrides."""
    job = {
        "role": "Senior Engineer",
        "jd_file": "JD-senior-engineer.md",
        "status": "drafted",
        "location": "Remote (US)",
        "url": "https://example.test/jobs/1",
        "posted_date": "2026-07-18",
        "workplace": "remote",
        "sponsorship": "unknown",
        "job_level": {
            "normalized": "senior",
            "min": 5.0,
            "max": 5.8,
            "confidence": "low",
            "source": "title",
        },
        "required_yoe": {
            "min": 5,
            "max": None,
            "confidence": "high",
            "source": "job_description",
        },
        "salary_range": None,
    }
    job.update(overrides)
    return job


def _valid_meta(**overrides) -> dict:
    meta = {
        "job_metadata_schema_version": APPLICATION_SCHEMA_VERSION,
        "company": "Acme",
        "research_date": "2026-07-19",
        "jobs": [_valid_job()],
    }
    meta.update(overrides)
    return meta


class YoeExtractionTests(unittest.TestCase):
    def test_extracts_most_restrictive_yoe_range(self):
        text = (
            "Requires 3-5 years of Python experience and at least 6 years of "
            "professional experience."
        )
        self.assertEqual(
            extract_required_yoe(text),
            {"min": 6, "max": None, "source": "job_description"},
        )

    def test_keeps_explicit_yoe_upper_bound(self):
        self.assertEqual(
            extract_required_yoe("Candidates should have 4 to 7 years of experience."),
            {"min": 4, "max": 7, "source": "job_description"},
        )

    def test_handles_markdown_escaped_plus(self):
        self.assertEqual(extract_required_yoe(r"Requires 5\+ years of experience.")["min"], 5)

    def test_ignores_preferred_yoe_and_keeps_required_yoe(self):
        text = (
            "Requires at least 4 years of professional experience. "
            "8+ years of experience preferred."
        )
        self.assertEqual(extract_required_yoe(text)["min"], 4)

    def test_contextual_yoe_is_medium_confidence(self):
        details = extract_required_yoe_details(
            "Requires 7+ years of experience with Kubernetes.")
        self.assertEqual(details["min"], 7)
        self.assertEqual(details["requirement_kind"], "contextual")
        self.assertEqual(details["confidence"], "medium")

    def test_required_yoe_is_not_suppressed_by_later_preferred_clause(self):
        details = extract_required_yoe_details(
            "At least 4 years of professional experience required; "
            "8+ years preferred."
        )
        self.assertEqual(details["min"], 4)
        self.assertEqual(details["confidence"], "high")

    def test_no_yoe_reports_not_stated(self):
        details = extract_required_yoe_details("We value curiosity and grit.")
        self.assertIsNone(details["min"])
        self.assertEqual(details["source"], "not_stated")
        self.assertEqual(details["confidence"], "unknown")


class SalaryExtractionTests(unittest.TestCase):
    def test_parses_period_between_salary_bounds(self):
        salary = extract_salary_range(
            "The base salary range is USD $171,000 per year - "
            "USD $190,000 per year."
        )
        self.assertEqual((salary["min"], salary["max"], salary["period"]),
                         (171000, 190000, "year"))

    def test_does_not_combine_hourly_and_annual_salary_ranges(self):
        salary = extract_salary_range(
            "The annual base salary range is $150,000-$200,000 per year. "
            "The hourly base pay range is $70-$95 per hour."
        )
        self.assertIsNone(salary["min"])
        self.assertIsNone(salary["max"])
        self.assertEqual(
            {(band["period"], band["min"]) for band in salary["bands"]},
            {("year", 150000), ("hour", 70)},
        )

    def test_does_not_assume_currency_for_bare_numbers(self):
        self.assertIsNone(
            extract_salary_range(
                "The annual base salary range is 150,000-200,000 per year."))

    def test_ambiguous_hourly_boilerplate_does_not_relabel_annual_bounds(self):
        self.assertIsNone(extract_salary_range(
            "The base salary range (or hourly wage range, if applicable) "
            "is $190,000 to $280,000."
        ))


class AnalyzeTests(unittest.TestCase):
    def test_flat_shape_with_expected_keys(self):
        metadata = analyze_job_metadata(
            company="Acme",
            title="Senior Engineer",
            description="Requires at least 5 years of professional experience.",
        )
        self.assertEqual(
            set(metadata),
            {"workplace", "sponsorship", "job_level", "required_yoe", "salary_range"},
        )
        self.assertEqual(
            set(metadata["job_level"]),
            {"normalized", "min", "max", "confidence", "source"},
        )
        self.assertEqual(
            set(metadata["required_yoe"]),
            {"min", "max", "confidence", "source"},
        )
        self.assertIn(metadata["workplace"], {"onsite", "hybrid", "remote", "unknown"})
        self.assertIn(metadata["sponsorship"], {"likely", "unlikely", "unknown"})

    def test_company_reference_supplies_normalized_level_and_google_range(self):
        reference = {
            "companies": [{
                "name": "Acme",
                "last_verified": "2026-07-19",
                "levels": [{
                    "name": "Engineer 3",
                    "title_patterns": ["Engineer III"],
                    "normalized": "senior",
                    "google_equivalent": {"min": 4.7, "max": 5.3},
                    "required_yoe": {"min": 5, "max": 8},
                }],
            }],
        }
        metadata = analyze_job_metadata(
            company="Acme",
            title="Backend Engineer III",
            description="Build distributed systems.",
            company_levels=reference,
        )
        self.assertEqual(metadata["job_level"]["normalized"], "senior")
        self.assertEqual(metadata["job_level"]["min"], 4.7)
        self.assertEqual(metadata["job_level"]["max"], 5.3)
        self.assertEqual(metadata["job_level"]["source"], "company_reference")
        self.assertEqual(metadata["required_yoe"]["source"], "company_reference")
        self.assertEqual(metadata["required_yoe"]["min"], 5)
        self.assertIsNone(metadata["salary_range"])

    def test_company_alias_ignores_legal_suffix_punctuation(self):
        reference = {
            "companies": [{
                "name": "Amazon",
                "aliases": ["Amazon Web Services"],
                "levels": [{
                    "name": "SDE II",
                    "title_patterns": ["Software Development Engineer II"],
                    "normalized": "mid",
                    "google_equivalent": {"min": 4.0, "max": 4.7},
                }],
            }],
        }
        metadata = analyze_job_metadata(
            company="Amazon Web Services, Inc.",
            title="Software Development Engineer II",
            description="",
            company_levels=reference,
        )
        self.assertEqual(metadata["job_level"]["normalized"], "mid")
        self.assertEqual(metadata["job_level"]["source"], "company_reference")

    def test_yoe_fills_level_when_title_is_unleveled(self):
        metadata = analyze_job_metadata(
            company="Unknown",
            title="Software Engineer",
            description="Requires 5+ years of professional experience.",
        )
        self.assertEqual(metadata["job_level"]["normalized"], "senior")
        self.assertEqual(metadata["job_level"]["source"], "required_yoe")
        self.assertEqual(metadata["job_level"]["min"], 5.0)

    def test_unknown_level_has_null_google_range(self):
        metadata = analyze_job_metadata(
            company="Unknown",
            title="Solutions Architect",
            description="Design solutions.",
        )
        self.assertEqual(metadata["job_level"]["normalized"], "unknown")
        self.assertIsNone(metadata["job_level"]["min"])
        self.assertIsNone(metadata["job_level"]["max"])

    def test_analyze_reads_yoe_stated_in_title(self):
        metadata = analyze_job_metadata(
            company="Unknown",
            title="Software Engineer (3+ Years)",
            description="Build distributed systems.",
        )
        self.assertEqual(metadata["required_yoe"]["min"], 3)
        self.assertEqual(metadata["required_yoe"]["source"], "job_description")

    def test_architect_is_not_generic_principal(self):
        self.assertEqual(classify_level("Solutions Architect")[0], "unknown")

    def test_member_of_technical_staff_is_not_staff_level(self):
        # The trailing "Staff" in the MTS role family must not read as L6 Staff.
        self.assertEqual(classify_level("Member of Technical Staff")[0], "unknown")
        self.assertEqual(
            classify_level("Member of the Technical Staff")[0], "unknown")
        self.assertEqual(
            classify_level("Members of Technical Staff")[0], "unknown")
        # A real seniority prefix on an MTS title still classifies by that prefix.
        self.assertEqual(
            classify_level("Senior Member of Technical Staff")[0], "senior")
        self.assertEqual(
            classify_level("Principal Member of Technical Staff")[0], "principal")
        self.assertEqual(
            classify_level("Distinguished Member of Technical Staff")[0],
            "distinguished")
        # Genuine Staff-level titles are unaffected.
        self.assertEqual(classify_level("Staff Software Engineer")[0], "staff")
        self.assertEqual(classify_level("Senior Staff Engineer")[0], "senior_staff")

    def test_live_jd_salary_is_flat_and_high_confidence(self):
        metadata = analyze_job_metadata(
            company="Acme",
            title="Senior Engineer",
            description="The base salary range is $170,000-$210,000 per year.",
            supplied_salary_range={
                "min": 150000,
                "max": 190000,
                "source": "adzuna_api",
            },
        )
        self.assertEqual(metadata["salary_range"]["min"], 170000)
        self.assertEqual(metadata["salary_range"]["max"], 210000)
        self.assertEqual(metadata["salary_range"]["confidence"], "high")
        self.assertEqual(metadata["salary_range"]["source"], "job_description")

    def test_supplied_salary_used_only_when_jd_has_none(self):
        metadata = analyze_job_metadata(
            company="Acme",
            title="Senior Engineer",
            description="No pay information here.",
            supplied_salary_range={
                "min": 150000,
                "max": 190000,
                "source": "adzuna_api",
            },
        )
        self.assertEqual(metadata["salary_range"]["min"], 150000)
        self.assertEqual(metadata["salary_range"]["confidence"], "medium")
        self.assertEqual(metadata["salary_range"]["source"], "adzuna_api")

    def test_no_salary_anywhere_is_null(self):
        metadata = analyze_job_metadata(
            company="Acme",
            title="Senior Engineer",
            description="Requires 5+ years of experience.",
        )
        self.assertIsNone(metadata["salary_range"])


class WorkplaceTests(unittest.TestCase):
    def test_location_remote_wins(self):
        self.assertEqual(classify_workplace("Remote (US)"), "remote")

    def test_location_hybrid_wins_over_city(self):
        self.assertEqual(classify_workplace("San Francisco, CA (Hybrid)"), "hybrid")

    def test_concrete_city_is_onsite(self):
        self.assertEqual(classify_workplace("Seattle, WA"), "onsite")

    def test_falls_back_to_description_when_no_location(self):
        self.assertEqual(
            classify_workplace("", "This role is fully remote across the US."),
            "remote",
        )

    def test_unknown_when_nothing_signals_arrangement(self):
        self.assertEqual(classify_workplace("", "Build great products."), "unknown")

    def test_analyze_sets_workplace_from_location(self):
        metadata = analyze_job_metadata(
            company="Acme", title="Engineer", description="", location="Austin, TX")
        self.assertEqual(metadata["workplace"], "onsite")


class SponsorshipTests(unittest.TestCase):
    def test_explicit_denial_is_unlikely(self):
        self.assertEqual(
            classify_sponsorship("We do not offer sponsorship for this role."),
            "unlikely",
        )

    def test_explicit_offer_is_likely(self):
        self.assertEqual(
            classify_sponsorship("H-1B sponsorship available for strong candidates."),
            "likely",
        )

    def test_denial_beats_offer(self):
        self.assertEqual(
            classify_sponsorship(
                "We sponsor visas in some cases, but this role has no sponsorship."),
            "unlikely",
        )

    def test_silent_posting_is_unknown(self):
        self.assertEqual(
            classify_sponsorship("Join our platform team building distributed systems."),
            "unknown",
        )

    # Regression: two real-world denial wordings the phrase list missed (GH issue
    # #15 negation-phrase residual). Both previously classified as "likely" — a
    # false positive — because the negation was missed while a positive substring
    # ("immigration sponsorship" / "provide visa sponsorship") matched.
    def test_immigration_sponsorship_will_not_be_available_is_unlikely(self):
        self.assertEqual(
            classify_sponsorship(
                "Immigration Sponsorship support will NOT be available for this position"),
            "unlikely",
        )

    def test_unable_to_provide_visa_sponsorship_is_unlikely(self):
        self.assertEqual(
            classify_sponsorship("We are unable to provide visa sponsorship."),
            "unlikely",
        )

    def test_analyze_sets_sponsorship_from_description(self):
        metadata = analyze_job_metadata(
            company="Acme",
            title="Engineer",
            description="This position does not sponsor work visas.",
        )
        self.assertEqual(metadata["sponsorship"], "unlikely")


class ReferenceCacheTests(unittest.TestCase):
    def test_manual_override_beats_higher_tier(self):
        manual = {
            "min": 100000,
            "max": 120000,
            "provenance": {
                "tier": "market_benchmark",
                "provider": "manual",
                "confidence": "high",
                "manual_override": True,
            },
        }
        live = {
            "min": 130000,
            "max": 150000,
            "provenance": {
                "tier": "live_jd",
                "provider": "job_description",
                "confidence": "high",
            },
        }
        self.assertIs(pick_candidate(live, manual), manual)

    def test_fresher_fact_wins_within_same_tier(self):
        old = {
            "min": 1, "max": 2,
            "provenance": {
                "tier": "market_benchmark",
                "provider": "licensed_export",
                "confidence": "medium",
                "retrieved_at": "2025-01-01",
            },
        }
        new = {
            "min": 1, "max": 2,
            "provenance": {
                "tier": "market_benchmark",
                "provider": "licensed_export",
                "confidence": "medium",
                "retrieved_at": "2026-01-01",
            },
        }
        self.assertIs(pick_candidate(old, new), new)

    def test_v1_cache_is_normalized_with_per_fact_provenance(self):
        content = """
schema_version: 1
companies:
  - name: Acme
    last_verified: "2026-07-19"
    sources:
      - https://www.levels.fyi/companies/acme/salaries/software-engineer
      - https://acme.example/careers/levels
    levels:
      - name: Engineer II
        normalized: mid
        google_equivalent: {min: 4.0, max: 4.6}
        required_yoe: {min: 2, max: 5}
        compensation:
          salary_range: {min: 120000, max: 150000, currency: USD, period: year}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "company-levels.yaml"
            path.write_text(content)
            reference = load_company_levels(path)
        level = reference["companies"][0]["levels"][0]
        self.assertEqual(reference["schema_version"], 2)
        self.assertEqual(
            level["google_equivalent"]["provenance"]["tier"],
            "market_benchmark",
        )
        self.assertEqual(
            level["compensation"]["salary_range"]["provenance"]["tier"],
            "employer_official",
        )


class ValidationTests(unittest.TestCase):
    def test_valid_meta_passes(self):
        self.assertEqual(validate_meta(_valid_meta()), [])

    def test_missing_schema_version_is_rejected(self):
        meta = _valid_meta()
        del meta["job_metadata_schema_version"]
        self.assertEqual(
            validate_meta(meta),
            ["job_metadata_schema_version must be 4"],
        )

    def test_old_schema_version_is_rejected(self):
        # v3 is now legacy: it is rejected outright, not migrated.
        self.assertEqual(
            validate_meta({"job_metadata_schema_version": 3}),
            ["job_metadata_schema_version must be 4"],
        )

    def test_float_schema_version_is_rejected(self):
        self.assertEqual(
            validate_meta({"job_metadata_schema_version": 4.0}),
            ["job_metadata_schema_version must be 4"],
        )

    def test_jobs_list_is_required(self):
        errors = validate_meta({
            "job_metadata_schema_version": APPLICATION_SCHEMA_VERSION,
            "company": "Acme",
        })
        self.assertIn(
            "jobs must be a non-empty list (one entry per posting)", errors)

    def test_company_is_required(self):
        meta = _valid_meta(company="")
        self.assertIn("company is required", validate_meta(meta))

    def test_role_and_jd_file_required_per_job(self):
        meta = _valid_meta(jobs=[_valid_job(role="", jd_file="")])
        errors = validate_meta(meta)
        self.assertIn("jobs[0].role is required", errors)
        self.assertIn("jobs[0].jd_file is required", errors)

    def test_invalid_confidence_is_rejected(self):
        job = _valid_job()
        job["job_level"]["confidence"] = "definitely"
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertTrue(any(
            "jobs[0].job_level.confidence must be one of" in error
            for error in errors))

    def test_invalid_normalized_level_is_rejected(self):
        job = _valid_job()
        job["job_level"]["normalized"] = "wizard"
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertTrue(any(
            "jobs[0].job_level.normalized must be one of" in error
            for error in errors))

    def test_negative_and_nan_ranges_are_rejected(self):
        job = _valid_job()
        job["required_yoe"]["min"] = -1
        job["job_level"]["max"] = math.nan
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertIn("jobs[0].required_yoe.min must be non-negative", errors)
        self.assertIn("jobs[0].job_level.max must be finite", errors)

    def test_salary_range_may_be_null(self):
        self.assertEqual(validate_meta(_valid_meta()), [])

    def test_salary_range_requires_a_bound_when_present(self):
        job = _valid_job(salary_range={
            "min": None, "max": None, "confidence": "high", "source": "job_description",
        })
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertTrue(any(
            "jobs[0].salary_range must contain at least one numeric bound" in error
            for error in errors))

    def test_missing_structured_field_is_reported(self):
        job = _valid_job()
        del job["salary_range"]
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertIn("jobs[0].salary_range is missing", errors)

    def test_missing_workplace_and_sponsorship_are_reported(self):
        job = _valid_job()
        del job["workplace"]
        del job["sponsorship"]
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertIn("jobs[0].workplace is required", errors)
        self.assertIn("jobs[0].sponsorship is required", errors)

    def test_invalid_workplace_and_sponsorship_are_rejected(self):
        job = _valid_job(workplace="in_office", sponsorship="maybe")
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertTrue(any(
            "jobs[0].workplace must be one of" in error for error in errors))
        self.assertTrue(any(
            "jobs[0].sponsorship must be one of" in error for error in errors))

    def test_checks_exact_multi_role_jd_files_with_app_dir(self):
        job = _valid_job()
        with tempfile.TemporaryDirectory() as temporary:
            app_dir = Path(temporary)
            source = app_dir / "source"
            source.mkdir()
            (source / "JD-backend.md").write_text("Backend")
            (source / "JD-platform.md").write_text("Platform")
            meta = _valid_meta(jobs=[
                {**job, "role": "Backend", "jd_file": "JD-backend.md"},
                {**job, "role": "Platform", "jd_file": "JD-backend.md"},
            ])
            errors = validate_meta(meta, app_dir=app_dir)
        self.assertTrue(any("duplicates another role" in error for error in errors))
        self.assertTrue(any(
            "unreferenced JD file: JD-platform.md" in error for error in errors))


class DeriveStatusTests(unittest.TestCase):
    def _jobs(self, *statuses) -> list:
        return [{"status": s} for s in statuses]

    def test_all_rejected_rolls_up_to_rejected(self):
        self.assertEqual(derive_status(self._jobs("rejected", "rejected")), "rejected")

    def test_in_progress_beats_applied_beats_drafted(self):
        self.assertEqual(
            derive_status(self._jobs("drafted", "applied", "in_progress")),
            "in_progress")
        self.assertEqual(
            derive_status(self._jobs("drafted", "applied")), "applied")
        self.assertEqual(
            derive_status(self._jobs("drafted", "drafted")), "drafted")

    def test_drafted_beats_rejected_beats_ignored(self):
        self.assertEqual(
            derive_status(self._jobs("ignored", "rejected", "drafted")), "drafted")
        self.assertEqual(
            derive_status(self._jobs("ignored", "rejected")), "rejected")
        self.assertEqual(derive_status(self._jobs("ignored")), "ignored")

    def test_mixed_applied_and_rejected_is_applied(self):
        self.assertEqual(
            derive_status(self._jobs("applied", "rejected")), "applied")

    def test_precedence_order_is_documented_constant(self):
        self.assertEqual(
            STATUS_VALUES,
            ("in_progress", "applied", "drafted", "rejected", "ignored"))

    def test_empty_or_invalid_jobs_raise(self):
        with self.assertRaises(ValueError):
            derive_status([])
        with self.assertRaises(ValueError):
            derive_status([{"status": "offer"}])
        with self.assertRaises(ValueError):
            derive_status([{"role": "no status here"}])


class SchemaV4JobFieldTests(unittest.TestCase):
    def test_missing_status_is_rejected(self):
        job = _valid_job()
        del job["status"]
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertIn("jobs[0].status is required", errors)

    def test_bad_status_enum_is_rejected(self):
        errors = validate_meta(_valid_meta(jobs=[_valid_job(status="offer")]))
        self.assertTrue(any(
            "jobs[0].status must be one of" in error for error in errors))

    def test_optional_stage_and_status_date_pass(self):
        job = _valid_job(status="applied", stage="onsite", status_date="2026-07-20")
        self.assertEqual(validate_meta(_valid_meta(jobs=[job])), [])

    def test_non_string_stage_is_rejected(self):
        errors = validate_meta(_valid_meta(jobs=[_valid_job(stage=42)]))
        self.assertIn("jobs[0].stage must be a string", errors)

    def test_bad_status_date_format_is_rejected(self):
        errors = validate_meta(_valid_meta(jobs=[_valid_job(status_date="07/20/2026")]))
        self.assertTrue(any(
            "jobs[0].status_date must be a YYYY-MM-DD" in error for error in errors))

    def test_impossible_status_date_is_rejected(self):
        errors = validate_meta(_valid_meta(jobs=[_valid_job(status_date="2026-13-40")]))
        self.assertTrue(any("status_date" in error for error in errors))

    def test_top_level_stage_is_rejected(self):
        errors = validate_meta(_valid_meta(stage="onsite"))
        self.assertTrue(any(
            "top-level stage is not allowed" in error for error in errors))

    def test_top_level_status_is_rejected(self):
        errors = validate_meta(_valid_meta(status="applied"))
        self.assertTrue(any(
            "top-level status is not allowed" in error for error in errors))

    def test_folder_consistency_mismatch_is_flagged(self):
        # A drafted posting sitting in the 5_applied folder must be flagged.
        with tempfile.TemporaryDirectory() as temporary:
            applied = Path(temporary) / "5_applied"
            app_dir = applied / "acme-senior-engineer-20260720"
            source = app_dir / "source"
            source.mkdir(parents=True)
            (source / "JD-senior-engineer.md").write_text("Senior")
            meta = _valid_meta(jobs=[_valid_job(status="drafted")])
            errors = validate_meta(meta, app_dir=app_dir)
        self.assertTrue(any(
            "folder status 'applied' does not match derived status 'drafted'" in error
            for error in errors))

    def test_folder_consistency_holds_when_folder_matches_rollup(self):
        with tempfile.TemporaryDirectory() as temporary:
            applied = Path(temporary) / "5_applied"
            app_dir = applied / "acme-senior-engineer-20260720"
            source = app_dir / "source"
            source.mkdir(parents=True)
            (source / "JD-senior-engineer.md").write_text("Senior")
            meta = _valid_meta(jobs=[_valid_job(status="applied")])
            self.assertEqual(validate_meta(meta, app_dir=app_dir), [])


if __name__ == "__main__":
    unittest.main()
