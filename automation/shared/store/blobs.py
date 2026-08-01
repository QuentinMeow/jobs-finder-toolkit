"""Content-addressed payload blob store (zstd), with verify-on-read.

Separates *what we received* (upstream's opaque bytes) from *what we know about
receiving it* (the manifest). A blob is named by the sha256 of its **uncompressed**
bytes — the compression codec is a storage detail, never part of identity — and
sharded by the first two hex characters. Writes dedupe (an existing blob is a
no-op, so a same-content race between two processes is a benign rename-nothing).

Four availability states a caller must never conflate (store-core retention rules):

- ``present``       — the blob file exists and verifies against its name;
- ``corrupt``       — the file exists but fails its hash (the only error state);
- ``pruned``        — a retention tombstone exists (the blob was deliberately GC'd);
- ``not-synced-here`` — no file, no tombstone (normal on the owner's multi-laptop,
  manually-synced setup) — INFORMATIONAL, never a failure.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import zstandard

from . import serialization
from .atomic import atomic_write_bytes, atomic_write_text
from .constants import ZSTD_LEVEL

# Availability states.
PRESENT = "present"
CORRUPT = "corrupt"
PRUNED = "pruned"
NOT_SYNCED_HERE = "not-synced-here"

_CONTENT_TYPE_EXT = {
    "application/json": "json",
    "text/html": "html",
    "text/markdown": "md",
    "text/plain": "txt",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/x-ndjson": "jsonl",
}

# A blob filename's leading component is a sha256 hex digest and nothing else.
_SHA_RE = re.compile(r"[0-9a-f]{64}")


class BlobCorrupt(Exception):
    """A blob's bytes do not hash to its name (bit-rot / tampering)."""


def ext_for_content_type(content_type: str | None) -> str:
    if not content_type:
        return "bin"
    base = content_type.split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(base, "bin")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class BlobRef:
    """The manifest's view of a stored payload."""

    sha256: str
    bytes_raw: int
    ext: str

    def as_payload(self, content_type: str | None) -> dict:
        return {
            "blob": self.sha256,
            "bytes_raw": self.bytes_raw,
            "content_type": content_type or "application/octet-stream",
        }


class BlobStore:
    """Read/write/verify content-addressed blobs under ``blobs_root``."""

    def __init__(self, blobs_root: Path, level: int = ZSTD_LEVEL) -> None:
        self.root = Path(blobs_root)
        self.level = level

    # ── path helpers ──
    def _filename(self, sha: str, ext: str | None) -> str:
        return f"{sha}.{ext}.zst" if ext else f"{sha}.zst"

    def path_for(self, sha: str, ext: str | None) -> Path:
        return self.root / sha[:2] / self._filename(sha, ext)

    def tombstone_path(self, sha: str) -> Path:
        return self.root / sha[:2] / f"{sha}.tombstone"

    def find_all(self, sha: str) -> list[Path]:
        """Every file in the shard holding this sha's bytes, whatever its extension.

        One sha can legitimately sit on disk more than once: the filename embeds
        the *content-type* extension, so identical bytes fetched once as
        ``application/json`` and once with no ``Content-Type`` land as
        ``<sha>.json.zst`` AND ``<sha>.bin.zst``. Identity is the sha alone, so
        anything that answers a question about "this blob" must see all of them.
        """
        shard = self.root / sha[:2]
        if not shard.is_dir():
            return []
        found = sorted(shard.glob(f"{sha}.*.zst"))
        plain = shard / f"{sha}.zst"
        if plain.exists():
            found.append(plain)
        return found

    def find(self, sha: str) -> Path | None:
        """Locate a stored blob by sha alone (any extension), or ``None``."""
        found = self.find_all(sha)
        return found[0] if found else None

    # ── write ──
    def write(self, data: bytes, content_type: str | None = None) -> BlobRef:
        """Store ``data`` (compress + name by uncompressed sha256). Dedup no-op.

        The dedupe is a bare ``exists()`` — a re-capture holding the correct bytes
        does NOT repair an already-corrupt file. That is deliberate: verifying on
        every duplicate write costs a full read+decompress on the capture hot path,
        where duplicates are the common case, and ``corrupt`` is already a loud
        state (:meth:`state`, ``validate_store`` and ``store_show`` all report it),
        never a silent one. Repair belongs in an explicit operator path.
        """
        sha = sha256_hex(data)
        ext = ext_for_content_type(content_type)
        path = self.path_for(sha, ext)
        if not path.exists():
            compressed = zstandard.ZstdCompressor(level=self.level).compress(data)
            atomic_write_bytes(path, compressed)
        return BlobRef(sha256=sha, bytes_raw=len(data), ext=ext)

    # ── prune (retention GC) ──
    def write_tombstone(self, sha: str, *, reason: str | None = None,
                        meta: dict | None = None) -> Path:
        """Write the retention tombstone for ``sha`` (what :meth:`state` reads as pruned).

        The tombstone is the ``<sha>.tombstone`` marker file next to where the blob
        would live; its *existence* is the only thing :meth:`state` consults (it
        returns ``pruned`` only when the blob file is absent AND this marker exists),
        so the content is human-facing metadata only. Written atomically. The GC
        writes the tombstone BEFORE deleting the blob, so a crash in the window leaves
        blob-present-plus-tombstone — :meth:`state` still reads ``present`` (the blob
        verifies), i.e. a re-sweepable "pruned-pending", never ``corrupt``.
        """
        record = {"tombstone": True, "sha": sha, "pruned_at": serialization.now_z()}
        if reason:
            record["reason"] = reason
        if meta:
            record["meta"] = meta
        path = self.tombstone_path(sha)
        atomic_write_text(path, serialization.dumps_json(record))
        return path

    def delete(self, sha: str, ext: str | None = None) -> bool:
        """Delete EVERY stored copy of ``sha`` (idempotent). ``True`` if any went.

        Only payload files are touched — never the tombstone or the manifest. After
        a paired :meth:`write_tombstone` + :meth:`delete`, :meth:`state` reports
        ``pruned``.

        ``ext`` is accepted (callers pass the extension their manifest recorded) but
        is not a filter: deleting only that one file while the same bytes survive
        under another content-type's extension leaves :meth:`state` reporting
        ``present``, so the sweep re-lists and re-tombstones the blob on every pass
        and never reclaims a byte.
        """
        removed = False
        for path in self.find_all(sha):
            try:
                path.unlink()
                removed = True
            except FileNotFoundError:  # a concurrent sweep got there first
                pass
        return removed

    def is_pruned_pending(self, sha: str, ext: str | None = None) -> bool:
        """A tombstone exists but the blob file is still present (crash window).

        The GC order is frozen-facts → tombstone → delete; a crash between the last
        two leaves this re-sweepable state. It is NOT ``pruned`` yet (the bytes are
        still here and verify), so the next GC pass re-completes the delete.

        Like :meth:`state`, this falls back to the any-extension lookup: the bytes
        surviving under a *different* content-type's extension is exactly the state
        that needs re-sweeping.
        """
        if not self.tombstone_path(sha).exists():
            return False
        path = self.path_for(sha, ext) if ext else None
        if path is None or not path.exists():
            path = self.find(sha)
        return path is not None and path.exists()

    # ── read (verify-on-read) ──
    def read(self, sha: str, ext: str | None = None) -> bytes:
        """Return the uncompressed bytes, verifying the sha (raises on corruption).

        Raises :class:`FileNotFoundError` when the blob is not present here (the
        caller decides whether that is ``pruned`` or ``not-synced-here`` via
        :meth:`state`) and :class:`BlobCorrupt` when the bytes fail their hash.
        """
        path = self.path_for(sha, ext) if ext else self.find(sha)
        if path is None or not path.exists():
            raise FileNotFoundError(f"blob {sha} not present in {self.root}")
        compressed = path.read_bytes()
        try:
            data = zstandard.ZstdDecompressor().decompress(compressed)
        except zstandard.ZstdError as exc:
            # A truncated / bit-rotted frame fails in the codec, BEFORE the hash
            # check below. That is still "these bytes are not the blob", so it
            # surfaces as the one documented failure type rather than leaking a
            # codec exception every caller's except clause would miss.
            raise BlobCorrupt(
                f"blob {sha} could not be decompressed ({exc})") from exc
        actual = sha256_hex(data)
        if actual != sha:
            raise BlobCorrupt(f"blob {sha} failed verify-on-read (got {actual})")
        return data

    # ── availability ──
    def state(self, sha: str, ext: str | None = None) -> str:
        """Return one of ``present`` / ``corrupt`` / ``pruned`` / ``not-synced-here``.

        Identity is the uncompressed sha alone, so even when a specific ``ext`` is
        requested we fall back to an any-extension lookup before concluding the
        blob is absent — the same content stored under a different ext IS present.
        """
        path = self.path_for(sha, ext) if ext else None
        if path is None or not path.exists():
            path = self.find(sha)
        if path is not None and path.exists():
            try:
                compressed = path.read_bytes()
                data = zstandard.ZstdDecompressor().decompress(compressed)
            except Exception:
                return CORRUPT
            return PRESENT if sha256_hex(data) == sha else CORRUPT
        if self.tombstone_path(sha).exists():
            return PRUNED
        return NOT_SYNCED_HERE

    def present_shas(self) -> set[str]:
        """Every blob sha physically present under the store (from filenames).

        Only well-formed sha names count. A crash mid-``atomic_write_bytes`` leaves
        a ``.tmp-<rand>.zst`` in the shard, whose leading component is the empty
        string — and this set is what the GC subtracts the reference set from, so a
        phantom name would be reported as a nameless orphan. The stray temp file is
        left where it is: this store has no unattended delete path into ``_blobs``.
        """
        found: set[str] = set()
        if not self.root.is_dir():
            return found
        for shard in self.root.iterdir():
            if not shard.is_dir():
                continue
            for f in shard.glob("*.zst"):
                name = f.name.split(".", 1)[0]
                if _SHA_RE.fullmatch(name):
                    found.add(name)
        return found
