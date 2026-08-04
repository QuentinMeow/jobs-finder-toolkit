from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from _vendor.mail.contract.transport import TransportError
from _vendor.mail.providers.outlook_graph.provider import (
    DraftOnlyGraphClient,
    DraftOnlyRoutePolicy,
    DraftPolicyError,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, access_token, payload=None, headers=None):
        self.calls.append((method, url, access_token, payload, headers))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class DraftOnlyGraphClientTests(unittest.TestCase):
    def test_unapproved_routes_are_rejected(self):
        with self.assertRaises(DraftPolicyError):
            DraftOnlyRoutePolicy.assert_allowed(
                "POST", "https://graph.microsoft.com/v1.0/me/sendMail"
            )
        with self.assertRaises(DraftPolicyError):
            DraftOnlyRoutePolicy.assert_allowed(
                "DELETE", "https://graph.microsoft.com/v1.0/me/messages/example"
            )

    def test_graph_parenthesized_folder_continuation_is_read_only_allowlisted(self):
        DraftOnlyRoutePolicy.assert_allowed(
            "GET",
            "https://graph.microsoft.com/v1.0/me/mailFolders('inbox')/messages?$skiptoken=opaque",
        )
        DraftOnlyRoutePolicy.assert_allowed(
            "GET",
            "https://graph.microsoft.com/v1.0/me/mailFolders('sentitems')/messages/delta?$deltatoken=opaque",
        )
        DraftOnlyRoutePolicy.assert_allowed(
            "GET",
            "https://graph.microsoft.com/v1.0/me/mailFolders('deleteditems')/messages?$skiptoken=opaque",
        )
        with self.assertRaises(DraftPolicyError):
            DraftOnlyRoutePolicy.assert_allowed(
                "POST",
                "https://graph.microsoft.com/v1.0/me/mailFolders('inbox')/messages",
            )

    def test_arbitrary_folder_discovery_and_reads_are_read_only_allowlisted(self):
        for path in (
            "/v1.0/me/mailFolders",
            "/v1.0/me/mailFolders/archive-id",
            "/v1.0/me/mailFolders/archive-id/childFolders",
            "/v1.0/me/mailFolders/archive-id/messages",
            "/v1.0/me/mailFolders('archive-id')/messages/delta",
        ):
            DraftOnlyRoutePolicy.assert_allowed("GET", f"https://graph.microsoft.com{path}")
        with self.assertRaises(DraftPolicyError):
            DraftOnlyRoutePolicy.assert_allowed(
                "POST", "https://graph.microsoft.com/v1.0/me/mailFolders/archive-id/messages"
            )

    def test_folder_discovery_recurses_and_preserves_well_known_keys(self):
        core = [
            ("inbox", "Inbox"),
            ("sentitems", "Sent Items"),
            ("drafts", "Drafts"),
            ("deleteditems", "Deleted Items"),
        ]
        root = [
            {"id": folder_id, "displayName": display_name, "childFolderCount": 0}
            for folder_id, display_name in core
        ] + [{"id": "archive-id", "displayName": "Archive", "childFolderCount": 1}]
        transport = FakeTransport(
            [
                *({"id": folder_id, "displayName": display_name} for folder_id, display_name in core),
                {"value": root},
                {"value": [{"id": "custom-id", "displayName": "Recruiting", "childFolderCount": 0}]},
            ]
        )
        client = DraftOnlyGraphClient("token", transport=transport)

        folders = client.list_mail_folders()

        by_id = {item["id"]: item for item in folders}
        self.assertEqual(by_id["inbox"]["key"], "inbox")
        self.assertEqual(by_id["deleteditems"]["key"], "deleteditems")
        self.assertEqual(by_id["archive-id"]["display_name"], "Archive")
        self.assertRegex(by_id["archive-id"]["key"], r"^folder-[0-9a-f]{10}$")
        self.assertEqual(by_id["custom-id"]["display_name"], "Recruiting")
        self.assertTrue(any("archive-id/childFolders" in call[1] for call in transport.calls))

    def test_new_message_must_be_confirmed_as_draft(self):
        transport = FakeTransport([{"id": "draft-1", "isDraft": False}])
        client = DraftOnlyGraphClient("token", transport=transport)
        recipient = "recruiter" + chr(64) + "example.invalid"
        with self.assertRaises(DraftPolicyError):
            client.create_draft(
                subject="Interview availability",
                body_text="Thank you.",
                to=[recipient],
            )

    def test_reply_draft_is_verified_before_and_after_update(self):
        transport = FakeTransport(
            [
                {
                    "id": "message-1",
                    "subject": "Interview",
                    "receivedDateTime": "2026-07-20T10:00:00Z",
                    "isDraft": False,
                    "conversationId": "conversation-1",
                },
                {"value": []},
                {"value": []},
                {
                    "id": "draft-2",
                    "isDraft": True,
                    "body": {"contentType": "Text", "content": "Original"},
                },
                {"id": "draft-2", "isDraft": True},
                {
                    "id": "draft-2",
                    "subject": "Re: Interview",
                    "isDraft": True,
                    "webLink": "https://outlook.example/draft-2",
                },
            ]
        )
        client = DraftOnlyGraphClient("token", transport=transport)
        result = client.create_reply_draft(source_message_id="message-1", body_text="Thanks")
        self.assertTrue(result["isDraft"])
        self.assertEqual(
            [call[0] for call in transport.calls],
            ["GET", "GET", "GET", "POST", "PATCH", "GET"],
        )
        self.assertEqual(
            transport.calls[4][3]["body"]["content"],
            "Thanks\n\nOriginal",
        )

    def test_existing_draft_update_replaces_body_and_verifies_both_sides(self):
        transport = FakeTransport(
            [
                {"id": "draft-1", "isDraft": True},
                {"id": "draft-1", "isDraft": True},
                {
                    "id": "draft-1",
                    "subject": "Re: Interview",
                    "isDraft": True,
                    "body": {"contentType": "text", "content": "Replacement"},
                },
            ]
        )
        client = DraftOnlyGraphClient("token", transport=transport)

        result = client.update_draft(
            draft_message_id="draft-1", body_text="Replacement"
        )

        self.assertTrue(result["isDraft"])
        self.assertEqual([call[0] for call in transport.calls], ["GET", "PATCH", "GET"])
        self.assertEqual(
            transport.calls[1][3],
            {"body": {"contentType": "Text", "content": "Replacement"}},
        )

    def test_existing_draft_update_refuses_non_draft_before_write(self):
        transport = FakeTransport([{"id": "sent-1", "isDraft": False}])
        client = DraftOnlyGraphClient("token", transport=transport)

        with self.assertRaises(DraftPolicyError):
            client.update_draft(draft_message_id="sent-1", body_text="No")

        self.assertEqual([call[0] for call in transport.calls], ["GET"])

    def test_draft_listing_rejects_non_draft_item(self):
        transport = FakeTransport([{"value": [{"id": "x", "isDraft": False}]}])
        client = DraftOnlyGraphClient("token", transport=transport)
        with self.assertRaises(DraftPolicyError):
            client.list_drafts()

    def test_sent_items_are_allowlisted_and_ordered_by_sent_time(self):
        transport = FakeTransport([{"value": [{"id": "sent-1", "isDraft": False}]}])
        client = DraftOnlyGraphClient("token", transport=transport)
        self.assertEqual(client.list_sent(), [{"id": "sent-1", "isDraft": False}])
        self.assertIn("/mailFolders/sentitems/messages?", transport.calls[0][1])
        self.assertIn("sentDateTime+desc", transport.calls[0][1])

    def test_deleted_items_are_allowlisted_read_only_and_ordered_by_modified_time(self):
        transport = FakeTransport([{"value": [{"id": "deleted-1", "isDraft": False}]}])
        client = DraftOnlyGraphClient("token", transport=transport)
        self.assertEqual(client.list_deleted(), [{"id": "deleted-1", "isDraft": False}])
        self.assertIn("/mailFolders/deleteditems/messages?", transport.calls[0][1])
        self.assertIn("lastModifiedDateTime+desc", transport.calls[0][1])
        self.assertEqual(transport.calls[0][0], "GET")

    def test_folder_listing_paginates_beyond_graph_page_size(self):
        first_page = [{"id": f"message-{index}"} for index in range(50)]
        second_page = [{"id": f"message-{index}"} for index in range(50, 70)]
        transport = FakeTransport([{"value": first_page}, {"value": second_page}])
        client = DraftOnlyGraphClient("token", transport=transport)

        messages = client.list_inbox(70)

        self.assertEqual(len(messages), 70)
        self.assertEqual([call[0] for call in transport.calls], ["GET", "GET"])
        self.assertIn("%24top=50", transport.calls[0][1])
        self.assertIn("%24top=20", transport.calls[1][1])
        self.assertIn("%24skip=50", transport.calls[1][1])

    def test_sync_reads_request_immutable_provider_ids(self):
        transport = FakeTransport([{"id": "immutable-1", "body": {"content": "local only"}}])
        client = DraftOnlyGraphClient("token", transport=transport)
        self.assertEqual(client.read_message("immutable-1")["id"], "immutable-1")
        self.assertEqual(transport.calls[0][4], {"Prefer": 'IdType="ImmutableId"'})

    def test_attachment_metadata_select_never_requests_content_bytes(self):
        transport = FakeTransport([{
            "value": [{
                "id": "attachment-1", "name": "offer.pdf", "size": 210000,
                "contentType": "application/pdf", "isInline": False,
            }]
        }])
        client = DraftOnlyGraphClient("token", transport=transport)
        self.assertEqual(client.attachment_metadata("message-1"), [{
            "attachment_id": "attachment-1", "name": "offer.pdf", "size": 210000,
            "content_type": "application/pdf", "is_inline": False,
        }])
        self.assertIn("%24select=id%2Cname%2Csize%2CcontentType%2CisInline", transport.calls[0][1])
        self.assertNotIn("contentBytes", transport.calls[0][1])

    def test_delta_returns_opaque_link_and_explicit_field_set_version(self):
        transport = FakeTransport([{
            "value": [{"id": "immutable-1"}],
            "@odata.deltaLink": (
                "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?token=opaque"
            ),
        }])
        client = DraftOnlyGraphClient("token", transport=transport)
        delta = client.delta_sync("inbox")
        self.assertEqual(delta["messages"], [{"id": "immutable-1"}])
        self.assertIn("token=opaque", delta["sync_token"])
        self.assertEqual(delta["field_set_version"], 1)

    def test_mid_delta_401_refreshes_and_retries_the_read_once(self):
        next_link = (
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta"
            "?$skiptoken=page-2"
        )
        delta_link = (
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta"
            "?$deltatoken=complete"
        )
        transport = FakeTransport([
            {"value": [{"id": "message-1"}], "@odata.nextLink": next_link},
            TransportError("Graph returned HTTP 401", status_code=401),
            {"value": [{"id": "message-2"}], "@odata.deltaLink": delta_link},
        ])
        refresh = Mock(return_value="replacement-token")
        client = DraftOnlyGraphClient(
            "initial-token",
            transport=transport,
            token_refresher=refresh,
        )

        result = client.delta_sync("inbox")

        self.assertEqual(result["messages"], [{"id": "message-1"}, {"id": "message-2"}])
        refresh.assert_called_once_with()
        self.assertEqual(
            [call[2] for call in transport.calls],
            ["initial-token", "initial-token", "replacement-token"],
        )
        self.assertEqual(transport.calls[1][1], transport.calls[2][1])

    def test_second_read_401_fails_without_another_refresh_or_retry(self):
        transport = FakeTransport([
            TransportError("first HTTP 401", status_code=401),
            TransportError("second HTTP 401", status_code=401),
        ])
        refresh = Mock(return_value="replacement-token")
        client = DraftOnlyGraphClient(
            "initial-token",
            transport=transport,
            token_refresher=refresh,
        )

        with self.assertRaisesRegex(TransportError, "second HTTP 401"):
            client.read_message("message-1")

        refresh.assert_called_once_with()
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(
            [call[2] for call in transport.calls],
            ["initial-token", "replacement-token"],
        )

    def test_draft_post_401_is_not_refreshed_or_replayed(self):
        transport = FakeTransport([
            TransportError("draft HTTP 401", status_code=401),
        ])
        refresh = Mock(return_value="replacement-token")
        client = DraftOnlyGraphClient(
            "initial-token",
            transport=transport,
            token_refresher=refresh,
        )

        with self.assertRaisesRegex(TransportError, "draft HTTP 401"):
            client.create_draft(
                subject="Interview availability",
                body_text="Thank you.",
                to=["recruiter@example.invalid"],
            )

        refresh.assert_not_called()
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0][0], "POST")

    def test_later_sent_reply_blocks_duplicate_draft_before_write(self):
        transport = FakeTransport(
            [
                {
                    "id": "message-1",
                    "receivedDateTime": "2026-07-20T10:00:00Z",
                    "isDraft": False,
                    "conversationId": "conversation-1",
                },
                {
                    "value": [
                        {
                            "id": "sent-1",
                            "sentDateTime": "2026-07-20T10:05:00Z",
                            "conversationId": "conversation-1",
                        }
                    ]
                },
                {"value": []},
            ]
        )
        client = DraftOnlyGraphClient("token", transport=transport)
        with self.assertRaisesRegex(DraftPolicyError, "Sent reply already exists"):
            client.create_reply_draft(source_message_id="message-1", body_text="Duplicate")
        self.assertEqual([call[0] for call in transport.calls], ["GET", "GET", "GET"])

    def test_reply_preflight_finds_sent_reply_beyond_first_page(self):
        first_sent_page = [
            {
                "id": f"sent-{index}",
                "sentDateTime": "2026-07-20T09:00:00Z",
                "conversationId": f"other-{index}",
            }
            for index in range(50)
        ]
        transport = FakeTransport(
            [
                {
                    "id": "message-1",
                    "receivedDateTime": "2026-07-20T10:00:00Z",
                    "isDraft": False,
                    "conversationId": "conversation-1",
                },
                {"value": first_sent_page},
                {
                    "value": [
                        {
                            "id": "sent-later",
                            "sentDateTime": "2026-07-20T10:05:00Z",
                            "conversationId": "conversation-1",
                        }
                    ]
                },
                {"value": []},
            ]
        )
        client = DraftOnlyGraphClient("token", transport=transport)

        with self.assertRaisesRegex(DraftPolicyError, "Sent reply already exists"):
            client.create_reply_draft(source_message_id="message-1", body_text="Duplicate")

        self.assertEqual([call[0] for call in transport.calls], ["GET", "GET", "GET", "GET"])
        self.assertIn("%24skip=50", transport.calls[2][1])

    def test_existing_thread_draft_blocks_duplicate_draft_before_write(self):
        transport = FakeTransport(
            [
                {
                    "id": "message-1",
                    "receivedDateTime": "2026-07-20T10:00:00Z",
                    "isDraft": False,
                    "conversationId": "conversation-1",
                },
                {"value": []},
                {
                    "value": [
                        {
                            "id": "draft-1",
                            "isDraft": True,
                            "lastModifiedDateTime": "2026-07-20T10:05:00Z",
                            "conversationId": "conversation-1",
                        }
                    ]
                },
            ]
        )
        client = DraftOnlyGraphClient("token", transport=transport)
        with self.assertRaisesRegex(DraftPolicyError, "draft already exists"):
            client.create_reply_draft(source_message_id="message-1", body_text="Duplicate")
        self.assertEqual([call[0] for call in transport.calls], ["GET", "GET", "GET"])
