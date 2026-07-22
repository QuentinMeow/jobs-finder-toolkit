"""gardener routine: raw-data-layer store health report (report-only, ALWAYS).

The store-core Retention contract gives the gardener a store routine
(``design/raw-data-layer/01-store-core.md`` §9). Unlike the retention GC
(``scripts/store/gc_store.py``), the gardener NEVER prunes — it only *reports*, so
a human sees growth and integrity problems before deciding to run the GC. Every
dimension the contract lists, per domain under the configured data root:

- zone sizes (raw / _blobs / derived / index / annotations / state);
- manifest + blob counts;
- the four blob availability states (present / pruned / not-synced-here / corrupt);
- orphaned blobs (present, referenced by no manifest — refcount 0);
- manifest-less fetch directories under ``raw/<source>/`` (crash debris);
- torn JSONL tails (detected + reported; REPAIR belongs to the writers, not here);
- stale locks — the builder lock (stale after its threshold) AND the identifier
  ``.alloc.lock`` (which has NO auto-steal, so a crash leaves it forever: reported
  loudly at ANY age);
- cursor ages (``state/cursors.yaml``);
- suppressed-review queue file count + ages (``index/triage/``);
- annotation-conflict backlog length (``state/annotation-conflicts.jsonl``);
- the ``validate_store`` result (a library call) — a corrupt blob or schema
  violation is the one condition that makes this routine exit non-zero.

Usage:
    .venv/bin/python scripts/maintenance/gardener/store_report.py
    (or via the front-end)  gardener.py store-report
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402  (bootstraps scripts/shared onto sys.path)

try:
    import config  # noqa: E402  (bootstrapped by _common)
except ImportError:  # pragma: no cover
    config = C.config

from store import blobs as _blobs  # noqa: E402
from store import retention, validation  # noqa: E402
from store.constants import LOCK_STALE_SECONDS, ZONES  # noqa: E402
from store.manifest import audit_refcounts, iter_manifests  # noqa: E402
from store.paths import DomainLayout  # noqa: E402
from store.serialization import loads_yaml, parse_z  # noqa: E402

ALLOC_LOCK_NAME = "identifiers.yaml.alloc.lock"


def _dir_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def _torn_tail(path: Path) -> bool:
    """True if a JSONL file has a torn (non-newline-terminated) final line."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            if fh.tell() == 0:
                return False
            fh.seek(-1, 2)
            return fh.read(1) != b"\n"
    except OSError:
        return False


def _lock_age_seconds(path: Path, now: float) -> float | None:
    try:
        return now - path.stat().st_mtime
    except FileNotFoundError:
        return None


def _find_domains(root: Path) -> list[Path]:
    return [c for c in sorted(root.iterdir())
            if c.is_dir() and any((c / z).is_dir() for z in ZONES)]


def _cursor_ages(layout: DomainLayout, now: datetime) -> list[tuple[str, str, float]]:
    """``(name, updated_at, age_days)`` for each cursor in ``state/cursors.yaml``."""
    out: list[tuple[str, str, float]] = []
    if not layout.cursors.exists():
        return out
    try:
        data = loads_yaml(layout.cursors.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return out
    for name, cur in (data.get("cursors") or {}).items():
        updated = (cur or {}).get("updated_at") if isinstance(cur, dict) else None
        age = None
        if updated:
            try:
                age = (now - parse_z(updated)).total_seconds() / 86400.0
            except ValueError:
                age = None
        out.append((name, updated or "?", age if age is not None else -1.0))
    return out


def report_domain(layout: DomainLayout) -> dict:
    """Collect (never mutate) every store-health dimension for one domain."""
    now_dt = datetime.now(timezone.utc)
    now_s = time.time()
    blobstore = _blobs.BlobStore(layout.blobs)

    zone_sizes = {z: _dir_bytes(getattr(layout, z)) for z in ZONES}
    zone_sizes["_blobs"] = _dir_bytes(layout.blobs)

    manifest_count = 0
    blob_states: dict[str, int] = {}
    for _p, env in iter_manifests(layout):
        manifest_count += 1
        payload = env.get("payload")
        if isinstance(payload, dict) and payload.get("blob"):
            ext = _blobs.ext_for_content_type(payload.get("content_type"))
            st = blobstore.state(payload["blob"], ext)
            blob_states[st] = blob_states.get(st, 0) + 1

    audit = audit_refcounts(layout, blobstore)
    debris = retention.find_debris_dirs(layout, now=now_dt)

    # Torn tails across the JSONL surfaces (ledger, index, per-entity events).
    torn: list[Path] = []
    for jsonl in [layout.build_ledger, layout.state / "annotation-conflicts.jsonl"]:
        if jsonl.exists() and _torn_tail(jsonl):
            torn.append(jsonl)
    for jsonl in sorted(layout.index.rglob("*.jsonl")) if layout.index.is_dir() else []:
        if _torn_tail(jsonl):
            torn.append(jsonl)
    if layout.derived.is_dir():
        for jsonl in sorted(layout.derived.rglob("events.jsonl")):
            if _torn_tail(jsonl):
                torn.append(jsonl)

    # Locks: builder (stale after threshold) + identifier alloc lock (any age = loud).
    builder_lock_age = _lock_age_seconds(layout.lock_path(), now_s)
    alloc_lock_age = _lock_age_seconds(layout.state / ALLOC_LOCK_NAME, now_s)

    # Suppressed-review queue files + annotation-conflict backlog.
    triage = layout.index / "triage"
    suppressed_files = sorted(triage.glob("*.jsonl")) if triage.is_dir() else []
    suppressed_ages = [(f.name, (now_s - f.stat().st_mtime) / 86400.0)
                       for f in suppressed_files]
    conflicts_path = layout.state / "annotation-conflicts.jsonl"
    conflict_count = 0
    if conflicts_path.exists():
        from store.atomic import read_jsonl
        conflict_count = len(read_jsonl(conflicts_path))

    vreport = validation.validate_store(layout.root.parent)

    return {
        "domain": layout.domain,
        "zone_sizes": zone_sizes,
        "manifest_count": manifest_count,
        "blob_count": len(blobstore.present_shas()),
        "blob_states": blob_states,
        "orphans": audit["orphans"],
        "debris": debris,
        "torn": torn,
        "builder_lock_age": builder_lock_age,
        "alloc_lock_age": alloc_lock_age,
        "cursors": _cursor_ages(layout, now_dt),
        "suppressed": suppressed_ages,
        "conflict_count": conflict_count,
        "validate_errors": list(vreport.errors),
    }


def _print_domain(r: dict) -> None:
    print(f"\n  domain: {r['domain']}")
    zs = r["zone_sizes"]
    order = ["raw", "_blobs", "derived", "index", "annotations", "state"]
    print("    zone sizes: " + ", ".join(
        f"{z}={_fmt_bytes(zs.get(z, 0))}" for z in order))
    print(f"    manifests: {r['manifest_count']}   present blobs: {r['blob_count']}")
    if r["blob_states"]:
        print("    blob states: " + ", ".join(
            f"{k}={v}" for k, v in sorted(r["blob_states"].items())))
    print(f"    orphaned blobs (refcount 0): {len(r['orphans'])}")
    print(f"    manifest-less debris dirs (>24h): {len(r['debris'])}")
    for d in r["debris"]:
        print(f"      - {d.path}  ({d.age_hours:.1f}h)")
    if r["torn"]:
        print(f"    torn JSONL tails (writers repair on next build): {len(r['torn'])}")
        for p in r["torn"]:
            print(f"      - {p}")
    else:
        print("    torn JSONL tails: 0")

    bl = r["builder_lock_age"]
    if bl is None:
        print("    builder lock: absent (no build in flight)")
    elif bl >= LOCK_STALE_SECONDS:
        print(f"    builder lock: STALE ({bl:.0f}s ≥ {LOCK_STALE_SECONDS}s) — a "
              f"crashed build left it; the next builder auto-steals it")
    else:
        print(f"    builder lock: held {bl:.0f}s (fresh)")
    al = r["alloc_lock_age"]
    if al is None:
        print("    identifier alloc lock: absent (normal)")
    else:
        print(f"    identifier alloc lock: PRESENT ({al:.0f}s old) — LOUD: this lock "
              f"has NO auto-steal; a crashed allocation leaves it forever. "
              f"Investigate and remove {ALLOC_LOCK_NAME} by hand if no allocation is running.")

    if r["cursors"]:
        print("    cursors: " + ", ".join(
            f"{n}@{u}({a:.1f}d)" if a >= 0 else f"{n}@{u}(?)"
            for n, u, a in r["cursors"]))
    print(f"    suppressed-review queue files: {len(r['suppressed'])}"
          + ("  [" + ", ".join(f"{n}:{a:.1f}d" for n, a in r["suppressed"]) + "]"
             if r["suppressed"] else ""))
    print(f"    annotation-conflict backlog: {r['conflict_count']}")
    if r["validate_errors"]:
        print(f"    validate_store: FAIL ({len(r['validate_errors'])} error(s))")
        for e in r["validate_errors"][:5]:
            print(f"      - {e}")
    else:
        print("    validate_store: OK")


def run(apply: bool = False) -> int:  # apply is ignored — report-only, ALWAYS
    C.print_header("store-report", False)
    root = config.data_root()
    if root is None:
        print("  store not configured (paths.data_root / JOBHUNT_DATA_ROOT unset) — "
              "nothing to report.")
        return 0
    print(f"  data root: {root}")
    if not Path(root).is_dir():
        print(f"  data root does not exist: {root} — nothing to report.")
        return 0
    domains = _find_domains(Path(root))
    if not domains:
        print(f"  no store domains found under {root}.")
        return 0
    rc = 0
    for domain_root in domains:
        layout = DomainLayout(root=domain_root, domain=domain_root.name)
        r = report_domain(layout)
        _print_domain(r)
        if r["validate_errors"]:
            rc = 1  # a corrupt blob / schema violation is a real integrity failure
    print("\n  store-report is READ-ONLY (the gardener never prunes; run "
          "scripts/store/gc_store.py --execute to act on retention).")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="ignored — this routine is report-only, always")
    return run(ap.parse_args(argv).apply)


if __name__ == "__main__":
    raise SystemExit(main())
