"""Identity pinning — ``state/key-registry.yaml``.

Entity keys are computed by versioned code, and identity code improves over time,
which threatens anything that *points at* a key. The rule: an entity that has
annotations, or that an application folder references, is **never silently
re-keyed**. Once pinned (first annotation, first reference), identity improvements
may add aliases but a proposed re-key returns "needs human confirmation" instead of
moving it. Unpinned entities re-key freely (nothing external points at them).
"""
from __future__ import annotations

from pathlib import Path

from . import serialization
from .atomic import atomic_write_text

SCHEMA_VERSION = 1

# Result of a proposed re-key.
REKEYED = "rekeyed"
NEEDS_CONFIRMATION = "needs-human-confirmation"
NOOP = "noop"


class KeyRegistry:
    """Read/pin/alias/re-key entity identities for one domain state dir."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            data = serialization.loads_yaml(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("schema_version", SCHEMA_VERSION)
                data.setdefault("keys", {})
                return data
        return {"schema_version": SCHEMA_VERSION, "keys": {}}

    def _save(self) -> None:
        atomic_write_text(self.path, serialization.dumps_yaml(self._data))

    def _entry(self, key: str) -> dict:
        return self._data["keys"].setdefault(
            key, {"pinned": False, "reason": None, "aliases": []})

    def has(self, key: str) -> bool:
        return key in self._data["keys"]

    def is_pinned(self, key: str) -> bool:
        return bool(self._data["keys"].get(key, {}).get("pinned"))

    def aliases(self, key: str) -> list[str]:
        return list(self._data["keys"].get(key, {}).get("aliases", []))

    def pin(self, key: str, reason: str) -> None:
        """Pin ``key`` (idempotent). ``reason`` is e.g. ``annotation`` / ``reference``."""
        entry = self._entry(key)
        if not entry["pinned"]:
            entry["pinned"] = True
            entry["reason"] = reason
            self._save()

    def add_alias(self, key: str, alias: str) -> None:
        entry = self._entry(key)
        if alias != key and alias not in entry["aliases"]:
            entry["aliases"].append(alias)
            entry["aliases"].sort()
            self._save()

    def resolve(self, key_or_alias: str) -> str | None:
        """Return the canonical key for a key or one of its aliases, else ``None``."""
        if key_or_alias in self._data["keys"]:
            return key_or_alias
        for key, entry in self._data["keys"].items():
            if key_or_alias in entry.get("aliases", []):
                return key
        return None

    def propose_rekey(self, old: str, new: str) -> str:
        """Propose moving identity ``old`` → ``new``.

        Pinned: refuse and return ``NEEDS_CONFIRMATION`` (the old key keeps winning,
        the disagreement is never invisible). Unpinned: perform the move and return
        ``REKEYED``. Same key: ``NOOP``.
        """
        if old == new:
            return NOOP
        if self.is_pinned(old):
            # Never silently re-key; record nothing destructive.
            return NEEDS_CONFIRMATION
        entry = self._data["keys"].pop(old, {"pinned": False, "reason": None,
                                             "aliases": []})
        # Carry the old key forward as an alias so references still resolve.
        aliases = set(entry.get("aliases", []))
        aliases.add(old)
        aliases.discard(new)
        merged = self._data["keys"].get(new, {"pinned": False, "reason": None,
                                              "aliases": []})
        merged_aliases = set(merged.get("aliases", [])) | aliases
        self._data["keys"][new] = {
            "pinned": merged.get("pinned", False) or entry.get("pinned", False),
            "reason": merged.get("reason") or entry.get("reason"),
            "aliases": sorted(merged_aliases),
        }
        self._save()
        return REKEYED
