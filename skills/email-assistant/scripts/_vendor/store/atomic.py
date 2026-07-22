"""Atomic write discipline and torn-tail-tolerant JSONL reading.

Two rules from the store-core write-discipline section, made concrete:

- **write-temp-then-rename, same directory.** ``rename`` is only atomic within one
  filesystem, so the temp file is created in the *target's own directory* — a temp
  dir on another volume would silently downgrade the rename to a copy. A reader
  therefore never sees a half-written file: it sees the old bytes or the new bytes.
- **line-atomic JSONL append.** Each append is a single ``O_APPEND`` write of one
  complete, newline-terminated line. Every reader tolerates a torn final line (the
  only crash artifact possible), because raw is the source of truth and the next
  build repairs the tail by truncation.

Both rules assume the data root is a local, non-cloud-synced volume (a
Dropbox/iCloud-style syncer breaks rename atomicity) — stated in the store README.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (temp-in-same-dir, fsync, rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-",
                               suffix=path.suffix or ".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Atomic-write UTF-8 text (see :func:`atomic_write_bytes`)."""
    atomic_write_bytes(path, text.encode("utf-8"))


def repair_jsonl(path: Path) -> bool:
    """Truncate a torn (non-newline-terminated) tail to the last complete record.

    The design's crash-repair step ("the next build repairs it by truncation"): a
    JSONL file that does not end in ``\\n`` has a torn final line — a half-flushed
    append. Truncating to the last ``\\n`` (or to empty when there is none) drops
    only the incomplete fragment; every complete record survives, and a subsequent
    append no longer merges onto the fragment (which would silently lose a record
    and later poison the reader). A no-op on a clean / empty / missing file.
    Returns ``True`` iff it truncated something.
    """
    path = Path(path)
    if not path.exists():
        return False
    with open(path, "rb+") as fh:
        data = fh.read()
        if not data or data.endswith(b"\n"):
            return False
        idx = data.rfind(b"\n")
        fh.truncate(idx + 1 if idx != -1 else 0)
        fh.flush()
        os.fsync(fh.fileno())
    return True


def append_line(path: Path, line: str) -> None:
    """Append one complete line via a single atomic ``O_APPEND`` write.

    ``line`` must be a complete record; a trailing newline is added if missing so
    the file stays one-record-per-line and torn-tail tolerant. A torn tail from a
    prior crash is **repaired first** (truncated to the last complete record) so
    the new line can never merge onto a half-written fragment.
    """
    if not line.endswith("\n"):
        line = line + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    repair_jsonl(path)
    data = line.encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_jsonl(path: Path, *, strict_interior: bool = True) -> list[Any]:
    """Read a JSONL file, tolerating a torn final line (crash artifact).

    A complete record is a newline-terminated line that parses as JSON. A trailing
    fragment with no terminator is a torn write and is dropped; a final terminated
    line that fails to parse is likewise tolerated (dropped).

    ``strict_interior`` (default) raises on an *interior* unparseable line — real
    corruption that silence would hide. ``strict_interior=False`` instead skips it
    with a stderr warning; the ledger loader uses this so a pre-repair merged line
    from an older file can never hard-crash a build.
    """
    path = Path(path)
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw:
        return []
    text = raw.decode("utf-8", errors="replace")
    parts = text.split("\n")
    # A clean file ends in "\n" → the final split element is "". If it is not empty
    # the last physical line was never terminated → a torn fragment; drop it.
    if parts and parts[-1] == "":
        parts = parts[:-1]
    elif parts:
        parts = parts[:-1]
    objects: list[Any] = []
    last = len(parts) - 1
    for i, part in enumerate(parts):
        if not part.strip():
            continue
        try:
            objects.append(json.loads(part))
        except json.JSONDecodeError:
            if i == last:
                # Tolerate a torn/half-flushed final terminated line.
                continue
            if not strict_interior:
                print(f"store: WARNING skipping unparseable interior line "
                      f"{i + 1} in {path} (treating as crash debris)",
                      file=sys.stderr)
                continue
            raise
    return objects


def iter_jsonl(path: Path) -> Iterator[Any]:
    """Iterate parsed JSONL records (torn-tail tolerant); see :func:`read_jsonl`."""
    yield from read_jsonl(path)
