"""Builder-only lock: fail fast on contention, steal when stale, release by identity."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

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


# ── release is by IDENTITY, not by path ──────────────────────
class ReleaseIdentityTests(unittest.TestCase):
    """A lock releasable by someone who no longer holds it is not a lock.

    ``_is_stale`` reads an mtime stamped once at creation, so a holder that simply
    runs longer than the stale window (a full rebuild, a GC over a real store) has
    its lock legitimately stolen while it is still writing. If its ``release()``
    then unlinks BY PATH it removes the STEALER's lock, and a third builder walks
    straight in — two concurrent writers over ``derived/`` and ``index/``, silently.
    Declining to unlink costs at most one stale-window wait; unlinking someone
    else's lock costs mutual exclusion outright.
    """

    def test_owner_token_identifies_one_acquisition(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jobs.build.lock"
            import json
            with DomainLock(path) as a:
                first = json.loads(path.read_text())["owner_token"]
                self.assertEqual(first, a._token)
            with DomainLock(path) as b:
                self.assertNotEqual(json.loads(path.read_text())["owner_token"], first)
                self.assertEqual(b._token, json.loads(path.read_text())["owner_token"])

    def test_victim_of_a_steal_does_not_delete_the_stealers_lock(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jobs.build.lock"
            victim = DomainLock(path, stale_seconds=1)
            victim.acquire()
            old = time.time() - 10
            os.utime(path, (old, old))          # the victim is merely SLOW, not dead
            stealer = DomainLock(path, stale_seconds=1).acquire()

            victim.release()                    # the victim finishes and exits
            self.assertTrue(path.exists(), "the stealer's lock was deleted")
            self.assertFalse(victim._held)
            with self.assertRaises(LockContention):
                DomainLock(path).acquire()      # a third builder stays excluded
            stealer.release()
            self.assertFalse(path.exists())

    def test_unreadable_lock_file_is_never_assumed_to_be_ours(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jobs.build.lock"
            holder = DomainLock(path)
            holder.acquire()
            path.write_text("{ truncated", encoding="utf-8")  # half-written / bit-rot
            holder.release()
            self.assertTrue(path.exists())      # fail closed: not provably ours

    def test_release_after_the_lock_vanished_is_quiet(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "jobs.build.lock"
            holder = DomainLock(path)
            holder.acquire()
            os.unlink(path)
            holder.release()                    # no raise, no resurrection
            self.assertFalse(path.exists())


_HOLDER = textwrap.dedent("""
    import sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from store.locking import DomainLock
    lock_path, ctl = Path(sys.argv[2]), Path(sys.argv[3])
    lock = DomainLock(lock_path, stale_seconds=1)
    lock.acquire()
    (ctl / "acquired").write_text("1")
    deadline = time.time() + 60
    while not (ctl / "go").exists() and time.time() < deadline:
        time.sleep(0.01)
    lock.release()
    (ctl / "released").write_text("1")
""")


class TwoProcessStealTests(unittest.TestCase):
    """The same race across a real process boundary (no mocks, no shared memory).

    Process A holds the lock and is still running; the parent ages the lock past the
    stale window and steals it (process B); A then releases. B's lock must survive
    and a third acquirer must still be excluded.
    """

    def _await(self, marker: Path, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while not marker.exists():
            if time.time() > deadline:
                self.fail(f"timed out waiting for {marker.name}")
            time.sleep(0.01)

    def test_a_second_process_release_does_not_free_the_stealers_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctl = root / "ctl"
            ctl.mkdir()
            script = root / "holder.py"
            script.write_text(_HOLDER, encoding="utf-8")
            path = root / "jobs.build.lock"

            proc = subprocess.Popen(
                [sys.executable, str(script), str(SHARED), str(path), str(ctl)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self._await(ctl / "acquired")   # A holds a real lock
                # A is slow, not dead: age its lock past the stale window.
                old = time.time() - 10
                os.utime(path, (old, old))
                stealer = DomainLock(path, stale_seconds=1).acquire()   # B steals
                self.assertTrue(path.exists())

                (ctl / "go").write_text("1")    # tell A to finish and release
                out, err = proc.communicate(timeout=60)
                self.assertEqual(proc.returncode, 0, err)
                self._await(ctl / "released", timeout=1.0)

                self.assertTrue(path.exists(),
                                "process A deleted process B's lock on its way out")
                # The default stale window: B's lock is fresh, so C must be excluded.
                with self.assertRaises(LockContention):
                    DomainLock(path).acquire()
                stealer.release()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
