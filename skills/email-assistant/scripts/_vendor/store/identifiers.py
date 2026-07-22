"""Neutral identifier registry — ``state/identifiers.yaml``.

Owner-identifying context values (profile labels, mailbox names) never appear in a
path, manifest, or query output; they are neutral slugs (``profile-01``,
``acct-01``) resolved through this private lookup. The privacy guarantee is
*mechanical*: agents can never hand-type a slug — the library allocates the next
free ``profile-NN`` / ``acct-NN`` for a real label and resolves existing ones, and
every slug field is pattern-validated at write time (see ``paths.validate_identifier``).

The file lives in ``state/`` (tracked in the private overlay only); the leak
guard's token scan covers the mapped real values, so any escape into the public
tree still trips it.
"""
from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from . import serialization
from .atomic import atomic_write_text

SCHEMA_VERSION = 1

# Registry namespaces and their slug prefixes.
_NAMESPACES = {"profile": "profile", "account": "acct"}

# Allocation is guarded by a tiny exclusive lock file next to identifiers.yaml so
# two processes allocating DIFFERENT labels cannot both compute the same slug and
# last-writer-wins bind it to the wrong real identity. The lock is held for
# microseconds (re-read → allocate → write); on timeout we raise (capture's
# totality wrapper turns that into a warning and the fetch continues). This does
# NOT violate "fetchers never lock" — that rule protects the capture WRITE path
# (blobs/manifests stay lock-free); the design explicitly sanctions library-only
# identifier allocation as the guarded path. ``resolve*`` stays lock-free.
_ALLOC_LOCK_TIMEOUT_S = 5.0
_ALLOC_LOCK_POLL_S = 0.02


class IdentifierAllocationError(RuntimeError):
    """Could not acquire the identifier-allocation lock within the deadline."""


class IdentifierRegistry:
    """Read/allocate/resolve neutral identifier slugs for one domain state dir."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            data = serialization.loads_yaml(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("schema_version", SCHEMA_VERSION)
                for ns in _NAMESPACES:
                    data.setdefault(ns, {})
                return data
        return {"schema_version": SCHEMA_VERSION, **{ns: {} for ns in _NAMESPACES}}

    def _save(self) -> None:
        atomic_write_text(self.path, serialization.dumps_yaml(self._data))

    def _prefix(self, namespace: str) -> str:
        if namespace not in _NAMESPACES:
            raise ValueError(f"unknown identifier namespace {namespace!r} "
                             f"(known: {sorted(_NAMESPACES)})")
        return _NAMESPACES[namespace]

    @contextlib.contextmanager
    def _alloc_lock(self):
        """Exclusive allocation lock (O_CREAT|O_EXCL spin, short poll, deadline)."""
        lock_path = self.path.with_name(self.path.name + ".alloc.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + _ALLOC_LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(str(lock_path),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise IdentifierAllocationError(
                        f"could not acquire {lock_path.name} within "
                        f"{_ALLOC_LOCK_TIMEOUT_S}s (another allocation in flight)"
                    ) from None
                time.sleep(_ALLOC_LOCK_POLL_S)
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                pass

    def allocate(self, namespace: str, label: str) -> str:
        """Return the slug for ``label``, allocating the next free ``NN`` if new.

        Idempotent and concurrency-safe: the whole path (re-read → allocate →
        write) runs under an exclusive lock, so two processes allocating DIFFERENT
        labels each observe the other's write and get DISTINCT slugs. Callers pass
        a *real* label and receive only a neutral slug — the real value never
        leaves this file.
        """
        prefix = self._prefix(namespace)  # validates namespace before locking
        with self._alloc_lock():
            self._data = self._load()  # RE-READ under the lock (never stale)
            table: dict = self._data[namespace]
            for slug, existing in table.items():
                if existing == label:
                    return slug
            used = {int(slug.rsplit("-", 1)[1]) for slug in table
                    if slug.startswith(prefix + "-")}
            n = 1
            while n in used:
                n += 1
            slug = f"{prefix}-{n:02d}"
            table[slug] = label
            self._save()
            return slug

    def resolve_slug(self, slug: str) -> str | None:
        """Return the real label for a slug, or ``None`` if unknown."""
        for ns in _NAMESPACES:
            if slug in self._data.get(ns, {}):
                return self._data[ns][slug]
        return None

    def resolve_label(self, namespace: str, label: str) -> str | None:
        """Return the slug for ``label`` if already allocated, else ``None``."""
        for slug, existing in self._data.get(namespace, {}).items():
            if existing == label:
                return slug
        return None
