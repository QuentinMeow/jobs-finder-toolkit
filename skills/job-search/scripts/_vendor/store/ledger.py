"""Build ledger, materialization sequence, and the clock-monotonicity guard.

``state/build-ledger.jsonl`` records every fetch a build has already processed.
Each build processes the **set difference** — all committed manifests minus the
ledger — which (unlike a "process everything newer than the last build" watermark)
never skips a fetch that *started* before a build but *committed* after it, because
fetch ids are stamped at fetch start.

Each ledger line carries a monotonically increasing **materialization sequence**
number that the builder stamps; cursors ride this sequence (not timestamps), so a
posting recovered retroactively by a bug fix still surfaces in the next delta.

``built_at`` is wall-clock and lives only here in ``state/`` — it is excluded from
determinism comparisons by construction.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import serialization
from .atomic import append_line, read_jsonl, repair_jsonl
from .manifest import iter_manifests
from .paths import DomainLayout


class BuildLedger:
    """Append-only record of processed fetches with a materialization sequence."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lines = self._load()

    def _load(self) -> list[dict]:
        # Repair any torn tail from a prior crash, then read tolerantly: a merged
        # line from a pre-repair file is treated as crash debris (skipped + warned),
        # never a hard crash of the build (the ledger is regenerable from raw).
        repair_jsonl(self.path)
        return read_jsonl(self.path, strict_interior=False)

    def reload(self) -> None:
        self._lines = self._load()

    def processed_fetch_ids(self) -> set[str]:
        return {ln["fetch_id"] for ln in self._lines if "fetch_id" in ln}

    def head(self) -> dict | None:
        """The most recently appended ledger line (or ``None`` if empty)."""
        return self._lines[-1] if self._lines else None

    def max_seq(self) -> int:
        return max((int(ln.get("seq", 0)) for ln in self._lines), default=0)

    def next_seq(self) -> int:
        return self.max_seq() + 1

    def record(self, fetch_id: str, *, fetched_at: str, built_at: str,
               seq: int | None = None, clock_ok: bool = True,
               extra: dict | None = None) -> int:
        """Append a ledger line for a processed fetch; return its sequence number."""
        seq = self.next_seq() if seq is None else seq
        line = {
            "fetch_id": fetch_id,
            "seq": seq,
            "fetched_at": fetched_at,
            "built_at": built_at,
            "clock_ok": clock_ok,
        }
        if extra:
            line.update(extra)
        append_line(self.path, serialization.dumps_jsonl_line(line))
        self._lines.append(line)
        return seq

    def head_fetched_at(self) -> str | None:
        head = self.head()
        return head.get("fetched_at") if head else None


def pending_manifests(layout: DomainLayout,
                      ledger: BuildLedger) -> list[tuple[Path, dict]]:
    """All committed manifests not yet in the ledger, in canonical (fetch_id) order.

    This is the set-difference the builder processes each run — the mechanism that
    has no started-before/committed-after hole.
    """
    done = ledger.processed_fetch_ids()
    pending = [(p, env) for p, env in iter_manifests(layout)
               if env.get("fetch_id") not in done]
    pending.sort(key=lambda pe: pe[1].get("fetch_id", ""))
    return pending


def check_clock_monotonic(fetched_at: str, ledger: BuildLedger) -> bool:
    """Return ``False`` (and warn) when ``fetched_at`` predates the ledger head.

    A run whose clock went backwards is marked so absence-based inference can
    exclude it — an NTP jump must not be allowed to fabricate history.
    """
    head = ledger.head_fetched_at()
    if head is None:
        return True
    try:
        ok = serialization.parse_z(fetched_at) >= serialization.parse_z(head)
    except ValueError:
        return True
    if not ok:
        print(f"store: WARNING clock went backwards: capture {fetched_at} "
              f"precedes ledger head {head}; excluded from absence inference",
              file=sys.stderr)
    return ok
