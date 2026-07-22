from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from _vendor.mail.providers.outlook_graph.reconciliation import (
    reconcile_message,
    reconcile_recent,
)


class MailReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.inbox = {
            "id": "inbox-1",
            "subject": "Interview availability",
            "receivedDateTime": "2026-07-20T10:00:00Z",
            "conversationId": "conversation-1",
        }

    def test_sent_reply_after_inbound_marks_already_replied(self):
        sent = [{
            "id": "sent-1",
            "subject": "Re: Interview availability",
            "sentDateTime": "2026-07-20T10:05:00Z",
            "conversationId": "conversation-1",
        }]
        result = reconcile_message(self.inbox, sent, [])
        self.assertEqual(result["status"], "already_replied")
        self.assertFalse(result["action_required"])

    def test_earlier_sent_message_does_not_count_as_reply_to_new_inbound(self):
        sent = [{
            "id": "sent-1",
            "sentDateTime": "2026-07-20T09:55:00Z",
            "conversationId": "conversation-1",
        }]
        result = reconcile_message(self.inbox, sent, [])
        self.assertEqual(result["status"], "reply_may_be_needed")

    def test_sent_reply_plus_draft_emits_manual_cleanup_warning(self):
        sent = [{
            "id": "sent-1",
            "sentDateTime": "2026-07-20T10:05:00Z",
            "conversationId": "conversation-1",
        }]
        drafts = [{
            "id": "draft-1",
            "lastModifiedDateTime": "2026-07-20T10:06:00Z",
            "conversationId": "conversation-1",
        }]
        result = reconcile_message(self.inbox, sent, drafts)
        self.assertEqual(result["status"], "already_replied_with_redundant_draft")
        self.assertIn("ACTION REQUIRED", result["warning"])
        self.assertIn("manually delete", result["warning"])

    def test_review_window_summarizes_action_items(self):
        result = reconcile_recent([self.inbox], [], [])
        self.assertTrue(result["draft_only"])
        self.assertTrue(result["sending_is_manual"])
        self.assertEqual(result["summary"]["action_required_count"], 0)
