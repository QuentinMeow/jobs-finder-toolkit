"""Build ledger: set-difference (incl. started-before/committed-after), clock guard."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from store import serialization  # noqa: E402
from store.ledger import BuildLedger, check_clock_monotonic, pending_manifests  # noqa: E402
from store.manifest import build_envelope, write_manifest  # noqa: E402
from store.paths import domain_layout  # noqa: E402


def _commit(layout, fetch_id, dt):
    env = build_envelope(
        fetch_id=fetch_id, source="greenhouse", operation="board",
        request={"url": "u"}, status=200, fetched_at=serialization.to_z(dt),
        payload=None, context={"company": "examplecorp"},
    )
    write_manifest(layout.manifest_path("greenhouse", dt, fetch_id), env)


class LedgerBasicsTests(unittest.TestCase):
    def test_sequence_is_monotonic(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = BuildLedger(Path(td) / "build-ledger.jsonl")
            s1 = ledger.record("f1", fetched_at="2026-07-21T09:30:00Z",
                               built_at="2026-07-21T10:00:00Z")
            s2 = ledger.record("f2", fetched_at="2026-07-21T09:31:00Z",
                               built_at="2026-07-21T10:00:00Z")
            self.assertEqual((s1, s2), (1, 2))
            self.assertEqual(ledger.next_seq(), 3)

    def test_reload_recovers_state(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "build-ledger.jsonl"
            BuildLedger(p).record("f1", fetched_at="2026-07-21T09:30:00Z",
                                  built_at="2026-07-21T10:00:00Z")
            fresh = BuildLedger(p)
            self.assertEqual(fresh.processed_fetch_ids(), {"f1"})
            self.assertEqual(fresh.max_seq(), 1)


class SetDifferenceTests(unittest.TestCase):
    def test_started_before_committed_after_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            ledger = BuildLedger(layout.build_ledger)

            # A fetch that started later commits and is processed by build #1.
            late_start = "20260721T093000Z-000002-bbbbbb"
            _commit(layout, late_start,
                    datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc))
            first = pending_manifests(layout, ledger)
            self.assertEqual([e["fetch_id"] for _p, e in first], [late_start])
            ledger.record(late_start, fetched_at="2026-07-21T09:30:00Z",
                          built_at="2026-07-21T10:00:00Z")

            # Now a fetch that STARTED earlier (older fetch_id / timestamp) commits
            # AFTER build #1. A timestamp watermark would skip it forever; the
            # set-difference picks it up because it is simply not in the ledger.
            early_start = "20260721T092800Z-000001-aaaaaa"
            _commit(layout, early_start,
                    datetime(2026, 7, 21, 9, 28, tzinfo=timezone.utc))
            ledger.reload()
            second = pending_manifests(layout, ledger)
            self.assertEqual([e["fetch_id"] for _p, e in second], [early_start])

    def test_pending_is_canonically_ordered(self):
        with tempfile.TemporaryDirectory() as td:
            layout = domain_layout(Path(td), "jobs")
            _commit(layout, "20260721T093100Z-000002-bbbbbb",
                    datetime(2026, 7, 21, 9, 31, tzinfo=timezone.utc))
            _commit(layout, "20260721T093000Z-000001-aaaaaa",
                    datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc))
            pending = pending_manifests(layout, BuildLedger(layout.build_ledger))
            self.assertEqual([e["fetch_id"] for _p, e in pending],
                             ["20260721T093000Z-000001-aaaaaa",
                              "20260721T093100Z-000002-bbbbbb"])


class ClockGuardTests(unittest.TestCase):
    def test_backwards_clock_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = BuildLedger(Path(td) / "build-ledger.jsonl")
            ledger.record("f1", fetched_at="2026-07-21T09:30:00Z",
                          built_at="2026-07-21T10:00:00Z")
            self.assertTrue(check_clock_monotonic("2026-07-21T09:31:00Z", ledger))
            self.assertFalse(check_clock_monotonic("2026-07-21T09:29:00Z", ledger))

    def test_empty_ledger_is_ok(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = BuildLedger(Path(td) / "build-ledger.jsonl")
            self.assertTrue(check_clock_monotonic("2026-07-21T09:30:00Z", ledger))


class TornLedgerTests(unittest.TestCase):
    """BuildLedger loads never hard-crash on torn / merged lines; append repairs."""

    def _line(self, fid, seq, ts):
        return serialization.dumps_jsonl_line(
            {"fetch_id": fid, "seq": seq, "fetched_at": ts,
             "built_at": "2026-07-21T10:00:00Z", "clock_ok": True})

    def test_init_tolerates_torn_and_merged_interior_lines(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "build-ledger.jsonl"
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(self._line("f1", 1, "2026-07-21T09:30:00Z"))
                fh.write('{"fetch_id": "f2" GARBAGE-MERGED-LINE\n')  # corrupt interior
                fh.write(self._line("f3", 3, "2026-07-21T09:32:00Z"))
            # Must NOT raise (the pre-fix code hard-raised here); recovers f1 + f3.
            ledger = BuildLedger(p)
            self.assertEqual(ledger.processed_fetch_ids(), {"f1", "f3"})

    def test_append_after_torn_tail_recovers_and_extends(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "build-ledger.jsonl"
            first = BuildLedger(p)
            first.record("f1", fetched_at="2026-07-21T09:30:00Z",
                         built_at="2026-07-21T10:00:00Z")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write('{"fetch_id": "f2" tor')  # torn tail, no newline
            second = BuildLedger(p)  # repairs the torn tail on load
            second.record("f3", fetched_at="2026-07-21T09:32:00Z",
                          built_at="2026-07-21T10:00:00Z")
            fresh = BuildLedger(p)
            # The torn f2 is gone; f1 and f3 survive — no record silently lost.
            self.assertEqual(fresh.processed_fetch_ids(), {"f1", "f3"})


if __name__ == "__main__":
    unittest.main()
