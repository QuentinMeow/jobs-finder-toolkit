"""Golden test for the compact stdout contract (summary + top-K table).

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s skills/job-search/scripts/tests \
        -t skills/job-search/scripts/tests

No network: pure rendering of hand-built postings.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS), str(_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import search_jobs  # noqa: E402
from common import JobPosting  # noqa: E402


def _row(company, title, url, score, level, age, visa):
    p = JobPosting(source="board", company=company, title=title, url=url)
    p.score = score
    p.job_level = {"normalized": level}
    p.age_days = age
    p.visa_label = visa
    return p


# Fixed-width, deterministic: company clipped to 20, title to 32, URL last (unpadded,
# so no line has trailing whitespace). This is the contract agents read instead of
# dumping the discoveries file.
GOLDEN_TABLE = (
    "  #  Company               Title                              Score  Level"
    "          Age  Visa     URL\n"
    "------------------------------------------------------------------------"
    "------------------------  ---\n"
    "  1  Acme AI               Senior Backend Engineer               42  senior"
    "        0.5d  yes      https://acme.example/jobs/1\n"
    "  2  Beacon Labs Incorpor  Distributed Systems Engineer (Pl    33.5  mid"
    "           2.0d  unclear  https://beacon.example/careers/42\n"
    "  3  Delta                 Site Reliability Engineer             12  staff"
    "            ?  no       https://delta.example/j/7"
)


class CompactTableGoldenTests(unittest.TestCase):
    def _kept(self):
        return [
            _row("Acme AI", "Senior Backend Engineer",
                 "https://acme.example/jobs/1", 42.0, "senior", 0.5, "yes"),
            _row("Beacon Labs Incorporated Longname",
                 "Distributed Systems Engineer (Platform, Core Infra Team)",
                 "https://beacon.example/careers/42", 33.5, "mid", 2.0, "unclear"),
            _row("Delta", "Site Reliability Engineer",
                 "https://delta.example/j/7", 12.0, "staff", None, "no"),
        ]

    def test_table_matches_golden(self):
        self.assertEqual(search_jobs.render_compact_table(self._kept()), GOLDEN_TABLE)

    def test_no_line_has_trailing_whitespace(self):
        for line in search_jobs.render_compact_table(self._kept()).splitlines():
            self.assertEqual(line, line.rstrip(), f"trailing space in: {line!r}")

    def test_missing_age_renders_question_mark(self):
        table = search_jobs.render_compact_table(self._kept())
        self.assertRegex(table, r"staff\s+\?\s+no")   # age None -> "?"

    def test_run_summary_is_five_lines(self):
        meta = {"stage": 1, "n_companies": 42,
                "aggregators": ["jobicy", "themuse"], "n_raw": 1234}
        summary = search_jobs.render_run_summary(
            meta, self._kept(), snapshot_display="local/search_cache/example-stage1-x.json",
            discoveries_path="applications/1_discoveries/20260115-example.md",
            json_path=None)
        lines = summary.splitlines()
        self.assertEqual(len(lines), 5)
        self.assertIn("42 company boards + 2 aggregator sources", lines[0])
        self.assertIn("Fetched 1234 postings -> kept 3", lines[1])
        self.assertIn("example-stage1-x.json", lines[2])
        self.assertTrue(lines[4].endswith("-"))       # JSON: - when no --json-out

    def test_all_matches_bypasses_top_k_and_diversity(self):
        postings = self._kept()
        selected = search_jobs.select_diverse(
            postings, top_k=None, max_per_company=1)
        self.assertEqual(selected, postings)

    def test_dedupe_keeps_highest_scoring_row_not_fetch_order(self):
        low = _row("Acme AI", "Senior Backend Engineer",
                   "https://acme.example/jobs/old", 10, "senior", 3, "unclear")
        high = _row("acme ai", "senior backend engineer",
                    "https://acme.example/jobs/best", 40, "senior", 1, "yes")
        self.assertEqual(search_jobs.dedupe([low, high]), [high])

    def test_review_report_writes_a_run_file_and_a_stable_pointer(self):
        posting = self._kept()[0]
        posting.review_reasons = ["location_requires_review"]
        with TemporaryDirectory() as tmp:
            run_path, pointer = search_jobs.write_review_report(
                [posting], Path(tmp), "example", stamp="20260115T090000Z")
            self.assertTrue(run_path.is_file())
            self.assertTrue(pointer.is_file())
            self.assertEqual(run_path.name,
                             "example-filter-review-20260115T090000Z.json")
            self.assertEqual(pointer.name, "example-filter-review.json")
            self.assertEqual(json.loads(run_path.read_text()),
                             json.loads(pointer.read_text()))
            self.assertEqual(json.loads(pointer.read_text())["count"], 1)

    def test_an_empty_review_run_never_deletes_the_previous_run_artifact(self):
        """Regression: a zero-row run used to unlink the artifact outright.

        The filename is fixed per (cache dir, profile), so the file it removed was
        the PREVIOUS run's evidence — and afterwards nothing on disk told "this run
        flagged nothing" apart from "no run ever wrote one".
        """
        posting = self._kept()[0]
        posting.review_reasons = ["location_requires_review"]
        with TemporaryDirectory() as tmp:
            first_run, pointer = search_jobs.write_review_report(
                [posting], Path(tmp), "example", stamp="20260115T090000Z")
            empty_run, pointer_again = search_jobs.write_review_report(
                [], Path(tmp), "example", stamp="20260115T101500Z")

            self.assertTrue(first_run.is_file())          # NOT deleted
            self.assertEqual(json.loads(first_run.read_text())["count"], 1)
            self.assertNotEqual(first_run, empty_run)
            self.assertEqual(pointer, pointer_again)
            # Zero rows is a recorded fact, not an absence.
            self.assertTrue(empty_run.is_file())
            self.assertTrue(pointer.is_file())
            self.assertEqual(json.loads(pointer.read_text())["count"], 0)
            self.assertEqual(json.loads(pointer.read_text())["postings"], [])

    def test_two_runs_inside_one_second_do_not_share_a_run_file(self):
        with TemporaryDirectory() as tmp:
            first, _ = search_jobs.write_review_report(
                [], Path(tmp), "example", stamp="20260115T090000Z")
            second, _ = search_jobs.write_review_report(
                [], Path(tmp), "example", stamp="20260115T090000Z")
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_file() and second.is_file())

    def test_review_payload_names_the_snapshot_and_marks_clipped_descriptions(self):
        posting = self._kept()[0]
        posting.review_reasons = ["title_occupation_ambiguous"]
        posting.description = "x" * 5000                 # to_dict clips at 400
        short = self._kept()[1]
        short.review_reasons = ["title_occupation_ambiguous"]
        short.description = "Backend engineer."
        with TemporaryDirectory() as tmp:
            _run, pointer = search_jobs.write_review_report(
                [posting, short], Path(tmp), "example",
                snapshot_path="/cache/example-stage1-latest.json")
            payload = json.loads(pointer.read_text())
            self.assertEqual(payload["snapshot"],
                             "/cache/example-stage1-latest.json")
            self.assertTrue(payload["postings"][0]["description_truncated"])
            self.assertFalse(payload["postings"][1]["description_truncated"])

    def test_json_output_creates_nested_parent_directory(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "audit" / "matches.json"
            written = search_jobs.write_json_output(path, self._kept(), {})
            self.assertEqual(written, path)
            self.assertEqual(len(json.loads(path.read_text())), 3)


def _meta(**over):
    """Minimal render_markdown meta, overridable per test."""
    meta = {"profile": "example", "generated": "2026-01-15 09:00 UTC",
            "max_age_days": 3, "visa_policy": "exclude_negative", "n_companies": 4,
            "aggregators": [], "stage": 1, "n_raw": 10, "n_raw_unique": None,
            "n_blacklisted": 0, "n_considered": 0, "n_recently_searched": 0,
            "n_low_quality": 0, "n_review": 0, "n_occupation_ambiguous_overflow": 0,
            "n_title_hard_excluded": 0, "n_title_word_filter_review": 0,
            "n_title_word_filter_review_kept": 0, "max_per_company": 3, "errors": []}
    meta.update(over)
    return meta


def _review_row(company, title, url, score, reasons):
    p = JobPosting(source="board", company=company, title=title, url=url)
    p.score = score
    p.review_reasons = list(reasons)
    return p


class MarkdownClipTests(unittest.TestCase):
    """No cell is cut mid-token, and a cut cell says it was cut."""

    def assertWholeWords(self, clipped, original):
        """The kept text is a prefix of the original ending on a token boundary."""
        body = clipped.rstrip(search_jobs.CLIP_MARK)
        self.assertTrue(original.startswith(body), clipped)
        self.assertTrue(
            len(body) == len(original) or original[len(body)] in " \t;,/",
            f"{clipped!r} cuts inside a token of {original!r}")

    def test_a_long_value_is_clipped_at_a_word_boundary_and_marked(self):
        original = "Distributed Systems Engineer (Platform, Core Infra Team)"
        clipped = search_jobs._clip(original, 46)
        self.assertLessEqual(len(clipped), 46)
        self.assertTrue(clipped.endswith(search_jobs.CLIP_MARK))
        self.assertFalse(clipped.rstrip(search_jobs.CLIP_MARK).endswith(" "))
        self.assertWholeWords(clipped, original)
        self.assertNotEqual(clipped, original[:46])   # the old raw slice

    def test_a_single_long_token_still_fits_the_budget(self):
        clipped = search_jobs._clip("x" * 200, 12)
        self.assertEqual(len(clipped), 12)
        self.assertTrue(clipped.endswith(search_jobs.CLIP_MARK))

    def test_a_short_value_is_untouched(self):
        self.assertEqual(search_jobs._clip("Acme AI", 24), "Acme AI")

    def test_a_reason_is_whole_or_absent_never_a_fragment(self):
        reasons = ["skills: python, kubernetes, distributed systems, terraform",
                   "recent posting (0.5d)", "over-leveled (-2)", "visa: unclear"]
        why = search_jobs._clip_reasons(reasons, 100)
        self.assertLessEqual(len(why), 100)
        for reason in reasons:
            if reason.split(";")[0] in why:
                self.assertIn(reason, why)      # present => present in full
        self.assertRegex(why, r"\+\d+ more$")   # and the rest are counted

    def test_every_reason_that_fits_is_kept_verbatim(self):
        self.assertEqual(
            search_jobs._clip_reasons(["over-leveled (-2)", "visa: unclear"], 100),
            "over-leveled (-2); visa: unclear")

    def test_the_table_clips_company_title_location_and_why(self):
        p = JobPosting(
            source="board",
            company="Beacon Laboratories International Incorporated",
            title="Distributed Systems Engineer (Platform, Core Infra Team)",
            url="https://beacon.example/careers/42",
            location="Greater Seattle Metropolitan Area, Washington, United States")
        p.score = 33.5
        p.age_days = 2.0
        p.workplace = "hybrid"
        p.reasons = ["skills: python, kubernetes, distributed systems, terraform, go",
                     "recent posting (2.0d)", "over-leveled (-2)", "visa: unclear"]
        row = [line for line in
               search_jobs.render_markdown([p], {"name": "Example"}, _meta()).splitlines()
               if line.startswith("| 1 |")][0]
        cells = [c.strip() for c in row.split("|")[1:-1]]
        company, title, loc, why = cells[2], cells[3], cells[7], cells[11]
        for cell, budget in ((company, search_jobs.CLIP_COMPANY),
                             (title, search_jobs.CLIP_TITLE),
                             (loc, search_jobs.CLIP_LOC),
                             (why, search_jobs.CLIP_WHY)):
            self.assertLessEqual(len(cell), budget, cell)
        self.assertTrue(company.endswith(search_jobs.CLIP_MARK), company)
        self.assertTrue(title.endswith(search_jobs.CLIP_MARK), title)
        self.assertWholeWords(title, p.title)
        self.assertWholeWords(company, p.company)
        self.assertNotEqual(title, p.title[:46])          # the old raw slices
        self.assertNotEqual(loc, p.location[:30])
        # Every reason shown is shown whole; the rest are counted, not amputated.
        body, plus, marker = why.rpartition(" +")
        self.assertTrue(plus and marker.endswith("more"), why)
        for item in body.split("; "):
            self.assertIn(item, p.reasons)
        self.assertNotEqual(why, "; ".join(p.reasons)[:100])   # the old raw slice


class FunnelArithmeticTests(unittest.TestCase):
    """The header's nested counts must describe the same population."""

    def test_the_rescue_count_can_never_exceed_the_review_count(self):
        # The exact shape of the audited "420 preserved... of which 561 were kept":
        # the raw rescue count is pre-dedupe, the review count is post-dedupe+cap.
        review = [_review_row(f"Co {i}", "Member of Technical Staff",
                              f"https://co{i}.example/j", 10,
                              ["title_word_filter_override"])
                  for i in range(3)]
        meta = search_jobs.build_meta(
            {}, types.SimpleNamespace(profile="example"), stage=1, n_companies=1,
            aggregators=[], n_raw=99,
            counts={"n_blacklisted": 0, "n_considered": 0, "n_recently_searched": 0,
                    "n_non_ai": 0, "n_low_quality": 0, "n_review": len(review),
                    "n_title_word_filter_review": 561, "review_postings": review},
            max_age=3, max_per_company=3, errors=[],
            now=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(meta["n_title_word_filter_review_kept"], 3)

        header = [line for line in
                  search_jobs.render_markdown([], {"name": "Example"}, meta).splitlines()
                  if "preserved for filter review" in line][0]
        self.assertIn("3 preserved for filter review, 3 of them kept by "
                      "titles.word_filter", header)
        # the pre-dedupe total is still reported, but not nested inside the smaller one
        self.assertIn("rescued 561 raw postings", header)
        self.assertNotIn("of which 561", header)

    def test_scanned_says_how_many_of_the_raw_rows_were_unique(self):
        md = search_jobs.render_markdown(
            [], {"name": "Example"}, _meta(n_raw=99, n_raw_unique=61))
        self.assertIn("Scanned 99 postings (61 unique)", md)

    def test_scanned_omits_the_unique_count_when_it_was_not_computed(self):
        md = search_jobs.render_markdown([], {"name": "Example"}, _meta(n_raw=99))
        self.assertIn("Scanned 99 postings ", md)
        self.assertNotIn("unique", md)


class ManualReviewSectionTests(unittest.TestCase):
    """The persistent report has to name the artifact it keeps counting."""

    def _rows(self, n):
        return [_review_row(f"Company {i}", f"Ambiguous Role {i}",
                            f"https://co{i}.example/j/{i}", 100 - i,
                            ["title_occupation_ambiguous"])
                for i in range(n)]

    def test_the_section_names_the_artifact_and_how_to_read_it(self):
        rows = self._rows(3)
        md = search_jobs.render_markdown(
            [], {"name": "Example"},
            _meta(n_review=len(rows),
                  review_families=search_jobs.reason_families(rows)),
            review_path="/cache/example-filter-review.json", review_postings=rows)
        self.assertIn("## Manual review (3 shown of 3)", md)
        self.assertIn("/cache/example-filter-review.json", md)
        self.assertIn("json.tool", md)                       # a runnable command
        self.assertIn("[link](https://co0.example/j/0)", md)
        self.assertIn("By review reason: title_occupation_ambiguous 3", md)

    def test_the_preview_is_capped_but_the_full_count_is_stated(self):
        rows = self._rows(25)
        md = search_jobs.render_markdown(
            [], {"name": "Example"}, _meta(n_review=len(rows)),
            review_path="/cache/example-filter-review.json", review_postings=rows)
        self.assertIn("## Manual review (10 shown of 25)", md)
        self.assertEqual(md.count("[link](https://co"), 10)
        self.assertIn("all 25 row(s)", md)
        self.assertIn("15 further row(s) are in the artifact only", md)

    def test_the_capped_rows_are_counted_split_by_rule_and_given_a_path(self):
        overflow = self._rows(37)
        md = search_jobs.render_markdown(
            [], {"name": "Example"},
            _meta(n_review=2, n_occupation_ambiguous_overflow=len(overflow),
                  overflow_families=search_jobs.reason_families(overflow)),
            review_path="/cache/example-filter-review.json",
            review_postings=self._rows(2),
            overflow_path="/cache/example-filter-review-overflow.json")
        self.assertIn("37 ambiguous-occupation posting(s) exceeded", md)
        self.assertIn("titles.occupation_review_cap", md)
        self.assertIn("/cache/example-filter-review-overflow.json", md)
        self.assertIn("By review reason: title_occupation_ambiguous 37", md)

    def test_a_run_that_preserved_and_capped_nothing_has_no_section(self):
        md = search_jobs.render_markdown([], {"name": "Example"}, _meta())
        self.assertNotIn("## Manual review", md)

    def test_the_run_summary_names_both_lanes_with_their_rule_split(self):
        review, overflow = self._rows(4), self._rows(37)
        summary = search_jobs.render_run_summary(
            {"stage": 1, "n_companies": 4, "aggregators": [], "n_raw": 99,
             "n_review": len(review),
             "n_occupation_ambiguous_overflow": len(overflow),
             "review_families": search_jobs.reason_families(review),
             "overflow_families": search_jobs.reason_families(overflow)},
            [], snapshot_display="snap.json", discoveries_path="d.md", json_path=None,
            review_path="/cache/example-filter-review.json",
            overflow_path="/cache/example-filter-review-overflow.json")
        self.assertIn("Review:      /cache/example-filter-review.json — 4 row(s) "
                      "[title_occupation_ambiguous 4]", summary)
        self.assertIn("Overflow:    /cache/example-filter-review-overflow.json — "
                      "37 row(s) over titles.occupation_review_cap", summary)

    def test_the_run_summary_stays_quiet_when_nothing_was_capped(self):
        summary = search_jobs.render_run_summary(
            {"stage": 1, "n_companies": 4, "aggregators": [], "n_raw": 99,
             "n_review": 0, "n_occupation_ambiguous_overflow": 0},
            [], snapshot_display="snap.json", discoveries_path="d.md", json_path=None,
            review_path="/cache/example-filter-review.json")
        self.assertNotIn("Overflow:", summary)


class OverflowPersistenceTests(unittest.TestCase):
    """The occupation cap bounds what is SHOWN, never what is kept on disk."""

    def _ambiguous(self, n):
        rows = []
        for i in range(n):
            p = JobPosting(source="board", company=f"Co {i}",
                           title="Member of Technical Staff",
                           url=f"https://co{i}.example/j/{i}",
                           location="Remote, United States",
                           description="Python, distributed systems.")
            p.review_reasons = ["title_occupation_ambiguous"]
            p.score = float(n - i)
            rows.append(p)
        return rows

    def test_build_meta_splits_both_lanes_by_rule(self):
        rows = self._ambiguous(5)
        counts = {"n_blacklisted": 0, "n_considered": 0, "n_recently_searched": 0,
                  "n_non_ai": 0, "n_low_quality": 0,
                  "n_occupation_ambiguous_overflow": 3,
                  "n_review": 2, "review_postings": rows[:2],
                  "overflow_postings": rows[2:]}
        meta = search_jobs.build_meta(
            {}, types.SimpleNamespace(profile="example"), stage=1, n_companies=0,
            aggregators=[], n_raw=5, counts=counts, max_age=None,
            max_per_company=3, errors=[],
            now=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(meta["review_families"],
                         [("title_occupation_ambiguous", 2)])
        self.assertEqual(meta["overflow_families"],
                         [("title_occupation_ambiguous", 3)])

    def test_filter_score_rank_returns_every_row_the_cap_demoted(self):
        from registry import Registry

        profile = {"titles": {"include": ["engineer"], "exclude": [],
                              "occupation_review_cap": 2}}
        rows = self._ambiguous(5)
        ctx = {"considered_urls": set(), "considered_pairs": set(), "skip_days": 0,
               "search_tokens": [], "ignore_search_log": True, "ai_native_keys": set()}
        _kept, counts = search_jobs.filter_score_rank(
            rows, profile, ctx, max_age=None, top_k=40, max_per_company=10,
            sponsor_index=None, company_levels={}, registry=Registry([]),
            now=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc))
        n_over = counts["n_occupation_ambiguous_overflow"]
        self.assertGreater(n_over, 0, "fixture must actually trip the cap")
        self.assertEqual(len(counts["overflow_postings"]), n_over)
        self.assertEqual(len(counts["review_postings"]) + n_over, len(rows))
        # The demoted rows keep the rule ids that demoted them.
        for p in counts["overflow_postings"]:
            self.assertIn("title_occupation_ambiguous", p.review_reasons)

    def test_the_overflow_lane_gets_its_own_durable_artifact(self):
        rows = self._ambiguous(3)
        with TemporaryDirectory() as tmp:
            run_path, pointer = search_jobs.write_review_report(
                rows, Path(tmp), "example", kind=search_jobs.OVERFLOW_KIND,
                stamp="20260115T090000Z")
            self.assertEqual(
                run_path.name,
                "example-filter-review-overflow-20260115T090000Z.json")
            self.assertEqual(pointer.name, "example-filter-review-overflow.json")
            payload = json.loads(pointer.read_text())
            self.assertEqual(payload["kind"], search_jobs.OVERFLOW_KIND)
            self.assertEqual(payload["count"], 3)
            self.assertEqual(payload["families"],
                             {"title_occupation_ambiguous": 3})
            self.assertEqual(payload["postings"][0]["review_reasons"],
                             ["title_occupation_ambiguous"])


if __name__ == "__main__":
    unittest.main()
