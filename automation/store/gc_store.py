"""Retention garbage collector for the raw-data-layer store.

Prunes payload blobs the domain's ``retention.yaml`` marks disposable, honoring the
store-core contract exactly (``design/raw-data-layer/01-store-core.md`` §9):

- **manifests are never pruned** (they are the observation log);
- a blob is deletable only when EVERY manifest referencing it is in a prunable tier
  AND past that tier's dates — any keep-class reference vetoes (refcounts computed
  at sweep time);
- before a candidate blob that feeds a materialized entity is deleted, that entity's
  source-derived facts are snapshotted to ``state/frozen-facts/`` so a later rebuild
  carries it forward (marked ``carried+frozen``) instead of leaving a data hole;
- strict per-blob order frozen-facts → tombstone → delete, so a crash never destroys
  data — the worst crash window is blob-present-plus-tombstone (re-sweepable).

``--dry-run`` is the DEFAULT: it prints the full plan (candidate blobs, per-tier
counts, bytes reclaimable, frozen-facts to write, why each candidate qualifies,
manifest-less debris, orphaned blobs, pruned-pending blobs) and touches nothing.
``--execute`` performs it. GC takes the BUILDER lock and fails fast on contention
(a skipped GC costs nothing). Debris under ``raw/<source>/`` older than 24h is
removed under ``--execute``; orphaned blobs are removed only with ``--remove-orphans``.

Usage:
    .venv/bin/python automation/store/gc_store.py                      # dry-run (default)
    .venv/bin/python automation/store/gc_store.py --execute
    .venv/bin/python automation/store/gc_store.py --execute --remove-orphans
    .venv/bin/python automation/store/gc_store.py --data-root /path/to/store --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import config  # noqa: E402
from store import retention  # noqa: E402
from store.blobs import BlobStore  # noqa: E402
from store.locking import DomainLock, LockContention  # noqa: E402
from store.paths import domain_layout  # noqa: E402
from store.serialization import to_z  # noqa: E402

DOMAIN = "jobs"


def _resolve_root(arg: str | None) -> Path | None:
    if arg:
        return Path(arg).expanduser().resolve()
    return config.data_root()


def _fmt_dt(dt) -> str:
    return to_z(dt) if dt is not None else "—"


def _fmt_kb(nbytes: int) -> str:
    return f"{nbytes / 1024:.1f} KB"


def _print_plan(plan: retention.SweepPlan, *, execute: bool, remove_orphans: bool) -> None:
    layout = plan.layout
    cfg_path = retention.config_path(layout)
    print("Store GC")
    print(f"  data root:   {layout.root.parent}")
    print(f"  domain:      {layout.domain}")
    print(f"  config:      {cfg_path}"
          f"{'' if cfg_path.exists() else '  (missing → everything never; GC opt-in)'}")
    if plan.config.is_opt_in_only:
        print("  note: no prunable tier configured — nothing is a candidate.")

    print(f"\n  CANDIDATE blobs (deletable): {len(plan.candidates)}  "
          f"({_fmt_kb(plan.disk_bytes)} on disk reclaimable)")
    for tier, n in sorted(plan.tier_counts.items()):
        print(f"    tier {tier}: {n}")
    for c in plan.candidates:
        print(f"    - {c.sha[:12]}…  tier={c.tier}  {_fmt_kb(c.disk_bytes)}  "
              f"[{c.reason}]")
        print(f"        posting_date={_fmt_dt(c.posting_date)}  "
              f"last_observed={_fmt_dt(c.last_observed)}  "
              f"feeds {len(c.fed_entity_keys)} entity(ies)")
    print(f"  keep-class / not-yet-past blobs vetoed: {plan.vetoed}")

    frozen = plan.frozen_entity_keys
    print(f"\n  FROZEN-FACTS to write/refresh (materialized entities fed by "
          f"candidates): {len(frozen)}")

    print(f"\n  manifest-less debris dirs under raw/<source>/ (>24h): {len(plan.debris)}")
    for d in plan.debris:
        print(f"    - {d.path}  ({d.age_hours:.1f}h old)")

    print(f"\n  orphaned blobs (present, referenced by no manifest): "
          f"{len(plan.orphans)}"
          f"{'  (removed with --remove-orphans)' if plan.orphans else ''}")

    if plan.pruned_pending:
        print(f"\n  pruned-pending (tombstone present, blob still here — crash "
              f"window, re-sweepable): {len(plan.pruned_pending)}")

    if not execute:
        print("\n  DRY-RUN: nothing changed. Re-run with --execute to prune.")


def _print_result(result: retention.ExecResult) -> None:
    print("\n  EXECUTED:")
    print(f"    frozen-facts written: {result.frozen_written}")
    print(f"    tombstones written:   {result.tombstoned}")
    print(f"    blobs deleted:        {result.deleted}  "
          f"({_fmt_kb(result.disk_bytes_reclaimed)} reclaimed)")
    if result.re_vetoed:
        print(f"    re-vetoed (mid-sweep capture; blob kept): {result.re_vetoed}")
    print(f"    debris dirs removed:  {result.debris_removed}")
    print(f"    orphan blobs removed: {result.orphans_removed}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=None,
                        help="store data root (default: config.data_root())")
    parser.add_argument("--domain", default=DOMAIN, help="store domain (default: jobs)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and change nothing (the DEFAULT)")
    parser.add_argument("--execute", action="store_true",
                        help="perform the sweep (frozen-facts → tombstone → delete)")
    parser.add_argument("--remove-orphans", action="store_true",
                        help="also delete orphaned blobs (present, refcount 0); "
                             "requires --execute")
    args = parser.parse_args(argv)

    if args.dry_run and args.execute:
        parser.error("--dry-run and --execute are mutually exclusive")
    if args.remove_orphans and not args.execute:
        parser.error("--remove-orphans requires --execute (it deletes orphaned blobs)")
    execute = args.execute  # dry-run is the default

    data_root = _resolve_root(args.data_root)
    if data_root is None:
        print("store not configured (set paths.data_root or JOBHUNT_DATA_ROOT); "
              "nothing to garbage-collect.")
        return 0

    layout = domain_layout(data_root, args.domain)
    layout.state.mkdir(parents=True, exist_ok=True)
    blobstore = BlobStore(layout.blobs)
    cfg = retention.load_config(layout)

    # GC mutates derived/state/raw → take the builder lock, fail fast on contention.
    try:
        with DomainLock(layout.lock_path()):
            plan = retention.plan_sweep(layout, blobstore, cfg)
            _print_plan(plan, execute=execute, remove_orphans=args.remove_orphans)
            if execute:
                result = retention.execute_sweep(
                    plan, blobstore, remove_orphans=args.remove_orphans)
                _print_result(result)
    except LockContention as exc:
        print(f"gc_store: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
