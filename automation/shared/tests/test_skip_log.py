"""The append-only skip-log: identity, fold order, tombstones, and append safety.

Three properties here are the reason the module exists, and each is a bug that was
found rather than imagined:

1. **The fold is file order, last wins.** Sorting on ``recorded`` lets a clock that
   stepped backwards elect the older event, so a reader sees a stale status with
   nothing to indicate it.
2. **The identity keeps the query string and never merges its two branches.**
   Dropping the query over-merges distinct postings; merging the ``url`` and
   ``pair`` branches makes a URL-less row collide with a URL-bearing one.
3. **A malformed interior line raises.** A silently dropped line is a silently
   lost skip, which resurfaces a posting the owner already dealt with.

Every fixture here is fictional (``examplecorp``, ``fakejobs.test``); nothing in
this suite touches a real log.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import skip_log  # noqa: E402

REPO_ROOT = SHARED.parents[1]


def _row(**over) -> dict:
    row = {"company": "Examplecorp", "slug": "examplecorp-swe-20260101",
           "date": "2026-01-01", "status": "applied", "role": "Software Engineer",
           "url": "https://fakejobs.test/jobs/1"}
    row.update(over)
    return row


class NormalizerTests(unittest.TestCase):
    def test_norm_url_keeps_the_query_string(self):
        # Dropping the query collapsed 367 distinct URLs in the starting corpus to
        # 353. An over-merged skip-log suppresses a posting nobody ever saw.
        a = skip_log.norm_url("https://fakejobs.test/apply?gh_jid=111")
        b = skip_log.norm_url("https://fakejobs.test/apply?gh_jid=222")
        self.assertNotEqual(a, b)

    def test_norm_url_keeps_the_fragment(self):
        a = skip_log.norm_url("https://fakejobs.test/board#job-111")
        b = skip_log.norm_url("https://fakejobs.test/board#job-222")
        self.assertNotEqual(a, b)

    def test_norm_url_casefolds_strips_and_drops_one_trailing_slash(self):
        self.assertEqual(skip_log.norm_url("  HTTPS://FakeJobs.TEST/Jobs/1/  "),
                         "https://fakejobs.test/jobs/1")

    def test_norm_url_collapses_internal_whitespace(self):
        # A URL pasted out of a wrapped email arrives with a newline in it.
        self.assertEqual(skip_log.norm_url("https://fakejobs.test/a\n  b"),
                         "https://fakejobs.test/a b")

    def test_norm_url_of_nothing_is_empty(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(skip_log.norm_url(value), "")

    def test_norm_text_collapses_strips_and_casefolds(self):
        self.assertEqual(skip_log.norm_text("  Example   Corp\tInc "),
                         "example corp inc")


class FoldKeyTests(unittest.TestCase):
    def test_url_branch_wins_when_there_is_a_url(self):
        self.assertEqual(skip_log.fold_key(_row(url="https://fakejobs.test/Jobs/1/")),
                         ("url", "https://fakejobs.test/jobs/1"))

    def test_pair_branch_when_the_url_is_empty_missing_or_whitespace(self):
        expected = ("pair", "examplecorp", "software engineer")
        for row in (_row(url=""), _row(url="   "), _row(url=None),
                    {k: v for k, v in _row().items() if k != "url"}):
            with self.subTest(url=row.get("url")):
                self.assertEqual(skip_log.fold_key(row), expected)

    def test_a_url_row_and_a_url_less_row_do_not_collide(self):
        # Same company and role, but one carries a URL. A reader treats these as
        # two independent skips (search_jobs derives a url key AND a pair key from
        # every row); merging them here would fold one posting's event onto the
        # other's and lose a skip.
        with_url = skip_log.fold_key(_row())
        without = skip_log.fold_key(_row(url=""))
        self.assertNotEqual(with_url, without)
        self.assertEqual(with_url[0], "url")
        self.assertEqual(without[0], "pair")

    def test_the_pair_branch_normalizes_both_halves(self):
        self.assertEqual(skip_log.fold_key(_row(url="", company="  EXAMPLE  Corp ",
                                                role="Software\tEngineer")),
                         ("pair", "example corp", "software engineer"))


class ReadEventsTests(unittest.TestCase):
    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(skip_log.read_events(Path(td) / "nope.jsonl"), [])

    def test_events_come_back_in_file_order(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text('{"n": 1}\n{"n": 2}\n{"n": 3}\n', encoding="utf-8")
            self.assertEqual([e["n"] for e in skip_log.read_events(path)], [1, 2, 3])

    def test_torn_final_line_is_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            # A process that died mid-append: no terminator on the last line.
            path.write_text('{"n": 1}\n{"n": 2, "part', encoding="utf-8")
            self.assertEqual([e["n"] for e in skip_log.read_events(path)], [1])

    def test_malformed_interior_line_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text('{"n": 1}\nGARBAGE\n{"n": 3}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                skip_log.read_events(path)

    def test_a_terminated_but_corrupt_final_line_also_raises(self):
        # A single fsync'd O_APPEND write cannot produce a terminated line that
        # fails to parse, so this is corruption rather than a crash artifact.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text('{"n": 1}\n{not json}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                skip_log.read_events(path)

    def test_a_non_object_line_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text('{"n": 1}\n[1, 2]\n{"n": 3}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                skip_log.read_events(path)

    def test_blank_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text('{"n": 1}\n\n   \n{"n": 2}\n', encoding="utf-8")
            self.assertEqual([e["n"] for e in skip_log.read_events(path)], [1, 2])


class FoldOrderTests(unittest.TestCase):
    def test_later_line_wins_even_when_its_recorded_clock_ran_backwards(self):
        """Regression guard: the clock-goes-backwards bug.

        An NTP step or a resume-from-suspend between two ``--sync-log`` runs makes
        the newer event carry the OLDER ``recorded`` stamp. File position is the
        causal order in an append-only file; a second-granularity wall clock is
        not. Sort on ``recorded`` and the stale status wins silently.
        """
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(status="applied"), source="sync",
                                  recorded="2026-02-01T10:00:00Z")
            skip_log.append_event(path, _row(status="rejected"), source="update",
                                  recorded="2026-01-01T09:00:00Z")   # earlier stamp
            postings = skip_log.read_postings(path)
            self.assertEqual(len(postings), 1)
            self.assertEqual(postings[0]["status"], "rejected")

    def test_last_line_wins_for_a_repeated_key(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            for status in ("drafted", "applied", "in_progress"):
                skip_log.append_event(path, _row(status=status), source="sync")
            folded = skip_log.fold(path)
            self.assertEqual(len(folded), 1)
            self.assertEqual(next(iter(folded.values()))["status"], "in_progress")

    def test_distinct_keys_all_survive(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(url="https://fakejobs.test/jobs/1"),
                                  source="sync")
            skip_log.append_event(path, _row(url="https://fakejobs.test/jobs/2"),
                                  source="sync")
            skip_log.append_event(path, _row(url="", role="Data Engineer"),
                                  source="sync")
            self.assertEqual(len(skip_log.fold(path)), 3)


class ForgetTests(unittest.TestCase):
    def test_a_tombstone_drops_the_key(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync")
            skip_log.append_event(path, skip_log.forget_row(url=_row()["url"]),
                                  source="update")
            self.assertEqual(skip_log.read_postings(path), [])

    def test_a_later_event_resurrects_a_forgotten_key(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(status="applied"), source="sync")
            skip_log.append_event(path, skip_log.forget_row(url=_row()["url"]),
                                  source="update")
            skip_log.append_event(path, _row(status="rejected"), source="sync")
            postings = skip_log.read_postings(path)
            self.assertEqual([p["status"] for p in postings], ["rejected"])

    def test_the_forget_flag_can_be_passed_to_append_event_directly(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync")
            skip_log.append_event(path, _row(), source="update", forget=True)
            self.assertEqual(skip_log.read_postings(path), [])

    def test_a_tombstone_by_company_and_role_addresses_the_pair_key(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(url=""), source="sync")
            skip_log.append_event(
                path,
                skip_log.forget_row(company="  examplecorp ", role="SOFTWARE ENGINEER"),
                source="update")
            self.assertEqual(skip_log.read_postings(path), [])

    def test_forget_row_refuses_an_unaddressable_tombstone(self):
        # Without this it would tombstone ("pair", "", ""), a key no real posting
        # holds — the un-skip would appear to work and change nothing.
        for kwargs in ({}, {"company": "Examplecorp"}, {"role": "Software Engineer"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    skip_log.forget_row(**kwargs)


class ReadPostingsTests(unittest.TestCase):
    def test_rows_carry_exactly_the_six_keys_the_yaml_rows_carried(self):
        # Every reader's parsing code must keep working untouched, so the row shape
        # is the old YAML `postings` shape and event metadata is not leaked into it.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync")
            (posting,) = skip_log.read_postings(path)
            self.assertEqual(set(posting),
                             {"company", "slug", "date", "status", "role", "url"})
            self.assertEqual(posting, _row())

    def test_missing_keys_come_back_blank_rather_than_absent(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            path.write_text(
                json.dumps({"url": "https://fakejobs.test/jobs/9",
                            "recorded": "2026-01-01T00:00:00Z", "source": "sync"}) + "\n",
                encoding="utf-8")
            (posting,) = skip_log.read_postings(path)
            self.assertEqual(posting["url"], "https://fakejobs.test/jobs/9")
            self.assertEqual(posting["company"], "")
            self.assertEqual(posting["slug"], "")

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(skip_log.read_postings(Path(td) / "nope.jsonl"), [])


class AppendEventTests(unittest.TestCase):
    def test_round_trips_through_read_events_with_its_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="backfill",
                                  recorded="2026-01-02T03:04:05Z")
            (event,) = skip_log.read_events(path)
            self.assertEqual(event["source"], "backfill")
            self.assertEqual(event["recorded"], "2026-01-02T03:04:05Z")
            self.assertNotIn("forget", event)
            for key, value in _row().items():
                self.assertEqual(event[key], value)

    def test_default_recorded_is_a_utc_z_stamp(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync")
            (event,) = skip_log.read_events(path)
            self.assertRegex(event["recorded"],
                             r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "market" / "logs" / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync")
            self.assertTrue(path.exists())

    def test_one_append_is_exactly_one_line(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync")
            skip_log.append_event(path, _row(url="https://fakejobs.test/jobs/2"),
                                  source="sync")
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(len(text.splitlines()), 2)

    def test_an_embedded_newline_never_reaches_the_file_raw(self):
        # A company string scraped out of HTML can carry a newline. One raw newline
        # in a value would split one event across two lines and hand the reader two
        # malformed records.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(company="Example\nCorp\r\nInc"),
                                  source="sync")
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)
            (event,) = skip_log.read_events(path)
            self.assertEqual(event["company"], "Example\nCorp\r\nInc")

    def test_non_ascii_is_written_unescaped(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(role="Ingénieur Logiciel"), source="sync")
            self.assertIn("Ingénieur", path.read_text(encoding="utf-8"))
            (event,) = skip_log.read_events(path)
            self.assertEqual(event["role"], "Ingénieur Logiciel")

    def test_keys_are_sorted_so_two_identical_events_are_identical_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync",
                                  recorded="2026-01-02T03:04:05Z")
            first = path.read_text(encoding="utf-8")
            path.unlink()
            shuffled = dict(reversed(list(_row().items())))
            skip_log.append_event(path, shuffled, source="sync",
                                  recorded="2026-01-02T03:04:05Z")
            self.assertEqual(path.read_text(encoding="utf-8"), first)

    def test_append_behind_a_torn_tail_does_not_merge_onto_the_fragment(self):
        # Otherwise one crash converts a tolerable torn tail into a malformed
        # INTERIOR line and takes the whole log offline.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write('{"company": "Examplecorp", "tor')  # no terminator
            skip_log.append_event(path, _row(url="https://fakejobs.test/jobs/2"),
                                  source="sync")
            self.assertEqual(len(skip_log.read_events(path)), 2)
            self.assertEqual(len(skip_log.read_postings(path)), 2)

    def test_the_file_is_only_ever_appended_to(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.jsonl"
            skip_log.append_event(path, _row(), source="sync")
            before = path.read_bytes()
            skip_log.append_event(path, _row(status="rejected"), source="update")
            skip_log.append_event(path, skip_log.forget_row(url=_row()["url"]),
                                  source="update")
            self.assertTrue(path.read_bytes().startswith(before))


class VendoringTests(unittest.TestCase):
    """The canonical module and both vendored copies must be byte-identical.

    ``sync_vendored.check()`` iterates ``TARGETS`` and never enumerates a skill's
    ``_vendor/`` to ask whether every file there is declared — so an undeclared
    copy leaves the pre-commit vendor gate green forever while the copies drift.
    The file that defines the identity and the normalizers is the worst one to
    leave undeclared, hence this direct check.
    """

    SOURCE = "automation/shared/skip_log.py"
    COPIES = ("skills/application-tracker/scripts/_vendor/skip_log.py",
              "skills/job-search/scripts/_vendor/skip_log.py")

    def test_declared_in_the_vendoring_targets(self):
        sys.path.insert(0, str(REPO_ROOT / "automation" / "vendoring"))
        try:
            import sync_vendored  # noqa: PLC0415
        finally:
            sys.path.pop(0)
        self.assertEqual(sync_vendored.TARGETS.get(self.SOURCE), list(self.COPIES))

    def test_copies_are_byte_identical(self):
        digest = hashlib.sha256((REPO_ROOT / self.SOURCE).read_bytes()).hexdigest()
        for copy in self.COPIES:
            with self.subTest(copy=copy):
                path = REPO_ROOT / copy
                self.assertTrue(path.exists(), f"{copy} missing — run sync_vendored.py")
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
