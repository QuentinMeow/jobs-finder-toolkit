"""Migrations scaffold — annotations/ and state/ only (the sole migratable zones).

``derived/`` and ``index/`` are never migrated: a breaking change there bumps the
schema version and triggers a full rebuild from raw. Only ``annotations/`` and
``state/`` carry real migrations, kept rare by keeping those schemas tiny. This is
the scaffold and a tiny idempotent runner; there are **no real migrations yet**.

A migration is a module ``NNNN_short_name.py`` in this package exposing::

    def migrate(state_dir: Path, annotations_dir: Path, *, dry_run: bool) -> None: ...

The runner applies pending migrations in numeric order and records each in
``state/migrations-applied.jsonl`` so re-running is a no-op.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

from .. import serialization
from ..atomic import append_line, read_jsonl

_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+$")


def discover() -> list[tuple[int, str]]:
    """Return ``(number, module_name)`` for every numbered migration, in order."""
    found: list[tuple[int, str]] = []
    for info in pkgutil.iter_modules(__path__):
        m = _MIGRATION_RE.match(info.name)
        if m:
            found.append((int(m.group(1)), info.name))
    found.sort()
    return found


def applied_path(state_dir: Path) -> Path:
    return Path(state_dir) / "migrations-applied.jsonl"


def applied_numbers(state_dir: Path) -> set[int]:
    return {int(ln["number"]) for ln in read_jsonl(applied_path(state_dir))
            if "number" in ln}


def run(state_dir: Path, annotations_dir: Path, *, dry_run: bool = True) -> list[str]:
    """Apply pending migrations (idempotent). Returns the names it (would) apply."""
    state_dir = Path(state_dir)
    done = applied_numbers(state_dir)
    ran: list[str] = []
    for number, name in discover():
        if number in done:
            continue
        ran.append(name)
        if dry_run:
            continue
        module = importlib.import_module(f"{__name__}.{name}")
        module.migrate(state_dir, Path(annotations_dir), dry_run=False)
        append_line(
            applied_path(state_dir),
            serialization.dumps_jsonl_line(
                {"number": number, "name": name, "applied_at": serialization.now_z()}),
        )
    return ran
