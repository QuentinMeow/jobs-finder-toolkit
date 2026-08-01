"""Neutral identifiers, slug/case enforcement, and key-registry pinning."""
from __future__ import annotations

import multiprocessing
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from store import identifiers, keyregistry, serialization  # noqa: E402
from store.identifiers import IdentifierRegistry  # noqa: E402
from store.keyregistry import KeyRegistry  # noqa: E402
from store.manifest import build_envelope  # noqa: E402
from store.paths import (  # noqa: E402
    SlugError,
    detect_case_collision,
    validate_identifier,
    validate_slug,
)


def _alloc_worker(path_str: str, label: str, q) -> None:
    """Worker: allocate a slug for ``label`` (used by the concurrency test)."""
    sys.path.insert(0, str(SHARED))
    from store.identifiers import IdentifierRegistry as Reg

    q.put((label, Reg(Path(path_str)).allocate("profile", label)))


def _envelope(context: dict) -> dict:
    return build_envelope(
        fetch_id="20260721T093000Z-000001-aaaaaa", source="greenhouse",
        operation="board", request={}, status=200,
        fetched_at="2026-07-21T09:30:00Z", payload=None, context=context)


class IdentifierAllocationTests(unittest.TestCase):
    def test_allocation_is_sequential_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            reg = IdentifierRegistry(Path(td) / "identifiers.yaml")
            a = reg.allocate("profile", "Real Person A")
            b = reg.allocate("profile", "Real Person B")
            self.assertEqual(a, "profile-01")
            self.assertEqual(b, "profile-02")
            # Same label always resolves to the same slug (no leak of a new number).
            self.assertEqual(reg.allocate("profile", "Real Person A"), "profile-01")
            self.assertEqual(reg.allocate("account", "mail@example.com"), "acct-01")

    def test_resolve_roundtrip_persists(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "identifiers.yaml"
            slug = IdentifierRegistry(path).allocate("profile", "Person")
            reloaded = IdentifierRegistry(path)
            self.assertEqual(reloaded.resolve_slug(slug), "Person")
            self.assertEqual(reloaded.resolve_label("profile", "Person"), slug)

    def test_agents_cannot_inject_freeform_slug(self):
        # The write-time gate: only (profile|acct)-NN passes.
        self.assertEqual(validate_identifier("profile-07"), "profile-07")
        with self.assertRaises(SlugError):
            validate_identifier("jordan")
        with self.assertRaises(SlugError):
            validate_identifier("profile-7")  # not two digits

    def test_concurrent_allocation_of_distinct_labels_is_race_safe(self):
        # N processes each allocating a DIFFERENT real label must receive DISTINCT
        # slugs (no last-writer-wins binding a slug to the wrong identity), and the
        # registry file must be intact and complete.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "identifiers.yaml"
            try:
                ctx = multiprocessing.get_context("fork")
            except ValueError:  # pragma: no cover
                self.skipTest("fork start method unavailable")
            labels = [f"Real Person {i}" for i in range(8)]
            q = ctx.Queue()
            procs = [ctx.Process(target=_alloc_worker, args=(str(path), lbl, q))
                     for lbl in labels]
            for p in procs:
                p.start()
            results = [q.get(timeout=30) for _ in labels]
            for p in procs:
                p.join(30)
                self.assertEqual(p.exitcode, 0)

            slugs = [slug for _lbl, slug in results]
            self.assertEqual(len(set(slugs)), len(labels))  # all distinct
            reg = IdentifierRegistry(path)
            self.assertEqual(len(reg._data["profile"]), len(labels))  # file complete
            for lbl in labels:
                self.assertIsNotNone(reg.resolve_label("profile", lbl))


class AllocationLockStalenessTests(unittest.TestCase):
    """An orphaned allocation lock must expire, not wedge allocation permanently.

    A process killed between ``O_CREAT|O_EXCL`` and its ``finally`` unlink leaves
    ``identifiers.yaml.alloc.lock`` on disk forever. Capture swallows the resulting
    error into a warning, so every later fetch that needs a new slug is simply not
    recorded — and recovery means hand-deleting an undocumented file.
    """

    def _orphan_lock(self, path: Path, age_seconds: float) -> Path:
        lock = path.with_name(path.name + ".alloc.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999")  # a pid that is long gone
        stamp = time.time() - age_seconds
        os.utime(lock, (stamp, stamp))
        return lock

    def test_stale_orphan_lock_is_stolen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "identifiers.yaml"
            self._orphan_lock(path, identifiers.ALLOC_LOCK_STALE_SECONDS + 10)
            reg = IdentifierRegistry(path)
            self.assertEqual(reg.allocate("profile", "Person"), "profile-01")
            self.assertEqual(IdentifierRegistry(path).resolve_slug("profile-01"),
                             "Person")

    def test_fresh_lock_is_still_respected(self):
        # The staleness path must not become a way around mutual exclusion: a lock
        # held by a live allocation still makes a concurrent caller wait and fail.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "identifiers.yaml"
            self._orphan_lock(path, 0)
            reg = IdentifierRegistry(path)
            with self.assertRaises(identifiers.IdentifierAllocationError):
                reg.allocate("profile", "Person")


class SlugEnforcementTests(unittest.TestCase):
    def test_lowercase_slug_required(self):
        self.assertEqual(validate_slug("examplecorp"), "examplecorp")
        with self.assertRaises(SlugError):
            validate_slug("ExampleCorp")
        with self.assertRaises(SlugError):
            validate_slug("example corp")

    def test_case_collision_detected(self):
        self.assertEqual(detect_case_collision(["examplecorp"], "ExampleCorp"),
                         "examplecorp")
        self.assertIsNone(detect_case_collision(["examplecorp"], "othercorp"))

    def test_manifest_rejects_freeform_identifier_context(self):
        with self.assertRaises(SlugError):
            _envelope({"company": "examplecorp", "profile": "Jordan Rivers"})

    def test_manifest_rejects_unknown_context_key(self):
        # Unknown keys bypass nothing — they are a hard error at write time.
        with self.assertRaises(SlugError):
            _envelope({"company": "examplecorp", "team": "control-plane"})

    def test_manifest_accepts_every_allowed_context_key(self):
        env = _envelope({"company": "examplecorp", "profile": "profile-01",
                         "account": "acct-02", "mailbox": "acct-03"})
        self.assertEqual(env["context"]["mailbox"], "acct-03")

    def test_allowed_context_key_still_pattern_validated(self):
        with self.assertRaises(SlugError):
            _envelope({"account": "not-a-slug"})  # allowed key, bad value


class KeyRegistryPinningTests(unittest.TestCase):
    def test_pinned_entity_cannot_be_silently_rekeyed(self):
        with tempfile.TemporaryDirectory() as td:
            reg = KeyRegistry(Path(td) / "key-registry.yaml")
            reg.pin("gh-1234567", reason="annotation")
            self.assertTrue(reg.is_pinned("gh-1234567"))
            result = reg.propose_rekey("gh-1234567", "gh-9999999")
            self.assertEqual(result, keyregistry.NEEDS_CONFIRMATION)
            # The old key is untouched; the new key was NOT created.
            self.assertTrue(reg.has("gh-1234567"))
            self.assertFalse(reg.has("gh-9999999"))

    def test_unpinned_entity_rekeys_freely_with_alias(self):
        with tempfile.TemporaryDirectory() as td:
            reg = KeyRegistry(Path(td) / "key-registry.yaml")
            reg.add_alias("url-abc", "url-old")  # materializes an unpinned entry
            result = reg.propose_rekey("url-abc", "gh-123")
            self.assertEqual(result, keyregistry.REKEYED)
            self.assertFalse(reg.has("url-abc"))
            self.assertTrue(reg.has("gh-123"))
            # Old key + prior alias resolve to the new canonical key.
            self.assertEqual(reg.resolve("url-abc"), "gh-123")
            self.assertEqual(reg.resolve("url-old"), "gh-123")

    def test_pin_is_idempotent_and_persists(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "key-registry.yaml"
            reg = KeyRegistry(path)
            reg.pin("gh-1", "annotation")
            reg.pin("gh-1", "reference")  # no-op; first reason kept
            self.assertTrue(KeyRegistry(path).is_pinned("gh-1"))


if __name__ == "__main__":
    unittest.main()
