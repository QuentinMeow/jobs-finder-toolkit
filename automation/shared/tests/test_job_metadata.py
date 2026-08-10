import math
import sys
import tempfile
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from job_metadata import (  # noqa: E402
    APPLICATION_SCHEMA_VERSION,
    STATUS_VALUES,
    _compensation_range,
    _salary_envelope,
    analyze_job_metadata,
    assess_required_yoe,
    assess_sponsorship,
    classify_level,
    classify_sponsorship,
    classify_workplace,
    derive_status,
    extract_required_yoe,
    extract_required_yoe_details,
    extract_salary_range,
    load_company_levels,
    pick_candidate,
    validate_job_metadata,
    validate_meta,
)


def _valid_job(**overrides) -> dict:
    """A schema-v6 jobs entry that passes validation, with optional overrides."""
    job = {
        "role": "Senior Engineer",
        "jd_file": "JD-senior-engineer.md",
        "status": "drafted",
        "progress": {"phase": "application_prep", "state": "action_required"},
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

    def test_escaped_range_dash_still_parses_as_a_range(self):
        # markdownify escapes a hyphen that could start a list item, so a JD
        # fetched through JobSpy arrives as "3\-5 years". The escape hid the
        # range separator, the range matched nothing, and a min-only pattern then
        # read the range's UPPER bound as a standalone minimum: the band's
        # CEILING became its FLOOR, which over-states the requirement and
        # hard-drops a posting the candidate qualifies for. Escaped and
        # unescaped text must grade identically, bound for bound.
        for escaped, plain in (
            (r"1\-3 years of experience.", "1-3 years of experience."),
            (r"3\-5+ years of experience.", "3-5+ years of experience."),
            (r"Requires 5 \- 8 years of professional experience.",
             "Requires 5 - 8 years of professional experience."),
        ):
            with self.subTest(text=escaped):
                self.assertEqual(
                    extract_required_yoe_details(escaped),
                    extract_required_yoe_details(plain),
                )
        # And the specific numbers, so an equal-but-both-wrong pair cannot pass.
        details = extract_required_yoe_details(r"3\-5+ years of experience.")
        self.assertEqual((details["min"], details["max"]), (3, 5))

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

    def test_general_requirement_not_contaminated_by_adjacent_clause(self):
        # A high, general requirement immediately followed by a lower, contextual
        # leadership clause must stay high/general — the adjacent clause's wording
        # must not bleed into this match's look-ahead and mark it contextual.
        text = (
            "Requires 15+ years of software engineering experience with at least "
            "5+ years in senior leadership roles."
        )
        details = extract_required_yoe_details(text)
        self.assertEqual(details["min"], 15)
        self.assertEqual(details["confidence"], "high")
        self.assertEqual(details["requirement_kind"], "required")

    def test_high_general_requirement_hard_gates_over_cap(self):
        # The same adjacency, now exercised through the shared tri-state gate: a
        # decisive 15-year minimum above the cap is a hard no_match, not review.
        text = (
            "Requires 15+ years of software engineering experience with at least "
            "5+ years in senior leadership roles."
        )
        self.assertEqual(assess_required_yoe(text, cap=8)["decision"], "no_match")
        self.assertEqual(assess_required_yoe(text, cap=20)["decision"], "match")

    def test_adjacent_tool_clauses_stay_contextual_review(self):
        # Two genuine tool/domain clauses joined by a conjunction: each stays
        # contextual/medium, so the decisive requirement is a non-hard-drop review
        # rather than being wrongly promoted to a high, general gate.
        text = (
            "Requires 8+ years of experience with Kubernetes and 5+ years working "
            "with Terraform."
        )
        result = assess_required_yoe(text, cap=8)
        self.assertEqual(result["decision"], "review")
        self.assertEqual(result["min"], 8)
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["requirement_kind"], "contextual")


class GeneralVersusToolSpecificYoeTests(unittest.TestCase):
    """The boundary the confidence grade turns on, from BOTH sides.

    "<N> years of experience" is the most common way an English job post states
    a seniority requirement, and it was graded tool-specific: the contextual
    regex's optional ``(?:of\\s+)?`` backtracked and let the preposition "of" BE
    the tool name, so "8 years <of> experience" read as a domain requirement.
    Only a HIGH-confidence grade is decisive, so the documented
    ``max_years_experience`` cap silently did nothing on exactly those postings.

    The fix must move ONLY that side. A specialty requirement ("8 years of
    experience WITH Kubernetes") is deliberately non-decisive — the candidate
    may well be hired without eight Kubernetes years — so it must stay medium
    even when the sentence carries a hard requirement cue.
    """

    CUES = ("Requirements: ", "Minimum ", "At least ", "You must have ",
            "Qualifications: ")

    def test_a_cued_general_requirement_is_decisive(self):
        for cue in self.CUES:
            text = f"Software Engineer\n{cue}8+ years of experience."
            with self.subTest(cue=cue):
                details = extract_required_yoe_details(text)
                self.assertEqual(details["min"], 8)
                self.assertEqual(details["confidence"], "high")
                self.assertEqual(details["requirement_kind"], "required")
                self.assertEqual(
                    assess_required_yoe(text, cap=6)["decision"], "no_match")
                self.assertEqual(
                    assess_required_yoe(text, cap=10)["decision"], "match")

    def test_a_cued_tool_specific_requirement_stays_non_decisive(self):
        # The other side of the same boundary: same cue, same number, one
        # prepositional phrase apart. None of these may become a hard drop.
        tails = (
            "of experience with Kubernetes.",
            "of experience in distributed systems.",
            "of experience with Python, Go, and Kubernetes.",
            "working with Terraform.",
            "of Kubernetes experience.",
        )
        for cue in self.CUES:
            for tail in tails:
                text = f"Software Engineer\n{cue}8+ years {tail}"
                with self.subTest(cue=cue, tail=tail):
                    details = extract_required_yoe_details(text)
                    self.assertEqual(details["min"], 8)
                    self.assertEqual(details["confidence"], "medium")
                    self.assertEqual(details["requirement_kind"], "contextual")
                    self.assertEqual(
                        assess_required_yoe(text, cap=6)["decision"], "review")

    def test_an_uncued_general_requirement_stays_medium(self):
        # Unchanged, deliberate design (corpus case `yoe-weak-general-required`):
        # no requirement cue AND no professional/industry qualifier is a review,
        # not a gate. The fix corrects the KIND without promoting the grade.
        details = extract_required_yoe_details(
            "Software Engineer\n8+ years of experience.")
        self.assertEqual(details["confidence"], "medium")
        self.assertEqual(details["requirement_kind"], "required")
        self.assertEqual(
            assess_required_yoe("Software Engineer\n8+ years of experience.",
                                cap=6)["decision"],
            "review",
        )


class ThirdPartyYoeAttributionTests(unittest.TestCase):
    """Years the JD attributes to somebody else are not the candidate's.

    Each About-us sentence below is fictional. All of them used to be read as a
    high-confidence minimum, which hard-dropped the posting under
    ``max_years_experience`` and wrote a fabricated ``required_yoe`` +
    ``job_level`` into tracking metadata.
    """

    def test_founders_experience_is_not_a_requirement(self):
        details = extract_required_yoe_details(
            "Our founders bring 25 years of engineering experience.")
        self.assertIsNone(details["min"])
        self.assertEqual(details["source"], "not_stated")
        self.assertEqual(details["confidence"], "unknown")

    def test_combined_team_total_is_not_a_requirement(self):
        details = extract_required_yoe_details(
            "Our team has 30 years of combined software engineering experience.")
        self.assertIsNone(details["min"])
        self.assertEqual(details["requirement_kind"], "not_stated")

    def test_customer_experience_is_not_a_requirement(self):
        details = extract_required_yoe_details(
            "We serve customers who have 40 years of industry experience.")
        self.assertIsNone(details["min"])

    def test_company_blurb_does_not_outrank_the_real_requirement(self):
        # The multi-sentence case: the wrong number must not win just because it
        # is larger, in either order.
        blurb = "Our founders bring 25 years of engineering experience."
        requirement = ("Requires 3+ years of professional software engineering "
                       "experience.")
        for text in (f"{blurb} {requirement}", f"{requirement} {blurb}"):
            with self.subTest(text=text):
                details = extract_required_yoe_details(text)
                self.assertEqual(details["min"], 3)
                self.assertEqual(details["confidence"], "high")

    def test_company_blurb_no_longer_hard_drops_the_posting(self):
        text = ("Our founders bring 25 years of engineering experience. "
                "Requires 3+ years of professional software engineering "
                "experience.")
        self.assertEqual(assess_required_yoe(text, cap=8)["decision"], "match")

    def test_company_blurb_does_not_fabricate_metadata(self):
        # The metadata cascade: no requirement, so no YOE-derived seniority.
        metadata = analyze_job_metadata(
            company="Unknown",
            title="Software Engineer",
            description="Our founders bring 25 years of engineering experience.",
        )
        self.assertIsNone(metadata["required_yoe"]["min"])
        self.assertEqual(metadata["required_yoe"]["source"], "not_stated")
        self.assertEqual(metadata["job_level"]["normalized"], "unknown")

    # --- guardrails: the guard must not eat a real requirement --------------
    def test_requirement_after_a_company_subject_still_counts(self):
        details = extract_required_yoe_details(
            "Our engineering team is hiring an engineer with 6+ years of "
            "professional experience.")
        self.assertEqual(details["min"], 6)
        self.assertEqual(details["confidence"], "high")

    def test_we_are_looking_for_still_counts(self):
        details = extract_required_yoe_details(
            "We are looking for an engineer with 6+ years of professional "
            "experience.")
        self.assertEqual(details["min"], 6)
        self.assertEqual(details["confidence"], "high")

    def test_we_have_an_opening_still_counts(self):
        details = extract_required_yoe_details(
            "We have an opening for an engineer with 6+ years of professional "
            "experience.")
        self.assertEqual(details["min"], 6)
        self.assertEqual(details["confidence"], "high")


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

    def test_the_word_remote_between_the_keyword_and_the_number_is_not_ote(self):
        # "ote" (on-target earnings) is a _TOTAL_TERMS token, and the keyword
        # NEAREST the number decides base-vs-total.  Found unanchored, it matched
        # inside "rem-OTE-", so an ordinary "this is a fully remote position"
        # sentence beat "base salary" and the whole range was discarded.
        salary = extract_salary_range(
            "The base salary range for this role is, for a fully remote "
            "position, $150,000 - $200,000 per year."
        )
        self.assertIsNotNone(salary)
        self.assertEqual((salary["min"], salary["max"]), (150000, 200000))

    def test_remote_does_not_relabel_a_base_range_as_total_comp(self):
        self.assertIsNone(_compensation_range(
            "The base salary range for this remote role is $150,000 - $200,000 "
            "per year.", total=True))

    def test_standalone_ote_still_reads_as_total_compensation(self):
        total = _compensation_range(
            "OTE for this role is $150,000 - $200,000 per year.", total=True)
        self.assertEqual((total["min"], total["max"]), (150000, 200000))
        self.assertIsNone(extract_salary_range(
            "OTE for this role is $150,000 - $200,000 per year."))


class ImplausibleSalaryBandTests(unittest.TestCase):
    """A band whose two ends were never a pair must be dropped, not reported.

    A live sweep printed "$240 - $175,000" for one posting — a three-digit low
    against a six-digit high, which no employer states. Two independent routes
    reach that shape, so each gets its own case below; the last two cases pin
    that the guards do not eat a band that is merely UNUSUAL.
    """

    def test_stipend_range_beside_the_salary_range_does_not_garble_the_band(self):
        # ROUTE 1 — two individually well-formed matches in one paragraph. The
        # nearest preceding keyword to BOTH is "base salary", so both were kept,
        # and _salary_envelope collapsed them to (min of mins, max of maxs) =
        # (240, 175000). Only the stipend band is wrong; the salary band survives.
        salary = extract_salary_range(
            "Compensation. The base salary range for this role is "
            "$140,000 - $175,000 per year. We also offer an annual wellness "
            "stipend of $240 - $300."
        )
        self.assertEqual((salary["min"], salary["max"]), (140000, 175000))
        self.assertNotIn("bands", salary)

    def test_a_digit_fragment_of_a_longer_figure_is_not_a_salary_bound(self):
        # ROUTE 2 — one match, one fabricated end. The bare 2-3 digit alternative
        # was unanchored, so the scan slid past the leading "3" of "$3240" and
        # read "240" as the low bound of a real $175,000 high.
        self.assertIsNone(extract_salary_range(
            "The annual base salary is $3240 - $175,000 per year."))

    def test_cents_do_not_void_a_salary_band(self):
        # The digit guard that closes the fragment route above was strict enough
        # to reject every well-formed decimal too: a posting that writes its band
        # with cents parsed as NOTHING, and deleting the cents by hand made the
        # same sentence parse. Cents are part of the figure, so the band is read
        # and rounded — the guard still runs after the cents group, which is what
        # keeps the fragment case above passing.
        for text, expected in (
            ("The base salary range is $60,000.00 - $90,000.00 per year.",
             (60000, 90000)),
            ("The base salary range is $120,500.50 - $150,750.25 per year.",
             (120500, 150750)),
            ("The base salary range is $1,000,000.00 - $1,200,000.00 per year.",
             (1000000, 1200000)),
        ):
            with self.subTest(text=text):
                salary = extract_salary_range(text)
                self.assertIsNotNone(salary)
                self.assertEqual((salary["min"], salary["max"]), expected)
        # A three-decimal figure is not a cents figure; refuse rather than
        # truncate, so the guard cannot become a new fragment route.
        self.assertIsNone(extract_salary_range(
            "The base salary range is $60,000.000 - $90,000.000 per year."))

    def test_hourly_range_and_hourly_rate_are_pay_keywords(self):
        # An hourly posting states pay in its own vocabulary. Neither spelling
        # was on the salary-keyword list, so the identical band parsed under
        # "pay range" and vanished under "hourly range" / "hourly rate".
        for text in (
            "The target hourly range for this role is $21 - $25 per hour.",
            "The hourly rate is $21 - $25 per hour.",
            "The pay range is $21 - $25 per hour.",
        ):
            with self.subTest(text=text):
                salary = extract_salary_range(text)
                self.assertIsNotNone(salary)
                self.assertEqual(
                    (salary["min"], salary["max"], salary["period"]),
                    (21, 25, "hour"))

    def test_stitched_envelope_orders_of_magnitude_apart_reports_nothing(self):
        # The backstop, unit-tested directly: even when every band is individually
        # credible, the collapse can hand back a pair no posting stated. There is
        # no way to tell which end is the salary, so neither is reported.
        fact = {
            "bands": [
                {"min": 15_000, "max": 24_000, "period": "year"},
                {"min": 180_000, "max": 220_000, "period": "year"},
            ],
            "source": "job_description",
        }
        self.assertEqual(_salary_envelope(fact), (None, None))

    def test_ordinary_annual_bands_still_parse(self):
        for text, expected in (
            ("The base salary range is $176,000 - $230,000 per year.",
             (176000, 230000)),
            ("The base salary range is $176k - $230k per year.",
             (176000, 230000)),
        ):
            with self.subTest(text=text):
                salary = extract_salary_range(text)
                self.assertEqual((salary["min"], salary["max"]), expected)

    def test_correct_but_unusual_bands_survive(self):
        # A three-digit low is only implausible AGAINST a six-digit high. Hourly
        # rates and part-time monthly bands are real, and each is judged against
        # its own period's floor rather than an annual one.
        hourly = extract_salary_range(
            "The base pay range for this role is $48 - $62 per hour.")
        self.assertEqual(
            (hourly["min"], hourly["max"], hourly["period"]), (48, 62, "hour"))
        monthly = extract_salary_range(
            "The base salary for this part-time role is $3,000 - $4,000 per month.")
        self.assertEqual(
            (monthly["min"], monthly["max"], monthly["period"]),
            (3000, 4000, "month"))

    def test_the_garbled_band_never_reaches_meta_yaml(self):
        # The field this defect is judged on: salary_range is written into
        # meta.yaml by --enrich-metadata and shown in the shortlist as fact.
        metadata = analyze_job_metadata(
            company="ExampleCorp",
            title="Senior Backend Engineer",
            description=(
                "The base salary range for this role is $140,000 - $175,000 per "
                "year, plus an annual wellness stipend of $240 - $300."
            ),
        )
        self.assertEqual(
            (metadata["salary_range"]["min"], metadata["salary_range"]["max"]),
            (140000, 175000),
        )


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

    def test_the_supplied_range_keeps_its_unit(self):
        # The unit used to be dropped here. `common.provided_salary_range` only
        # ever emits a range carrying BOTH an explicit currency and an explicit
        # period, so a contract role arrived fully labelled as $30-$35 per HOUR
        # and left as a bare {30, 35} — the same shape a $30k-$35k annual band
        # takes. Nothing downstream could tell the two apart.
        hourly = analyze_job_metadata(
            company="Acme",
            title="Contract Engineer",
            description="No pay information here.",
            supplied_salary_range={
                "min": 30, "max": 35, "currency": "USD",
                "period": "hour", "source": "jobspy_api",
            },
        )["salary_range"]
        self.assertEqual(
            (hourly["min"], hourly["max"], hourly["period"], hourly["currency"]),
            (30, 35, "hour", "USD"))
        annual = analyze_job_metadata(
            company="Acme",
            title="Engineer",
            description="No pay information here.",
            supplied_salary_range={
                "min": 30000, "max": 35000, "currency": "USD",
                "period": "year", "source": "jobspy_api",
            },
        )["salary_range"]
        self.assertEqual(annual["period"], "year")
        # A supplied range with no unit invents none rather than assuming annual.
        bare = analyze_job_metadata(
            company="Acme",
            title="Engineer",
            description="No pay information here.",
            supplied_salary_range={"min": 30, "max": 35, "source": "legacy"},
        )["salary_range"]
        self.assertNotIn("period", bare)
        self.assertNotIn("currency", bare)

    def test_a_jd_parsed_salary_is_labelled_annual(self):
        # _salary_envelope only ever returns an ANNUAL band, so the flat field
        # can state its unit as fact rather than leaving the reader to assume it.
        salary = analyze_job_metadata(
            company="Acme",
            title="Senior Engineer",
            description="The base salary range is £170,000-£210,000 per year.",
        )["salary_range"]
        self.assertEqual(
            (salary["period"], salary["currency"]), ("year", "GBP"))

    def test_the_unit_survives_schema_validation(self):
        # salary_range is written into meta.yaml; the two new keys must not make
        # a generated record fail the schema the tracker validates against.
        metadata = analyze_job_metadata(
            company="Acme",
            title="Contract Engineer",
            description="No pay information here.",
            supplied_salary_range={
                "min": 30, "max": 35, "currency": "USD",
                "period": "hour", "source": "jobspy_api",
            },
        )
        record = {
            "role": "Contract Engineer",
            "status": "drafted",
            "progress": {"phase": "application_prep", "state": "action_required"},
            **metadata,
        }
        self.assertEqual(validate_job_metadata(record), [])


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

    def test_office_list_reads_remote_alternative_from_full_description(self):
        description = (
            "x" * 1900
            + " This role can be held from one of our US hubs or remotely "
              "in the United States."
        )
        self.assertEqual(
            classify_workplace(
                "San Francisco, CA • New York, NY • United States",
                description,
            ),
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

    def test_conflicting_offer_and_denial_requires_review(self):
        self.assertEqual(
            classify_sponsorship(
                "We sponsor visas in some cases, but this role has no sponsorship."),
            "unknown",
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

    def test_visa_sponsorship_will_not_be_available_is_unlikely(self):
        # Explicit "visa sponsorship will not be available" subject wording.
        self.assertEqual(
            classify_sponsorship(
                "Please note: visa sponsorship will not be available for this role."),
            "unlikely",
        )

    def test_non_immigration_sponsorship_copy_is_unknown(self):
        self.assertEqual(
            classify_sponsorship(
                "We sponsor employee learning programs and community events."),
            "unknown",
        )

    def test_analyze_sets_sponsorship_from_description(self):
        metadata = analyze_job_metadata(
            company="Acme",
            title="Engineer",
            description="This position does not sponsor work visas.",
        )
        self.assertEqual(metadata["sponsorship"], "unlikely")


class SponsorshipNegationScopeTests(unittest.TestCase):
    """A denial that contains an OFFER substring must not read as an offer.

    Every sentence here is fictional. Each one previously classified ``likely``
    with ``decision: match`` and ``confidence: high`` because the denial wording
    was not in the phrase list while a positive substring inside it was — so
    ``--visa-policy require_positive`` returned postings that refuse sponsorship.
    """

    def test_negated_offer_with_adverb_is_unlikely(self):
        assessment = assess_sponsorship(
            "This role does not currently offer visa sponsorship.")
        self.assertEqual(assessment["verdict"], "unlikely")
        self.assertEqual(assessment["decision"], "no_match")
        self.assertEqual(
            assessment["rule_ids"],
            ["sponsorship.negated_offer.offer visa sponsorship"],
        )

    def test_negated_offer_with_distant_cue_is_unlikely(self):
        self.assertEqual(
            classify_sponsorship(
                "We will not consider applicants for employment immigration "
                "sponsorship or support for this position."),
            "unlikely",
        )

    def test_negated_offer_after_semicolon_is_unlikely(self):
        self.assertEqual(
            classify_sponsorship(
                "Must be eligible to work in the United States; no H1-B visa "
                "sponsorship available."),
            "unlikely",
        )

    def test_not_able_to_offer_is_unlikely(self):
        self.assertEqual(
            classify_sponsorship(
                "We are not able to offer visa sponsorship for this position at "
                "this time."),
            "unlikely",
        )

    def test_parenthetical_aside_does_not_break_the_negation(self):
        # A comma-delimited aside is not a new clause: the negation still reaches
        # the offer phrase on the far side of it.
        self.assertEqual(
            classify_sponsorship(
                "We are not, at this time, able to offer visa sponsorship."),
            "unlikely",
        )

    def test_double_negated_denial_is_unknown_not_a_denial(self):
        # Neither reading is guessed at: the posting is returned for a human read
        # rather than dropped. It used to be a high-confidence denial.
        assessment = assess_sponsorship(
            "It is not true that we cannot sponsor work visas.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["confidence"], "low")
        self.assertIn(
            "sponsorship.ambiguous.double_negation", assessment["rule_ids"])

    def test_coordinated_denials_are_not_a_double_negative(self):
        # Two denials in one sentence are two denials. Only cues with nothing of
        # substance between them are read as a double negative.
        self.assertEqual(
            classify_sponsorship(
                "We are unable to provide visa sponsorship at this time and "
                "cannot sponsor H-1B transfers."),
            "unlikely",
        )

    # --- guardrails: the negation scope must not swallow a real offer --------
    def test_offer_after_a_clause_restart_survives(self):
        self.assertEqual(
            classify_sponsorship(
                "There is no relocation budget, and visa sponsorship is "
                "available for this role."),
            "likely",
        )

    def test_offer_in_a_later_sentence_survives(self):
        self.assertEqual(
            classify_sponsorship(
                "We do not require a degree. Visa sponsorship is available."),
            "likely",
        )

    def test_caveat_after_the_offer_is_not_a_denial(self):
        # "not guaranteed" qualifies an offer; it does not withdraw it.
        self.assertEqual(
            classify_sponsorship(
                "Visa sponsorship is available for this role, though "
                "sponsorship is not guaranteed."),
            "likely",
        )

    def test_contrastive_conjunction_ends_the_negation(self):
        self.assertEqual(
            classify_sponsorship(
                "We cannot guarantee an outcome, but we do provide visa "
                "sponsorship for senior hires."),
            "likely",
        )

    def test_conditional_offer_stays_unclear(self):
        # A discretionary "we will consider" is not a guarantee. Unknown keeps the
        # posting and flags it, instead of promising sponsorship that may not come.
        self.assertEqual(
            classify_sponsorship(
                "We will consider visa sponsorship for exceptional candidates."),
            "unknown",
        )

    def test_work_authorization_boilerplate_stays_unclear(self):
        # Boilerplate used by sponsoring employers too — it must never become a
        # denial, or the filter would hide most of the market.
        self.assertEqual(
            classify_sponsorship(
                "Applicants must be authorized to work in the United States."),
            "unknown",
        )

    def test_silent_posting_never_becomes_a_denial(self):
        assessment = assess_sponsorship(
            "Build and operate reliable distributed services.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertFalse(assessment["signal_present"])


class SponsorshipNonImmigrationDenialTests(unittest.TestCase):
    """A "sponsor" that is not about immigration must not read as a visa denial.

    Offer phrases carried an immigration-context gate; denial phrases carried
    none, so "we do not sponsor community events" matched ``do not sponsor`` and
    graded a confident refusal — and the default ``exclude_negative`` policy
    DROPS refusals, so the posting was deleted for a sentence about a street
    fair.  Every sentence here is fictional.
    """

    def test_a_non_immigration_sponsee_is_not_a_denial(self):
        for text in (
            "We do not sponsor community events.",
            "We do not sponsor conference booths.",
            "We will not sponsor youth sports leagues in our marketing budget.",
            "We sponsor community events and do not sponsor local sports teams.",
        ):
            with self.subTest(text=text):
                assessment = assess_sponsorship(text)
                self.assertEqual(assessment["verdict"], "unknown")
                self.assertEqual(assessment["decision"], "review")

    def test_a_denial_naming_sponsorship_itself_needs_no_context(self):
        # The tripwire that makes a SYMMETRIC gate wrong. This sentence carries
        # no immigration word anywhere in it, and it is a real refusal — the
        # object of the verb IS sponsorship, so there is no other sponsee for it
        # to be about. Gating it would delete a denial the module can read.
        assessment = assess_sponsorship("This role does not offer sponsorship.")
        self.assertEqual(assessment["verdict"], "unlikely")
        self.assertEqual(assessment["confidence"], "high")
        self.assertEqual(assessment["decision"], "no_match")

    def test_a_bare_verb_denial_with_immigration_beside_it_still_lands(self):
        for text in (
            "Applicants must already hold a work visa; we do not sponsor.",
            "We cannot sponsor visas at all for this position.",
            "We do not sponsor. Applicants must be authorized to work in the "
            "United States.",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_sponsorship(text), "unlikely")

    def test_the_gate_runs_after_the_quantifier_reads_not_before(self):
        # Structural guard: the gate protects the bucket that produces
        # `unlikely`/`no_match`, and nothing else. A scope-limited or unsettled
        # reading is decided first and is unaffected, so this sentence keeps the
        # low-confidence review the quantifier rules give it rather than
        # silently losing its evidence.
        assessment = assess_sponsorship(
            "We are not able to sponsor every candidate who applies.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["confidence"], "low")
        self.assertIn("sponsorship.scope_limit.not able to sponsor",
                      assessment["rule_ids"])

    def test_the_context_window_errs_toward_keeping_the_denial(self):
        # The gate's known limit, pinned so it is not mistaken for a defect: the
        # window is positional, so a real sponsorship offer near a
        # non-immigration "sponsor" keeps that denial in the evidence. The
        # result is a CONFLICT — kept and flagged — never a drop and never a
        # promotion, which is the direction this module resolves ambiguity in.
        assessment = assess_sponsorship(
            "Our charitable giving programme does not sponsor political "
            "campaigns. Visa sponsorship is available for this role.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")


class SponsorshipOffListDenialTests(unittest.TestCase):
    """A denial phrased in words NEITHER phrase list contains must still land.

    Polarity was decided structurally, but detection was still lexical: with no
    phrase matching, the negation scope had nothing to act on and the posting
    classified ``unknown`` — the JD said no in writing and the pipeline read it
    as silence.  A negation that reaches a bare sponsorship head THROUGH AN
    OFFER VERB is a denial of that offer.  Every sentence here is fictional.
    """

    def test_coordinated_object_defeats_both_phrase_lists(self):
        # The filed reproduction: the denial phrases need "offer sponsorship"
        # contiguous and the offer phrases need "offer visa sponsorship"
        # contiguous, and one coordinated object defeats both.
        assessment = assess_sponsorship(
            "We do not offer relocation or visa sponsorship.")
        self.assertEqual(assessment["verdict"], "unlikely")
        self.assertEqual(assessment["confidence"], "high")
        self.assertEqual(assessment["decision"], "no_match")

    def test_other_offer_verbs_are_read_the_same_way(self):
        for text in (
            "We cannot extend visa sponsorship for this position.",
            "We are unable to provide relocation or employment sponsorship "
            "for this opening.",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_sponsorship(text), "unlikely")

    def test_eeo_copy_is_not_a_denial(self):
        # The misfire a generic "cue ... sponsorship head" rule produces, and the
        # reason the OFFER VERB is required rather than merely helpful: this
        # sentence puts a cue five tokens from the head and is the OPPOSITE of a
        # denial.  Reading it as one would drop an employer that sponsors.
        assessment = assess_sponsorship(
            "We do not discriminate against candidates who need visa "
            "sponsorship.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")

    def test_the_verb_to_head_window_stays_tight(self):
        # A head far enough from the offer verb is no longer plausibly its
        # object; the rule declines rather than guessing.
        self.assertEqual(
            classify_sponsorship(
                "We do not offer relocation or housing or transit or gym or "
                "childcare or visa sponsorship."),
            "unknown",
        )

    def test_a_later_sentences_offer_is_untouched(self):
        self.assertEqual(
            classify_sponsorship(
                "We do not offer relocation. Visa sponsorship is available "
                "for this role."),
            "likely",
        )

    def test_a_discretionary_offer_has_no_cue_to_negate(self):
        self.assertEqual(
            classify_sponsorship(
                "We will consider visa sponsorship for exceptional "
                "candidates."),
            "unknown",
        )

    def test_the_fallback_never_steals_a_wording_the_lists_already_read(self):
        # The rule only ADDS detection: a head already covered by a phrase from
        # either tuple keeps its existing path, evidence and rule id.
        assessment = assess_sponsorship(
            "This role does not currently offer visa sponsorship.")
        self.assertEqual(
            assessment["rule_ids"],
            ["sponsorship.negated_offer.offer visa sponsorship"],
        )

    def test_an_off_list_denial_obeys_the_double_negation_rule(self):
        assessment = assess_sponsorship(
            "It is not true that we do not offer relocation or visa "
            "sponsorship.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertIn(
            "sponsorship.ambiguous.double_negation", assessment["rule_ids"])

    def test_an_off_list_denial_beside_an_offer_is_a_conflict(self):
        assessment = assess_sponsorship(
            "We do not offer relocation or visa sponsorship. We sponsor H-1B "
            "transfers for senior hires.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")


class SponsorshipUnreachableCueTests(unittest.TestCase):
    """A cue the scope cannot reach must not leave the offer phrase asserted.

    Two independent bounds — the clause break and the token budget — can put a
    negation the sentence plainly contains out of an offer phrase's reach, and
    the failure was not symmetric: the phrase kept scoring as an explicit OFFER.
    A denial written with a parenthetical in the middle of it therefore graded
    ``likely``/``high``/``match``, so ``--visa-policy require_positive`` — the
    policy chosen by the one candidate who needs sponsorship — returned an
    employer that refuses it in writing, unflagged.

    The repair leaves both bounds exactly where they were and fails toward
    review instead, so the guardrail that keeps a clause restart readable is
    untouched. Every sentence here is fictional.
    """

    def test_clause_break_inside_a_parenthetical_no_longer_asserts_an_offer(self):
        # The filed reproduction. `_SPONSOR_CLAUSE_BREAK_RE` matches the "and the"
        # INSIDE the aside, which truncates the scope before the token budget is
        # ever consulted, so `unable` is not in scope at all.
        assessment = assess_sponsorship(
            "We are unable, given current headcount constraints and the "
            "timeline for this particular opening, to offer visa sponsorship.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["confidence"], "low")
        self.assertEqual(assessment["decision"], "review")
        self.assertIn(
            "sponsorship.unreachable_cue.offer visa sponsorship",
            assessment["rule_ids"])

    def test_the_token_budget_bound_is_closed_by_the_same_repair(self):
        # The OTHER bound, on the same sentence with the coordinator removed:
        # `unable` is back in scope, 9 tokens away, and refused by the budget. A
        # repair aimed at only one bound would leave this one open.
        assessment = assess_sponsorship(
            "We are unable, given current headcount constraints for this "
            "particular opening, to offer visa sponsorship.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")

    def test_an_unreachable_cue_is_never_promoted_to_a_denial(self):
        # The asymmetry that keeps the safety posture in BOTH directions: an
        # unreadable sentence is not evidence of refusal either, so it must not
        # drop the posting.
        assessment = assess_sponsorship(
            "We are unable, given current headcount constraints and the "
            "timeline for this particular opening, to offer visa sponsorship.")
        self.assertNotEqual(assessment["verdict"], "unlikely")
        self.assertNotEqual(assessment["decision"], "no_match")

    def test_an_offer_that_opens_its_own_clause_still_stands(self):
        # The guardrail the widening repair would have put at risk. The cue "no"
        # belongs to the relocation clause; the offer starts a new one, which is
        # measurable as an EMPTY clause scope, so no demotion applies.
        assessment = assess_sponsorship(
            "There is no relocation budget, and visa sponsorship is available "
            "for this role.")
        self.assertEqual(assessment["verdict"], "likely")
        self.assertEqual(assessment["confidence"], "high")

    def test_an_offer_in_a_later_sentence_is_out_of_the_cues_sentence(self):
        assessment = assess_sponsorship(
            "We are unable, given headcount and the timeline, to expand the "
            "team this quarter. Visa sponsorship is available for this role.")
        self.assertEqual(assessment["verdict"], "likely")

    def test_a_settled_denial_still_outranks_an_unreachable_cue(self):
        # Recording a reading as unsettled must never weaken a refusal the
        # module CAN read — the property the quantifier pass exists to protect.
        assessment = assess_sponsorship(
            "This role does not offer sponsorship. We are unable, given "
            "current headcount constraints and the timeline for this "
            "particular opening, to offer visa sponsorship.")
        self.assertEqual(assessment["verdict"], "unlikely")
        self.assertEqual(assessment["decision"], "no_match")

    def test_an_unreachable_cue_beside_a_real_offer_is_a_conflict(self):
        # An unreadable sentence is a POSSIBLE denial, so it conflicts with a
        # real offer rather than being ignored beside one.
        assessment = assess_sponsorship(
            "We are unable, given current headcount constraints and the "
            "timeline for this particular opening, to offer visa sponsorship. "
            "We sponsor H-1B transfers for senior hires.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")


class SponsorshipScopeLimitTests(unittest.TestCase):
    """An offer plus a limit ON that offer is a sponsor, not a refusal.

    Reading negation structurally was right and stays. It over-reached on the one
    shape that matters most to the person using ``--visa-policy require_positive``:
    an employer who says it sponsors and then bounds the promise. The hedge
    sentence carries its own negated offer phrase, denial beat offer, and the
    clearest sponsorship language in a whole market scan graded ``unknown`` — so
    the strict policy returned nothing where a real sponsor existed.

    The rule is logical rather than lexical: ``not (for every X)`` denies the
    UNIVERSAL and entails that some X ARE sponsored, while ``does not sponsor`` is
    the universal negation. Only the second is a denial. Every wording below is
    fictional.
    """

    OFFER_WITH_SCOPE_LIMIT = (
        "Visa sponsorship: we do sponsor visas. That said, we are not able to "
        "sponsor visas for every role and every candidate. If we make you an "
        "offer we will make every reasonable effort to obtain one for you."
    )

    def test_offer_followed_by_a_scope_limit_is_still_an_offer(self):
        assessment = assess_sponsorship(self.OFFER_WITH_SCOPE_LIMIT)
        self.assertEqual(assessment["verdict"], "likely")
        self.assertEqual(assessment["decision"], "match")
        self.assertTrue(any(rule.startswith("sponsorship.scope_limit.")
                            for rule in assessment["rule_ids"]),
                        assessment["rule_ids"])
        self.assertFalse(any(rule.startswith("sponsorship.negated_offer.")
                             or rule.startswith("sponsorship.negative.")
                             for rule in assessment["rule_ids"]),
                         assessment["rule_ids"])

    def test_a_scope_limit_alone_never_manufactures_an_offer(self):
        # The asymmetry that keeps the safety posture: a scope limit can only
        # REMOVE a denial. With no unhedged offer beside it the answer is unknown,
        # which keeps the posting and flags it — never `likely`.
        assessment = assess_sponsorship(
            "We are not able to sponsor every candidate who applies.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")
        self.assertIn("sponsorship.scope_limit.not able to sponsor",
                      assessment["rule_ids"])

    def test_cannot_guarantee_is_not_a_denial(self):
        self.assertEqual(
            classify_sponsorship(
                "We cannot guarantee that we will sponsor visas for this role."),
            "unknown",
        )

    def test_flat_denial_is_still_a_denial(self):
        for text in (
            "We do not offer visa sponsorship for this position.",
            "This role does not currently offer visa sponsorship.",
            "We do not sponsor visas for any role.",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_sponsorship(text), "unlikely")

    def test_at_all_intensifies_a_denial_rather_than_bounding_it(self):
        # "at all" INTENSIFIES a denial, so it is excluded from the ambiguous-
        # quantifier cue by name (``_SPONSOR_AMBIGUOUS_SCOPE_RE``). The exclusion
        # is load-bearing again: bare "all" no longer bounds nothing, it unsettles
        # a denial, and this is the one wording where it must not.
        self.assertEqual(
            classify_sponsorship("We cannot sponsor visas at all for this role."),
            "unlikely",
        )

    def test_all_as_a_requirement_subject_does_not_soften_a_denial(self):
        # "All" here is the subject of an eligibility rule, not a quantifier over
        # what is sponsored. A backward quantifier only counts inside the negation
        # it bounds.
        for text in (
            "All roles require work authorization without sponsorship.",
            "Every applicant must be authorized to work in the United States "
            "without sponsorship.",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_sponsorship(text), "unlikely")

    def test_offer_then_an_unrelated_negation_stays_an_offer(self):
        self.assertEqual(
            classify_sponsorship(
                "We sponsor visas for this role. We do not offer relocation "
                "assistance."),
            "likely",
        )

    def test_silence_is_still_unknown(self):
        self.assertEqual(
            classify_sponsorship(
                "Build backend services in Go. Competitive salary and equity."),
            "unknown",
        )


class QuantifiedDenialTests(unittest.TestCase):
    """An `all`-quantified denial is a denial — and not a CONFIDENT one.

    The scope-limit rule was right that ``not (for every role)`` negates a
    UNIVERSAL and so entails that some roles ARE sponsored. It went one quantifier
    too far by accepting the bare word "all": ``every``/``each`` are distributive
    and force that ``¬∀`` reading, while ``all`` also has a collective reading
    ("for all new hires" = "for the new hires, as a class") under which the
    quantifier bounds the DENIAL's own domain — ``∀x. ¬sponsor(x)`` — and nothing
    about sponsorship existing is entailed.

    The consequence was not a missing demotion but a two-step PROMOTION. Deleting
    the denial dissolves the ``denial and positive -> review`` conflict branch, so
    a JD that refuses in writing graded ``match``/``likely``/**high** and
    ``classify_visa`` returned "yes" — presented to a candidate who needs
    sponsorship as a confident sponsor, with no review flag. That is the invariant
    the earlier change asserted ("a scope limit can only REMOVE a denial, never
    create an offer") and never enforced anywhere but in prose, so it is pinned at
    the VERDICT level here, not just per phrase.

    Removing ``all`` from the scope-limit cue closed that, and opened its mirror:
    the phrase then fell through to the ordinary denial path and answered
    ``no_match``/``unlikely``/**high** with no review flag, so the posting was
    dropped under BOTH policies on a sentence this very docstring calls ambiguous.
    Both halves are pinned here together, because they are the two directions one
    quantifier can fail in and every previous revision fixed one by reopening the
    other: the phrase NEVER leaves the denial list (no promotion is reachable),
    and a denial resting only on it never carries a confident verdict. Every
    wording below is fictional.
    """

    DENIAL = "We are unable to sponsor visas for all new hires."
    # Offers that cover somebody OTHER than the reader, which is the shape that
    # makes the promotion dangerous rather than merely contradictory.
    OFFERS = (
        "We offer green card sponsorship to existing employees after two years.",
        "H-1B sponsorship is part of our benefits package for tenured staff.",
    )
    QUANTIFIED_DENIALS = (
        "We are unable to sponsor visas for all new hires.",
        "We do not sponsor all candidates.",
        "We cannot sponsor all applicants for this opening.",
    )

    # Offers phrased in words `_SPONSOR_POSITIVE` does not contain — the class the
    # confident drop actually swallowed, since a recognised offer phrase would have
    # sent the posting to the `denial and positive -> review` branch anyway.
    UNLISTED_OFFERS = (
        "Our immigration team supports H-1B and green card cases.",
        "Sponsorship is offered for many roles on this team.",
    )

    def test_a_quantified_denial_alone_is_not_a_confident_refusal(self):
        # It is still DENIAL evidence — that is the promotion guard, asserted on
        # the rule id — but the verdict it supports on its own is `review`, not a
        # silent `no_match` at high confidence.
        assessment = assess_sponsorship(self.DENIAL)
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["confidence"], "low")
        self.assertEqual(assessment["decision"], "review")
        self.assertIn("sponsorship.unsettled_denial.unable to sponsor",
                      assessment["rule_ids"])
        self.assertNotIn("sponsorship.scope_limit.unable to sponsor",
                         assessment["rule_ids"])

    def test_an_unsettled_denial_never_hides_an_offlist_sponsor(self):
        # The reported recall loss, over the class rather than the one sentence.
        for denial in self.QUANTIFIED_DENIALS:
            for offer in self.UNLISTED_OFFERS:
                for text in (f"{offer} {denial}", f"{denial} {offer}"):
                    with self.subTest(text=text):
                        assessment = assess_sponsorship(text)
                        self.assertEqual(assessment["decision"], "review", text)
                        self.assertEqual(assessment["verdict"], "unknown", text)

    def test_one_settled_denial_outranks_any_number_of_unsettled_ones(self):
        # Unsettling a denial must not unsettle the POSTING.
        assessment = assess_sponsorship(
            f"{self.DENIAL} We do not sponsor all candidates. This role does "
            "not offer sponsorship.")
        self.assertEqual(assessment["verdict"], "unlikely")
        self.assertEqual(assessment["confidence"], "high")
        self.assertEqual(assessment["decision"], "no_match")

    def test_a_quantified_denial_beside_an_offer_is_a_conflict(self):
        assessment = assess_sponsorship(f"{self.OFFERS[0]} {self.DENIAL}")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")
        self.assertEqual(assessment["confidence"], "low")

    def test_no_quantified_denial_is_ever_promoted_to_a_confident_offer(self):
        # The verdict-level invariant, over the whole class rather than the one
        # reported sentence: a denial the JD states cannot come back as `likely`
        # merely because the JD also praises its immigration benefits elsewhere.
        for denial in self.QUANTIFIED_DENIALS:
            for offer in self.OFFERS:
                for text in (f"{offer} {denial}", f"{denial} {offer}"):
                    with self.subTest(text=text):
                        assessment = assess_sponsorship(text)
                        self.assertNotEqual(assessment["verdict"], "likely", text)
                        self.assertNotEqual(assessment["decision"], "match", text)

    def test_a_distributive_quantifier_is_still_a_scope_limit(self):
        # The behaviour the earlier change existed to produce is untouched: the
        # narrowing is to `all`, not to the rule.
        offer_then_limit = (
            "Visa sponsorship: we do sponsor visas. That said, we are not able "
            "to sponsor visas for every role and every candidate.")
        assessment = assess_sponsorship(offer_then_limit)
        self.assertEqual(assessment["verdict"], "likely")
        self.assertEqual(assessment["confidence"], "high")
        self.assertEqual(
            assess_sponsorship(
                "We are not able to sponsor every candidate who applies."
            )["verdict"],
            "unknown",
        )


class SalaryPeriodFidelityTests(unittest.TestCase):
    """``salary_range`` is USD/year, so a band stated per hour is not a value.

    The period-aware band floor removes an implausible ANNUAL band before the
    envelope runs, and the envelope's "prefer annual" line then had no annual band
    left to prefer and fell through to the hourly one. The result is a
    plausible-looking number in the wrong unit — worse than the garbled band it
    replaced, because nothing about ``$30 - $45`` looks wrong in a column the
    reader is told holds annual pay.

    Refusal, not conversion: annualising would have to invent an hours-per-year
    figure the posting never stated, and the rich fact from
    ``extract_salary_range`` still carries the band and its ``period`` for any
    consumer that wants it.
    """

    GARBLED_ANNUAL_PLUS_HOURLY = (
        "The annual base salary is $3240 - $175,000 per year. "
        "Interns for this role are paid a base salary of $30 - $45 per hour."
    )

    def _salary(self, description: str):
        metadata = analyze_job_metadata(
            company="ExampleCorp",
            title="Senior Backend Engineer",
            description=description,
        )
        return metadata["salary_range"]

    def test_a_rejected_annual_band_does_not_fall_back_to_an_hourly_one(self):
        self.assertIsNone(self._salary(self.GARBLED_ANNUAL_PLUS_HOURLY))
        # The band is not lost, only kept out of the annual field.
        fact = extract_salary_range(self.GARBLED_ANNUAL_PLUS_HOURLY)
        self.assertEqual((fact["min"], fact["max"], fact["period"]),
                         (30, 45, "hour"))

    def test_every_route_that_rejects_the_annual_band_reports_nothing(self):
        for description in (
            # annual band under the per-year floor, hourly band beside it
            "The base salary range is $9,000 - $9,500 per year. "
            "The base pay range for interns is $50 - $80 per hour.",
            # annual band over the 10x spread limit, hourly band beside it
            "The base salary range is $50,000 - $600,000 per year. "
            "The base pay range for interns is $30 - $45 per hour.",
        ):
            with self.subTest(description=description):
                self.assertIsNone(self._salary(description))

    def test_a_lone_hourly_band_is_not_an_annual_salary(self):
        self.assertIsNone(
            self._salary("The base pay range for this role is $48 - $62 per hour."))

    def test_the_envelope_refuses_a_fact_with_no_annual_band(self):
        self.assertEqual(
            _salary_envelope({
                "bands": [
                    {"min": 30, "max": 45, "period": "hour"},
                    {"min": 3_000, "max": 4_000, "period": "month"},
                ],
            }),
            (None, None),
        )
        self.assertEqual(
            _salary_envelope({"min": 48, "max": 62, "period": "hour"}),
            (None, None),
        )

    def test_annual_bands_are_untouched(self):
        self.assertEqual(
            (lambda s: (s["min"], s["max"]))(
                self._salary("The base salary range is $140,000 - $175,000 per year.")),
            (140000, 175000),
        )
        # An hourly band beside a GOOD annual band still loses to it, as before.
        mixed = self._salary(
            "The annual base salary range is $150,000-$200,000 per year. "
            "The hourly base pay range is $70-$95 per hour.")
        self.assertEqual((mixed["min"], mixed["max"]), (150000, 200000))

    def test_the_aggregator_fallback_still_fills_the_field(self):
        metadata = analyze_job_metadata(
            company="ExampleCorp",
            title="Senior Backend Engineer",
            description="The base pay range for this role is $48 - $62 per hour.",
            supplied_salary_range={"min": 150_000, "max": 190_000,
                                   "source": "aggregator"},
        )
        self.assertEqual(
            (metadata["salary_range"]["min"], metadata["salary_range"]["max"],
             metadata["salary_range"]["confidence"]),
            (150000, 190000, "medium"),
        )


class SponsorshipHedgedOfferTests(unittest.TestCase):
    """A discretionary maybe is ``unknown``, the way LESSONS.md already says.

    The mirror of the case above, and observed in the same scan: a vague "limited
    sponsorship may be available" graded ``likely`` while the unambiguous offer
    graded ``unknown``, so the two labels were swapped. Grading on offer STRENGTH
    puts them back in order — unhedged offer > hedged offer > silence.
    """

    def test_limited_and_may_be_available_is_unknown(self):
        assessment = assess_sponsorship(
            "Limited immigration sponsorship may be available for this role.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")
        self.assertIn("sponsorship.hedged_offer.immigration sponsorship",
                      assessment["rule_ids"])

    def test_case_by_case_offer_is_unknown(self):
        self.assertEqual(
            classify_sponsorship(
                "Visa sponsorship is available on a case-by-case basis."),
            "unknown",
        )

    def test_an_unhedged_offer_outranks_a_hedged_one(self):
        # Both shapes in one posting: the plain statement decides.
        self.assertEqual(
            classify_sponsorship(
                "We sponsor work visas. Green card sponsorship may follow later."),
            "likely",
        )

    def test_a_hedge_across_a_coordinator_does_not_reach_the_offer(self):
        # "may" belongs to the relocation conjunct, not to the sponsorship offer.
        self.assertEqual(
            classify_sponsorship(
                "We sponsor H-1B visas, and relocation may be discussed "
                "separately."),
            "likely",
        )

    def test_a_denial_beside_a_hedged_offer_is_a_conflict_not_a_drop(self):
        # A denial silently DROPS the posting under both policies, so contradictory
        # evidence goes to a human rather than to the reject pile.
        assessment = assess_sponsorship(
            "This role does not offer sponsorship, though limited immigration "
            "sponsorship may be available on other teams.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")

    def test_a_caveat_outside_the_clause_leaves_the_offer_alone(self):
        self.assertEqual(
            classify_sponsorship(
                "Visa sponsorship is available for this role, though sponsorship "
                "is not guaranteed."),
            "likely",
        )


class MemberOfStaffTitleFamilyTests(unittest.TestCase):
    """"Member of <X> Staff" is an IC title family, not one spelling of one.

    ``Member of Technical Staff`` was neutralized by name, so ``Member of Data
    Staff`` — the same family, seen on a real board — read as Staff level and was
    dropped by a ``staff`` exclude.
    """

    def test_every_qualifier_in_the_family_is_neutralized(self):
        for title in (
            "Member of Technical Staff",
            "Member of Data Staff",
            "Member of Research Staff",
            "Member of the Technical Staff",
            "Members of Applied Research Staff",
        ):
            with self.subTest(title=title):
                self.assertEqual(classify_level(title)[0], "unknown")

    def test_a_real_seniority_prefix_still_resolves(self):
        self.assertEqual(
            classify_level("Senior Member of Data Staff")[0], "senior")
        self.assertEqual(
            classify_level("Principal Member of Technical Staff")[0], "principal")

    def test_genuine_staff_titles_are_untouched(self):
        for title in ("Staff Software Engineer", "Senior Staff Engineer",
                      "Chief of Staff"):
            with self.subTest(title=title):
                self.assertNotEqual(classify_level(title)[0], "unknown")


class SponsorshipExportControlSenseTests(unittest.TestCase):
    """"Sponsorship" in export-licensing boilerplate is not an immigration denial.

    The default ``exclude_negative`` policy DROPS denials, so reading this
    boilerplate as a denial removed export-controlled postings from the results
    without saying so. All wording below is fictional.
    """

    def test_export_license_boilerplate_is_not_a_denial(self):
        assessment = assess_sponsorship(
            "Candidates must be eligible to obtain the required authorizations "
            "without sponsorship for an export license.")
        self.assertEqual(assessment["verdict"], "unknown")
        self.assertEqual(assessment["decision"], "review")
        self.assertEqual(
            assessment["rule_ids"],
            ["sponsorship.non_immigration.export_control"],
        )

    def test_itar_clause_is_not_a_denial(self):
        self.assertEqual(
            classify_sponsorship(
                "This position requires access to export-controlled technology; "
                "you must qualify without sponsorship for an export license."),
            "unknown",
        )

    def test_export_clause_does_not_suppress_a_real_denial(self):
        # Both topics in one posting: the immigration sentence still decides.
        self.assertEqual(
            classify_sponsorship(
                "Access to export-controlled data is required. We do not "
                "provide visa sponsorship for this role."),
            "unlikely",
        )

    def test_export_clause_does_not_suppress_a_real_offer(self):
        self.assertEqual(
            classify_sponsorship(
                "Must be eligible for an export license. Visa sponsorship is "
                "available for this role."),
            "likely",
        )

    def test_immigration_word_in_the_same_sentence_keeps_the_denial(self):
        # The guard needs the sentence to be export-control language AND carry no
        # immigration word at all; one visa mention is enough to keep the denial.
        self.assertEqual(
            classify_sponsorship(
                "You must be able to obtain an export license and to work in "
                "the United States without visa sponsorship."),
            "unlikely",
        )


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
            [f"job_metadata_schema_version must be {APPLICATION_SCHEMA_VERSION}"],
        )

    def test_old_schema_version_is_rejected(self):
        # v4 is now legacy: it is rejected outright, migrate with migrate_to_v5.
        self.assertEqual(
            validate_meta({"job_metadata_schema_version": 4}),
            [f"job_metadata_schema_version must be {APPLICATION_SCHEMA_VERSION}"],
        )

    def test_float_schema_version_is_rejected(self):
        self.assertEqual(
            validate_meta({
                "job_metadata_schema_version": float(APPLICATION_SCHEMA_VERSION)}),
            [f"job_metadata_schema_version must be {APPLICATION_SCHEMA_VERSION}"],
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


class SchemaV6JobFieldTests(unittest.TestCase):
    def test_missing_status_is_rejected(self):
        job = _valid_job()
        del job["status"]
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertIn("jobs[0].status is required", errors)

    def test_bad_status_enum_is_rejected(self):
        errors = validate_meta(_valid_meta(jobs=[_valid_job(status="offer")]))
        self.assertTrue(any(
            "jobs[0].status must be one of" in error for error in errors))

    def test_optional_status_date_passes(self):
        job = _valid_job(
            status="applied",
            progress={"phase": "application_review", "state": "waiting_employer"},
            status_date="2026-07-20")
        self.assertEqual(validate_meta(_valid_meta(jobs=[job])), [])

    def test_retired_stage_key_is_rejected(self):
        errors = validate_meta(_valid_meta(jobs=[_valid_job(stage="onsite")]))
        self.assertTrue(any(
            "jobs[0].stage was removed in schema v6" in error for error in errors))

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

    def test_total_compensation_range_is_rejected_at_every_scope(self):
        job = _valid_job(total_compensation_range={
            "min": 200000,
            "max": 300000,
            "confidence": "high",
            "source": "company_reference",
        })
        errors = validate_meta(_valid_meta(
            total_compensation_range={"min": 200000, "max": 300000},
            jobs=[job],
        ))
        self.assertTrue(any(
            error.startswith("top-level total_compensation_range is not supported")
            for error in errors))
        self.assertTrue(any(
            error.startswith("jobs[0].total_compensation_range is not supported")
            for error in errors))

    def test_unknown_structured_job_field_is_rejected(self):
        errors = validate_meta(_valid_meta(jobs=[_valid_job(
            compensation={"currency": "USD"},
        )]))
        self.assertIn(
            "jobs[0].has unsupported structured field(s): compensation",
            errors,
        )

    def test_unknown_scalar_job_field_remains_tolerated(self):
        self.assertEqual(validate_meta(_valid_meta(jobs=[_valid_job(
            legacy_requisition_id="REQ-123",
        )])), [])

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


class CompanyKeyValidationTests(unittest.TestCase):
    """``company_key`` is optional, shape-checked, and top-level ONLY."""

    def test_company_key_is_optional(self):
        # Absent is the normal state: handoff scaffolds an application without a
        # key, and coverage is a number status.py prints rather than a gate.
        self.assertNotIn("company_key", _valid_meta())
        self.assertEqual(validate_meta(_valid_meta()), [])

    def test_an_explicit_null_company_key_is_still_optional(self):
        # ``company_key:`` with nothing after it parses as None. The reconciler
        # treats that as unkeyed, so this validator must agree.
        self.assertEqual(validate_meta(_valid_meta(company_key=None)), [])

    def test_a_wellformed_company_key_passes(self):
        for key in ("acmelabs", "acme-labs", "acme-labs-2", "7seas"):
            with self.subTest(key=key):
                self.assertEqual(validate_meta(_valid_meta(company_key=key)), [])

    def test_a_malformed_company_key_is_rejected(self):
        for key in ("Acme Labs", "acme labs", "-acme", "acme_labs", "acme.labs",
                    "", 7, True, ["acme-labs"], {"key": "acme-labs"}):
            with self.subTest(key=key):
                errors = validate_meta(_valid_meta(company_key=key))
                self.assertTrue(
                    any("company_key must be a lowercase company-index key" in error
                        for error in errors),
                    f"{key!r} was accepted: {errors}")

    def test_the_five_input_classes_all_three_validators_must_agree_on(self):
        """The exact table an adversarial review drove through all three checkers.

        ``absent`` is the only one of the five that is OK, and it is OK everywhere.
        The other four are an ERROR here, a FINDING to the reconciler, and a
        ``malformed`` row that fails ``status.py --company-keys --strict``. Before
        this, ``"acme-labs\\n"`` was ACCEPTED here — ``$`` matches before a trailing
        newline — while the reconciler called the same value a finding.
        """
        self.assertEqual(validate_meta(_valid_meta()), [],
                         "absent is the normal state and is valid")
        for key in ("acme-labs\n", "", False, 0):
            with self.subTest(key=key):
                errors = validate_meta(_valid_meta(company_key=key))
                self.assertTrue(
                    any("company_key must be a lowercase company-index key" in error
                        for error in errors),
                    f"{key!r} was accepted: {errors}")

    def test_no_surrounding_whitespace_is_tolerated_in_a_company_key(self):
        """None of the three strips, so none of them may accept whitespace.

        A key is spent as a folder name and as a URL fragment; a leading or
        trailing blank in one of those is a different key that looks the same.
        """
        for key in (" acme-labs", "acme-labs ", "acme-labs\t", "acme\nlabs",
                    "acme-labs\r\n"):
            with self.subTest(key=key):
                self.assertTrue(validate_meta(_valid_meta(company_key=key)),
                                f"{key!r} was accepted")

    def test_per_job_company_key_is_rejected(self):
        """A jobs[] entry tolerates unknown SCALARS, so this would be silent.

        Silently accepted and silently ignored is the worst outcome: the writer
        believes the key took effect. The message names the top level so the fix
        is obvious.
        """
        errors = validate_meta(_valid_meta(jobs=[_valid_job(company_key="acme-labs")]))
        self.assertTrue(
            any("jobs[0].company_key is not a per-job field" in error
                for error in errors), errors)
        self.assertTrue(
            any("belongs at the top level beside company" in error
                for error in errors), errors)

    def test_company_key_pattern_matches_the_index_module(self):
        """The duplicated regex is pinned to its source of truth.

        ``job_metadata`` deliberately does NOT import ``company_index``: it is
        vendored byte-identically into three skills and is stdlib+PyYAML only, and
        no module in that vendored set imports a sibling. This test is what makes
        the duplication safe — change either pattern without the other and it goes
        red.

        Both modules are loaded BY PATH out of ``automation/shared``. A plain
        ``import job_metadata`` here can resolve to a vendored copy, because other
        modules in this suite put a ``_vendor`` directory on ``sys.path`` first —
        and pinning a copy to the canonical index would let the canonical pattern
        drift until the next vendor sync.
        """
        import importlib.util

        def canonical(name: str):
            alias = f"_canonical_{name}"
            spec = importlib.util.spec_from_file_location(
                alias, SHARED_DIR / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            # ``@dataclass`` resolves its own module out of sys.modules, so the
            # alias must be registered before the body runs.
            sys.modules[alias] = module
            try:
                spec.loader.exec_module(module)
            finally:
                sys.modules.pop(alias, None)
            return module

        self.assertEqual(canonical("job_metadata")._COMPANY_KEY_RE.pattern,
                         canonical("company_index").KEY_RE.pattern)


class ProgressValidationTests(unittest.TestCase):
    def _errors(self, **job_overrides) -> list[str]:
        return validate_meta(_valid_meta(jobs=[_valid_job(**job_overrides)]))

    def test_missing_progress_is_rejected(self):
        job = _valid_job()
        del job["progress"]
        errors = validate_meta(_valid_meta(jobs=[job]))
        self.assertTrue(any(
            "jobs[0].progress is required" in error for error in errors))

    def test_bad_phase_and_state_are_rejected(self):
        errors = self._errors(progress={"phase": "vibes", "state": "chilling"})
        self.assertTrue(any("progress.phase must be one of" in e for e in errors))
        self.assertTrue(any("progress.state must be one of" in e for e in errors))

    def test_phase_other_requires_label(self):
        errors = self._errors(progress={"phase": "other", "state": "unknown"})
        self.assertTrue(any(
            "label is required when phase is 'other'" in e for e in errors))
        ok = self._errors(progress={
            "phase": "other", "state": "unknown", "label": "Bar raiser"})
        self.assertEqual(ok, [])

    def test_closed_state_couples_to_closed_statuses_both_ways(self):
        # rejected/ignored REQUIRE state closed...
        errors = self._errors(
            status="rejected",
            progress={"phase": "recruiter_screen", "state": "waiting_employer"})
        self.assertTrue(any(
            "state must be 'closed' when status is 'rejected'" in e
            for e in errors))
        # ...and closed requires rejected/ignored (an active role is never closed).
        errors = self._errors(
            status="applied",
            progress={"phase": "application_review", "state": "closed"})
        self.assertTrue(any(
            "state 'closed' requires status rejected or ignored" in e
            for e in errors))
        # A rejected role keeps its last phase with state closed — valid.
        ok = self._errors(
            status="rejected",
            progress={"phase": "interview_loop", "state": "closed"})
        self.assertEqual(ok, [])

    def test_email_source_requires_message_ref(self):
        errors = self._errors(progress={
            "phase": "recruiter_screen", "state": "booking_required",
            "source": {"kind": "email"}})
        self.assertTrue(any(
            "source.ref is required for an email source" in e for e in errors))
        ok = self._errors(progress={
            "phase": "recruiter_screen", "state": "booking_required",
            "source": {"kind": "email", "ref": "acct-01/abc123"}})
        self.assertEqual(ok, [])

    def test_manual_source_may_leave_ref_empty(self):
        ok = self._errors(progress={
            "phase": "recruiter_screen", "state": "booking_required",
            "source": {"kind": "manual", "ref": ""}})
        self.assertEqual(ok, [])

    def test_calendar_items_pattern_uniqueness_and_unknown_keys_are_gated(self):
        errors = self._errors(progress={
            "phase": "technical_interview", "state": "awaiting_schedule",
            "calendar_items": ["CAL 7!"], "surprise": True})
        self.assertTrue(any("calendar_items[0] must be" in e for e in errors))
        self.assertTrue(any("unknown key(s): surprise" in e for e in errors))
        ok = self._errors(progress={
            "phase": "technical_interview", "state": "awaiting_schedule",
            "calendar_items": ["cal-acme-senior-engineer-01"],
            "updated_at": "2026-07-22T10:00:00Z"})
        self.assertEqual(ok, [])

    def test_bad_updated_at_is_rejected(self):
        errors = self._errors(progress={
            "phase": "recruiter_screen", "state": "unknown",
            "updated_at": "yesterday-ish"})
        self.assertTrue(any(
            "updated_at must be an ISO-8601 timestamp" in e for e in errors))

    def test_extended_interview_process_phases_and_states_are_valid(self):
        for phase, state in (
            ("assessment", "in_progress"),
            ("offer", "decision_required"),
            ("reference_check", "follow_up_required"),
            ("work_authorization", "paused"),
        ):
            with self.subTest(phase=phase, state=state):
                self.assertEqual(
                    self._errors(progress={"phase": phase, "state": state}), [])


class ProgressMappingTests(unittest.TestCase):
    def test_migrate_job_progress_is_deterministic(self):
        from job_metadata import migrate_job_progress
        self.assertEqual(
            migrate_job_progress("drafted", ""),
            {"phase": "application_prep", "state": "action_required"})
        self.assertEqual(
            migrate_job_progress("applied", None),
            {"phase": "application_review", "state": "waiting_employer"})
        # Recognized legacy stage -> phase; the exact old text becomes label.
        self.assertEqual(
            migrate_job_progress("in_progress", "onsite"),
            {"phase": "interview_loop", "state": "unknown", "label": "onsite"})
        # Unrecognized stage -> other + label; state is never guessed.
        self.assertEqual(
            migrate_job_progress("in_progress", "vibe check"),
            {"phase": "other", "state": "unknown", "label": "vibe check"})
        # Empty stage: the status literal is the only exact old text available.
        self.assertEqual(
            migrate_job_progress("in_progress", ""),
            {"phase": "other", "state": "unknown", "label": "in_progress"})
        # Closed roles retain a deterministic last-known phase.
        self.assertEqual(
            migrate_job_progress("rejected", ""),
            {"phase": "application_review", "state": "closed"})
        self.assertEqual(
            migrate_job_progress("ignored", ""),
            {"phase": "application_prep", "state": "closed"})
        self.assertEqual(
            migrate_job_progress("rejected", "recruiter screen"),
            {"phase": "recruiter_screen", "state": "closed",
             "label": "recruiter screen"})
        with self.assertRaises(ValueError):
            migrate_job_progress("offer", "")

    def test_default_progress_for_status_transitions(self):
        from job_metadata import default_progress_for_status
        current = {"phase": "technical_interview", "state": "scheduled",
                   "label": "Virtual screen",
                   "calendar_items": ["cal-acme-01", "cal-acme-02"]}
        # Closing keeps phase + label + calendar link, state -> closed.
        self.assertEqual(
            default_progress_for_status("rejected", current=current),
            {"phase": "technical_interview", "state": "closed",
             "label": "Virtual screen",
             "calendar_items": ["cal-acme-01", "cal-acme-02"]})
        # Reopening to in_progress never resurrects 'closed' — state unknown.
        closed = {"phase": "offer", "state": "closed"}
        self.assertEqual(
            default_progress_for_status("in_progress", current=closed),
            {"phase": "offer", "state": "unknown"})
        # A deliberately-set scheduling state survives the transition...
        self.assertEqual(
            default_progress_for_status("in_progress", current=current),
            {"phase": "technical_interview", "state": "scheduled",
             "label": "Virtual screen",
             "calendar_items": ["cal-acme-01", "cal-acme-02"]})
        # A known employer wait also survives; the status change alone should
        # not erase who owns the next action.
        self.assertEqual(
            default_progress_for_status(
                "in_progress",
                current={"phase": "application_review",
                         "state": "waiting_employer"}),
            {"phase": "application_review", "state": "waiting_employer"})
        # drafted/applied reset to the deterministic defaults (calendar kept).
        self.assertEqual(
            default_progress_for_status("drafted", current=current),
            {"phase": "application_prep", "state": "action_required",
             "calendar_items": ["cal-acme-01", "cal-acme-02"]})
        self.assertEqual(
            default_progress_for_status("applied", current={}),
            {"phase": "application_review", "state": "waiting_employer"})


if __name__ == "__main__":
    unittest.main()
