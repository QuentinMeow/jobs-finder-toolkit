"""Synthetic tests for the private email-store synchronization contract."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from _vendor.mail.contract.interface import (  # noqa: E402
    MailCapabilities,
    MailProvider,
    MessageNotFound,
    SyncTokenExpired,
)
from _vendor.mail.store_sync import EmailStoreError, EmailStoreSync, STALE_BANNER  # noqa: E402
from _vendor.mail.store_review import EmailStoreReader, _content_free  # noqa: E402
from _vendor.store.blobs import BlobStore  # noqa: E402


class SyntheticMailbox(MailProvider):
    """In-memory mail provider with replayable folder delta events only."""

    name = "outlook_graph"
    route_policy = object()

    def __init__(self) -> None:
        self.folders: dict[str, list[dict[str, Any]]] = {
            "inbox": [], "sentitems": [], "drafts": [], "deleteditems": [], "archive": []
        }
        self.by_id: dict[str, dict[str, Any]] = {}
        self.attachments: dict[str, list[dict[str, Any]]] = {}
        self.events: dict[str, list[tuple[int, dict[str, Any]]]] = {
            folder: [] for folder in self.folders
        }
        self.revision = 0
        self.expire_next_delta = False
        self.list_limits: list[int | None] = []
        self.delta_tokens: list[str | None] = []

    def capabilities(self) -> MailCapabilities:
        return MailCapabilities(read=True, drafts=False, delta_sync=True, search=False)

    def verify_account(self) -> dict[str, Any]:
        return {"mail": "owner@example.com"}

    def review_window(self, limit: int = 20) -> dict[str, Any]:
        return {"draft_only": True, "sending_is_manual": True}

    def list_inbox(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_folder("inbox", limit)

    def list_sent(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_folder("sentitems", limit)

    def list_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_folder("drafts", limit)

    def list_deleted(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_folder("deleteditems", limit)

    def list_folder(
        self, folder: str, limit: int | None = None, since: str | None = None
    ) -> list[dict[str, Any]]:
        self.list_limits.append(limit)
        values = list(self.folders[folder])
        values.sort(key=lambda item: item.get("receivedDateTime") or item.get("sentDateTime")
                    or item.get("lastModifiedDateTime") or "", reverse=True)
        copied = [dict(item) for item in values]
        if since:
            copied = [
                item for item in copied
                if (item.get("receivedDateTime") or item.get("sentDateTime")
                    or item.get("lastModifiedDateTime") or "") >= since
            ]
        return copied if limit is None else copied[:limit]

    def probe_folder(self, folder: str) -> dict[str, Any]:
        values = self.list_folder(folder, 1)
        item = values[0] if values else {}
        latest = item.get("receivedDateTime") or item.get("sentDateTime") or item.get("lastModifiedDateTime")
        return {"folder": folder, "latest_at": latest, "item_count": len(self.folders[folder])}

    def read_message(self, message_id: str) -> dict[str, Any]:
        if message_id not in self.by_id:
            raise MessageNotFound("synthetic hard deletion")
        return dict(self.by_id[message_id])

    def attachment_metadata(self, message_id: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self.attachments.get(message_id, [])]

    def delta_sync(self, folder: str, sync_token: str | None = None) -> dict[str, Any]:
        self.delta_tokens.append(sync_token)
        if self.expire_next_delta and sync_token is not None:
            self.expire_next_delta = False
            raise SyncTokenExpired("synthetic token expired")
        if sync_token is None:
            values = [dict(item) for item in self.folders[folder]]
        else:
            since = int(sync_token)
            values = [dict(item) for revision, item in self.events[folder] if revision > since]
        return {
            "messages": values,
            "sync_token": str(self.revision),
            "field_set_version": 1,
        }

    def seed(
        self,
        *,
        folder: str = "inbox",
        message_id: str | None = None,
        at: datetime | None = None,
        body: str = "Synthetic full body.",
        attachments: list[dict[str, Any]] | None = None,
        sender: str = "recruiter@example.com",
        sender_name: str = "Recruiter",
        to_recipients: list[tuple[str, str]] | None = None,
        cc_recipients: list[tuple[str, str]] | None = None,
    ) -> str:
        when = at or datetime.now(timezone.utc) - timedelta(minutes=2)
        message_id = message_id or f"message-{len(self.by_id) + 1}"
        message: dict[str, Any] = {
            "id": message_id,
            "conversationId": f"thread-{message_id}",
            "internetMessageId": f"<{message_id}@example.com>",
            "subject": "Synthetic workflow notice",
            "from": {"emailAddress": {"name": sender_name, "address": sender}},
            "toRecipients": [
                {"emailAddress": {"name": name, "address": address}}
                for name, address in (to_recipients or [("Owner", "owner@example.com")])
            ],
            "ccRecipients": [
                {"emailAddress": {"name": name, "address": address}}
                for name, address in (cc_recipients or [])
            ],
            "bodyPreview": body[:40],
            "body": {"contentType": "Text", "content": body},
            "isDraft": folder == "drafts",
            "isRead": False,
            "webLink": "https://mail.example.com/synthetic",
        }
        if folder == "inbox":
            message["receivedDateTime"] = _z(when)
        elif folder == "sentitems":
            message["sentDateTime"] = _z(when)
        else:
            message["lastModifiedDateTime"] = _z(when)
        self.by_id[message_id] = message
        self.attachments[message_id] = list(attachments or [])
        self.folders[folder].append(message)
        self._event(folder, message)
        return message_id

    def move(self, message_id: str, *, source: str, destination: str) -> None:
        message = self.by_id[message_id]
        self.folders[source] = [item for item in self.folders[source] if item["id"] != message_id]
        self._event(source, {"id": message_id, "@removed": {"reason": "changed"}})
        self.folders[destination].append(message)
        self._event(destination, message)

    def hard_delete(self, message_id: str, *, source: str) -> None:
        self.folders[source] = [item for item in self.folders[source] if item["id"] != message_id]
        self.by_id.pop(message_id, None)
        self.attachments.pop(message_id, None)
        self._event(source, {"id": message_id, "@removed": {"reason": "deleted"}})

    def _event(self, folder: str, message: dict[str, Any]) -> None:
        self.revision += 1
        self.events[folder].append((self.revision, dict(message)))


def _z(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EmailStoreSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mailbox = SyntheticMailbox()
        self.recent = datetime.now(timezone.utc) - timedelta(minutes=2)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _syncer(self, account: str = "owner@example.com") -> EmailStoreSync:
        return EmailStoreSync(data_root=self.root, provider=self.mailbox, account_label=account)

    def test_full_30_day_sync_captures_bodies_metadata_and_no_attachment_bytes(self):
        message_id = self.mailbox.seed(
            at=self.recent,
            body="Synthetic full body stored only in raw.",
            attachments=[
                {
                    "id": "attachment-1", "name": "offer.pdf", "size": 210000,
                    "contentType": "application/pdf", "contentBytes": "NEVER_STORE_ATTACHMENT_BYTES",
                }
            ],
        )
        self.mailbox.seed(at=self.recent - timedelta(days=31), body="Old body outside window.")
        result = self._syncer().sync(days=30, force_full=True)
        self.assertEqual(result.mode, "full")
        self.assertEqual(self.mailbox.list_limits[:4], [None, None, None, None])
        self.assertEqual(self.mailbox.delta_tokens, [])
        state = json.loads((self.root / "email/state/acct-01/sync.json").read_text())
        self.assertEqual(len(state["messages"]), 1)
        record = next(iter(state["messages"].values()))
        self.assertEqual(record["provider_message_id"], message_id)
        self.assertEqual(record["attachments"], [{
            "attachment_id": "attachment-1", "content_type": "application/pdf",
            "is_inline": False, "name": "offer.pdf", "size": 210000,
        }])
        self.assertNotIn("subject", record)
        blobs = BlobStore(self.root / "email/raw/_blobs")
        raw_text = "\n".join(
            blobs.read(path.name.split(".", 1)[0]).decode("utf-8")
            for path in (self.root / "email/raw/_blobs").rglob("*.zst")
        )
        self.assertIn("Synthetic full body stored only in raw.", raw_text)
        self.assertNotIn("NEVER_STORE_ATTACHMENT_BYTES", raw_text)
        self.assertTrue((self.root / "email/index/acct-01/header.json").exists())

    def test_delta_replay_token_expiry_move_and_hard_delete_are_idempotent(self):
        first = self.mailbox.seed(at=self.recent)
        syncer = self._syncer()
        syncer.sync(days=None, force_full=True)
        self.mailbox.seed(at=self.recent + timedelta(minutes=1))
        delta = syncer.sync(days=None)
        self.assertEqual(delta.mode, "delta")
        replay = syncer.sync(days=None)
        self.assertEqual(replay.mode, "delta")
        state = json.loads((self.root / "email/state/acct-01/sync.json").read_text())
        self.assertEqual(len(state["messages"]), 2)

        self.mailbox.move(first, source="inbox", destination="sentitems")
        syncer.sync(days=None)
        state = json.loads((self.root / "email/state/acct-01/sync.json").read_text())
        moved = next(record for record in state["messages"].values()
                     if record["provider_message_id"] == first)
        self.assertEqual(moved["folder"], "sentitems")
        self.assertEqual(moved["direction"], "outbound")
        self.assertTrue(moved["in_scope"])

        self.mailbox.move(first, source="sentitems", destination="deleteditems")
        syncer.sync(days=None)
        state = json.loads((self.root / "email/state/acct-01/sync.json").read_text())
        moved = next(record for record in state["messages"].values()
                     if record["provider_message_id"] == first)
        self.assertEqual(moved["folder"], "deleteditems")
        self.assertEqual(moved["direction"], "outbound")
        self.assertEqual(moved["folder_history"], ["inbox", "sentitems", "deleteditems"])

        self.mailbox.hard_delete(first, source="deleteditems")
        syncer.sync(days=None)
        state = json.loads((self.root / "email/state/acct-01/sync.json").read_text())
        deleted = next(record for record in state["messages"].values()
                       if record["provider_message_id"] == first)
        self.assertTrue(deleted["tombstoned"])
        self.assertFalse(deleted["in_scope"])

        self.mailbox.expire_next_delta = True
        expired = syncer.sync(days=30)
        self.assertEqual(expired.mode, "full")
        self.assertTrue(expired.token_expired)

    def test_out_of_scope_move_is_retained_not_tombstoned_and_staleness_blocks_review(self):
        message_id = self.mailbox.seed(at=self.recent)
        syncer = self._syncer()
        syncer.sync(days=30, force_full=True)
        self.mailbox.move(message_id, source="inbox", destination="archive")
        syncer.sync(days=30)
        state = json.loads((self.root / "email/state/acct-01/sync.json").read_text())
        record = next(iter(state["messages"].values()))
        self.assertFalse(record["in_scope"])
        self.assertFalse(record["tombstoned"])

        self.mailbox.seed(at=self.recent + timedelta(minutes=5))
        stale = syncer.staleness_probe(threshold_seconds=0)
        self.assertTrue(stale["store_stale"])
        self.assertEqual(stale["banner"], STALE_BANNER)
        self.assertFalse(stale["review_complete"])

    def test_message_keys_are_partitioned_by_neutral_account(self):
        self.mailbox.seed(message_id="same-provider-id", at=self.recent)
        self._syncer("first@example.com").sync(days=30, force_full=True)
        self._syncer("second@example.com").sync(days=30, force_full=True)
        first = json.loads((self.root / "email/state/acct-01/sync.json").read_text())
        second = json.loads((self.root / "email/state/acct-02/sync.json").read_text())
        self.assertNotEqual(next(iter(first["messages"])), next(iter(second["messages"])))

    def test_read_only_store_access_never_allocates_an_account_partition(self):
        with self.assertRaisesRegex(EmailStoreError, "run sync-store first"):
            EmailStoreSync(
                data_root=self.root,
                provider=self.mailbox,
                account_label="owner@example.com",
                read_only=True,
            )
        self.assertFalse((self.root / "email/state/identifiers.yaml").exists())

        self.mailbox.seed(at=self.recent)
        self._syncer().sync(days=30, force_full=True)
        reader_handle = EmailStoreSync(
            data_root=self.root,
            provider=self.mailbox,
            account_label="owner@example.com",
            read_only=True,
        )
        self.assertEqual(reader_handle.account, "acct-01")
        with self.assertRaisesRegex(EmailStoreError, "read-only"):
            reader_handle.sync(days=30)

    def test_local_reader_audits_all_raw_payloads_and_returns_only_content_free_review(self):
        self.mailbox.seed(
            at=self.recent,
            body="REQ-123: please choose an interview time by 2026-08-01.",
            attachments=[{
                "id": "attachment-1", "name": "invite.ics", "size": 23,
                "contentType": "text/calendar",
            }],
        )
        self._syncer().sync(days=30, force_full=True)
        reader = EmailStoreReader.for_account_label(
            data_root=self.root, account_label="owner@example.com"
        )
        integrity = reader.integrity()
        self.assertTrue(integrity.ok, integrity.errors)
        self.assertEqual(integrity.messages, 1)
        self.assertEqual(integrity.raw_blobs_checked, 1)
        self.assertEqual(integrity.attachments_checked, 1)
        report = reader.review(
            applications=[{
                "slug": "example-platform-20260720", "company": "Example Corp",
                "jobs": [{
                    "role": "Platform Engineer", "status": "applied",
                    "requisition_id": "REQ-123",
                }],
            }],
            company_domains={"Example Corp": ["example.com"]},
        )
        self.assertTrue(report["review_complete"])
        self.assertEqual(report["counts"]["stored_messages"], 1)
        self.assertEqual(report["counts"]["hydrated_messages"], 1)
        self.assertTrue(_content_free(report))
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("Synthetic workflow notice", rendered)
        self.assertNotIn("recruiter@example.com", rendered)
        self.assertNotIn("<message-1@example.com>", rendered)

    def test_full_body_search_covers_all_four_folders_and_preserves_direction(self):
        for folder, sender in (
            ("inbox", "recruiter@example.com"),
            ("sentitems", "owner@example.com"),
            ("drafts", "owner@example.com"),
            ("deleteditems", "owner@example.com"),
            ("deleteditems", "recruiter@example.com"),
        ):
            self.mailbox.seed(
                folder=folder,
                at=self.recent,
                sender=sender,
                body=f"Example Corp {folder} update for Platform Engineer.",
            )
        self._syncer().sync(days=30, force_full=True)
        reader = EmailStoreReader.for_account_label(
            data_root=self.root, account_label="owner@example.com"
        )
        report = reader.search_raw(queries=["Example Corp", "Platform Engineer"])
        self.assertTrue(report["audit_complete"], report)
        self.assertEqual(report["counts"]["messages_scanned"], 5)
        self.assertEqual(report["counts"]["matches"], 5)
        self.assertEqual(report["counts"]["scanned_by_folder"], {
            "inbox": 1, "sentitems": 1, "drafts": 1, "deleteditems": 2,
        })
        self.assertEqual(
            {(item["folder"], item["direction"]) for item in report["matches"]},
            {
                ("inbox", "inbound"),
                ("sentitems", "outbound"),
                ("drafts", "draft"),
                ("deleteditems", "outbound"),
                ("deleteditems", "inbound"),
            },
        )
        self.assertTrue(_content_free(report))
        self.assertNotIn("body_text", json.dumps(report))

        content = reader.search_raw(
            queries=["Example Corp", "Platform Engineer"], include_content=True
        )
        self.assertTrue(all("body_text" in item for item in content["matches"]))

        state_path = self.root / "email/state/acct-01/sync.json"
        state = json.loads(state_path.read_text())
        del state["folders"]["deleteditems"]
        state_path.write_text(json.dumps(state))
        incomplete = EmailStoreReader.for_account_label(
            data_root=self.root, account_label="owner@example.com"
        ).search_raw(queries=["Example Corp"])
        self.assertFalse(incomplete["audit_complete"])
        self.assertEqual(incomplete["unsynced_folders"], ["deleteditems"])

    def test_full_body_search_matches_sender_to_and_cc_participant_aliases(self):
        self.mailbox.seed(
            folder="inbox",
            at=self.recent,
            sender="morgan@talent-only.example",
            sender_name="Morgan Lee",
            body="Generic mailbox update with no participant alias in its content.",
        )
        self.mailbox.seed(
            folder="sentitems",
            at=self.recent,
            sender="owner@example.com",
            to_recipients=[("Avery Chen", "avery@to-only.example")],
            body="Another generic mailbox update.",
        )
        self.mailbox.seed(
            folder="drafts",
            at=self.recent,
            sender="owner@example.com",
            cc_recipients=[("Unique Recruiter Alias", "alias@cc-only.example")],
            body="A third generic mailbox update.",
        )
        self._syncer().sync(days=30, force_full=True)
        reader = EmailStoreReader.for_account_label(
            data_root=self.root, account_label="owner@example.com"
        )

        cases = (
            ("talent-only.example", "inbox"),
            ("Avery Chen", "sentitems"),
            ("cc-only.example", "drafts"),
        )
        for query, folder in cases:
            with self.subTest(query=query):
                report = reader.search_raw(queries=[query])
                self.assertTrue(report["audit_complete"], report)
                self.assertEqual(report["counts"]["matches"], 1)
                self.assertEqual(report["matches"][0]["folder"], folder)
                self.assertEqual(report["matches"][0]["matched_fields"], ["participants"])
                self.assertNotIn("participants", report["matches"][0])

        rendered = json.dumps(reader.search_raw(queries=["talent-only.example"]))
        self.assertNotIn("morgan@talent-only.example", rendered)
        self.assertNotIn("Morgan Lee", rendered)
        content = reader.search_raw(
            queries=["talent-only.example"], include_content=True
        )
        self.assertEqual(content["matches"][0]["participants"][0], {
            "kind": "sender",
            "name": "Morgan Lee",
            "address": "morgan@talent-only.example",
        })

    def test_store_coverage_scans_once_and_reports_independent_folder_evidence(self):
        self.mailbox.seed(
            folder="inbox",
            at=self.recent,
            body="Example Corp interview scheduling update.",
        )
        self.mailbox.seed(
            folder="deleteditems",
            at=self.recent,
            body="Example Corp archived recruiting thread.",
        )
        self.mailbox.seed(
            folder="sentitems",
            at=self.recent,
            sender="owner@example.com",
            to_recipients=[("Recruiter", "recruiter@talent-only.example")],
            body="Generic follow-up.",
        )
        self._syncer().sync(days=30, force_full=True)
        reader = EmailStoreReader.for_account_label(
            data_root=self.root, account_label="owner@example.com"
        )

        with patch.object(reader, "hydrate", wraps=reader.hydrate) as hydrate:
            report = reader.coverage_raw(
                queries=["Example Corp", "talent-only.example", "Missing Corp"]
            )

        self.assertEqual(hydrate.call_count, 3)
        self.assertTrue(report["coverage_complete"], report)
        self.assertEqual(report["counts"]["messages_scanned"], 3)
        families = {family["query"]: family for family in report["query_families"]}
        self.assertEqual(families["Example Corp"]["match_count"], 2)
        self.assertEqual(
            families["Example Corp"]["matches_by_folder"]["deleteditems"]["match_count"],
            1,
        )
        self.assertEqual(
            len(families["Example Corp"]["matches_by_folder"]["deleteditems"]["message_keys"]),
            1,
        )
        self.assertEqual(families["talent-only.example"]["match_count"], 1)
        self.assertEqual(
            families["talent-only.example"]["matches_by_folder"]["sentitems"]["match_count"],
            1,
        )
        self.assertEqual(families["Missing Corp"]["match_count"], 0)
        self.assertTrue(all(
            folder_evidence["match_count"] == 0
            and folder_evidence["message_keys"] == []
            for folder_evidence in families["Missing Corp"]["matches_by_folder"].values()
        ))
        self.assertEqual(report["zero_match_queries"], ["Missing Corp"])
        self.assertTrue(_content_free(report))
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("Synthetic workflow notice", rendered)
        self.assertNotIn("recruiter@talent-only.example", rendered)

        state_path = self.root / "email/state/acct-01/sync.json"
        state = json.loads(state_path.read_text())
        del state["folders"]["deleteditems"]
        state_path.write_text(json.dumps(state))
        incomplete = EmailStoreReader.for_account_label(
            data_root=self.root, account_label="owner@example.com"
        ).coverage_raw(queries=["Example Corp"])
        self.assertFalse(incomplete["coverage_complete"])
        self.assertEqual(incomplete["unsynced_folders"], ["deleteditems"])

    def test_local_reader_reports_missing_raw_without_outputting_mail_content(self):
        self.mailbox.seed(at=self.recent)
        self._syncer().sync(days=30, force_full=True)
        state = json.loads((self.root / "email/state/acct-01/sync.json").read_text())
        record = next(iter(state["messages"].values()))
        manifest = next(
            json.loads(path.read_text())
            for path in (self.root / "email/raw").glob("*/**/manifest.json")
            if json.loads(path.read_text()).get("fetch_id") == record["raw_fetch_id"]
        )
        BlobStore(self.root / "email/raw/_blobs").delete(manifest["payload"]["blob"])
        reader = EmailStoreReader.for_account_label(
            data_root=self.root, account_label="owner@example.com"
        )
        report = reader.review(applications=[], company_domains={})
        self.assertFalse(report["review_complete"])
        self.assertEqual(report["counts"]["unavailable_messages"], 1)
        self.assertTrue(_content_free(report))


if __name__ == "__main__":
    unittest.main()
