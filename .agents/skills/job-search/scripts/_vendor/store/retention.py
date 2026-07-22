"""Retention GC — the config language, the reference-counted sweep, frozen facts.

The store-core Retention contract (``docs/design/raw-data-layer/01-store-core.md``
§9) made concrete. Three ideas, kept strictly separated:

1. **A GC expression config** (``retention.yaml`` at the domain root) over the only
   two dates that matter — the source's **posting date** and *our* **last-observed
   date**. Per-tier rules combine independent day-threshold filters with ``all_of``
   (AND, the default), ``any_of`` (OR), or a single filter; a tier may also be
   ``never``. Tier membership is by manifest ``operation`` (``scrape`` →
   ``aggregator_sweeps``; ``board`` / ``search`` / ``jd`` and anything unknown →
   the conservative ``boards_and_jds``). A MISSING config = everything ``never``
   (GC is strictly opt-in), and a tier the config does not mention = ``never``.

2. **A reference-counted sweep.** Manifests are NEVER pruned (they are the
   observation log). A payload blob is deletable only when EVERY manifest that
   references it is in a prunable tier AND past that tier's dates — any keep-class
   reference vetoes. Reference counts are computed at sweep time, never cached.

3. **Frozen facts.** Before a blob that feeds a materialized entity is pruned, that
   entity's source-derived facts are snapshotted to
   ``state/frozen-facts/<entity-key>.yaml`` via the canonical serializer, so a
   later rebuild that hits pruned raw carries the entity forward (the explicit,
   bounded exception to "everything re-derives from raw") instead of a data hole.

Execution order per candidate blob is strict and crash-safe: frozen-facts →
tombstone → delete. A crash between the last two leaves blob-present-plus-tombstone,
which :meth:`BlobStore.state` still reads as ``present`` (re-sweepable, never
``corrupt``). This module is store-generic; the jobs builder supplies nothing here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from . import serialization
from .atomic import atomic_write_text, read_jsonl
from .blobs import BlobStore, PRESENT, PRUNED, ext_for_content_type
from .manifest import audit_refcounts, is_group_manifest, iter_manifests
from .paths import DomainLayout

# ── config vocabulary ────────────────────────────────────────
RETENTION_FILENAME = "retention.yaml"
FROZEN_FACTS_SCHEMA_VERSION = 1

# The ONLY two filter keys the language accepts (an unknown key is a loud error).
POSTING_FILTER = "posting_date_older_than_days"
OBSERVED_FILTER = "last_observed_older_than_days"
FILTER_KEYS = frozenset({POSTING_FILTER, OBSERVED_FILTER})

# Manifest operation → retention tier. ``scrape`` is aggregator sweep output;
# everything else (and anything unknown) falls to the conservative high-value tier.
OPERATION_TIERS = {
    "scrape": "aggregator_sweeps",
    "board": "boards_and_jds",
    "search": "boards_and_jds",
    "jd": "boards_and_jds",
    "group": "boards_and_jds",
}
DEFAULT_TIER = "boards_and_jds"

# Combinator keys.
ALL_OF = "all_of"
ANY_OF = "any_of"
NEVER = "never"


class RetentionError(ValueError):
    """A ``retention.yaml`` is malformed (bad combinator, unknown filter key, …)."""


# ── date helpers ─────────────────────────────────────────────
def parse_dt(value) -> datetime | None:
    """Parse a store timestamp to an aware UTC datetime, tolerant of the shapes we
    actually store: canonical ``...Z``, ISO with an explicit offset
    (``2026-07-18T07:24:14+00:00``, how source posting dates land), and a bare
    ``YYYY-MM-DD``. Returns ``None`` for anything unparseable or empty.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return serialization.parse_z(text)
    except ValueError:
        pass
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _older_than(dt: datetime | None, now: datetime, days: int) -> bool:
    """``dt`` is strictly older than ``days`` before ``now`` (unknown dates are NOT
    older — a filter can never fire on a date we do not have; conservative keep)."""
    if dt is None:
        return False
    return (now - dt) > timedelta(days=days)


# ── the rule language ────────────────────────────────────────
@dataclass(frozen=True)
class Filter:
    """One day-threshold filter over one of the two dates."""

    key: str
    days: int

    def matches(self, posting_date: datetime | None,
                last_observed: datetime | None, now: datetime) -> bool:
        date = posting_date if self.key == POSTING_FILTER else last_observed
        return _older_than(date, now, self.days)

    def describe(self) -> str:
        which = "posting date" if self.key == POSTING_FILTER else "last-observed"
        return f"{which} older than {self.days}d"


@dataclass(frozen=True)
class Rule:
    """A tier's ``prune_blobs_when`` — ``never`` or a combinator over filters."""

    kind: str  # NEVER | ALL_OF | ANY_OF
    filters: tuple[Filter, ...] = ()

    @property
    def is_never(self) -> bool:
        return self.kind == NEVER

    def matches(self, posting_date: datetime | None,
                last_observed: datetime | None, now: datetime) -> bool:
        if self.kind == NEVER or not self.filters:
            return False
        results = [f.matches(posting_date, last_observed, now) for f in self.filters]
        return all(results) if self.kind == ALL_OF else any(results)

    def describe(self) -> str:
        if self.kind == NEVER:
            return "never"
        joiner = " AND " if self.kind == ALL_OF else " OR "
        return joiner.join(f.describe() for f in self.filters)


NEVER_RULE = Rule(NEVER)


@dataclass
class RetentionConfig:
    """Parsed ``retention.yaml`` — tier name → :class:`Rule`."""

    tiers: dict[str, Rule] = field(default_factory=dict)

    def rule_for_tier(self, tier: str) -> Rule:
        # A tier the config does not mention is ``never`` (conservative keep).
        return self.tiers.get(tier, NEVER_RULE)

    def rule_for_operation(self, operation: str) -> Rule:
        return self.rule_for_tier(OPERATION_TIERS.get(operation, DEFAULT_TIER))

    @property
    def is_opt_in_only(self) -> bool:
        """True when nothing is prunable (no config, or every tier is ``never``)."""
        return all(r.is_never for r in self.tiers.values())


def _parse_filter(obj, where: str) -> Filter:
    if not isinstance(obj, dict) or len(obj) != 1:
        raise RetentionError(
            f"{where}: a filter must be a single-key mapping "
            f"({sorted(FILTER_KEYS)}), got {obj!r}")
    (key, days), = obj.items()
    if key not in FILTER_KEYS:
        raise RetentionError(
            f"{where}: unknown filter key {key!r}; allowed keys are "
            f"{sorted(FILTER_KEYS)}")
    if not isinstance(days, int) or isinstance(days, bool) or days < 0:
        raise RetentionError(
            f"{where}: {key} must be a non-negative integer number of days, "
            f"got {days!r}")
    return Filter(key=key, days=days)


def _parse_rule(spec, tier: str) -> Rule:
    where = f"tiers.{tier}.prune_blobs_when"
    if spec == NEVER:
        return NEVER_RULE
    if not isinstance(spec, dict):
        raise RetentionError(
            f"{where}: expected 'never', a single filter, or an "
            f"{{{ALL_OF}|{ANY_OF}: [...]}} block, got {spec!r}")
    has_all = ALL_OF in spec
    has_any = ANY_OF in spec
    if has_all and has_any:
        raise RetentionError(f"{where}: cannot combine {ALL_OF} and {ANY_OF}")
    if has_all or has_any:
        if len(spec) != 1:
            raise RetentionError(
                f"{where}: a combinator block holds only "
                f"{ALL_OF!r}/{ANY_OF!r}, got extra keys {sorted(spec)}")
        kind = ALL_OF if has_all else ANY_OF
        items = spec[kind]
        if not isinstance(items, list) or not items:
            raise RetentionError(f"{where}.{kind}: must be a non-empty list of filters")
        filters = tuple(_parse_filter(it, f"{where}.{kind}[{i}]")
                        for i, it in enumerate(items))
        return Rule(kind=kind, filters=filters)
    # A single-filter mapping (implicitly all_of over one filter).
    return Rule(kind=ALL_OF, filters=(_parse_filter(spec, where),))


def parse_config(data) -> RetentionConfig:
    """Parse a ``retention.yaml`` document (a dict, or ``None`` = empty config)."""
    if data is None:
        return RetentionConfig()
    if not isinstance(data, dict):
        raise RetentionError(f"retention config must be a mapping, got {type(data).__name__}")
    tiers_raw = data.get("tiers")
    if tiers_raw is None:
        return RetentionConfig()
    if not isinstance(tiers_raw, dict):
        raise RetentionError("tiers: must be a mapping of tier-name → rule")
    tiers: dict[str, Rule] = {}
    for tier, tier_spec in tiers_raw.items():
        if not isinstance(tier_spec, dict) or "prune_blobs_when" not in tier_spec:
            raise RetentionError(
                f"tiers.{tier}: must be a mapping with a 'prune_blobs_when' key")
        tiers[tier] = _parse_rule(tier_spec["prune_blobs_when"], tier)
    return RetentionConfig(tiers=tiers)


def config_path(layout: DomainLayout) -> Path:
    return layout.root / RETENTION_FILENAME


def load_config(layout: DomainLayout) -> RetentionConfig:
    """Load the domain's ``retention.yaml`` (missing file = empty = everything never)."""
    path = config_path(layout)
    if not path.exists():
        return RetentionConfig()
    data = serialization.loads_yaml(path.read_text(encoding="utf-8"))
    return parse_config(data)


# ── entity + blob indexing ───────────────────────────────────
@dataclass
class EntityFacts:
    """One materialized derived entity's GC-relevant projection."""

    key: str
    entity_dir: Path
    entity_yaml: Path
    entity: dict
    posted_at: datetime | None
    fetch_ids: tuple[str, ...]


def _entity_posted_at(entity: dict) -> datetime | None:
    facts = entity.get("facts") if isinstance(entity.get("facts"), dict) else {}
    return parse_dt(facts.get("posted_at") or entity.get("posted_at"))


def build_entity_index(layout: DomainLayout) -> dict[str, EntityFacts]:
    """Scan ``derived/`` for materialized entities (a YAML with ``key`` + provenance).

    Store-generic: any entity current-state YAML whose parsed dict carries a ``key``
    and a ``provenance.fetch_ids`` list is indexed (the jobs builder writes
    ``posting.yaml``). Used to map a blob to the entities it feeds and to their
    posting dates.
    """
    out: dict[str, EntityFacts] = {}
    derived = layout.derived
    if not derived.is_dir():
        return out
    for yaml_path in sorted(derived.rglob("*.yaml")):
        try:
            data = serialization.loads_yaml(yaml_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        key = data.get("key")
        prov = data.get("provenance")
        if not key or not isinstance(prov, dict):
            continue
        fetch_ids = tuple(prov.get("fetch_ids") or ())
        out[key] = EntityFacts(
            key=key, entity_dir=yaml_path.parent, entity_yaml=yaml_path,
            entity=data, posted_at=_entity_posted_at(data), fetch_ids=fetch_ids)
    return out


@dataclass
class BlobRefs:
    """Every manifest reference to one payload blob, plus its derived last-observed."""

    sha: str
    ext: str | None
    operations: tuple[str, ...]
    fetch_ids: tuple[str, ...]
    last_observed: datetime | None


def build_blob_index(layout: DomainLayout) -> dict[str, BlobRefs]:
    """Map each referenced blob sha → its manifest references (op, fetch, observed)."""
    ops: dict[str, list[str]] = {}
    fids: dict[str, list[str]] = {}
    observed: dict[str, datetime | None] = {}
    ext: dict[str, str] = {}
    for _path, env in iter_manifests(layout):
        if is_group_manifest(env):
            continue
        payload = env.get("payload")
        if not (isinstance(payload, dict) and payload.get("blob")):
            continue
        sha = payload["blob"]
        ops.setdefault(sha, []).append(env.get("operation", ""))
        fid = env.get("fetch_id")
        if fid:
            fids.setdefault(sha, []).append(fid)
        ext.setdefault(sha, ext_for_content_type(payload.get("content_type")))
        dt = parse_dt(env.get("fetched_at"))
        if dt is not None:
            prev = observed.get(sha)
            if prev is None or dt > prev:
                observed[sha] = dt
    return {
        sha: BlobRefs(sha=sha, ext=ext.get(sha),
                      operations=tuple(ops[sha]), fetch_ids=tuple(fids.get(sha, ())),
                      last_observed=observed.get(sha))
        for sha in ops
    }


# ── the sweep plan ───────────────────────────────────────────
@dataclass
class Candidate:
    """A blob that qualifies for pruning, with the evidence for the report."""

    sha: str
    ext: str | None
    tier: str
    disk_bytes: int
    last_observed: datetime | None
    posting_date: datetime | None
    fed_entity_keys: tuple[str, ...]
    reason: str


@dataclass
class DebrisDir:
    path: Path
    age_hours: float


@dataclass
class SweepPlan:
    layout: DomainLayout
    config: RetentionConfig
    now: datetime
    candidates: list[Candidate] = field(default_factory=list)
    vetoed: int = 0
    tier_counts: dict[str, int] = field(default_factory=dict)
    orphans: list[str] = field(default_factory=list)
    debris: list[DebrisDir] = field(default_factory=list)
    pruned_pending: list[str] = field(default_factory=list)
    # The derived entity index at plan time. Derived cannot change between plan and
    # execute (the builder lock is held), so execute reuses this for freezing rather
    # than re-walking derived/ — only manifests (lock-free capture) are re-read.
    entities: dict[str, EntityFacts] = field(default_factory=dict)

    @property
    def disk_bytes(self) -> int:
        return sum(c.disk_bytes for c in self.candidates)

    @property
    def frozen_entity_keys(self) -> list[str]:
        keys: set[str] = set()
        for c in self.candidates:
            keys.update(c.fed_entity_keys)
        return sorted(keys)


def _blob_disk_bytes(blobstore: BlobStore, sha: str, ext: str | None) -> int:
    path = blobstore.path_for(sha, ext) if ext else blobstore.find(sha)
    if path is not None and path.exists():
        return path.stat().st_size
    return 0


def find_debris_dirs(layout: DomainLayout, *, now: datetime | None = None,
                     max_age_hours: float = 24.0) -> list[DebrisDir]:
    """Manifest-less fetch directories under ``raw/<source>/`` older than 24h.

    Scope is ``raw/<source>/`` ONLY — never ``state/``, never ``_blobs/`` (a fetch
    dir holds exactly a ``manifest.json``; its absence past the window is crash
    debris). Age comes from the dir mtime. Reported in dry-run, removed under execute.
    """
    now = now or datetime.now(timezone.utc)
    raw = layout.raw
    out: list[DebrisDir] = []
    if not raw.is_dir():
        return out
    # raw/<source>/YYYY/MM/DD/<fetch-id>/ — the fetch-dir depth.
    for fetch_dir in sorted(raw.glob("*/*/*/*/*")):
        if not fetch_dir.is_dir() or "_blobs" in fetch_dir.parts:
            continue
        if (fetch_dir / "manifest.json").exists():
            continue
        age_hours = (now.timestamp() - fetch_dir.stat().st_mtime) / 3600.0
        if age_hours >= max_age_hours:
            out.append(DebrisDir(path=fetch_dir, age_hours=age_hours))
    return out


def _fetch_to_entities(entities: dict[str, EntityFacts]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for key, ef in entities.items():
        for fid in ef.fetch_ids:
            out.setdefault(fid, set()).add(key)
    return out


def _evaluate_blob(refs: BlobRefs, fetch_to_entities: dict[str, set[str]],
                   entities: dict[str, EntityFacts], config: RetentionConfig,
                   now: datetime) -> tuple[bool, datetime | None, tuple[str, ...], str, str]:
    """Decide whether ``refs``'s blob is deletable, returning the evidence too.

    Shared by :func:`plan_sweep` and the execute-time re-check so both apply the
    IDENTICAL rule: a blob is deletable only if EVERY referencing manifest is in a
    prunable tier AND past its dates — any keep-class (``never``) reference, or any
    not-yet-past one, vetoes. Returns ``(deletable, posting_date, fed_keys, tier, reason)``.
    """
    fed = tuple(sorted({k for fid in refs.fetch_ids
                        for k in fetch_to_entities.get(fid, ())}))
    posting_dates = [entities[k].posted_at for k in fed
                     if entities[k].posted_at is not None]
    posting_date = max(posting_dates) if posting_dates else None
    deletable = True
    for op in refs.operations:
        rule = config.rule_for_operation(op)
        if rule.is_never or not rule.matches(posting_date, refs.last_observed, now):
            deletable = False
            break
    tier = OPERATION_TIERS.get(refs.operations[0], DEFAULT_TIER)
    reason = config.rule_for_operation(refs.operations[0]).describe()
    return deletable, posting_date, fed, tier, reason


def plan_sweep(layout: DomainLayout, blobstore: BlobStore,
               config: RetentionConfig, *, now: datetime | None = None) -> SweepPlan:
    """Compute the full sweep plan (pure read — mutates nothing)."""
    now = now or datetime.now(timezone.utc)
    plan = SweepPlan(layout=layout, config=config, now=now)

    entities = build_entity_index(layout)
    fetch_to_entities = _fetch_to_entities(entities)

    blob_index = build_blob_index(layout)
    for sha, refs in sorted(blob_index.items()):
        state = blobstore.state(sha, refs.ext)
        pending = blobstore.is_pruned_pending(sha, refs.ext)
        if pending:
            plan.pruned_pending.append(sha)
        # We can only reclaim bytes that are actually here (present, incl. pending).
        if state not in (PRESENT,) and not pending:
            continue

        deletable, posting_date, fed, tier, reason = _evaluate_blob(
            refs, fetch_to_entities, entities, config, now)
        if not deletable:
            plan.vetoed += 1
            continue

        plan.candidates.append(Candidate(
            sha=sha, ext=refs.ext, tier=tier,
            disk_bytes=_blob_disk_bytes(blobstore, sha, refs.ext),
            last_observed=refs.last_observed, posting_date=posting_date,
            fed_entity_keys=fed, reason=reason))
        plan.tier_counts[tier] = plan.tier_counts.get(tier, 0) + 1

    # Orphans (present blobs referenced by no manifest) — reported; removal is gated.
    plan.orphans = list(audit_refcounts(layout, blobstore)["orphans"])
    plan.debris = find_debris_dirs(layout, now=now)
    plan.entities = entities  # reused by execute_sweep (derived is lock-frozen)
    return plan


# ── frozen facts ─────────────────────────────────────────────
def frozen_facts_dir(layout: DomainLayout) -> Path:
    return layout.state / "frozen-facts"


def frozen_facts_path(layout: DomainLayout, key: str) -> Path:
    return frozen_facts_dir(layout) / f"{key}.yaml"


def snapshot_entity(ef: EntityFacts) -> dict:
    """Build the frozen-facts snapshot for one materialized entity.

    Captures the source-derived facts (the entity YAML) plus the large sibling
    artifacts (``jd.md`` and any content-versioned ``jd-*.md``) and the event log,
    so a rebuild on a machine where the raw blob was pruned reconstructs the FULL
    entity — not a husk. ``frozen_at`` is the entity's ``last_seen`` (deterministic,
    so re-snapshotting is byte-stable), falling back to a wall clock only if absent.
    """
    entity = ef.entity
    files: dict[str, str] = {}
    for sibling in sorted(ef.entity_dir.glob("jd*.md")):
        files[sibling.name] = sibling.read_text(encoding="utf-8")
    events = read_jsonl(ef.entity_dir / "events.jsonl")
    frozen_at = entity.get("last_seen") or serialization.now_z()
    snapshot = {
        "schema_version": FROZEN_FACTS_SCHEMA_VERSION,
        "key": ef.key,
        "frozen_at": frozen_at,
        "entity": entity,
        "events": events,
    }
    if files:
        snapshot["files"] = files
    return snapshot


def write_frozen_facts(layout: DomainLayout, snapshot: dict) -> Path:
    """Atomically write one frozen-facts snapshot (canonical YAML)."""
    path = frozen_facts_path(layout, snapshot["key"])
    atomic_write_text(path, serialization.dumps_yaml(snapshot))
    return path


def load_frozen_facts(layout: DomainLayout) -> dict[str, dict]:
    """Return ``{entity_key: snapshot}`` for every frozen-facts file."""
    out: dict[str, dict] = {}
    fdir = frozen_facts_dir(layout)
    if not fdir.is_dir():
        return out
    for path in sorted(fdir.glob("*.yaml")):
        data = serialization.loads_yaml(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("key"):
            out[data["key"]] = data
    return out


def load_frozen_fact(layout: DomainLayout, key: str) -> dict | None:
    path = frozen_facts_path(layout, key)
    if not path.exists():
        return None
    data = serialization.loads_yaml(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) and data.get("key") else None


# ── execution ────────────────────────────────────────────────
@dataclass
class ExecResult:
    frozen_written: int = 0
    tombstoned: int = 0
    deleted: int = 0
    disk_bytes_reclaimed: int = 0
    debris_removed: int = 0
    orphans_removed: int = 0
    re_vetoed: int = 0  # candidates a mid-sweep capture newly vetoed (skipped, safe)


def execute_sweep(plan: SweepPlan, blobstore: BlobStore, *,
                  remove_orphans: bool = False, sweep_debris: bool = True) -> ExecResult:
    """Perform the plan: frozen-facts → tombstone → delete, per candidate blob.

    Strict per-blob order gives crash-safety (a crash never leaves a blob deleted
    without its frozen facts, nor a tombstone without a still-safe present blob).
    Debris removal is scoped to ``raw/<source>/``; orphan removal is opt-in.

    Fetchers are lock-free by design, so a capture can add a reference to a candidate
    blob between plan and execute. As cheap defense-in-depth, the plan-time veto is
    RE-VERIFIED against the manifests on disk immediately before each delete (the
    store is re-read here); a blob that gained a keep-class reference or a newer
    last-observed since the plan is skipped this sweep and counted in ``re_vetoed``.
    """
    layout = plan.layout
    result = ExecResult()
    # Derived is lock-frozen (the builder lock is held), so reuse the plan's entity
    # index for freezing + posting dates. Only the MANIFESTS are re-read here, so a
    # mid-sweep lock-free capture (a new keep-class reference or a newer last-observed)
    # is caught — a cheap re-scan, not a second full derived walk.
    entities = plan.entities or build_entity_index(layout)
    fetch_to_entities = _fetch_to_entities(entities)
    blob_index = build_blob_index(layout)
    frozen_this_sweep: set[str] = set()

    for cand in plan.candidates:
        refs = blob_index.get(cand.sha)
        if refs is None:
            result.re_vetoed += 1  # no longer referenced — leave it to the orphan path
            continue
        deletable, _pd, fed, tier, _reason = _evaluate_blob(
            refs, fetch_to_entities, entities, plan.config, plan.now)
        if not deletable:
            result.re_vetoed += 1  # a mid-sweep capture re-vetoed it — skip, blob survives
            continue
        # (3) freeze every materialized entity this blob feeds — BEFORE the tombstone.
        # An entity fed by several candidate blobs is frozen once per sweep (the
        # snapshot is identical), but ALWAYS before the first of its blobs is deleted,
        # so crash-safety holds: no blob is ever deleted before its facts are frozen.
        for key in fed:
            if key in frozen_this_sweep:
                continue
            ef = entities.get(key)
            if ef is None:
                continue
            write_frozen_facts(layout, snapshot_entity(ef))
            frozen_this_sweep.add(key)
            result.frozen_written += 1
        # (4) tombstone, then (5) delete — the order :meth:`state` depends on.
        blobstore.write_tombstone(cand.sha, reason=f"retention:{tier}",
                                  meta={"last_observed": _z(refs.last_observed),
                                        "posting_date": _z(cand.posting_date)})
        result.tombstoned += 1
        if blobstore.delete(cand.sha, refs.ext):
            result.deleted += 1
            result.disk_bytes_reclaimed += cand.disk_bytes

    if sweep_debris:
        import shutil
        for d in plan.debris:
            if "_blobs" in d.path.parts or layout.state in d.path.parents:
                continue  # belt-and-braces: never state/, never _blobs/
            shutil.rmtree(d.path, ignore_errors=True)
            result.debris_removed += 1

    if remove_orphans:
        for sha in plan.orphans:
            if blobstore.delete(sha):
                result.orphans_removed += 1

    return result


def _z(dt: datetime | None) -> str | None:
    return serialization.to_z(dt) if dt is not None else None


# ── convenience for callers that want the whole story ────────
def sweep(layout: DomainLayout, blobstore: BlobStore, config: RetentionConfig, *,
          now: datetime | None = None, execute: bool = False,
          remove_orphans: bool = False) -> tuple[SweepPlan, ExecResult | None]:
    """Plan, and (when ``execute``) perform, one sweep. Returns ``(plan, result)``."""
    plan = plan_sweep(layout, blobstore, config, now=now)
    if not execute:
        return plan, None
    result = execute_sweep(plan, blobstore, remove_orphans=remove_orphans)
    return plan, result


def iter_referenced_entities(entities: dict[str, EntityFacts],
                             keys: Iterable[str]) -> Iterable[EntityFacts]:
    for key in keys:
        ef = entities.get(key)
        if ef is not None:
            yield ef
