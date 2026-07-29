from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import outlook_email as cli
from outlook_email import (
    CLI_COMMANDS,
    _compact_messages,
    _coverage_query_families,
    _job_field_identifiers,
    _job_url_identifiers,
    _store_coverage,
    _store_review,
    _store_review_summary,
    build_parser,
)


class CliPolicyTests(unittest.TestCase):
    def test_command_surface_is_draft_only(self):
        self.assertEqual(
            set(CLI_COMMANDS),
            {
                "doctor", "login", "logout", "inbox", "sent", "drafts", "review-window",
                "deleted", "read", "sync-store", "store-staleness", "store-review", "store-search",
                "store-coverage", "match-application", "create-draft",
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

    def test_live_client_wires_the_same_auth_manager_as_token_refresher(self):
        settings = Mock(account="owner@example.invalid")
        auth = Mock()
        auth.access_token.return_value = "initial-token"
        graph_client = Mock()
        graph_client.me.return_value = {"mail": settings.account}

        with (
            patch.object(cli, "_settings", return_value=settings),
            patch.object(cli, "AuthManager", return_value=auth),
            patch.object(cli, "DraftOnlyGraphClient", return_value=graph_client) as client_type,
        ):
            actual_settings, actual_client = cli._client()

        self.assertIs(actual_settings, settings)
        self.assertIs(actual_client, graph_client)
        client_type.assert_called_once_with(
            "initial-token",
            token_refresher=auth.access_token,
        )

    def test_live_lists_accept_since_and_compact_without_body_preview(self):
        args = build_parser().parse_args(
            ["inbox", "--limit", "2000", "--since", "2026-04-24T07:00:00Z", "--compact"]
        )
        self.assertEqual(args.limit, 2000)
        self.assertEqual(args.since, "2026-04-24T07:00:00Z")
        self.assertTrue(args.compact)
        self.assertEqual(
            _compact_messages(
                [{
                    "id": "message-1",
                    "subject": "Interview",
                    "bodyPreview": "private mailbox content",
                    "webLink": "https://outlook.example/message-1",
                    "receivedDateTime": "2026-07-23T19:18:40Z",
                }]
            ),
            [{
                "id": "message-1",
                "subject": "Interview",
                "receivedDateTime": "2026-07-23T19:18:40Z",
            }],
        )

        deleted = build_parser().parse_args(
            ["deleted", "--since", "2026-04-24T07:00:00Z", "--compact"]
        )
        self.assertEqual(deleted.since, "2026-04-24T07:00:00Z")
        self.assertTrue(deleted.compact)

    def test_store_search_requires_queries_and_content_is_explicit(self):
        args = build_parser().parse_args(
            ["store-search", "--query", "Example Corp", "--query", "Platform Engineer"]
        )
        self.assertEqual(args.query, ["Example Corp", "Platform Engineer"])
        self.assertFalse(args.include_content)
        self.assertEqual(args.threshold_seconds, 60)
        self.assertTrue(
            build_parser().parse_args(
                ["store-search", "--query", "Example Corp", "--include-content"]
            ).include_content
        )

    def test_store_coverage_accepts_independent_manual_and_application_families(self):
        args = build_parser().parse_args([
            "store-coverage",
            "--query", "recruiter.example",
            "--query", "thread-alias",
            "--in-progress-applications",
        ])
        self.assertEqual(args.query, ["recruiter.example", "thread-alias"])
        self.assertTrue(args.in_progress_applications)
        self.assertEqual(args.threshold_seconds, 60)

        applications = [{
            "company": "Example Corp",
            "jobs": [
                {
                    "role": "Platform Engineer",
                    "status": "in_progress",
                    "url": "https://jobs.example.test/example/7654321?gh_jid=7654321",
                    "requisition_id": "7654321",
                },
                {
                    "role": "AI Engineer",
                    "status": "in_progress",
                    "url": "https://jobs.example.test/Example-Role_R1234",
                },
                {
                    "role": "Data Engineer",
                    "status": "in_progress",
                    "url": "",
                    "req_id": "REQ-8800",
                    "store_key": "gh-8800",
                },
                {
                    "role": "Product Manager",
                    "status": "rejected",
                    "url": "https://jobs.example.test/example/9999999",
                },
            ],
        }]
        families = _coverage_query_families(
            manual_queries=args.query,
            applications=applications,
        )
        by_query = {family["query"]: family["sources"] for family in families}
        self.assertEqual(by_query["recruiter.example"], ["manual"])
        self.assertEqual(by_query["thread-alias"], ["manual"])
        self.assertEqual(by_query["Example Corp"], ["in_progress_company"])
        self.assertEqual(by_query["Platform Engineer"], ["in_progress_role"])
        self.assertEqual(by_query["AI Engineer"], ["in_progress_role"])
        self.assertEqual(by_query["Data Engineer"], ["in_progress_role"])
        self.assertEqual(
            by_query["7654321"],
            ["job_field_identifier", "job_url_identifier"],
        )
        self.assertEqual(by_query["R1234"], ["job_url_identifier"])
        self.assertEqual(by_query["REQ-8800"], ["job_field_identifier"])
        self.assertEqual(by_query["gh-8800"], ["job_field_identifier"])
        self.assertNotIn("Product Manager", by_query)
        self.assertNotIn("9999999", by_query)
        self.assertEqual(
            _job_url_identifiers("https://jobs.example.test/role/7654321?gh_jid=7654321"),
            ("7654321",),
        )
        self.assertEqual(
            _job_field_identifiers({
                "requisition_id": "REQ-1234",
                "posting_id": 5678,
                "store_key": "gh-1234",
                "external_id": "not a stable identifier",
            }),
            ("5678", "gh-1234", "REQ-1234"),
        )

    def test_store_coverage_stops_at_staleness_before_local_scan(self):
        class StaleStore:
            def staleness_probe(self, *, threshold_seconds):
                self.threshold_seconds = threshold_seconds
                return {"store_stale": True, "banner": "STORE STALE"}

        store = StaleStore()
        report, code = _store_coverage(
            store,
            families=[{"query": "Example Corp", "sources": ["manual"]}],
            threshold_seconds=19,
        )
        self.assertEqual(code, 2)
        self.assertTrue(report["store_stale"])
        self.assertEqual(store.threshold_seconds, 19)

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
