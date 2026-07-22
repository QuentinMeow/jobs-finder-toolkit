"""Idempotent event appends — identity is (entity, fetch, type)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from store.atomic import read_jsonl  # noqa: E402
from store.events import append_event  # noqa: E402


class IdempotentEventTests(unittest.TestCase):
    def test_duplicate_identity_is_noop(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.jsonl"
            ev = {"entity": "gh-1", "fetch": "f1", "type": "first_seen",
                  "at": "2026-07-21T09:30:00Z"}
            self.assertTrue(append_event(p, ev))
            # Re-append same identity (even with different payload) → no-op.
            self.assertFalse(append_event(p, {**ev, "at": "changed"}))
            self.assertEqual(len(read_jsonl(p)), 1)

    def test_distinct_identities_all_appended(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.jsonl"
            append_event(p, {"entity": "gh-1", "fetch": "f1", "type": "first_seen"})
            append_event(p, {"entity": "gh-1", "fetch": "f2", "type": "seen"})
            append_event(p, {"entity": "gh-1", "fetch": "f2", "type": "field_changed"})
            self.assertEqual(len(read_jsonl(p)), 3)

    def test_missing_identity_field_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.jsonl"
            with self.assertRaises(ValueError):
                append_event(p, {"entity": "gh-1", "type": "seen"})  # no 'fetch'

    def test_idempotent_across_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.jsonl"
            ev = {"entity": "gh-1", "fetch": "f1", "type": "first_seen"}
            append_event(p, ev)
            # A fresh process (re-read from disk) still sees the identity → no dup.
            self.assertFalse(append_event(p, ev))
            self.assertEqual(len(read_jsonl(p)), 1)


if __name__ == "__main__":
    unittest.main()
