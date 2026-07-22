from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

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
        return self.responses.pop(0)


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
        with self.assertRaises(DraftPolicyError):
            DraftOnlyRoutePolicy.assert_allowed(
                "POST",
                "https://graph.microsoft.com/v1.0/me/mailFolders('inbox')/messages",
            )

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
