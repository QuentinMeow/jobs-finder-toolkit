"""Builder-only per-domain lock — fail fast on contention, stale after a few minutes.

Builders are the single writer for ``derived/`` and ``index/``; a second builder
**fails fast** with a clear message (a skipped incremental build costs nothing —
the ledger catches it up next run). Fetchers and readers NEVER touch this lock.
The lock file is created atomically with ``O_CREAT|O_EXCL``; a lock older than
``LOCK_STALE_SECONDS`` is considered abandoned and stolen.

Stealing a stale lock is **race-safe**: instead of ``unlink`` then re-create (a
TOCTOU where two builders can both end up holding the lock, and the loser's
``unlink`` raises an uncaught ``FileNotFoundError``), a stealer atomically renames
the stale file to a unique claim name. ``os.rename`` is atomic and the source
exists exactly once, so of any number of concurrent stealers exactly ONE rename
succeeds; every loser gets ``FileNotFoundError`` and treats it as contention
(fail fast).

**A lock is identified by its contents, not by its path.** Every holder stamps a
unique ``owner_token`` into the lock file (the same ``<pid>-<random hex>`` shape
the steal path already uses for its claim names), and ``release()`` unlinks only
after re-reading the file and confirming that token. Without that check the victim
of a stale steal deletes the STEALER's lock on its way out, so a third builder
walks straight in and two writers run concurrently. Declining to unlink costs at
most one stale-window wait; unlinking someone else's lock costs mutual exclusion.
An unreadable lock file is therefore never treated as ours.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from . import serialization
from .constants import LOCK_STALE_SECONDS


def _new_owner_token() -> str:
    """A token unique to one acquisition (pid alone is reused; mtime is 1s-grained)."""
    return f"{os.getpid()}-{os.urandom(8).hex()}"


class LockContention(RuntimeError):
    """Another builder holds a fresh lock on this domain."""


class DomainLock:
    """Context manager for the per-domain builder lock."""

    def __init__(self, path: Path, *, stale_seconds: int = LOCK_STALE_SECONDS) -> None:
        self.path = Path(path)
        self.stale_seconds = stale_seconds
        self._held = False
        self._token: str | None = None

    def _write_owner(self) -> None:
        self._token = _new_owner_token()
        info = {"pid": os.getpid(), "acquired_at": serialization.now_z(),
                "owner_token": self._token}
        with os.fdopen(self._fd, "w") as fh:
            fh.write(serialization.dumps_json(info))

    def _is_ours(self) -> bool:
        """True only if the lock file on disk still carries THIS holder's token.

        Anything else — the file is gone, unreadable, malformed, or carries another
        token — answers False, so ``release()`` leaves it alone. Fail-closed: an
        unreadable lock is someone else's until proven otherwise.
        """
        if self._token is None:
            return False
        try:
            info = serialization.loads_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(info, dict) and info.get("owner_token") == self._token

    def _create_fresh(self) -> bool:
        """Try to create the lock exclusively; True on success, False if it exists."""
        try:
            self._fd = os.open(str(self.path),
                               os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        self._write_owner()
        self._held = True
        return True

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return False  # vanished (holder released) — not stale, just gone
        return age >= self.stale_seconds

    def _claim_stale(self) -> bool:
        """Atomically claim the stale lock via rename; True iff we won the steal.

        Only one concurrent stealer's ``os.rename`` can succeed (the source exists
        once); losers get ``FileNotFoundError`` → ``False`` → contention upstream.
        """
        claim = self.path.with_name(
            f"{self.path.name}.steal-{os.getpid()}-{os.urandom(4).hex()}")
        try:
            os.rename(self.path, claim)
        except FileNotFoundError:
            return False
        try:
            os.unlink(claim)
        except FileNotFoundError:
            pass
        return True

    def acquire(self) -> "DomainLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._create_fresh():
            return self
        # The lock file is present.
        if not self._is_stale():
            # Genuinely fresh, or it vanished in the window — one more attempt, else
            # fail fast (a skipped build is caught up by the ledger next run).
            if self._create_fresh():
                return self
            raise LockContention(
                f"another builder holds {self.path.name}; refusing to run. "
                f"A skipped build is caught up by the ledger next run.")
        # Stale → race-safe steal. Exactly one concurrent stealer wins.
        if not self._claim_stale():
            raise LockContention(
                f"lost the steal of stale lock {self.path.name} to another "
                f"builder; refusing to run.")
        if not self._create_fresh():
            raise LockContention(
                f"another builder acquired {self.path.name} after the steal; "
                f"refusing to run.")
        return self

    def release(self) -> None:
        """Drop the lock, removing the file ONLY while it is still ours.

        If our lock was stolen as stale while we ran, the file at ``self.path`` now
        belongs to the stealer: unlinking it would silently end mutual exclusion for
        a builder that is actively writing. We leave it and simply stop claiming to
        hold it — the worst residue is a lock file whose owner has moved on, which
        the stale-steal path already handles.
        """
        if self._held:
            if self._is_ours():
                try:
                    os.unlink(self.path)
                except OSError:
                    pass
            self._held = False
            self._token = None

    def __enter__(self) -> "DomainLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False
