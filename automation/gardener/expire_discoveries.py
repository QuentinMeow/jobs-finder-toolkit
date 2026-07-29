"""gardener routine: expire stale discovery scans (move, never delete).

Discovery/market-scan files are WORKING MEMORY (AGENTS.md "Memory Map" zone (d)). They go
stale in ~30 days, so:

  * files older than ``discovery_ttl_days`` (default 30) are EXPIRED -> moved to the
    sibling ``archive/`` folder on ``--apply`` (soft-delete; a one-line index entry
    is appended to ``archive/index.md``);
  * raw scans older than ``discovery_archive_days`` (default 14) but within the TTL
    are FLAGGED as soft-archive candidates for human review — never auto-moved,
    because a compacted ranked shortlist can legitimately live a few weeks and the
    gardener can't tell a shortlist from a raw scan.

Age is taken from the filename ``YYYYMMDD`` (prefix or embedded), falling back to
the file mtime. DRY-RUN by default: prints a per-file plan and moves nothing.

Usage:
    .venv/bin/python automation/maintenance/gardener/expire_discoveries.py
    .venv/bin/python automation/maintenance/gardener/expire_discoveries.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    import config  # noqa: E402  (bootstrapped onto sys.path by _common)
except ImportError:  # pragma: no cover
    config = C.config


def _archive_dir(discoveries: Path) -> Path:
    """Sibling ``archive/`` for a ``current/`` discoveries dir, else a nested one."""
    if discoveries.name == "current":
        return discoveries.parent / "archive"
    return discoveries.parent / "archive"


def plan(policy: dict) -> dict:
    """Compute expire (>TTL) and raw-archive (>archive_days) candidate lists."""
    discoveries = config.discoveries_dir()
    ttl = policy["discovery_ttl_days"]
    raw = policy["discovery_archive_days"]
    expire: list[dict] = []
    flag: list[dict] = []
    if discoveries.is_dir():
        for f in sorted(discoveries.glob("*.md")):
            if not f.is_file():
                continue
            age, eff, src = C.file_age_days(f)
            row = {"path": f, "age": age, "date": eff.isoformat(), "src": src}
            if age > ttl:
                expire.append(row)
            elif age > raw:
                flag.append(row)
    return {"discoveries": discoveries, "archive": _archive_dir(discoveries),
            "expire": expire, "flag": flag, "ttl": ttl, "raw": raw}


def run(apply: bool = False) -> int:
    policy = C.retention()
    C.print_header("expire-discoveries", apply)
    p = plan(policy)
    print(f"  discoveries: {C.rel(p['discoveries'])}  (TTL {p['ttl']}d, "
          f"raw-archive {p['raw']}d)")
    if not p["discoveries"].is_dir():
        print("  discoveries dir does not exist — nothing to do.")
        return 0

    print(f"\n  EXPIRE (age > {p['ttl']}d -> move to archive/): {len(p['expire'])}")
    for r in p["expire"]:
        print(f"    move  {r['path'].name}  ({r['age']}d, date {r['date']} via {r['src']})")
    print(f"\n  RAW-ARCHIVE candidates (age > {p['raw']}d, review only): {len(p['flag'])}")
    for r in p["flag"]:
        print(f"    flag  {r['path'].name}  ({r['age']}d, date {r['date']} via {r['src']})")

    if not apply:
        if p["expire"] or p["flag"]:
            print("\n  DRY-RUN: nothing moved. Re-run with --apply to move the EXPIRE set.")
        else:
            print("\n  Nothing to expire — all discoveries are within retention.")
        return 0

    if not p["expire"]:
        print("\n  APPLY: no files past the hard TTL — nothing moved.")
        return 0
    archive = p["archive"]
    archive.mkdir(parents=True, exist_ok=True)
    index = archive / "index.md"
    moved = 0
    with index.open("a", encoding="utf-8") as idx:
        for r in p["expire"]:
            src = r["path"]
            dst = archive / src.name
            if dst.exists():
                dst = archive / f"{src.stem}.dup-{C.today().isoformat()}{src.suffix}"
            src.rename(dst)
            idx.write(f"- {dst.name} — archived {C.today().isoformat()} "
                      f"(scan date {r['date']}, age {r['age']}d)\n")
            print(f"    moved {src.name} -> archive/{dst.name}")
            moved += 1
    print(f"\n  APPLY: moved {moved} file(s) to {C.rel(archive)} (index.md updated).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="perform the moves (default: dry-run plan only)")
    return run(ap.parse_args(argv).apply)


if __name__ == "__main__":
    raise SystemExit(main())
