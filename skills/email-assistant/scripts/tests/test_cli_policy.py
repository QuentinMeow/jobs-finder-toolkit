from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import outlook_email as cli
from outlook_email import CLI_COMMANDS, _store_review, _store_review_summary, build_parser


class CliPolicyTests(unittest.TestCase):
    def test_command_surface_is_draft_only(self):
        self.assertEqual(
            set(CLI_COMMANDS),
            {
                "doctor", "login", "logout", "inbox", "sent", "drafts", "review-window",
                "read", "sync-store", "store-staleness", "store-review", "match-application", "create-draft",
                "create-reply-draft",
            },
        )
        parser = build_parser()
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["send"])

    def test_store_sync_defaults_to_a_precise_30_day_window(self):
        args = build_parser().parse_args(["sync-store"])
        self.assertEqual(args.days, 30)
        self.assertFalse(args.all)
        self.assertFalse(args.full)

    def test_store_review_uses_the_same_freshness_tolerance(self):
        args = build_parser().parse_args(["store-review"])
        self.assertEqual(args.threshold_seconds, 60)
        self.assertFalse(args.details)
        self.assertTrue(build_parser().parse_args(["store-review", "--details"]).details)

    def test_store_review_summary_is_bounded_and_omits_full_projections(self):
        report = {
            "account": "acct-01",
            "review_complete": True,
            "freshness": {"store_stale": False},
            "integrity": {"ok": True},
            "counts": {"stored_messages": 3},
            "context_counts": {"applications": 2},
            "records": [{"message_key": "acct-01/one"}],
            "projections": {
                "needs_reply": [
                    {"message_key": "acct-01/one"},
                    {"message_key": "acct-01/two"},
                ],
                "deadlines": [{"message_key": "acct-01/three"}],
                "unresolved": [{"message_key": "acct-01/four"}],
            },
        }
        summary = _store_review_summary(report, key_limit=1)
        self.assertNotIn("records", summary)
        self.assertNotIn("projections", summary)
        self.assertEqual(summary["sample_message_keys"], {
            "needs_reply": ["acct-01/one"],
            "deadlines": ["acct-01/three"],
            "unresolved": ["acct-01/four"],
            "limit_per_queue": 1,
        })
        self.assertTrue(summary["details_available"])

    def test_store_review_cli_defaults_to_summary_and_details_is_explicit(self):
        full_report = {
            "account": "acct-01",
            "review_complete": True,
            "freshness": {"store_stale": False},
            "integrity": {"ok": True},
            "counts": {"stored_messages": 1},
            "context_counts": {"applications": 0},
            "records": [{"message_key": "acct-01/one"}],
            "projections": {"needs_reply": [], "deadlines": [], "unresolved": []},
        }
        settings = object()
        with (
            patch.object(cli, "_settings", return_value=settings),
            patch.object(cli, "AuthManager"),
            patch.object(cli, "_client", return_value=(settings, object())),
            patch.object(cli, "_email_store", return_value=object()),
            patch.object(cli, "_store_review", return_value=(full_report, 0)),
            patch.object(cli, "_json") as emit,
        ):
            self.assertEqual(cli.main(["store-review"]), 0)
            default_output = emit.call_args.args[0]
            self.assertNotIn("records", default_output)
            self.assertNotIn("projections", default_output)

            self.assertEqual(cli.main(["store-review", "--details"]), 0)
            self.assertIs(emit.call_args.args[0], full_report)

    def test_store_review_stops_at_staleness_before_local_hydration_or_claims(self):
        class StaleStore:
            def staleness_probe(self, *, threshold_seconds):
                self.threshold_seconds = threshold_seconds
                return {
                    "account": "acct-01",
                    "store_stale": True,
                    "banner": "STORE STALE — sync broken",
                    "review_complete": False,
                    "folders": {"inbox": {"stale": True}},
                }

        store = StaleStore()
        report, code = _store_review(store, threshold_seconds=17)
        self.assertEqual(code, 2)
        self.assertTrue(report["store_stale"])
        self.assertEqual(store.threshold_seconds, 17)
        self.assertEqual(
            _store_review_summary(report)["freshness"],
            {
                "store_stale": True,
                "banner": "STORE STALE — sync broken",
                "folders": {"inbox": {"stale": True}},
            },
        )
