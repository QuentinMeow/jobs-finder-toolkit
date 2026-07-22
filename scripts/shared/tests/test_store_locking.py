"""Builder-only lock: fail fast on contention, steal when stale."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from store.locking import DomainLock, LockContention  # noqa: E402


class DomainLockTests(unittest.TestCase):
    def test_fail_fast_on_contention(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jobs.build.lock"
            with DomainLock(path):
                with self.assertRaises(LockContention):
                    DomainLock(path).acquire()
            # Released on exit → re-acquirable.
            with DomainLock(path):
                self.assertTrue(path.exists())
            self.assertFalse(path.exists())

    def test_stale_lock_is_stolen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jobs.build.lock"
            lock = DomainLock(path, stale_seconds=1)
            lock.acquire()
            # Age the lock past the stale window.
            old = time.time() - 10
            os.utime(path, (old, old))
            # A fresh builder steals the abandoned lock instead of failing.
            stealer = DomainLock(path, stale_seconds=1).acquire()
            self.assertTrue(path.exists())
            stealer.release()


class StealRaceTests(unittest.TestCase):
    """The stale-steal path is race-safe: exactly one concurrent stealer wins."""

    def _stale_lock(self, td: str) -> Path:
        path = Path(td) / "jobs.build.lock"
        holder = DomainLock(path, stale_seconds=1)
        holder.acquire()
        holder._held = False  # simulate a crashed holder (never releases)
        old = time.time() - 10
        os.utime(path, (old, old))
        return path

    def test_two_stealers_only_one_wins(self):
        # Drive the atomic claim step for both stealers deterministically (no
        # timing): the rename is atomic, so exactly one wins and the loser sees
        # FileNotFoundError -> False (which acquire turns into contention).
        with tempfile.TemporaryDirectory() as td:
            path = self._stale_lock(td)
            a = DomainLock(path, stale_seconds=1)
            b = DomainLock(path, stale_seconds=1)
            self.assertTrue(a._claim_stale())    # A wins the rename
            self.assertFalse(b._claim_stale())   # B loses — no bare OSError
            self.assertTrue(a._create_fresh())   # A finalizes and holds
            self.assertTrue(path.exists())
            a.release()
            self.assertFalse(path.exists())

    def test_losing_stealer_fails_fast_with_contention(self):
        # A stealer whose claim loses raises LockContention, NOT the uncaught
        # FileNotFoundError the old unlink-then-recreate path could raise.
        class LosingLock(DomainLock):
            def _claim_stale(self):
                return False

        with tempfile.TemporaryDirectory() as td:
            path = self._stale_lock(td)
            with self.assertRaises(LockContention):
                LosingLock(path, stale_seconds=1).acquire()

    def test_fresh_lock_created_after_steal_is_contention(self):
        # If another builder creates a fresh lock in the window after our steal, we
        # fail fast rather than double-hold.
        class PostStealLoserLock(DomainLock):
            def _create_fresh(self):
                return False  # steal succeeds, but the re-create always "loses"

        with tempfile.TemporaryDirectory() as td:
            path = self._stale_lock(td)
            with self.assertRaises(LockContention):
                PostStealLoserLock(path, stale_seconds=1).acquire()


if __name__ == "__main__":
    unittest.main()
