"""Adversarial unit coverage for the pure stored-mail reconciliation layer."""
from __future__ import annotations

import sys
import unittest
from hashlib import sha256
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from _vendor.mail.reconciliation import (
    categorize_message,
    hydrate_stored_message,
    link_message,
    normalize_stored_message,
    propose_reconciliation,
    reconcile_messages,
    reverify_transition,
    validate_company_email_domains,
)


DOMAINS = {"Example Corp": ["example.com"], "Other Corp": ["other.example"]}
APPS = [
    {
        "slug": "example-backend-20260720",
        "company": "Example Corp",
        "jobs": [
            {
                "role": "Backend Engineer",
                "status": "applied",
                "url": "https://jobs.example.com/postings/backend-123",
                "requisition_id": "REQ-123",
                "progress": {"phase": "technical_interview", "state": "awaiting_schedule"},
            },
        ],
    },
    {
        "slug": "example-platform-20260720",
        "company": "Example Corp",
        "jobs": [
            {
                "role": "Platform Engineer",
                "status": "applied",
                "url": "https://jobs.example.com/postings/platform-456",
                "requisition_id": "REQ-456",
            },
        ],
    },
]


def incoming(key: str, body: str, *, subject: str = "", thread: str = "t-1", sender: str = "recruiter@example.com", timestamp: str = "2026-07-22T10:00:00Z", **extra):
    return {
        "message_key": key,
        "folder": "inbox",
        "from": sender,
        "subject": subject,
        "body_text": body,
        "thread_key": thread,
        "received_at": timestamp,
        **extra,
    }


class StoredMailCategorizationTests(unittest.TestCase):
    def test_store_envelope_requires_deliberate_hydration_and_public_record_stays_content_free(self):
        envelope = {
            "schema_version": "email-message.v1",
            "message_key": "acct-01/provider-hash",
            "account": "acct-01",
            "provider": "outlook",
            "provider_message_id": "opaque-provider-id",
            "provider_thread_id": "opaque-thread-id",
            "rfc_message_id": "<neutral@example.test>",
            "folder": "inbox",
            "in_scope": True,
            "tombstoned": False,
            "received_at": "2026-07-22T10:00:00Z",
            "attachments": [{"attachment_id": "opaque", "name": "invite.ics", "size": 23, "content_type": "text/calendar", "is_inline": False}],
            "raw_fetch_id": "fetch-01",
        }
        # Envelope-only input is intentionally fail-closed for body-dependent work.
        self.assertFalse(normalize_stored_message(envelope)["body_present"])
        hydrated = hydrate_stored_message(envelope, {"subject": "Interview", "body_text": "REQ-123: please choose a time."})
        result = reconcile_messages([hydrated], APPS, DOMAINS)
        record = result["records"][0]
        self.assertNotIn("subject", record)
        self.assertNotIn("body_text", record)
        self.assertNotIn("sender", record)
        self.assertEqual(record["message_key"], "acct-01/provider-hash")
        self.assertEqual(record["thread_keys"], (
            "thread-" + sha256(b"<neutral@example.test>").hexdigest()[:24],
            "thread-" + sha256(b"opaque-thread-id").hexdigest()[:24],
        ))

    def test_categories_are_nonexclusive_and_confirmed_time_requires_full_body_evidence(self):
        message = normalize_stored_message(incoming(
            "acct-01/m-1",
            "Requisition ID: REQ-123. Please choose a time by 2026-08-01 for your technical interview.",
            subject="Interview scheduling",
        ))
        result = categorize_message(message)
        self.assertEqual(result["categories"], ("follow_up_needed", "interview_invite", "scheduling"))
        self.assertEqual(result["scheduling_subtypes"], ("booking_requested",))
        self.assertEqual(result["deadline"], {"due_at": "2026-08-01", "kind": "explicit_date"})

        confirmed = categorize_message(normalize_stored_message(incoming(
            "acct-01/m-2",
            "REQ-123: your interview is confirmed for 2026-08-04 10:30 AM PT.",
        )))
        self.assertEqual(confirmed["scheduling_subtypes"], ("schedule_confirmed",))
        self.assertEqual(confirmed["explicit_schedule"], {
            "starts_at": "2026-08-04T10:30:00", "timezone": "America/Los_Angeles"
        })

    def test_attachment_metadata_cannot_schedule_an_interview(self):
        message = normalize_stored_message(incoming(
            "acct-01/attachment-only",
            "Please see the attached invite.",
            subject="Interview invitation",
            attachments=[{"name": "interview.ics", "content_type": "text/calendar"}],
        ))
        result = categorize_message(message)
        self.assertTrue(result["attachment_schedule_hint"])
        self.assertIsNone(result["explicit_schedule"])
        self.assertNotIn("schedule_confirmed", result["scheduling_subtypes"])
        link = link_message(message, APPS, DOMAINS)
        self.assertFalse(any(item["target"].get("progress", {}).get("state") == "scheduled"
                             for item in propose_reconciliation(message, link, APPS)))


class StoredMailLinkingTests(unittest.TestCase):
    def test_company_gated_structured_tokens_are_exact_but_bare_numbers_are_not(self):
        exact = normalize_stored_message(incoming(
            "acct-01/exact", "REQ-123: your technical interview is confirmed for 2026-08-04 10:30 AM PT."
        ))
        link = link_message(exact, APPS, DOMAINS)
        self.assertEqual(link["application_slug"], "example-backend-20260720")
        self.assertEqual(link["role"], "Backend Engineer")
        self.assertEqual((link["derivation"], link["confidence"]), ("direct_rule", "exact"))

        bare = normalize_stored_message(incoming("acct-01/bare", "Interview update for ticket 90210."))
        weak = link_message(bare, APPS, DOMAINS)
        self.assertIsNone(weak["application_slug"])
        self.assertEqual(weak["confidence"], "weak")
        self.assertEqual(set(weak["candidates"]), {"example-backend-20260720", "example-platform-20260720"})

    def test_shared_ats_domains_never_identify_a_company_or_role(self):
        message = normalize_stored_message(incoming(
            "acct-01/ats", "REQ-123: your interview is confirmed for 2026-08-04 10:30 AM PT.",
            sender="greenhouse.io",
        ))
        link = link_message(message, APPS, DOMAINS)
        self.assertEqual(link["derivation"], "shared_ats_vendor")
        self.assertIsNone(link["application_slug"])
        with self.assertRaisesRegex(ValueError, "shared ATS domain"):
            validate_company_email_domains({"Example Corp": ["greenhouse.io"]})

    def test_drifting_thread_cannot_reject_the_old_role(self):
        first = incoming("acct-01/old", "REQ-123: thanks for applying.", thread="thread-a")
        drift = incoming(
            "acct-01/drift", "Unfortunately, we decided not to move forward.",
            thread="thread-a", sender="recruiter@new-company.test", timestamp="2026-07-23T10:00:00Z",
        )
        result = reconcile_messages([first, drift], APPS, DOMAINS)
        old, later = result["records"]
        self.assertEqual(old["link"]["confidence"], "exact")
        self.assertEqual(later["link"]["derivation"], "thread_inheritance")
        raw_later = normalize_stored_message(drift)
        proposals = propose_reconciliation(raw_later, later["link"], APPS)
        rejection = next(item for item in proposals if item["kind"] == "status_transition")
        self.assertFalse(rejection["ready_for_tracker_transaction"])
        verified = reverify_transition(rejection, lambda key: drift if key == "acct-01/drift" else None, APPS, DOMAINS)
        self.assertFalse(verified["verified"])


class StoredMailProposalTests(unittest.TestCase):
    def _proposal_for(self, key: str, body: str, *, folder: str = "inbox", to: list[dict] | None = None):
        raw = incoming(key, body)
        raw["folder"] = folder
        if to is not None:
            raw["toRecipients"] = to
        message = normalize_stored_message(raw)
        link = link_message(message, APPS, DOMAINS)
        return link, propose_reconciliation(message, link, APPS)

    def test_all_scheduling_effects_are_proposals_with_evidence_and_never_auto_apply(self):
        cases = [
            ("booking", "REQ-123: please choose a time by 2026-08-01.", "booking_required", "create_action_needed"),
            ("confirmed", "REQ-123: your technical interview is confirmed for 2026-08-04 10:30 AM PT.", "scheduled", "confirm_occurrence"),
            ("reschedule", "REQ-123: we need to reschedule your interview.", "reschedule_required", "request_reschedule"),
            ("replacement", "REQ-123: your interview is rescheduled to 2026-08-05 11:00 AM PT and confirmed.", "scheduled", "append_replacement"),
            ("cancel", "REQ-123: your interview has been cancelled.", "action_required", "cancel_occurrence"),
            ("result", "REQ-123: thank you for interviewing. Your interview is complete.", "awaiting_result", "mark_complete"),
        ]
        for key, body, state, calendar_action in cases:
            with self.subTest(key=key):
                _, proposals = self._proposal_for(f"acct-01/{key}", body)
                item = next(proposal for proposal in proposals if proposal["kind"] == "progress_calendar")
                self.assertEqual(item["target"]["progress"]["state"], state)
                self.assertEqual(item["target"]["calendar"]["action"], calendar_action)
                self.assertFalse(item["auto_apply"])
                self.assertTrue(item["requires_exact_message_verification"])
                self.assertEqual(item["evidence"]["source"], {"kind": "email", "ref": f"acct-01/{key}"})

    def test_sent_availability_matches_recipient_company_and_waits_for_confirmation(self):
        link, proposals = self._proposal_for(
            "acct-01/sent-availability", "REQ-123: my availability is 2026-08-03 at 10:00 AM PT.",
            folder="sent", to=[{"emailAddress": {"address": "recruiter@example.com"}}],
        )
        self.assertEqual(link["confidence"], "exact")
        proposal = next(item for item in proposals if item["kind"] == "progress_calendar")
        self.assertEqual(proposal["target"]["progress"]["state"], "awaiting_schedule")

    def test_cross_account_later_sent_message_clears_needs_reply(self):
        inbound = incoming("acct-01/inbound", "REQ-123: please reply with your availability.", thread="rfc-1", timestamp="2026-07-22T10:00:00Z")
        outbound = {
            "message_key": "acct-02/sent", "folder": "sent", "from": "me@personal.test",
            "to": "recruiter@example.com", "body_text": "My availability is attached.",
            "thread_key": "rfc-1", "sent_at": "2026-07-22T11:00:00Z",
        }
        result = reconcile_messages([inbound, outbound], APPS, DOMAINS)
        self.assertEqual(result["projections"]["needs_reply"], [])

    def test_content_free_projections_cover_application_unresolved_reply_and_deadline_queues(self):
        actionable = incoming(
            "acct-01/actionable", "REQ-123: please choose a time by 2026-08-01.",
            thread="action-thread",
        )
        unknown = incoming(
            "acct-01/unknown", "A message with no job association.",
            sender="person@unlisted.test", thread="unknown-thread",
        )
        projections = reconcile_messages([actionable, unknown], APPS, DOMAINS)["projections"]
        self.assertEqual(list(projections["by_application"]), ["example-backend-20260720"])
        self.assertEqual(projections["by_application"]["example-backend-20260720"][0]["message_key"], "acct-01/actionable")
        self.assertEqual([item["message_key"] for item in projections["unresolved"]], ["acct-01/unknown"])
        self.assertEqual([item["message_key"] for item in projections["needs_reply"]], ["acct-01/actionable"])
        self.assertEqual([item["message_key"] for item in projections["deadlines"]], ["acct-01/actionable"])

    def test_needs_reply_hard_excludes_terminal_bulk_and_neutral_mail(self):
        # Each case deliberately includes an otherwise actionable phrase.  The
        # hard category exclusion must win so a receipt/rejection/digest/vendor
        # notice never turns into an owner TODO.
        cases = [
            ("receipt", "Thank you for applying. Please reply to confirm your application received."),
            ("rejection", "Unfortunately, we are not moving forward. Please reply with questions."),
            ("job-alert", "Job alert: new jobs matching your profile. Please reply if interested."),
            ("unrelated", "Invoice for your order. Action required: please reply immediately."),
            ("neutral", "Application status update: you are still under consideration."),
        ]
        messages = [incoming(f"acct-01/{key}", body, thread=f"thread-{key}") for key, body in cases]
        projections = reconcile_messages(messages, APPS, DOMAINS)["projections"]
        self.assertEqual(projections["needs_reply"], [])

    def test_needs_reply_requires_an_explicit_actionable_signal(self):
        confirmed = incoming(
            "acct-01/confirmed",
            "REQ-123: your interview is confirmed for 2026-08-04 10:30 AM PT.",
            thread="confirmed-thread",
        )
        booking = incoming(
            "acct-01/booking",
            "REQ-123: please choose a time for your interview by 2026-08-01.",
            thread="booking-thread",
        )
        reschedule = incoming(
            "acct-01/reschedule",
            "REQ-123: we need to reschedule your interview.",
            thread="reschedule-thread",
        )
        projections = reconcile_messages([confirmed, booking, reschedule], APPS, DOMAINS)["projections"]
        self.assertEqual(
            [item["message_key"] for item in projections["needs_reply"]],
            ["acct-01/booking", "acct-01/reschedule"],
        )

    def test_confirmed_schedule_suppresses_incidental_follow_up_unless_booking_or_reschedule(self):
        confirmed = incoming(
            "acct-01/confirmed-follow-up",
            "REQ-123: your interview is confirmed for 2026-08-04 10:30 AM PT. Please reply to confirm.",
            thread="confirmed-follow-up-thread",
        )
        combined_action = incoming(
            "acct-01/confirmed-booking",
            "REQ-123: your interview is confirmed for 2026-08-04 10:30 AM PT. Please choose a time.",
            thread="confirmed-booking-thread",
        )
        projections = reconcile_messages([confirmed, combined_action], APPS, DOMAINS)["projections"]
        self.assertEqual(
            [item["message_key"] for item in projections["needs_reply"]],
            ["acct-01/confirmed-booking"],
        )

    def test_exact_transition_must_reopen_the_same_stored_message(self):
        raw = incoming("acct-01/transition", "REQ-123: your technical interview is confirmed for 2026-08-04 10:30 AM PT.")
        message = normalize_stored_message(raw)
        link = link_message(message, APPS, DOMAINS)
        transition = next(item for item in propose_reconciliation(message, link, APPS) if item["kind"] == "status_transition")
        self.assertFalse(transition["auto_apply"])
        verified = reverify_transition(transition, lambda key: raw if key == "acct-01/transition" else None, APPS, DOMAINS)
        self.assertTrue(verified["verified"], verified)
        self.assertTrue(verified["proposal"]["ready_for_tracker_transaction"])


if __name__ == "__main__":
    unittest.main()
