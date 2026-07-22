"""query_postings.py — code-only filtering over the job store (no AI, no network).

Reads the index and derived entities (NEVER raw), the "filter with code, not AI"
interface. Compact table + count by default; ``--jsonl`` / ``--full`` are opt-ins;
hashes and fetch ids appear only under ``--debug``. The query takes NO lock.

Cursors ride the builder's **materialization sequence** (not timestamps), so a
posting recovered retroactively by a bug fix still surfaces in the next delta:

* ``--new-since-cursor NAME``  show entities with seq > the cursor (never advances)
* ``--since SEQ``              manual sequence override
* ``--mark-reviewed NAME``     advance the cursor to the max seq just displayed
                               (advance-AFTER-action; never auto-advance)

Filter semantics share the vendored location/registry gate code with the live
pipeline so store-side and fetch-side filtering cannot drift.

    query_postings.py --new-since-cursor shortlist-review --profile profile-01
    query_postings.py --company examplecorp
    query_postings.py --visa yes --workplace remote --max-age-days 7
    query_postings.py --key gh-1234567 --history

Store-derived rows must never be pasted into public PRs, evals, or benchmarks.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SKILL_SCRIPTS = Path(__file__).resolve().parent
for _p in (str(_SKILL_SCRIPTS), str(_SKILL_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
from _vendor.store import serialization  # noqa: E402
from _vendor.store.atomic import atomic_write_text, read_jsonl  # noqa: E402
from _vendor.store.keyregistry import KeyRegistry  # noqa: E402
from _vendor.store.paths import domain_layout  # noqa: E402
from registry import load_registry  # noqa: E402

DOMAIN = "jobs"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_days(row: dict) -> float | None:
    # Anchor on the source-claimed posted_at ONLY — the live pipeline's date anchor
    # (scoring.date_ok uses days_since(posted_at)). Returns None when the source gave
    # no date; callers keep None-date rows (matching date_ok's "unknown date -> keep").
    dt = _parse_ts(row.get("posted_at"))
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def _load_index(layout) -> list[dict]:
    path = layout.index / "postings.jsonl"
    lines = read_jsonl(path)
    return lines[1:] if lines else []  # drop the machine-generated header


def _load_cursors(layout) -> dict:
    path = layout.cursors
    if path.exists():
        data = serialization.loads_yaml(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {"schema_version": 1, "cursors": {}}


def _save_cursor(layout, name: str, seq: int) -> None:
    """Advance a cursor under a short O_EXCL lock, monotonically (never regress).

    The whole read-modify-write runs under an exclusive lock (the same O_EXCL
    pattern the identifier registry uses), and the stored seq is ``max(existing,
    new)`` — so a concurrent advance to a higher sequence is never silently lost.
    """
    lock_path = layout.cursors.with_name(layout.cursors.name + ".advance.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 5.0
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"could not acquire {lock_path.name} to advance cursor {name!r}")
            time.sleep(0.02)
    try:
        os.close(fd)
        data = _load_cursors(layout)            # re-read UNDER the lock (never stale)
        cursors = data.setdefault("cursors", {})
        prior = int((cursors.get(name) or {}).get("seq", 0))
        cursors[name] = {"seq": max(prior, int(seq)),
                         "updated_at": serialization.now_z()}
        data.setdefault("schema_version", 1)
        atomic_write_text(layout.cursors, serialization.dumps_yaml(data))
    finally:
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass


def _apply_filters(rows, args, registry, layout) -> list[dict]:
    out = rows
    if args.company:
        want = registry.canonical(args.company) or args.company
        want_keys = registry.match_keys(args.company)

        def _match(r):
            rc = r.get("company", "")
            return (registry.canonical(rc) or rc) == want or \
                rc.strip().lower() in {k for k in want_keys}
        out = [r for r in out if _match(r)]
    if args.visa:
        out = [r for r in out if r.get("visa") == args.visa]
    if args.workplace:
        out = [r for r in out if r.get("workplace") == args.workplace]
    if args.identity:
        out = [r for r in out if r.get("identity", "strong") == args.identity]
    if args.profile:
        out = [r for r in out if args.profile in (r.get("profiles") or [])]
    if args.max_age_days is not None:
        def _fresh(r):
            age = _age_days(r)
            # Align with scoring.date_ok: an unknown posted_at (None) is KEPT.
            return age is None or age <= args.max_age_days
        out = [r for r in out if _fresh(r)]
    # sequence-cursor filters
    since = None
    if args.since is not None:
        since = args.since
    elif args.new_since_cursor:
        cur = _load_cursors(layout).get("cursors", {}).get(
            args.new_since_cursor, {})
        since = int(cur.get("seq", 0))
    if since is not None:
        out = [r for r in out if int(r.get("seq", 0)) > since]
    return out


def _print_table(rows, args) -> None:
    if args.jsonl:
        for r in rows:
            print(serialization.dumps_jsonl_line(r), end="")
        print(f"# {len(rows)} posting(s)")
        return
    if not rows:
        print("(no matching postings)")
        print("0 posting(s)")
        return
    header = ["KEY", "COMPANY", "TITLE", "LOCATION", "VISA", "WORK", "AGE"]
    if args.debug:
        header += ["SEQ", "IDENT"]
    display = []
    for r in rows:
        age = _age_days(r)
        cells = [
            str(r.get("key", ""))[:20],
            str(r.get("company", ""))[:18],
            str(r.get("title", ""))[:40],
            str(r.get("location", ""))[:24],
            str(r.get("visa", "")),
            str(r.get("workplace", "")),
            (f"{age:.0f}d" if age is not None else "-"),
        ]
        if args.debug:
            cells += [str(r.get("seq", "")), str(r.get("identity", ""))]
        display.append(cells)
    widths = [max(len(header[i]), *(len(row[i]) for row in display))
              for i in range(len(header))]

    def fmt(cols):
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    print(fmt(header))
    print(fmt(["-" * w for w in widths]))
    for row in display:
        print(fmt(row))
    print(f"\n{len(rows)} posting(s)")


def _show_history(layout, key: str, args) -> int:
    reg = KeyRegistry(layout.key_registry)
    resolved = reg.resolve(key) or key
    # locate the entity dir
    from _vendor.store.resolver import find_entity_dir
    entity_dir = find_entity_dir(layout, resolved)
    if entity_dir is None:
        print(f"no entity {key!r} in the store", file=sys.stderr)
        return 1
    pyaml = entity_dir / "posting.yaml"
    if args.full:
        print(pyaml.read_text(encoding="utf-8"), end="")
        return 0
    data = serialization.loads_yaml(pyaml.read_text(encoding="utf-8"))
    print(f"{resolved}  {data.get('company', '')}  {data.get('title', '')}")
    print(f"  first_seen {data.get('first_seen')}  last_seen {data.get('last_seen')}"
          f"  identity {data.get('identity', 'strong')}")
    events = read_jsonl(entity_dir / "events.jsonl")
    for ev in events:
        line = f"  {ev.get('at', '')}  {ev.get('type', '')}"
        if ev.get("type") == "changed":
            fields = ", ".join(c.get("field", "") for c in ev.get("changes", []))
            line += f"  [{fields}]"
        if args.debug:
            line += f"  fetch={ev.get('fetch', '')} seq={ev.get('seq', '')}"
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--domain", default=DOMAIN)
    parser.add_argument("--company")
    parser.add_argument("--visa", choices=["yes", "no", "unclear"])
    parser.add_argument("--workplace", choices=["remote", "hybrid", "onsite", "unknown"])
    parser.add_argument("--identity", choices=["strong", "weak"])
    parser.add_argument("--max-age-days", type=float, dest="max_age_days",
                        help="keep postings whose source-claimed posted_at is within "
                        "N days (the live pipeline's anchor); unknown-date rows are kept")
    parser.add_argument("--profile", help="filter to postings observed under this "
                        "profile slug (membership in the entity's profile set)")
    parser.add_argument("--key", help="one posting's key")
    parser.add_argument("--history", action="store_true",
                        help="with --key: print the posting's event biography")
    parser.add_argument("--new-since-cursor", dest="new_since_cursor",
                        help="show entities with seq > this cursor (never advances)")
    parser.add_argument("--since", type=int, help="manual sequence override")
    parser.add_argument("--mark-reviewed", dest="mark_reviewed",
                        help="advance the named cursor to the max seq displayed")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    data_root = (Path(args.data_root).expanduser().resolve()
                 if args.data_root else config.data_root())
    if data_root is None:
        print("store not configured (set paths.data_root or JOBHUNT_DATA_ROOT).")
        return 0
    layout = domain_layout(data_root, args.domain)

    if args.key:
        return _show_history(layout, args.key, args)

    registry = load_registry(None)
    rows = _apply_filters(_load_index(layout), args, registry, layout)
    rows.sort(key=lambda r: (int(r.get("seq", 0)), r.get("key", "")))
    _print_table(rows, args)

    if args.mark_reviewed and rows:
        max_seq = max(int(r.get("seq", 0)) for r in rows)
        _save_cursor(layout, args.mark_reviewed, max_seq)
        print(f"# cursor {args.mark_reviewed!r} advanced to seq {max_seq}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
