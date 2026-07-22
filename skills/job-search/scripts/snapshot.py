"""Pre-filter fetch snapshots for the job-search skill.

A snapshot is the normalized posting set written *before* filtering, so a later
``--refilter`` run can re-apply filter -> score -> rank without paying for another
fetch. The freshness mission is preserved by a short TTL (see ``TTL_HOURS``): the
cache is a within-session artifact, not a store.

Stdlib-only (plus the skill's own ``common`` module). Postings round-trip with
**full fidelity** — the whole ``JobPosting`` dataclass, the complete (untruncated)
description, and an ISO ``posted_at`` — so a refilter re-scores byte-identically to
the fetch run that wrote the snapshot. (``JobPosting.to_dict`` deliberately truncates
the description for light JSON output; snapshots must not, or scoring would drift.)
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import JobPosting, parse_dt

# How stale a snapshot may be before --refilter refuses it without --allow-stale.
# Freshness is this toolkit's product; the cache is a within-session artifact.
TTL_HOURS = 6
SCHEMA_VERSION = 1

_POSTING_FIELDS = [f.name for f in fields(JobPosting)]


def safe_label(profile: str) -> str:
    """Filesystem-safe token for a profile label (which may be a path)."""
    base = Path(profile).name or profile
    if base.endswith(".yaml"):
        base = base[: -len(".yaml")]
    return re.sub(r"[^A-Za-z0-9_.-]", "_", base) or "profile"


def posting_to_dict(p: JobPosting) -> dict:
    """Serialize a JobPosting with full fidelity (untruncated description)."""
    d: dict = {}
    for name in _POSTING_FIELDS:
        value = getattr(p, name)
        if name == "posted_at":
            value = value.isoformat() if value else None
        d[name] = value
    return d


def posting_from_dict(d: dict) -> JobPosting:
    """Rebuild a JobPosting from :func:`posting_to_dict` output."""
    kwargs = {}
    for name in _POSTING_FIELDS:
        if name not in d:
            continue
        value = d[name]
        if name == "posted_at":
            value = parse_dt(value) if value else None
        kwargs[name] = value
    return JobPosting(**kwargs)


def _stamp(fetched_at: datetime) -> str:
    """Compact, sortable, filesystem-safe UTC timestamp for a snapshot filename."""
    return fetched_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_snapshot(
    cache_dir: Path,
    *,
    profile: str,
    stage: int,
    fetched_at: datetime,
    source_selection: dict,
    postings: list[JobPosting],
    errors: list[str] | None = None,
) -> tuple[Path, Path]:
    """Write ``<profile>-stage<N>-<stamp>.json`` plus a ``-latest.json`` pointer.

    The pointer is a **full copy** (not a symlink): robust across platforms and
    trivial to load, and the whole ``tmp/`` tree is disposable anyway. Returns
    ``(snapshot_path, latest_path)``.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    label = safe_label(profile)
    payload = {
        "schema": SCHEMA_VERSION,
        "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
        "profile": profile,
        "stage": stage,
        "source_selection": source_selection,
        "errors": list(errors or []),
        "n_postings": len(postings),
        "postings": [posting_to_dict(p) for p in postings],
    }
    snap_path = cache_dir / f"{label}-stage{stage}-{_stamp(fetched_at)}.json"
    snap_path.write_text(json.dumps(payload, indent=2))
    latest_path = cache_dir / f"{label}-stage{stage}-latest.json"
    shutil.copyfile(snap_path, latest_path)
    return snap_path, latest_path


def resolve_snapshot_path(cache_dir: Path, profile: str, ref: str) -> Path:
    """Resolve a ``--refilter`` argument to a concrete snapshot file.

    ``ref == "latest"`` picks the newest (by fetch time) ``-latest.json`` pointer for
    this profile across all stages, so callers never need a fetch-affecting ``--stage``
    just to locate it. Any other value is treated as a path (absolute, cwd-relative,
    or relative to ``cache_dir``).
    """
    cache_dir = Path(cache_dir)
    if ref == "latest":
        label = safe_label(profile)
        pointers = sorted(cache_dir.glob(f"{label}-stage*-latest.json"))
        if not pointers:
            raise FileNotFoundError(
                f"No snapshot found for profile '{profile}' in {cache_dir}. "
                "Run a fresh search first (a snapshot is written on every fetch)."
            )
        return max(pointers, key=lambda p: load_snapshot(p).get("fetched_at") or "")
    candidate = Path(ref)
    if candidate.exists():
        return candidate
    in_cache = cache_dir / ref
    if in_cache.exists():
        return in_cache
    raise FileNotFoundError(f"Snapshot not found: {ref}")


def load_snapshot(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def snapshot_fetched_at(snapshot: dict) -> datetime:
    dt = parse_dt(snapshot.get("fetched_at"))
    if dt is None:
        raise ValueError("Snapshot has no valid 'fetched_at' timestamp.")
    return dt


def format_age(delta: timedelta) -> str:
    """Human-readable snapshot age, e.g. ``2h 05m`` or ``0h 42m``."""
    total = int(max(delta.total_seconds(), 0))
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m"


def is_stale(fetched_at: datetime, now: datetime, ttl_hours: int = TTL_HOURS) -> bool:
    return (now - fetched_at) > timedelta(hours=ttl_hours)
