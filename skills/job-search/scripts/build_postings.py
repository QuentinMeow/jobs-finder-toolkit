"""build_postings.py — the job-postings store builder (Stage 2, committed core).

Reads the raw zone (never writes it), materializes one derived entity per posting,
and regenerates the index — deterministically, so a rebuild is byte-identical and
an incremental build equals a full rebuild. Three modes:

* **incremental** (default): process the ledger set-difference under the builder
  lock. Normally this folds ONLY the pending manifests into per-entity state
  persisted in ``state/postings-fold-cache.jsonl``, so the run costs O(new
  manifests) rather than O(store) — see
  ``docs/designs/raw-data-layer/05-incremental-build.md``. When anything that
  state does not model has moved (a changed code fingerprint, a pruned blob, an
  out-of-order capture, a drifted derived zone, …) the run falls back to the
  whole-raw-zone fold — recompute every entity from its full manifest history,
  write only the ones whose bytes changed, regenerate index/triage/README
  wholesale. Both paths produce identical bytes; the fallback is only slower.
* ``--rebuild``: build derived+index ASIDE into fresh dirs, verify (schemas,
  counts, 100% annotation joins, an incremental-equals-rebuild spot check), then
  atomically swap. Never touches ``annotations/`` or ``state/`` except the ledger.
* ``--opinions-only``: re-run the classifiers over STORED facts (no raw re-read)
  and print a diff report ("N postings changed visa yes→no") — the payoff of the
  facts/opinions split.

Determinism pins (store-core contract): every timestamp derives from manifest
fetch times; the index header's ``built_at`` is the ledger-head fetch time (never
wall clock); everything is written through the store's canonical serializer;
opinion/provenance version stamps are 8-hex content hashes of the stamping module
file (work on uncommitted trees, deterministic for identical code).

Observations only — first_seen / seen / changed. NO closed/disappeared inference:
the store never says "closed"; postings carry last_seen staleness only.

The committed ``index/postings.jsonl`` is itself a durable floor: index regeneration
is a deterministic union of every entity built this run with pre-existing index-only
rows that have no current entity, no derived on disk, and no tombstone (see
``_carry_forward_from_index``) — "missing derived is as normal as missing raw." Those
survivors are preserved verbatim at their original ``seq`` and marked
``carried``/``carried_from: index``; they are never materialized as fabricated
derived artifacts, and ``by-day``/``triage`` stay event-derived from this run's
entities only. **The floor is enforced at the single writer**
(``_write_postings_index``), which every build path — incremental fast, incremental
full, ``--rebuild``, ``--opinions-only`` — goes through, because those rows are the
only surviving record of their postings and no path may forget them.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

_SKILL_SCRIPTS = Path(__file__).resolve().parent
for _p in (str(_SKILL_SCRIPTS), str(_SKILL_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # vendored toolkit config loader  # noqa: E402
import job_metadata  # vendored classifier machinery  # noqa: E402
import location as location_mod  # vendored location classifier  # noqa: E402
import posting_identity as ident  # noqa: E402
import posting_parsers as parsers  # noqa: E402
import postings_fold_state as fold_state  # persisted per-entity fold state  # noqa: E402
import visa as visa_mod  # noqa: E402
from _vendor.store import serialization  # noqa: E402
from _vendor.store.annotations import (AnnotationOrphanError, assert_no_orphans,  # noqa: E402
                                       load_annotations)
from _vendor.store.atomic import append_line, atomic_write_text, read_jsonl  # noqa: E402
from _vendor.store.blobs import BlobCorrupt, BlobStore, ext_for_content_type  # noqa: E402
from _vendor.store.keyregistry import KeyRegistry  # noqa: E402
from _vendor.store.ledger import BuildLedger, check_clock_monotonic, pending_manifests  # noqa: E402
from _vendor.store.locking import DomainLock, LockContention  # noqa: E402
from _vendor.store.manifest import iter_manifests  # noqa: E402
from _vendor.store.paths import detect_case_collision, domain_layout, validate_slug  # noqa: E402
from _vendor.store.retention import load_frozen_facts  # noqa: E402
from _vendor.store.validation import load_schema, validate as schema_validate  # noqa: E402
from registry import Registry, _slugify, load_registry  # noqa: E402

DOMAIN = "jobs"
POSTING_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
INDEX_NOTE = ("store-derived — machine-generated; do NOT cat into context or paste "
              "into any public surface. Use query_postings.py.")

# Fields whose change between consecutive observations emits a `changed` event.
_TRACKED = ("title", "location", "url", "workplace_raw", "salary_text",
            "salary_range", "posted_at", "jd_hash")

# Cheap pre-gate for the (expensive, per-call regex-compiling) visa classifier.
# A SUPERSET of every trigger token in job_metadata's sponsorship phrase lists: a
# JD with none of these can only classify "unclear" (the classifier finds no
# negative/positive matches and returns "unknown"), so skipping it is exact, not
# approximate — it just avoids ~58 regex compiles over JDs with no visa language.
_VISA_HINT_RE = re.compile(
    r"sponsor|visa|immigration|work\s*authoriz|authorized\s+to\s+work|"
    r"h-?1b|green\s*card|permanent\s+resid|\bperm\b|cap[-\s]exempt|"
    r"citizen|i-140|\bgc\b|relocation",
    re.I)

# The pre-gate MUST remain a SUPERSET of every sponsorship phrase token, or a gated
# JD could be silently misclassified. Assert it at import so a future phrase added
# to the classifier that escapes the gate fails the build loudly (not silently).
_UNCAUGHT_SPONSOR_PHRASES = [
    p for p in (job_metadata._SPONSOR_NEGATIVE + job_metadata._SPONSOR_POSITIVE)
    if not _VISA_HINT_RE.search(p)]
assert not _UNCAUGHT_SPONSOR_PHRASES, (
    "visa pre-gate _VISA_HINT_RE misses sponsorship phrase(s) — widen it: "
    f"{_UNCAUGHT_SPONSOR_PHRASES}")

# Annotation fact key -> the opinion field + the opinion's value subkey it overrides.
_ANN_FIELD_SUBKEY = {"workplace": "value", "visa": "label", "level": "value"}


class BuildError(RuntimeError):
    """A build invariant failed (case collision, orphaned annotation, verify)."""


# ── version stamps ───────────────────────────────────────────
def _module_stamp(module) -> str:
    """``<basename>@<8-hex>`` content hash of a module's source file.

    Deterministic for identical code and works on uncommitted trees (no git SHA),
    so a classifier tweak changes the stamp and ``--opinions-only`` can show it.
    """
    path = Path(getattr(module, "__file__", "") or "")
    if not path.exists():
        return f"{getattr(module, '__name__', 'unknown')}@00000000"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    return f"{path.name}@{digest}"


def _stamps() -> dict:
    return {
        "visa": _module_stamp(visa_mod),
        "job_metadata": _module_stamp(job_metadata),
        "location": _module_stamp(location_mod),
        "builder": _module_stamp(sys.modules[__name__]),
    }


# ── observations ─────────────────────────────────────────────
class Observation:
    """One parsed row from one manifest — the atom the builder folds over."""

    __slots__ = ("key", "strength", "row", "fetch_id", "fetched_at", "company",
                 "company_slug", "manifest_path", "profile")

    def __init__(self, key, strength, row, fetch_id, fetched_at, company,
                 company_slug, manifest_path, profile=None):
        self.key = key
        self.strength = strength
        self.row = row
        self.fetch_id = fetch_id
        self.fetched_at = fetched_at
        self.company = company
        self.company_slug = company_slug
        self.manifest_path = manifest_path
        self.profile = profile


def _resolve_company(env: dict, row: dict, registry: Registry):
    """Return ``(display_name, neutral_slug)`` for a row's company.

    When the registry resolves a canonical for the captured context slug, the slug
    is the SLUGIFIED CANONICAL — so three aliases of one company (three context
    slugs) all namespace to ONE key (critical for Workday ``wd-<company>-<req>``).
    The raw context slug is only the fallback when no canonical resolves; unpinned
    entities re-key freely on rebuild so the real store heals itself.
    """
    ctx = env.get("context") or {}
    ctx_slug = ctx.get("company")
    if ctx_slug:
        canonical = registry.canonical_for_slug(ctx_slug)
        if canonical:
            return canonical, (_slugify(canonical) or ctx_slug)
        return ctx_slug, ctx_slug
    display = row.get("company_name") or "unknown"
    return display, (_slugify(display) or "unknown")


def _is_structurally_foreign(location: str) -> bool:
    """Conservative structural-foreign test for tier-3 suppression.

    Uses the vendored location classifier at its most conservative: suppress only a
    decisive foreign no_match (the classifier's ``foreign`` category). When in doubt
    (unknown / mixed / US), MATERIALIZE. Title/seniority are never gates here.
    """
    if not str(location or "").strip():
        return False
    assessment = location_mod.assess_location(location, {"us_only": True,
                                                         "require_match": True})
    return assessment.category == "foreign" and assessment.decision == "no_match"


def _collect(layout, blobstore, manifests, registry):
    """Parse every member manifest into observations; collect suppressed scrape rows.

    Returns ``(observations, suppressed, notes)``. A group manifest or an absent,
    CORRUPT or unparseable blob yields nothing (missing-raw tolerance: never an
    error) — but never silently: ``notes`` carries what this run could not use, and
    :func:`_report_collect_notes` states it on stderr and in the build summary.

    **Why a corrupt blob degrades rather than fails.** This store is documented as
    living on a manually-rsynced multi-laptop setup, where a half-copied ``.zst`` is
    the ordinary shape of "the sync is still running", not an exotic event — the
    same condition as ``not-synced-here`` observed a moment earlier, and it repairs
    itself on the next sync. Raising is not the loud alternative it looks like:
    ``search_jobs.py`` catches a failed store build in one stderr line and reports
    success, and ``build_incremental`` advances the ledger and leaves its
    incomplete marker before the fold — so one torn frame would wedge the fast
    path, the full fold AND ``--rebuild`` on every future run while the pipeline
    still looked healthy. Degrading keeps an already-materialized entity alive
    through carry-forward and loses only a posting the next sync brings back.
    Recovery for one that is genuinely bit-rotted is: re-sync (or delete) the
    blob, then ``--rebuild`` — which re-reads every manifest regardless of the
    ledger. ``automation/store/validate_store.py`` names every corrupt blob.
    """
    observations: list[Observation] = []
    suppressed: list[dict] = []
    notes: dict[str, list] = {"corrupt": [], "no_rows": []}
    for path, env in manifests:
        # Store a domain-root-RELATIVE manifest path: portable across machines and
        # never an absolute home path in the (tracked) example fixture.
        try:
            rel_path = str(Path(path).relative_to(layout.root))
        except ValueError:
            rel_path = str(path)
        payload = env.get("payload")
        if not (isinstance(payload, dict) and payload.get("blob")):
            continue
        sha = payload["blob"]
        ext = ext_for_content_type(payload.get("content_type"))
        try:
            data = blobstore.read(sha, ext)
        except FileNotFoundError:
            continue  # not-synced-here / pruned — never an error
        except BlobCorrupt as exc:
            # A torn frame is transient on a synced store; degrade like an absent
            # blob, but COUNT it (see this function's docstring).
            notes["corrupt"].append({"manifest": rel_path, "sha": sha,
                                     "source": env.get("source") or "",
                                     "error": str(exc)})
            continue
        rows = parsers.parse_manifest(env, data)
        if not rows and env.get("operation") not in ("group",) \
                and env.get("kind") != "group" \
                and env.get("source") in parsers.SUPPORTED_SOURCES:
            # An implemented parser read a present payload and produced nothing.
            # `parse_manifest` swallows deliberately (one bad payload is not
            # build-fatal), but a source-wide envelope change looks exactly like an
            # empty board — same success line, same processed ledger entry, and a
            # `last_seen` that quietly stops advancing. The store cannot tell the
            # two apart from the payload alone, so it reports the count instead of
            # guessing, and the operator re-checks the live board.
            notes["no_rows"].append({"manifest": rel_path,
                                     "source": env.get("source") or "",
                                     "company": (env.get("context") or {}).get("company") or ""})
        fetch_id = env.get("fetch_id")
        fetched_at = env.get("fetched_at")
        profile = (env.get("context") or {}).get("profile")
        for row in rows:
            company, company_slug = _resolve_company(env, row, registry)
            # Tier-3 suppression: only aggregator SCRAPE rows, only decisively
            # foreign geography. Board/search rows are never suppressed.
            if row.get("operation") == "scrape" and \
                    _is_structurally_foreign(row.get("location", "")):
                suppressed.append({
                    "company": company,
                    "title": row.get("title", ""),
                    "location": row.get("location", ""),
                    "gate": "structural_foreign_location",
                    "source": row.get("source", ""),
                    "manifest": rel_path,
                    "at": fetched_at,
                })
                continue
            key, strength = ident.identify(row, company_slug=company_slug)
            observations.append(Observation(
                key=key, strength=strength, row=row, fetch_id=fetch_id,
                fetched_at=fetched_at, company=company, company_slug=company_slug,
                manifest_path=rel_path, profile=profile))
    return observations, suppressed, notes


def _sources_of(rows: list[dict]) -> str:
    """``source[:company]`` labels for a note list, deduped and bounded."""
    labels = sorted({f"{r.get('source') or '?'}"
                     + (f":{r['company']}" if r.get("company") else "")
                     for r in rows})
    head = ", ".join(labels[:5])
    return head + (f", +{len(labels) - 5} more" if len(labels) > 5 else "")


def _report_collect_notes(notes: dict) -> dict:
    """State what this run could not use; return the counters for the summary.

    Reporting only — it changes no byte of derived or index. Both counters are
    omitted when zero so a healthy build's summary line is unchanged and a
    non-zero one is unmissable.
    """
    out: dict[str, int] = {}
    corrupt = (notes or {}).get("corrupt") or []
    if corrupt:
        out["corrupt"] = len(corrupt)
        print(f"store: {len(corrupt)} manifest(s) skipped — corrupt blob "
              f"[{_sources_of(corrupt)}]; the postings they carry are NOT in this "
              f"build. Re-sync raw and run --rebuild; "
              f"automation/store/validate_store.py names every corrupt blob.",
              file=sys.stderr)
    no_rows = (notes or {}).get("no_rows") or []
    if no_rows:
        out["no_rows"] = len(no_rows)
        print(f"store: {len(no_rows)} manifest(s) produced no rows "
              f"[{_sources_of(no_rows)}] — an empty board, or a parser that no "
              f"longer matches the payload; re-check the live board.",
              file=sys.stderr)
    return out


# ── opinions ─────────────────────────────────────────────────
def _opinions(title, location, jd_text, workplace_raw, fetch_id, stamps) -> dict:
    text = jd_text or ""
    opinions: dict = {}
    try:
        if _VISA_HINT_RE.search(text):
            label, hits = visa_mod.classify_visa(text)
        else:
            label, hits = "unclear", []  # no visa language ⇒ classifier returns unclear
    except Exception:  # noqa: BLE001
        label, hits = "unclear", []
    opinions["visa"] = {"label": label, "hits": list(hits),
                        "by": stamps["visa"], "from": fetch_id}
    try:
        workplace = job_metadata.classify_workplace(location, text, workplace_raw or "")
    except Exception:  # noqa: BLE001
        workplace = "unknown"
    opinions["workplace"] = {"value": workplace, "by": stamps["job_metadata"],
                             "from": fetch_id}
    try:
        level, _signal = job_metadata.classify_level(title)
        if level == "unknown" and text:
            yoe = job_metadata.assess_required_yoe(text) or {}
            level = job_metadata.infer_level_from_yoe(yoe.get("minimum"))
    except Exception:  # noqa: BLE001
        level = "unknown"
    opinions["level"] = {"value": level, "by": stamps["job_metadata"],
                         "from": fetch_id}
    return opinions


# ── reduction ────────────────────────────────────────────────
def _z(ts: str | None) -> str:
    return ts or ""


def _obs_sort_key(o: Observation):
    return (o.fetched_at or "", o.fetch_id or "", o.row.get("native_id") or "")


def _posting_sid(row: dict) -> tuple | None:
    """``(source, native_id)`` — WHICH posting this row is, or ``None`` if unknowable.

    Only the source's own posting id can distinguish two postings that landed on
    one entity key; a row without one cannot be told apart from any other row of
    the same source, so it answers ``None`` (unknown) rather than a value that
    would compare unequal to everything.
    """
    source = row.get("source")
    native = row.get("native_id")
    if not source or not native:
        return None
    return (str(source), str(native))


def _jd_origin_of(posting: dict) -> tuple | None:
    """Read a resumed entity's ``jd.from`` back into a ``(source, id)`` sid.

    Entities written before ``jd.from`` existed simply have no such field and
    resume as ``None`` (unknown) — the conservative state, which leaves their JD
    exactly where it is until a fresh observation re-establishes the origin.
    """
    src = ((posting or {}).get("jd") or {}).get("from") or {}
    source, native = src.get("source"), src.get("id")
    if not source or not native:
        return None
    return (str(source), str(native))


class EntityBuild:
    """The computed derived artifacts for one entity (pre-serialization).

    ``fold`` carries the accumulator that produced it when — and only when — the
    entity came straight out of :class:`_Fold` over present raw. Anything that
    mutates an entity after the fold (the frozen-facts merge) or reconstructs one
    without folding at all (carry-forward, frozen reconstruction) leaves it
    ``None``, which is the incremental path's signal that this entity may not be
    continued and its arrival forces a full fold.
    """

    __slots__ = ("key", "partition", "posting", "jd_text", "jd_versions", "events",
                 "fold")

    def __init__(self, key, partition, posting, jd_text, jd_versions, events,
                 fold=None):
        self.key = key
        self.partition = partition
        self.posting = posting
        self.jd_text = jd_text
        self.jd_versions = jd_versions  # {hash: text} for prior JD versions
        self.events = events
        self.fold = fold


class _Fold:
    """The ordered accumulator one entity's observations are folded through.

    This is where the build's ONE genuinely order-dependent step lives: a
    `changed` event compares an observation against ``prior``, the immediately
    preceding observation's snapshot. Everything else the fold accumulates is
    order-insensitive in value (sets, sorted lists) or first/last-wins. Because
    the state is explicit and small, an incremental build can rehydrate it and
    continue — provided every new observation sorts AFTER the last folded one,
    which the caller proves before using this (see ``_fast_plan``).

    Both build paths fold through this same class, so a full rebuild and a
    continued fold cannot drift apart in the event semantics.
    """

    __slots__ = ("key", "source_ids", "_seen_sid", "jd_versions", "events", "prior",
                 "started", "profiles", "fetch_ids", "jd_text", "jd_origin", "last",
                 "first_at")

    def __init__(self, key: str) -> None:
        self.key = key
        self.source_ids: list[dict] = []
        self._seen_sid: set = set()
        self.jd_versions: dict = {}
        self.events: list[dict] = []
        self.prior: dict = {}
        self.started = False
        self.profiles: set = set()
        self.fetch_ids: set = set()
        self.jd_text = ""
        # WHICH posting supplied ``jd_text`` — (source, native_id). The title and
        # location come from the LATEST observation, which is normally the same
        # posting; when it is not, the entity would ship one job's title welded to
        # another job's body, so ``_finish`` needs to be able to tell. ``None``
        # means "no JD yet" and is not a posting.
        self.jd_origin: tuple | None = None
        self.last: Observation | None = None
        self.first_at = ""

    # ── rehydration (incremental path only) ──
    def resume(self, *, source_ids, profiles, fetch_ids, events, jd_text, prior,
               first_at, jd_versions=None, jd_origin=None) -> None:
        """Restore the accumulator to the end of a previously folded history.

        ``jd_versions`` stays empty for the derived-backed resume (the prior
        ``jd-*.md`` siblings are already on disk and ``_write_entity`` never
        deletes). A frozen-snapshot resume passes them, because a ``--rebuild``
        writes into a fresh dir and the snapshot is the only copy left.

        ``jd_origin`` is read back from the entity's own ``jd.from`` (derived
        expresses it, so the fold cache does not have to). A resumed fold that
        cannot recover it keeps ``None`` — unknown, so ``_finish`` leaves the JD
        alone rather than dropping a good one on a guess.
        """
        self.source_ids = [dict(s) for s in source_ids]
        self._seen_sid = {(s.get("source"), s.get("id"), s.get("url", ""))
                          for s in self.source_ids}
        self.profiles = set(profiles)
        self.fetch_ids = set(fetch_ids)
        self.events = list(events)
        self.jd_versions = dict(jd_versions or {})
        self.jd_text = jd_text
        self.jd_origin = jd_origin
        self.prior = dict(prior)
        self.first_at = first_at
        self.started = True

    def add(self, o: Observation, seq_of: dict) -> None:
        """Fold one observation in (must sort at or after every prior one)."""
        row = o.row
        sid = (row.get("source"), row.get("native_id"), row.get("url", ""))
        if sid not in self._seen_sid:
            self._seen_sid.add(sid)
            self.source_ids.append({"source": row.get("source"),
                                    "id": row.get("native_id"),
                                    "url": row.get("url", "")})
        if row.get("description"):
            self.jd_text = row["description"]
            self.jd_origin = _posting_sid(row)
        if o.profile:
            self.profiles.add(o.profile)
        self.fetch_ids.add(o.fetch_id)
        jd_hash = (parsers.content_hash(row.get("description"))
                   if row.get("description") else None)
        snap = {"title": row.get("title", ""), "location": row.get("location", ""),
                "url": row.get("url", ""), "workplace_raw": row.get("workplace_raw"),
                "salary_text": row.get("salary_text"),
                "salary_range": row.get("salary_range"),
                "posted_at": row.get("posted_at"),
                "jd_hash": jd_hash}
        seq = seq_of.get(o.fetch_id)
        base = {"entity": self.key, "fetch": o.fetch_id, "at": _z(o.fetched_at)}
        if seq is not None:
            base["seq"] = seq
        if not self.started:
            self.events.append({**base, "type": "first_seen"})
            self.first_at = _z(o.fetched_at)
            self.started = True
        else:
            self.events.append({**base, "type": "seen"})
            changes = []
            for f in _TRACKED:
                if snap.get(f) != self.prior.get(f):
                    changes.append({"field": f, "old": self.prior.get(f),
                                    "new": snap.get(f)})
            if changes:
                self.events.append({**base, "type": "changed", "changes": changes})
                # A JD text change snapshots the PRIOR JD as a content-versioned sibling.
                if any(c["field"] == "jd_hash" for c in changes) and \
                        self.prior.get("jd_hash"):
                    prev_text = self.prior.get("_jd_text")
                    if prev_text:
                        self.jd_versions[self.prior["jd_hash"]] = prev_text
        self.prior = dict(snap)
        self.prior["_jd_text"] = row.get("description") or ""
        self.last = o

    def carried_state(self) -> dict:
        """The minimal state a later build needs to continue this fold.

        ``l`` is where this fold stopped — ``(fetched_at, fetch_id)`` of the last
        observation — so a later build can CHECK, per entity, that what it is
        about to append really does come after it, rather than only trusting the
        whole-store argument in ``_fast_plan``.

        ``_jd_text`` is deliberately NOT stored: it is only ever read when
        ``jd_hash`` is set, and in exactly that case it equals the entity's
        current ``jd.md`` — so the derived file is the single copy, and ``n``
        records the one bit ``jd.md`` normalization would lose.
        """
        prior = {k: v for k, v in self.prior.items() if k != "_jd_text"}
        return {
            "l": [self.last.fetched_at or "", self.last.fetch_id or ""],
            "s": prior,
            "n": None if not self.jd_text else self.jd_text.endswith("\n"),
        }


def _finish(fold: _Fold, stamps: dict) -> EntityBuild:
    """Turn a completed accumulator into the entity's derived artifacts.

    ``title``/``location``/``company`` come from the LATEST observation — freshest
    wins, which is what a re-titled or relocated posting needs. The JD is
    different: ``_Fold.add`` keeps the last JD it was GIVEN, so an observation
    that carries no description leaves the previous one standing. For one real
    posting re-observed by a listing-only scrape that is exactly right (the JD is
    stale, not foreign). But if two DIFFERENT postings ever fold under one key,
    the same rule welds one job's title to another job's body and ships it as a
    single entity — a chimera no reader can detect.

    So the JD is kept only while it can still belong to the posting the rest of
    the entity describes: same ``(source, native_id)``, or an unknown id on either
    side (unprovable, so not disturbed). When the JD demonstrably belongs to a
    DIFFERENT posting, it is dropped and ``provenance.jd_conflict`` names both
    postings — losing a JD that is regenerable from raw beats publishing a body
    that was never this job's. When it is kept, ``jd.from`` records which posting
    supplied it, so title and body never come from different observations
    silently.

    This mutates ``fold.jd_text`` on the drop path so ``carried_state`` describes
    the artifacts actually written rather than the ones that were not.
    """
    latest = fold.last
    company = latest.company
    partition = validate_slug(_slugify(company) or "unknown", field="company partition")
    fetch_ids = sorted(fold.fetch_ids)
    latest_row = latest.row
    facts = {}
    if latest_row.get("posted_at"):
        facts["posted_at"] = latest_row["posted_at"]
    if latest_row.get("salary_text"):
        facts["salary_text"] = latest_row["salary_text"]
    if latest_row.get("salary_range"):
        facts["salary_range"] = latest_row["salary_range"]
    if latest_row.get("workplace_raw"):
        facts["workplace_raw"] = latest_row["workplace_raw"]

    # ── entity coherence: does the folded JD belong to THIS posting? ──
    latest_sid = _posting_sid(latest_row)
    jd_sid = fold.jd_origin
    jd_conflict = None
    if fold.jd_text and jd_sid is not None and latest_sid is not None \
            and jd_sid != latest_sid:
        jd_conflict = {
            "reason": "jd_from_another_posting",
            "jd_from": {"source": jd_sid[0], "id": jd_sid[1]},
            "entity_from": {"source": latest_sid[0], "id": latest_sid[1]},
        }
        fold.jd_text = ""
        fold.jd_origin = None
        jd_sid = None
    jd_text = fold.jd_text
    posting = {
        "schema_version": POSTING_SCHEMA_VERSION,
        "key": fold.key,
        "identity": latest.strength,
        "company": company,
        "title": latest_row.get("title", ""),
        "location": latest_row.get("location", ""),
        "source_ids": fold.source_ids,
        "profiles": sorted(fold.profiles),
        "first_seen": _z(fold.first_at),
        "last_seen": _z(latest.fetched_at),
        "facts": facts,
        "opinions": _opinions(latest_row.get("title", ""), latest_row.get("location", ""),
                              jd_text, latest_row.get("workplace_raw"),
                              fetch_ids[-1], stamps),
        "provenance": {
            "built_by": stamps["builder"],
            "fetch_ids": fetch_ids,
            "normalizer_version": parsers.NORMALIZER_VERSION,
            "canonicalizer_version": ident.CANONICALIZER_VERSION,
        },
    }
    if jd_conflict is not None:
        posting["provenance"]["jd_conflict"] = jd_conflict
    if jd_text:
        posting["jd"] = {
            "file": "jd.md",
            "content_hash": parsers.content_hash(jd_text),
            "normalizer_version": parsers.NORMALIZER_VERSION,
            "fetched_verbatim": True,
        }
        if jd_sid is not None:
            # Which posting the body came from — the title above may be a LATER
            # observation's, and this is what says so.
            posting["jd"]["from"] = {"source": jd_sid[0], "id": jd_sid[1]}
    return EntityBuild(fold.key, partition, posting, jd_text, fold.jd_versions,
                       fold.events, fold.carried_state())


def _reduce(key, obs_list, seq_of, stamps, frozen=None) -> EntityBuild | None:
    """Fold one entity's observations, optionally SEEDED from a frozen snapshot.

    Returns ``None`` when a frozen snapshot already accounts for every present
    observation — the entity then *is* its snapshot, and the caller reconstructs it
    with :func:`_reconstruct_from_frozen`.
    """
    fold = _Fold(key)
    obs = sorted(obs_list, key=_obs_sort_key)
    resumed = False
    if frozen is not None:
        already = _resume_from_frozen(fold, frozen, {o.fetch_id for o in obs})
        if already is not None:
            resumed = True
            obs = [o for o in obs if o.fetch_id not in already]
    for o in obs:
        fold.add(o, seq_of)
    if fold.last is None:
        return None
    eb = _finish(fold, stamps)
    if resumed:
        prov = eb.posting.setdefault("provenance", {})
        prov["carried"] = True
        prov["frozen"] = True
        # Its history reaches outside the raw this machine holds, so a later
        # incremental build may not continue this fold.
        eb.fold = None
    return eb


# ── migration + duplicate post-pass ──────────────────────────
# Map an entity key's platform prefix to the registry ATS name so a declared
# `previous: [{ats: greenhouse, ...}]` record matches a `gh-<id>` key.
_KEY_PREFIX_ATS = {"gh": "greenhouse", "ashby": "ashby", "lever": "lever",
                   "sr": "smartrecruiters", "wd": "workday"}


def _ats_of(key: str) -> str:
    prefix = key.split("-", 1)[0] if "-" in key else key
    return _KEY_PREFIX_ATS.get(prefix, prefix)


def _post_pass(entities: dict, registry: Registry) -> None:
    """Apply declared ATS-migration links and exact-duplicate hints (deterministic).

    A migration record LICENSES a `migrated_from` link across one ATS boundary
    (same company + normalized title + JD content hash). Exact cross-key matches
    without a licensing record become `possible_duplicate` hints — never a merge.
    """
    # index entities by (company, normalized title, jd hash)
    triples: dict[tuple, list[str]] = {}
    for key, eb in entities.items():
        p = eb.posting
        jd_hash = (p.get("jd") or {}).get("content_hash")
        if not jd_hash:
            continue
        triple = (ident._norm_company(p.get("company", "")),
                  ident._norm_title(p.get("title", "")), jd_hash)
        triples.setdefault(triple, []).append(key)

    for triple, keys in triples.items():
        if len(keys) < 2:
            continue
        keys = sorted(keys)
        for key in keys:
            eb = entities[key]
            others = [k for k in keys if k != key]
            licensed = None
            for rec in registry.migration_records(eb.posting.get("company")):
                prev_ats = str(rec.get("ats") or "").lower()
                for other in others:
                    if _ats_of(other) == prev_ats and _ats_of(key) != prev_ats:
                        licensed = {"key": other, "ats": prev_ats,
                                    "token": rec.get("token"), "until": rec.get("until"),
                                    "first_seen": entities[other].posting.get("first_seen")}
            if licensed is not None:
                eb.posting["migrated_from"] = licensed
            else:
                hints = sorted(others)
                if hints:
                    eb.posting["possible_duplicate"] = hints


# ── serialization + writing ──────────────────────────────────
def _read_derived_text(path: Path) -> str:
    """Read a derived text file EXACTLY as it was written (no newline translation).

    `atomic_write_text` writes `text.encode("utf-8")`, so the only read that can
    round-trip it is a byte read. `Path.read_text()` applies universal-newline
    translation, which silently rewrites a CRLF the payload really contains — a
    difference the contract "an incremental build produces the rebuild's bytes"
    cannot tolerate anywhere derived is read back and re-serialized.
    """
    path = Path(path)
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def _entity_files(eb: EntityBuild) -> dict[str, str]:
    """Map of ``relative-path -> text`` for an entity's derived files."""
    files = {
        "posting.yaml": serialization.dumps_yaml(eb.posting),
        "events.jsonl": "".join(serialization.dumps_jsonl_line(e) for e in eb.events),
    }
    if eb.jd_text:
        files["jd.md"] = eb.jd_text if eb.jd_text.endswith("\n") else eb.jd_text + "\n"
    for h, text in sorted(eb.jd_versions.items()):
        files[f"jd-{h[:12]}.md"] = text if text.endswith("\n") else text + "\n"
    return files


def _entity_dir(derived_root: Path, eb: EntityBuild) -> Path:
    return derived_root / "postings" / eb.partition / eb.key


def _partition_index(derived_root: Path) -> dict[str, set[str]]:
    """``{entity key: {partition, ...}}`` for the derived entity dirs on disk NOW.

    Snapshotted ONCE per build and handed to every :func:`_write_entity` call, so
    the stale-partition sweep costs a dict lookup per entity rather than a
    directory listing per entity. A snapshot taken before the write loop is exact
    for the whole loop: an entity key is unique within a build, so writing entity
    K can never add a directory for any other key.
    """
    postings_root = Path(derived_root) / "postings"
    if not postings_root.is_dir():
        return {}
    out: dict[str, set[str]] = {}
    for partition in os.scandir(postings_root):
        if not partition.is_dir():
            continue
        for entity in os.scandir(partition.path):
            if entity.is_dir():
                out.setdefault(entity.name, set()).add(partition.name)
    return out


def _drop_stale_partitions(derived_root: Path, eb: EntityBuild,
                           partitions: dict[str, set[str]]) -> None:
    """Remove this entity's derived dirs at partitions it no longer belongs to.

    ``derived/postings/<company>/<key>/`` is partitioned by company, and an
    aggregator row carries no context company — its partition comes from the row's
    own ``companyName``, which the aggregator can and does change between sweeps
    ("UsCo" -> "UsCo Inc"). The key is URL-derived and unchanged, so it is the same
    entity at a NEW partition, and a writer that only ever writes leaves the key
    materialized at both. That is not merely tree drift: :func:`_carry_forward`
    iterates ``sorted(rglob("posting.yaml"))`` assigning ``out[key]``, so the
    alphabetically LAST partition wins — and once raw is not present locally, the
    orphan at the old partition silently reinstates the old company and title into
    the index, which ``validate_store`` reports as ``ok`` and no later full fold
    cleans up.

    **This is the builder's only deletion of a derived directory**, and it is
    legitimate under the "agents never delete owner data" rule: ``derived/`` is
    regenerated output, every byte removed here re-derives from ``raw/`` (or from a
    ``state/frozen-facts/`` snapshot), and ``raw/``, ``annotations/`` and
    ``state/`` are never touched. The zone check below refuses to remove anything
    that is not exactly ``<derived>/postings/<partition>/<key>``, so no partition
    string can steer the removal out of the derived postings zone.
    """
    postings_root = (Path(derived_root) / "postings").resolve()
    keep = _entity_dir(derived_root, eb)
    for partition in sorted(partitions.get(eb.key, ())):
        if partition == eb.partition:
            continue
        stale = Path(derived_root) / "postings" / partition / eb.key
        if not stale.is_dir():
            continue
        # Case-insensitive filesystems: "UsCo" and "usco" name ONE directory, and
        # on this machine it is the one just written. Compare identity, not spelling.
        if keep.is_dir() and stale.samefile(keep):
            continue
        resolved = stale.resolve()
        if resolved.parent.parent != postings_root:
            raise BuildError(
                f"refusing to remove {resolved}: not a "
                f"{postings_root}/<partition>/<key> directory")
        shutil.rmtree(resolved)
        # A rebuild never leaves an empty partition dir, so keeping one is the same
        # drift one level up. `rmdir` removes ONLY an empty directory — a partition
        # that still holds another entity raises OSError and is left alone.
        try:
            resolved.parent.rmdir()
        except OSError:
            pass


def _check_case_collisions(derived_root: Path, entities: dict) -> None:
    """Wire ``detect_case_collision`` into the derived writer (store-core case rule).

    A case-only collision would merge on Mac and fork on Linux — a build error,
    never a silent merge. Checked at both the partition and the entity-key level.
    """
    partitions: dict[str, list[str]] = {}
    for eb in entities.values():
        partitions.setdefault(eb.partition, [])
    existing_parts = list(partitions)
    for eb in entities.values():
        clash = detect_case_collision([p for p in existing_parts if p != eb.partition],
                                      eb.partition)
        if clash:
            raise BuildError(f"case-only partition collision: {eb.partition!r} vs {clash!r}")
        partitions[eb.partition].append(eb.key)
    for part, keys in partitions.items():
        for key in keys:
            clash = detect_case_collision([k for k in keys if k != key], key)
            if clash:
                raise BuildError(f"case-only key collision under {part!r}: "
                                 f"{key!r} vs {clash!r}")


def _write_entity(derived_root: Path, eb: EntityBuild, *, only_if_changed: bool,
                  partitions: dict[str, set[str]]) -> bool:
    """Write one entity's derived files, then drop its dirs at old partitions.

    ``partitions`` is the pre-loop :func:`_partition_index` snapshot and is a
    REQUIRED argument on purpose: a caller can forget an optional one, and every
    write path (both incremental folds and the rebuild's fresh aside) has to be
    swept or the store keeps forking entities that change company.
    """
    entity_dir = _entity_dir(derived_root, eb)
    files = _entity_files(eb)
    wrote = False
    for rel, text in files.items():
        target = entity_dir / rel
        # Byte comparison, not text: a text compare is newline-blind, so a JD that
        # changed only from CRLF to LF would be judged unchanged and left stale —
        # while a rebuild (writing into a fresh dir) would write the new bytes.
        if only_if_changed and target.exists() and \
                target.read_bytes() == text.encode("utf-8"):
            continue
        atomic_write_text(target, text)
        wrote = True
    _drop_stale_partitions(derived_root, eb, partitions)
    return wrote


def _index_built_at(ledger: BuildLedger) -> str:
    return _z(ledger.head_fetched_at())


def _effective(op_field: dict, subkey: str, default):
    """The human-overridden value if a human annotation set one, else the opinion."""
    if not isinstance(op_field, dict):
        return default
    if op_field.get("source") == "human" and op_field.get("effective") is not None:
        return op_field["effective"]
    return op_field.get(subkey, default)


def _index_row(eb: EntityBuild, seq: int) -> dict:
    p = eb.posting
    op = p.get("opinions") or {}
    # Canonicalized primary source URL — the join key the search pipeline uses to
    # thread store_key onto kept postings WITHOUT re-deriving identity (drift-free:
    # the builder wrote it, the same canonicalizer version reads it).
    src0 = (p.get("source_ids") or [{}])[0]
    canonical_url = ident.canonicalize_url(src0.get("url", "") or "")
    row = {
        "key": eb.key,
        "identity": p.get("identity", "strong"),
        "company": p.get("company", ""),
        "title": p.get("title", ""),
        "location": p.get("location", ""),
        "canonical_url": canonical_url,
        "profiles": p.get("profiles", []),
        "first_seen": p.get("first_seen"),
        "last_seen": p.get("last_seen"),
        "posted_at": (p.get("facts") or {}).get("posted_at"),
        "visa": _effective(op.get("visa") or {}, "label", "unclear"),
        "workplace": _effective(op.get("workplace") or {}, "value", "unknown"),
        "level": _effective(op.get("level") or {}, "value", "unknown"),
        "source": (p.get("source_ids") or [{}])[0].get("source", ""),
        "seq": seq,
    }
    return row


def _live_index(index_root: Path) -> Path:
    """The LIVE index dir for a (possibly build-aside) index root.

    ``--rebuild`` writes into ``index.building`` and swaps, but the durable floor is
    always read from the COMMITTED generation. Deriving that from the write
    destination — rather than taking it as an argument — means no caller can point
    the floor read at the wrong file, or omit it.
    """
    p = Path(index_root)
    aside = ".building"
    return p.with_name(p.name[:-len(aside)]) if p.name.endswith(aside) else p


def _write_postings_index(index_root: Path, rows: dict, header: dict,
                          tombstoned=()) -> dict:
    """THE one writer of ``index/postings.jsonl``. It applies the durable floor.

    ``rows`` is ``{key: row}`` for every key the caller accounts for. Any key in the
    LIVE index that ``rows`` does not cover and no tombstone explains (a frozen-facts
    snapshot — ``tombstoned``) is re-added VERBATIM at its original ``seq``, marked
    ``carried``/``carried_from: index`` by :func:`_carry_forward_from_index`.
    Returns the survivor rows it added.

    **Why the floor lives at the write and not in each caller.** It used to be
    threaded through the build paths as an argument, and ``build_opinions_only`` —
    which rebuilds the index from ``derived/`` alone — was never handed it. Every row
    whose raw AND derived were both gone was therefore destroyed by a pass documented
    as a cheap re-classification, and those rows are the only surviving record of
    those postings: nothing regenerates them and ``--rebuild`` cannot, because there
    is nothing left to rebuild from. A caller can forget an argument; it cannot
    forget the write it has to make. ``tombstoned`` stays optional for the same
    reason inverted — omitting it keeps a row that maybe should have gone, and only
    the other direction is unrecoverable.
    """
    survivors = _carry_forward_from_index(_live_index(index_root),
                                          set(rows), set(tombstoned))
    merged = {**rows, **survivors}
    lines = [serialization.dumps_jsonl_line(header)]
    lines += [serialization.dumps_jsonl_line(merged[k]) for k in sorted(merged)]
    atomic_write_text(Path(index_root) / "postings.jsonl", "".join(lines))
    return survivors


def _write_index(index_root: Path, entities: dict, entity_seq: dict, built_at: str,
                 tombstoned=()) -> dict:
    """Write ``index/postings.jsonl`` + ``by-day/`` from this build's entities.

    ``entities`` (every entity built this run: fresh ∪ derived-carried ∪
    frozen-reconstructed) always wins its own row; :func:`_write_postings_index` then
    fills the rest of the floor in. On a full-raw machine there are no survivors, so
    this is byte-identical to a plain rewrite from ``entities`` (a pure superset
    guarantee). ``by-day/`` stays event-derived from ``entities`` only — index-only
    survivors have no events this build and are never fabricated one.
    Returns ``(survivor rows the floor contributed, the paths written)``.
    """
    header = {"_schema": INDEX_SCHEMA_VERSION, "built_at": built_at, "note": INDEX_NOTE}
    # postings.jsonl — sorted by key for determinism; entities win by key.
    rows = {key: _index_row(eb, entity_seq.get(key, 0))
            for key, eb in entities.items()}
    survivors = _write_postings_index(index_root, rows, header, tombstoned)
    written = {Path(index_root) / "postings.jsonl"}

    # by-day/<date>.jsonl — every observation event bucketed by UTC capture day
    by_day: dict[str, list[dict]] = {}
    for key in sorted(entities):
        for ev in entities[key].events:
            at = ev.get("at") or ""
            day = at[:10] if len(at) >= 10 else "unknown"
            by_day.setdefault(day, []).append(
                {"entity": ev["entity"], "fetch": ev["fetch"], "type": ev["type"],
                 "at": ev.get("at"), "seq": ev.get("seq")})
    for day, day_rows in by_day.items():
        day_rows.sort(key=lambda r: (r.get("at") or "", r["entity"], r["type"]))
        out = [serialization.dumps_jsonl_line(header)]
        out += [serialization.dumps_jsonl_line(r) for r in day_rows]
        path = Path(index_root) / "by-day" / f"{day}.jsonl"
        atomic_write_text(path, "".join(out))
        written.add(path)
    return survivors, written


def _write_suppressed(index_root: Path, suppressed: list[dict], built_at: str) -> set:
    """Write ``triage/suppressed-<month>.jsonl``; return the paths written."""
    header = {"_schema": INDEX_SCHEMA_VERSION, "built_at": built_at, "note": INDEX_NOTE}
    by_month: dict[str, list[dict]] = {}
    written = set()
    for s in suppressed:
        at = s.get("at") or ""
        month = at[:7] if len(at) >= 7 else "unknown"
        by_month.setdefault(month, []).append(s)
    for month, rows in by_month.items():
        rows.sort(key=lambda r: (r.get("at") or "", r.get("source", ""),
                                 r.get("company", ""), r.get("title", ""),
                                 r.get("manifest", "")))
        out = [serialization.dumps_jsonl_line(header)]
        out += [serialization.dumps_jsonl_line(r) for r in rows]
        path = Path(index_root) / "triage" / f"suppressed-{month}.jsonl"
        atomic_write_text(path, "".join(out))
        written.add(path)
    return written


# ── generated store README ───────────────────────────────────
def _write_readme(data_root: Path, layout, stamps) -> None:
    text = f"""# Job store — generated map & cookbook

STORE-DERIVED. Machine-generated by `build_postings.py` ({stamps['builder']}).
It describes a corpus of REAL personal job-search data. **Never** paste its
contents — or any query row, company+date, or posting URL — into a public PR,
eval, benchmark, or commit message. Aggregate counts are fine; rows are not.

## Zones (domain: `{DOMAIN}`)

| Zone | Holds | Regenerable |
|------|-------|-------------|
| `raw/` | exact fetched bytes + one manifest per fetch | NO — source of truth |
| `derived/postings/<company>/<key>/` | `posting.yaml` (facts + code-stamped opinions), `jd.md` | yes, from raw |
| `index/postings.jsonl` | one summary line per posting (code-side filtering) | yes, from derived |
| `index/by-day/<date>.jsonl` | observations bucketed by capture day | yes, from derived |
| `index/triage/suppressed-<yyyy-mm>.jsonl` | structurally-foreign scrape rows (write-only review queue) | yes, from raw |
| `annotations/<key>.yaml` | human-verified facts (survive rebuilds) | NO — human judgment |
| `state/` | build ledger, key registry, cursors, identifiers | NO — operational state |

Schema versions: posting v{POSTING_SCHEMA_VERSION}, index v{INDEX_SCHEMA_VERSION},
normalizer v{parsers.NORMALIZER_VERSION}, URL canonicalizer v{ident.CANONICALIZER_VERSION}.

The store never says "closed" — a posting carries honest `last_seen` staleness only.
Treat a stale `last_seen` as a prompt to re-check the live board before acting.

## Query one-liners (no network, no AI)

```bash
query_postings.py --new-since-cursor shortlist-review --profile <slug>
query_postings.py --company <name>
query_postings.py --visa yes --workplace remote --max-age-days 7
query_postings.py --key gh-1234567 --history
```

## Cookbook (three recipes a stuck investigator needs)

1. **Grep an index past its header line** (skip the machine-generated header):
   ```bash
   tail -n +2 {data_root}/{DOMAIN}/index/postings.jsonl | grep -i '"company":"<name>"'
   ```
2. **Resolve an entity to its raw blob**:
   ```bash
   automation/store/store_show.py <entity-key> --data-root {data_root}
   ```
3. **Decompress & pretty-print a blob** (the sanctioned raw path; needs `zstd`):
   ```bash
   automation/store/store_show.py <entity-key> --raw --data-root {data_root}
   ```
"""
    atomic_write_text(data_root / "README.md", text)


# ── build orchestration ──────────────────────────────────────
def _record_pending(layout, ledger: BuildLedger, pending) -> list[str]:
    built_at = serialization.now_z()
    newly = []
    for _path, env in pending:
        fetch_id = env.get("fetch_id")
        if not fetch_id:
            continue
        fetched_at = env.get("fetched_at", "")
        clock_ok = check_clock_monotonic(fetched_at, ledger)
        ledger.record(fetch_id, fetched_at=fetched_at, built_at=built_at,
                      clock_ok=clock_ok)
        newly.append(fetch_id)
    return newly


def _seq_map(ledger: BuildLedger) -> dict:
    return {ln["fetch_id"]: int(ln.get("seq", 0)) for ln in ledger._lines
            if "fetch_id" in ln}


# ── post-fold overlays: stripped on EVERY load path ──────────
def _strip_post_fold_overlays(posting: dict) -> dict:
    """Remove every overlay a post-fold pass stamps, so the pass can re-derive it.

    ``_post_pass`` and the annotation overlay only ever SET values — neither has a
    "and otherwise remove it" branch, because for a freshly folded entity there is
    nothing to remove. So an entity that enters the working set still carrying last
    generation's overlays can GAIN a hint but never LOSE one: a
    ``possible_duplicate`` whose bucket has since emptied survives forever, and an
    annotation the owner DELETED keeps overriding ``index/postings.jsonl`` through
    ``_effective``.

    The invariant is therefore about the working set, not about how an entity got
    into it: **every posting handed to those passes arrives bare.** One this run
    re-folded never had the overlays; one it LOADED — from derived
    (:func:`_load_derived_entity`, :func:`_load_existing_entity`) or from a frozen
    snapshot (:func:`_reconstruct_from_frozen`) — must have them stripped here.
    Stripping on only some load paths inverts the store's own promise, leaving
    ``--rebuild`` (the authoritative path) unable to repair what the O(new) fast
    path repairs routinely.
    """
    posting.pop("migrated_from", None)
    posting.pop("possible_duplicate", None)
    posting.pop("human", None)
    for op in (posting.get("opinions") or {}).values():
        if isinstance(op, dict):
            for field in ("human", "effective", "source"):
                op.pop(field, None)
    return posting


# ── carry-forward (missing-raw tolerance, owner's multi-laptop contract) ──
def _load_existing_entity(entity_dir: Path, key: str):
    """Reconstruct an :class:`EntityBuild` from an existing derived entity dir.

    Used to CARRY FORWARD an entity whose raw blob is absent this build (marked
    ``provenance.carried``). JD prior-version siblings are carried too so a rebuild
    does not drop them. The post-fold overlays are stripped before
    ``provenance.carried`` is stamped, so ``_post_pass`` and the annotation overlay
    re-derive them exactly as they do for a fresh entity — see
    :func:`_strip_post_fold_overlays`.
    """
    posting = _strip_post_fold_overlays(serialization.loads_yaml(
        (entity_dir / "posting.yaml").read_text(encoding="utf-8")) or {})
    posting.setdefault("provenance", {})["carried"] = True  # idempotent
    jd_text = _read_derived_text(entity_dir / "jd.md")  # bytes: see `_read_derived_text`
    jd_versions = {}
    for f in sorted(entity_dir.glob("jd-*.md")):
        jd_versions[f.name[len("jd-"):-len(".md")]] = _read_derived_text(f)
    events = read_jsonl(entity_dir / "events.jsonl")
    seq = next((int(e.get("seq", 0)) for e in events
                if e.get("type") == "first_seen"), 0)
    return EntityBuild(key, entity_dir.parent.name, posting, jd_text,
                       jd_versions, events), seq


def _carry_forward(derived_root: Path, fresh_keys: set) -> dict:
    """Entities in the existing derived that this build did NOT rematerialize.

    A key present in derived but with zero present-blob observations means its raw
    is absent-without-tombstone (``not-synced-here``) — the store-core contract says
    keep the existing entity, never drop or error. Deterministic (reads only the
    existing generation), so incremental and rebuild carry the identical set.
    """
    out = {}
    postings_root = Path(derived_root) / "postings"
    if not postings_root.is_dir():
        return out
    for pyaml in sorted(postings_root.rglob("posting.yaml")):
        entity_dir = pyaml.parent
        key = entity_dir.name
        if key in fresh_keys:
            continue
        out[key] = _load_existing_entity(entity_dir, key)
    return out


# ── index-as-durable-floor (committed index outlives missing derived) ────
def _read_index_rows(index_root: Path) -> dict[str, dict]:
    """Pre-existing ``index/postings.jsonl`` rows keyed by ``key`` (header skipped).

    Reads the LIVE index file (never a ``.building`` aside), so incremental and
    rebuild see the identical pre-build generation. Tolerates an absent/empty index
    (fresh store) — returns ``{}``.
    """
    rows: dict[str, dict] = {}
    for row in read_jsonl(index_root / "postings.jsonl"):
        if isinstance(row, dict) and "key" in row:
            rows[row["key"]] = row
    return rows


def _carry_forward_from_index(index_root: Path, built_keys: set,
                              frozen_keys: set) -> dict:
    """Pre-existing index rows this build neither (re)materialized nor tombstoned.

    Extends the missing-raw tolerance one level further: "missing derived is as
    normal as missing raw." A key surviving only in the committed
    ``index/postings.jsonl`` — no current entity (fresh / derived-carried /
    frozen-reconstructed — the caller's ``built_keys``) and no tombstone signal (a
    frozen-facts snapshot — ``frozen_keys``, whether or not it reconstructed) — is
    preserved VERBATIM at its original ``seq`` (cursor/delta semantics stay stable)
    and marked ``carried: true`` / ``carried_from: "index"`` so consumers know it
    lacks derived backing this build and its ``last_seen`` is old. Never fabricates
    a derived ``posting.yaml`` — the entity stays honestly derived-absent; only the
    queryable index floor is preserved. Deterministic (reads only the pre-existing
    index), so incremental and rebuild read the identical survivor set from the same
    live index file — on a machine with full raw there are no survivors, so this is
    a pure superset guarantee with byte-identical output to today.
    """
    out = {}
    for key, row in _read_index_rows(index_root).items():
        if key in built_keys or key in frozen_keys:
            continue
        survivor = dict(row)
        survivor["carried"] = True
        survivor["carried_from"] = "index"
        out[key] = survivor
    return out


def _reconstruct_from_frozen(frozen: dict, key: str):
    """Rebuild an :class:`EntityBuild` from a ``state/frozen-facts/<key>.yaml`` snapshot.

    The retention GC writes these before pruning a blob that feeds a materialized
    entity. When BOTH the raw blob is pruned AND no derived entity is on disk (a
    fresh rebuild on a pruned store), this is the ONLY way the entity survives — the
    bounded, explicit exception to "everything re-derives from raw". Marked
    ``provenance.carried + provenance.frozen``. Deterministic (pure function of the
    snapshot), so incremental and rebuild reconstruct byte-identically. Returns
    ``None`` for an empty/malformed snapshot (never a husk).
    """
    entity = frozen.get("entity")
    if not isinstance(entity, dict) or not entity.get("key"):
        return None
    # The snapshot is the entity YAML verbatim, overlays included. They are derived
    # (`_post_pass` recomputes a hint on every build from whole buckets, and the
    # annotation overlay from the annotation that still exists), so they are
    # stripped here like on every other load path — otherwise a pruned entity's
    # human fact could never be taken back by any build path at all.
    posting = _strip_post_fold_overlays(dict(entity))
    prov = dict(posting.get("provenance") or {})
    prov["carried"] = True
    prov["frozen"] = True
    posting["provenance"] = prov
    files = frozen.get("files") or {}
    jd_text = files.get("jd.md", "") or ""
    jd_versions = {}
    for name, text in files.items():
        if name.startswith("jd-") and name.endswith(".md"):
            jd_versions[name[len("jd-"):-len(".md")]] = text
    events = list(frozen.get("events") or [])
    seq = next((int(e.get("seq", 0)) for e in events
                if e.get("type") == "first_seen"), 0)
    partition = validate_slug(_slugify(posting.get("company", "")) or "unknown",
                              field="company partition")
    return EntityBuild(key, partition, posting, jd_text, jd_versions, events), seq


# Deterministic event ordering (matches _reduce: an observation is first_seen OR
# seen[+changed]; within one (at, fetch) seen precedes changed).
_EVENT_TYPE_ORDER = {"first_seen": 0, "seen": 1, "changed": 2}


def _event_sort_key(e: dict):
    return (e.get("at") or "", e.get("fetch") or "",
            _EVENT_TYPE_ORDER.get(e.get("type"), 9))


def _frozen_prior(fentity: dict, jd_text: str) -> dict:
    """The fold snapshot of the last observation a frozen entity recorded.

    The inverse of :func:`_finish`: ``title``/``location`` are last-observation-wins
    and the ``facts`` block IS the last row's tracked payload (each key omitted
    exactly when the row's value was falsy, which reads back as ``None`` — the value
    ``_Fold.add`` compares against), so seven of the eight ``_TRACKED`` fields come
    back exactly. The eighth, ``url``, is not stored per observation — ``source_ids``
    is a first-appearance dedup — so the most recently ADDED source id is the closest
    the snapshot can prove; it differs from the true last url only for an entity
    whose observations alternate between two urls across the freeze boundary.
    """
    facts = fentity.get("facts") or {}
    src = (fentity.get("source_ids") or [{}])[-1]
    prior = {
        "title": fentity.get("title", ""),
        "location": fentity.get("location", ""),
        "url": src.get("url", "") or "",
        "workplace_raw": facts.get("workplace_raw"),
        "salary_text": facts.get("salary_text"),
        "salary_range": facts.get("salary_range"),
        "posted_at": facts.get("posted_at"),
        "jd_hash": (fentity.get("jd") or {}).get("content_hash"),
    }
    # `_jd_text` is read only when the previous observation carried a JD, and in
    # exactly that case it is the snapshot's own `jd.md` (as in `_resume_fold`).
    prior["_jd_text"] = jd_text if prior["jd_hash"] else ""
    return prior


def _resume_from_frozen(fold: _Fold, frozen: dict, fresh_fetches: set) -> set | None:
    """Seed ``fold`` with a frozen snapshot's pre-prune history; return its fetches.

    MAJOR-1: an entity fed by several blobs where only SOME survive materializes
    from the survivors alone — losing the pruned observations and, with them, an
    accurate ``first_seen`` (store-core §5: a pruned blob's manifest still proves it
    was observed). The retention GC writes the snapshot *before* pruning, so it —
    not the surviving raw — is the authority for every fetch it recorded.

    SEEDING the accumulator rather than merging into the finished entity is what
    makes the result ONE timeline instead of two spliced halves. A from-scratch
    fold that is then merged starts ``unstarted`` and priorless, so it stamps its
    earliest surviving observation ``first_seen`` — leaving TWO ``first_seen``
    events on one entity (two ``index/by-day/`` days claiming discovery, against a
    ``posting.first_seen`` that names only one) — and it has nothing to diff that
    observation against, so the ``changed`` event at the freeze boundary is never
    emitted at all. A seeded fold is already ``started`` and already holds
    ``prior``, so both fall out of the ordinary fold: the boundary observation is a
    ``seen`` + ``changed`` against the pre-prune state.

    Returns the set of fetch ids frozen accounts for — the caller drops those
    observations, since frozen already folded them and saw the fuller history — or
    ``None`` when the snapshot is malformed or holds nothing the present raw lacks
    (then the fresh fold stands exactly as it did before).
    """
    fentity = frozen.get("entity")
    if not isinstance(fentity, dict) or not fentity.get("key"):
        return None
    events = sorted((e for e in (frozen.get("events") or []) if isinstance(e, dict)),
                    key=_event_sort_key)
    fetches = {e.get("fetch") for e in events}
    if not (fetches - fresh_fetches):
        return None  # frozen holds no observation the present raw lacks — no-op
    files = frozen.get("files") or {}
    jd_text = files.get("jd.md", "") or ""
    fold.resume(
        source_ids=fentity.get("source_ids") or [],
        profiles=fentity.get("profiles") or [],
        fetch_ids=(fentity.get("provenance") or {}).get("fetch_ids") or [],
        events=events,
        jd_text=jd_text,
        jd_origin=_jd_origin_of(fentity),
        prior=_frozen_prior(fentity, jd_text),
        first_at=fentity.get("first_seen") or "",
        jd_versions={name[len("jd-"):-len(".md")]: text
                     for name, text in files.items()
                     if name.startswith("jd-") and name.endswith(".md")})
    return fetches


# ── annotation merge + conflict queue (store-core §1) ────────
def _append_conflict(path: Path, entity, field, opinion_value, human_value,
                     opinion_by) -> None:
    """Append one annotation-conflict line (idempotent by entity+field+opinion_by).

    ``state/annotation-conflicts.jsonl`` is STATE — never wiped by a rebuild. The
    annotation keeps winning in the view; the disagreement is just never invisible.
    """
    identity = (entity, field, opinion_by)
    existing = {(ln.get("entity"), ln.get("field"), ln.get("opinion_by"))
                for ln in read_jsonl(path)}
    if identity in existing:
        return
    append_line(path, serialization.dumps_jsonl_line({
        "entity": entity, "field": field, "opinion_value": opinion_value,
        "human_value": human_value, "opinion_by": opinion_by,
        "at": serialization.now_z()}))


def _overlay_annotation(opinions: dict, facts: dict, conflicts_path: Path,
                        key: str) -> None:
    """Overlay human facts onto an opinions dict: human WINS, conflict is recorded.

    The raw opinion value (``label``/``value``) is left intact for the diff report;
    ``human`` / ``effective`` / ``source: human`` mark the merged view the index and
    query filters read.
    """
    for field, subkey in _ANN_FIELD_SUBKEY.items():
        if field not in facts:
            continue
        human_val = facts[field]
        op = opinions.setdefault(field, {})
        computed = op.get(subkey)
        op["human"] = human_val
        op["effective"] = human_val
        op["source"] = "human"
        if computed is not None and computed != human_val:
            _append_conflict(conflicts_path, key, field, computed, human_val,
                             op.get("by"))


def _apply_annotations(entities: dict, layout) -> None:
    """Merge each entity's human annotation into its built view (human facts win)."""
    annotations = load_annotations(layout.annotations)
    if not annotations:
        return
    reg = KeyRegistry(layout.key_registry)
    conflicts_path = layout.state / "annotation-conflicts.jsonl"
    for ann_key, ann in annotations.items():
        key = ann_key if ann_key in entities else reg.resolve(ann_key)
        if key not in entities or not isinstance(ann, dict):
            continue
        facts = ann.get("facts") or {}
        if not facts:
            continue
        eb = entities[key]
        eb.posting["human"] = {"facts": dict(facts),
                               "verified_by": ann.get("verified_by", "human"),
                               "verified_at": ann.get("verified_at")}
        _overlay_annotation(eb.posting.setdefault("opinions", {}), facts,
                            conflicts_path, key)


def _build_entities(layout, registry, stamps, manifests=None, blobstore=None):
    """Reduce the full raw zone into ``{key: EntityBuild}`` + carried entities.

    Reads every present-blob member manifest, groups observations by entity key,
    reduces each, carries forward not-synced entities, then applies migration/dup
    hints and the annotation merge — a pure function of the processed set + the
    existing generation, so incremental and rebuild produce identical entities.
    Returns ``(entities, suppressed, entity_seq, groups, seq_of, index_survivors,
    frozen_keys, notes)`` — ``groups`` and ``seq_of`` let the spot-equivalence check
    re-reduce sampled keys cheaply; ``index_survivors`` is the durable-floor set from
    :func:`_carry_forward_from_index` (never merged into ``entities`` — index-only
    survivors stay honestly derived-absent, never fabricated as derived artifacts),
    pre-computed here so a rebuild can schema-verify those rows BEFORE its swap;
    ``frozen_keys`` is the tombstone set the index writer needs; ``notes`` is what
    :func:`_collect` could not use this run.
    """
    blobstore = BlobStore(layout.blobs) if blobstore is None else blobstore
    manifests = list(iter_manifests(layout)) if manifests is None else manifests
    ledger = BuildLedger(layout.build_ledger)
    seq_of = _seq_map(ledger)
    observations, suppressed, notes = _collect(layout, blobstore, manifests, registry)
    groups: dict[str, list[Observation]] = {}
    for o in observations:
        groups.setdefault(o.key, []).append(o)
    frozen_all = load_frozen_facts(layout)
    # MAJOR-1: an entity fed by several blobs where only SOME were pruned would
    # materialize from the survivors alone, so its fold is SEEDED from the frozen
    # snapshot (see `_resume_from_frozen`) and its sequence recomputed over the union
    # of fetches, so a cursor still surfaces it correctly.
    entities: dict[str, EntityBuild] = {}
    entity_seq: dict[str, int] = {}
    for key, obs in groups.items():
        eb = _reduce(key, obs, seq_of, stamps, frozen=frozen_all.get(key))
        if eb is None:
            continue  # frozen accounts for every present observation — see below
        entities[key] = eb
        prov = eb.posting.get("provenance") or {}
        entity_seq[key] = (
            min((seq_of.get(f, 0) for f in prov.get("fetch_ids") or []), default=0)
            if prov.get("frozen")
            else min(seq_of.get(o.fetch_id, 0) for o in obs))
    fresh_keys = set(entities)
    # Reconstruct entities that materialized NO fresh observation (all their blobs
    # pruned). Sourced from frozen facts REGARDLESS of whether derived is on disk, so
    # a derived-present build and a derived-wiped build agree byte-for-byte (MINOR-1).
    for key, frozen in frozen_all.items():
        if key in fresh_keys:
            continue
        rec = _reconstruct_from_frozen(frozen, key)
        if rec is not None:
            entities[key], entity_seq[key] = rec[0], rec[1]
    # Carry forward not-synced-here entities (raw absent, no tombstone, no frozen):
    # keep the existing derived rather than drop it (missing-raw tolerance).
    for key, (eb, seq) in _carry_forward(layout.derived, set(entities)).items():
        entities[key] = eb
        entity_seq[key] = seq
    _post_pass(entities, registry)
    _apply_annotations(entities, layout)
    # Durable-floor merge (Decision 2): pre-existing index rows this build neither
    # (re)materialized nor tombstoned. Computed LAST, against the final entities set,
    # and kept separate — never folded into `entities` (no fabricated derived facts).
    index_survivors = _carry_forward_from_index(
        layout.index, set(entities), set(frozen_all))
    return (entities, suppressed, entity_seq, groups, seq_of, index_survivors,
            set(frozen_all), notes)


def _verify_schemas(entities: dict, entity_seq: dict,
                    index_survivors: dict | None = None) -> None:
    """Schema-validate every derived posting + event + index line before a swap.

    The store validator (schemas) applied in-memory to the aside generation, so a
    rebuild that would write a schema-invalid artifact fails BEFORE the atomic swap
    rather than shipping bad data. Also asserts one index line per entity (counts).
    Carried index-only survivor rows are validated too — a corrupt legacy row must
    fail loudly here, never poison a rebuild's index floor.
    """
    posting_schema = load_schema("posting")
    event_schema = load_schema("event-line")
    line_schema = load_schema("posting-index-line")
    errors: list[str] = []
    for key, eb in entities.items():
        errors += [f"{key}: {e}" for e in schema_validate(eb.posting, posting_schema, key)]
        for ev in eb.events:
            errors += [f"{key}: {e}" for e in schema_validate(ev, event_schema, key)]
        errors += [f"{key}: {e}" for e in
                   schema_validate(_index_row(eb, entity_seq.get(key, 0)), line_schema, key)]
        if len(errors) > 20:
            break
    for key, row in (index_survivors or {}).items():
        errors += [f"{key}: {e}" for e in schema_validate(row, line_schema, key)]
        if len(errors) > 20:
            break
    if errors:
        raise BuildError(f"schema verification failed ({len(errors)}+ error(s)): "
                         f"{errors[:5]}")


def _verify(entities: dict, layout) -> None:
    """Rebuild verification: annotation orphan hard-fail + case-collision guard."""
    ann_keys = set(load_annotations(layout.annotations))
    # Annotations join through the entity key OR any registered alias.
    registry_keys = set(entities)
    reg = KeyRegistry(layout.key_registry)
    resolvable = set()
    for ann in ann_keys:
        resolved = reg.resolve(ann)
        if resolved in entities or ann in entities:
            resolvable.add(ann)
    assert_no_orphans(ann_keys, registry_keys | resolvable)


def _pin_referenced_keys(layout, entities: dict) -> None:
    """Pin keys on first annotation join or when an application references them.

    Scans the applications root read-only for `store_key` fields (cheap glob;
    absent field = nothing pinned). Pinned keys never silently re-key on rebuild.
    """
    reg = KeyRegistry(layout.key_registry)
    for ann in load_annotations(layout.annotations):
        if ann in entities and not reg.is_pinned(ann):
            reg.pin(ann, "annotation")
    try:
        apps_root = config.applications_root()
    except Exception:  # noqa: BLE001
        apps_root = None
    if apps_root and Path(apps_root).is_dir():
        for meta in Path(apps_root).rglob("meta.yaml"):
            try:
                data = serialization.loads_yaml(meta.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for key in _iter_store_keys(data):
                if key in entities and not reg.is_pinned(key):
                    reg.pin(key, "reference")


def _iter_store_keys(data):
    """Yield every `store_key` value found anywhere in a meta.yaml structure."""
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "store_key" and isinstance(v, str) and v:
                yield v
            else:
                yield from _iter_store_keys(v)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_store_keys(item)


# ── fold cache: fingerprint + store digests ─────────────────
def _module_fingerprint(registry: Registry) -> dict:
    """Everything OUTSIDE the raw zone that decides an entity's bytes.

    Any difference here means a cached fold could no longer reproduce what a
    rebuild would write, so the build re-derives from raw — which is also how a
    classifier tweak still reaches every historical posting.
    """
    return {
        **_stamps(),
        "parsers": _module_stamp(parsers),
        "identity": _module_stamp(ident),
        "registry_mod": _module_stamp(sys.modules[Registry.__module__]),
        "normalizer": parsers.NORMALIZER_VERSION,
        "canonicalizer": ident.CANONICALIZER_VERSION,
        "posting_schema": POSTING_SCHEMA_VERSION,
        "index_schema": INDEX_SCHEMA_VERSION,
        "registry": fold_state.digest_obj(registry.entries),
    }


def _manifest_sort_key(env: dict) -> tuple:
    return (env.get("fetched_at") or "", env.get("fetch_id") or "")


def _store_state(manifests, blobstore, registry, present=None) -> dict:
    """Digests of everything the per-entity cache does not model itself.

    ``manifest_digest`` covers ``(fetch_id, payload blob)`` PAIRS, not bare fetch
    ids. Raw is contractually append-only and immutable, so a manifest rewritten
    in place is out-of-contract — but the refusal table promises that "a manifest
    was removed, or the raw zone was not synced" is detected, and a bare fetch-id
    digest cannot see a folded manifest re-pointed at different bytes: the fast
    path folds only the pending set, so the replaced manifest's new rows never
    reach derived and no refusal fires. Widening the digest is what makes the code
    match the promise; it costs one full fold for every store built by the
    narrower version (``postings_fold_state.CACHE_SCHEMA`` is bumped alongside so
    the refusal names the cause).
    """
    ids, absent, cap = [], [], ("", "")
    present = blobstore.present_shas() if present is None else present
    for _path, env in manifests:
        payload = env.get("payload")
        blob = payload.get("blob") if isinstance(payload, dict) else None
        ids.append(f"{env.get('fetch_id') or ''}\x1f{blob or ''}")
        cap = max(cap, _manifest_sort_key(env))
        if blob and blob not in present:
            absent.append(blob)
    return {
        "fingerprint": _module_fingerprint(registry),
        "manifest_digest": fold_state.digest_strings(ids),
        "absent_digest": fold_state.digest_strings(absent),
        "max_manifest": list(cap),
    }


def _entity_triple(posting: dict):
    """The (company, title, JD-hash) bucket ``_post_pass`` groups entities into."""
    jd_hash = (posting.get("jd") or {}).get("content_hash")
    if not jd_hash:
        return None
    return (ident._norm_company(posting.get("company", "")),
            ident._norm_title(posting.get("title", "")), jd_hash)


def _cache_entry(eb: EntityBuild) -> dict:
    triple = _entity_triple(eb.posting)
    entry = {"k": eb.key, "p": eb.partition}
    if eb.fold is not None:
        entry["f"] = eb.fold
    if triple is not None:
        entry["t"] = list(triple)
    return entry


def _annotation_targets(layout, keys) -> dict:
    """``{entity key: annotation}`` for every annotation that joins an entity."""
    reg = None
    out = {}
    for ann_key, ann in load_annotations(layout.annotations).items():
        key = ann_key
        if key not in keys:
            reg = reg if reg is not None else KeyRegistry(layout.key_registry)
            key = reg.resolve(ann_key)
        if key in keys and isinstance(ann, dict):
            out[key] = ann
    return out


def _write_cache(layout, entities: dict, state: dict, ledger: BuildLedger,
                 frozen_digest: str) -> None:
    """Persist the fold state for the next run (ALWAYS the build's last write).

    Derived and index have already landed when this runs, so a crash here leaves a
    cache whose ``ledger_digest`` no longer matches the ledger — which the next
    build detects and answers with a full fold.
    """
    header = dict(state)
    header["ledger_digest"] = fold_state.digest_strings(ledger.processed_fetch_ids())
    header["frozen_digest"] = frozen_digest
    header["ann_keys"] = sorted(_annotation_targets(layout, set(entities)))
    fold_state.save(fold_state.cache_path(layout),
                    header, {k: _cache_entry(eb) for k, eb in entities.items()})


def _frozen_digest(layout) -> str:
    """Content digest of every frozen-facts snapshot (they feed entity bytes)."""
    fdir = layout.state / "frozen-facts"
    if not fdir.is_dir():
        return fold_state.digest_pairs([])
    return fold_state.digest_pairs(
        (p.name, p.read_bytes()) for p in sorted(fdir.glob("*.yaml")))


_DERIVED_REQUIRED = ("posting.yaml", "events.jsonl")


def _derived_keys(derived_root: Path) -> set:
    """Every ``(partition, key)`` whose derived files are all present, as a
    stat-only two-level scan.

    PAIRS, not bare keys: the cache holds exactly one partition per key
    (``entry["p"]``), so comparing key SETS cannot see a key materialized at two
    partitions at once — the shape a company rename used to leave behind. The pair
    comparison refuses the fast path on any such pre-existing mess, and the full
    fold that follows heals it (:func:`_drop_stale_partitions`).

    ``events.jsonl`` as well as ``posting.yaml``: this answers "is this entity's
    derived intact enough to resume its fold from?", and :func:`_resume_fold`
    reads the event list too. ``posting.yaml`` alone as the proxy meant a deleted
    ``events.jsonl`` silently truncated that entity's event history — the resumed
    fold started from an empty list, ``by-day/`` lost every earlier day, and
    nothing refused. (:func:`_carry_forward` keeps ``posting.yaml`` as ITS
    predicate on purpose: it answers a different question — "is there an entity
    here to keep?" — where a missing event list is not a reason to drop a posting.)

    ``os.scandir`` rather than ``rglob`` on purpose: at 15k entities the pathlib
    walk measured 2.25s and this measures 0.23s for the identical answer, and
    this check runs on every build.
    """
    postings_root = Path(derived_root) / "postings"
    if not postings_root.is_dir():
        return set()
    pairs = set()
    for partition in os.scandir(postings_root):
        if not partition.is_dir():
            continue
        for entity in os.scandir(partition.path):
            if entity.is_dir() and all(
                    os.path.exists(os.path.join(entity.path, name))
                    for name in _DERIVED_REQUIRED):
                pairs.add((partition.name, entity.name))
    return pairs


# ── the fast path's admission test ───────────────────────────
def _refuse(reason: str) -> None:
    print(f"store: full fold this run ({reason})", file=sys.stderr)
    return None


def _fast_plan(layout, registry, ledger, manifests, pending, blobstore):
    """May this run fold ONLY the pending manifests? Plan, or ``None`` with a reason.

    Every check answers one question: "is there anything the persisted per-entity
    state does not already account for?" A yes anywhere refuses, and the refusal
    costs exactly one full fold — the behaviour that shipped before this cache
    existed. Nothing here can make a build wrong; it can only make it slow.
    """
    # Checked FIRST and unconditionally: every other signal below is a comparison
    # against state the build did not write, so it can only detect a crash that
    # happened to move one of them. The marker detects the crash itself — including
    # a zero-pending build (applying an annotation), which moves nothing else at all.
    stale = fold_state.read_incomplete(fold_state.incomplete_path(layout))
    if stale is not None:
        return _refuse(f"a previous {stale.get('mode') or 'build'} did not finish"
                       + (f" (started {stale['started_at']})"
                          if stale.get("started_at") else ""))
    loaded = fold_state.load(fold_state.cache_path(layout))
    if loaded is None:
        return _refuse("no usable fold cache")
    header, entries = loaded
    pending_ids = {env.get("fetch_id") for _p, env in pending}
    folded = [(p, e) for p, e in manifests if e.get("fetch_id") not in pending_ids]

    present = blobstore.present_shas()
    now = _store_state(folded, blobstore, registry, present)
    now["ledger_digest"] = fold_state.digest_strings(ledger.processed_fetch_ids())
    now["frozen_digest"] = _frozen_digest(layout)
    bad = fold_state.compare_header(header, now)
    if bad:
        return _refuse(f"fold cache stale ({bad} changed)")

    # ORDER: the fold is a left fold, so continuing it is only equal to redoing it
    # when every new observation sorts after every folded one. One tuple compare
    # per pending manifest proves that for every entity at once.
    cap = tuple(header.get("max_manifest") or ("", ""))
    for _p, env in pending:
        if not env.get("fetch_id"):
            # The ledger cannot record it, so it would stay "pending" forever and
            # be folded again on every run — the one way this design could double
            # an observation. Refuse rather than risk it.
            return _refuse("a pending manifest carries no fetch id")
        if _manifest_sort_key(env) <= cap:
            return _refuse("capture out of order (clock skew or backfill)")

    derived = _derived_keys(layout.derived)
    if derived != {(entry.get("p") or "", key) for key, entry in entries.items()}:
        return _refuse("derived zone no longer matches the fold cache")

    # The committed index is the last zone with no signal of its own. `_patch_index_zone`
    # reads it as authoritative for every row this run does not rebuild, so a row
    # deleted from it stays lost across every subsequent fast build — in the zone the
    # design calls committed, durable history. The cache says which rows must be
    # there: every cached entity was written to derived AND given an index row by the
    # same build. A PROPER SUBSET means the index moved under the cache. (A superset
    # is normal and stays allowed — those are the index-only floor survivors.)
    if set(entries) - set(_read_index_rows(layout.index)):
        return _refuse("the committed index is missing rows the fold cache holds")

    return {"header": header, "entries": entries, "derived": derived,
            "state": _store_state(manifests, blobstore, registry, present),
            "frozen_digest": now["frozen_digest"]}


def build_incremental(layout, registry) -> dict:
    _recover_swap_remnants(layout)  # before ANY read of the live zones
    stamps = _stamps()
    ledger = BuildLedger(layout.build_ledger)
    blobstore = BlobStore(layout.blobs)
    manifests = list(iter_manifests(layout))
    done = ledger.processed_fetch_ids()
    pending = sorted((pe for pe in manifests if pe[1].get("fetch_id") not in done),
                     key=lambda pe: pe[1].get("fetch_id", ""))
    plan = _fast_plan(layout, registry, ledger, manifests, pending, blobstore)
    # Write-ahead, AFTER `_fast_plan` has read the previous run's marker: from here
    # until the cache lands, derived may be a generation ahead of the cache that
    # describes it. Anything that stops the process in that window leaves the
    # marker, and the next build answers it with a full fold.
    fold_state.mark_incomplete(fold_state.incomplete_path(layout), "incremental build")
    newly = _record_pending(layout, ledger, pending)
    if plan is None:
        summary = _build_incremental_full(layout, registry, stamps, ledger, newly,
                                          manifests, blobstore)
    else:
        summary = _build_incremental_fast(layout, registry, stamps, ledger, newly,
                                          pending, plan, blobstore, manifests)
    fold_state.clear_incomplete(fold_state.incomplete_path(layout))
    return summary


def _build_incremental_full(layout, registry, stamps, ledger, newly, manifests,
                            blobstore) -> dict:
    """The unchanged whole-raw-zone fold — still the fallback and the safety net."""
    (entities, suppressed, entity_seq, _groups, _seq, _survivors, frozen_keys,
     notes) = _build_entities(
        layout, registry, stamps, manifests=manifests, blobstore=blobstore)

    _check_case_collisions(layout.derived, entities)
    _verify(entities, layout)  # orphan hard-fail on EVERY build path (incl. incremental)
    # Write only entities whose bytes changed (carry the rest unchanged).
    changed = 0
    partitions = _partition_index(layout.derived)
    for eb in entities.values():
        if _write_entity(layout.derived, eb, only_if_changed=True,
                         partitions=partitions):
            changed += 1
    built_at = _index_built_at(ledger)
    index_survivors = _regen_index_zone(layout.index, entities, entity_seq,
                                        suppressed, built_at, frozen_keys)
    _pin_referenced_keys(layout, entities)
    _write_readme(layout.root.parent, layout, stamps)
    _write_cache(layout, entities, _store_state(manifests, blobstore, registry),
                 ledger, _frozen_digest(layout))
    return {"mode": "incremental", "fold": "full", "pending": len(newly),
            "entities": len(entities), "changed": changed,
            "suppressed": len(suppressed),
            "carried_from_index": len(index_survivors),
            **_report_collect_notes(notes)}


# ── the fast path ────────────────────────────────────────────
def _resume_fold(key: str, entry: dict, entity_dir: Path) -> _Fold:
    """Rehydrate one entity's accumulator from its OWN derived files + the cache.

    The cache holds only what derived cannot express (the carried snapshot and the
    one bit ``jd.md`` normalization drops); everything else is read back from the
    entity, so the two can never disagree about the same fact.
    """
    posting = serialization.loads_yaml(
        (entity_dir / "posting.yaml").read_text(encoding="utf-8")) or {}
    # BYTES, not `read_text`: universal-newline translation would turn a CRLF the
    # JD really contains into LF, and the resumed fold would then archive a
    # `jd-<hash>.md` prior version that raw never held. Ashby's and Lever's
    # `descriptionPlain` reach `jd.md` without passing through `strip_html`, so a
    # CR in derived is a real payload shape, not a hypothetical.
    jd_text = _read_derived_text(entity_dir / "jd.md")
    if jd_text and entry["f"].get("n") is False:
        jd_text = jd_text[:-1]  # `_entity_files` appended the newline; undo it
    fold = _Fold(key)
    fold.resume(source_ids=posting.get("source_ids") or [],
                profiles=posting.get("profiles") or [],
                fetch_ids=(posting.get("provenance") or {}).get("fetch_ids") or [],
                events=read_jsonl(entity_dir / "events.jsonl"),
                jd_text=jd_text,
                jd_origin=_jd_origin_of(posting),
                prior=dict(entry["f"].get("s") or {}),
                first_at=posting.get("first_seen") or "")
    # `_jd_text` is read only when the previous observation carried a JD, and in
    # that case it IS the current jd.md — reconstructed exactly above.
    if fold.prior.get("jd_hash"):
        fold.prior["_jd_text"] = jd_text
    return fold


def _load_derived_entity(derived_root: Path, partition: str, key: str) -> EntityBuild:
    """Load an untouched entity as the fold would have produced it (pre-overlay).

    Used only for the handful of entities a touched one can reach: duplicate/
    migration siblings and annotation targets. The post-fold overlays are stripped
    so re-running them reproduces a fresh build exactly, including REMOVING a hint
    or a human fact that no longer applies.
    """
    entity_dir = Path(derived_root) / "postings" / partition / key
    posting = _strip_post_fold_overlays(serialization.loads_yaml(
        (entity_dir / "posting.yaml").read_text(encoding="utf-8")) or {})
    jd_text = _read_derived_text(entity_dir / "jd.md")  # bytes: see `_resume_fold`
    return EntityBuild(key, partition, posting, jd_text, {},
                       read_jsonl(entity_dir / "events.jsonl"), None)


def _duplicate_participants(entries: dict, touched: dict) -> set:
    """Untouched entities whose duplicate/migration hints this run can change.

    ``_post_pass`` is the one reduction that is NOT a per-key partition: it groups
    entities by (company, title, JD hash) and stamps hints on every member of a
    multi-member bucket. A newly folded entity can therefore change an entity it
    never observed — and a departure can leave a stale hint behind. Both bucket
    memberships (before and after) are pulled in so the pass sees whole buckets.

    This covers the entities this run FOLDED. An entity that joins the working set
    some other way needs its bucket closed too — see :func:`_bucket_closure`.
    """
    buckets: dict[tuple, set] = {}
    for k, entry in entries.items():
        if entry.get("t"):
            buckets.setdefault(tuple(entry["t"]), set()).add(k)
    after = {t: set(ks) for t, ks in buckets.items()}
    affected: set = set()
    for key, eb in touched.items():
        old = entries.get(key, {}).get("t")
        new = _entity_triple(eb.posting)
        if old:
            after.get(tuple(old), set()).discard(key)
        if new:
            after.setdefault(new, set()).add(key)
    for key, eb in touched.items():
        old = entries.get(key, {}).get("t")
        for triple in (tuple(old) if old else None, _entity_triple(eb.posting)):
            if triple is None:
                continue
            before_members = buckets.get(triple, set())
            after_members = after.get(triple, set())
            if max(len(before_members), len(after_members)) >= 2:
                affected |= before_members | after_members
    return affected - set(touched)


def _bucket_closure(entries: dict, reached: set) -> set:
    """Complete every duplicate bucket the working set touches.

    EVERY entity in the working set arrives WITHOUT its `_post_pass` hints: one
    this run re-folded never had them, and one it merely loaded had them stripped
    on purpose (:func:`_load_derived_entity`) so they can be re-derived. So the
    pass does not just fail to *add* a hint when a bucket is only half present —
    it silently DELETES the hint that was there, and only a `--rebuild` restores
    it. The invariant is therefore about the working set as a whole, not about how
    an entity got into it: **it must be closed under bucket membership.**

    :func:`_duplicate_participants` closes the buckets of the entities this run
    FOLDED. This closes the buckets of the ones it merely REACHED — annotation
    targets, the previous run's annotation targets, and anything a future reach
    adds — so the invariant holds for every entry point rather than for the two
    that were thought of.

    One pass is the fixed point: buckets are equivalence classes on the
    (company, title, JD-hash) triple, so a bucket mate's bucket mates are the same
    bucket. Entities with no JD hash have no triple and form no bucket at all.
    """
    buckets: dict[tuple, set] = {}
    for key, entry in entries.items():
        if entry.get("t"):
            buckets.setdefault(tuple(entry["t"]), set()).add(key)
    out: set = set()
    for key in reached:
        triple = entries.get(key, {}).get("t")
        if triple:
            out |= buckets.get(tuple(triple), set())
    return out


def _check_case_collisions_incremental(entries: dict, touched: dict) -> None:
    """Case-collision guard restricted to what this run adds or moves.

    The pre-existing set passed the same guard when it was written, so only the
    newcomers need checking against it — the identical failure, at O(new) cost.
    """
    partitions: dict[str, set] = {}
    for key, entry in entries.items():
        if key in touched:
            continue  # re-checked below at its (possibly new) partition
        partitions.setdefault(entry.get("p") or "", set()).add(key)
    for key, eb in touched.items():
        clash = detect_case_collision([p for p in partitions if p != eb.partition],
                                      eb.partition)
        if clash:
            raise BuildError(f"case-only partition collision: {eb.partition!r} vs "
                             f"{clash!r}")
        siblings = partitions.setdefault(eb.partition, set())
        clash = detect_case_collision([k for k in siblings if k != key], key)
        if clash:
            raise BuildError(f"case-only key collision under {eb.partition!r}: "
                             f"{key!r} vs {clash!r}")
        siblings.add(key)


def _build_incremental_fast(layout, registry, stamps, ledger, newly, pending, plan,
                            blobstore, manifests) -> dict:
    """Fold ONLY the pending manifests into the persisted prior state."""
    entries = plan["entries"]
    seq_of = _seq_map(ledger)
    observations, suppressed, notes = _collect(layout, blobstore, pending, registry)
    groups: dict[str, list[Observation]] = {}
    for o in observations:
        groups.setdefault(o.key, []).append(o)

    frozen_keys = set(load_frozen_facts(layout))
    for key in groups:
        entry = entries.get(key)
        if key in frozen_keys or (entry is not None and "f" not in entry):
            # A carried / frozen / frozen-merged entity has no continuable fold;
            # its history lives outside the raw this run can see.
            print(f"store: full fold this run (entity {key} is not continuable)",
                  file=sys.stderr)
            return _build_incremental_full(layout, registry, stamps, ledger, newly,
                                           manifests, blobstore)

    # 1. Continue each touched entity's fold from its persisted state.
    touched: dict[str, EntityBuild] = {}
    for key, obs in groups.items():
        entry = entries.get(key)
        obs = sorted(obs, key=_obs_sort_key)
        if entry is None:
            fold = _Fold(key)  # brand new (or an index-only key materializing now)
        else:
            # `_fast_plan` already proved this for the run as a whole, from the
            # manifest bound. Re-check it here per entity, against where this
            # entity's own fold actually stopped: a left fold appended to out of
            # order would produce different `changed` events, and that is the one
            # way this optimization could silently corrupt the store.
            stopped = tuple(entry["f"].get("l") or ("", ""))
            if _obs_sort_key(obs[0])[:2] <= stopped:
                print(f"store: full fold this run (entity {key} would be folded "
                      f"out of order)", file=sys.stderr)
                return _build_incremental_full(layout, registry, stamps, ledger,
                                               newly, manifests, blobstore)
            fold = _resume_fold(key, entry,
                                Path(layout.derived) / "postings" / entry["p"] / key)
        for o in obs:
            fold.add(o, seq_of)
        touched[key] = _finish(fold, stamps)

    # 2. Pull in the untouched entities this run can still change.
    derived_root = Path(layout.derived)
    extra: dict[str, EntityBuild] = {}
    all_keys = set(entries) | set(touched)
    ann_targets = _annotation_targets(layout, all_keys)
    reach = _duplicate_participants(entries, touched)
    reach |= set(ann_targets) - set(touched)
    reach |= (set(plan["header"].get("ann_keys") or []) & set(entries)) - set(touched)
    # Whatever pulled an entity in, its whole duplicate bucket comes with it: the
    # working set must be closed under bucket membership or `_post_pass` sees a
    # partial bucket and DELETES a hint instead of re-stamping it. Applied to the
    # assembled reach (not to one source of it) so a future reach is covered too.
    reach |= _bucket_closure(entries, reach) - set(touched)
    for key in sorted(reach):
        entry = entries.get(key)
        if entry is not None:
            extra[key] = _load_derived_entity(derived_root, entry["p"], key)
    working = {**extra, **touched}

    # 3. The passes that are not per-key partitions, over the reachable set only.
    _post_pass(working, registry)
    conflicts_path = layout.state / "annotation-conflicts.jsonl"
    for key, ann in ann_targets.items():
        eb = working.get(key)
        facts = (ann.get("facts") or {}) if eb is not None else {}
        if not facts:
            continue
        eb.posting["human"] = {"facts": dict(facts),
                               "verified_by": ann.get("verified_by", "human"),
                               "verified_at": ann.get("verified_at")}
        _overlay_annotation(eb.posting.setdefault("opinions", {}), facts,
                            conflicts_path, key)

    _check_case_collisions_incremental(entries, touched)
    _verify(all_keys, layout)

    # 4. Write only what changed. The partition snapshot comes from the scan
    # `_fast_plan` already did (it proved it equals the cache), so the O(new) path
    # does not pay for a second walk of the derived zone.
    partitions: dict[str, set[str]] = {}
    for partition, key in plan["derived"]:
        partitions.setdefault(key, set()).add(partition)
    changed = 0
    for eb in working.values():
        if _write_entity(derived_root, eb, only_if_changed=True,
                         partitions=partitions):
            changed += 1

    built_at = _index_built_at(ledger)
    # Only a re-folded entity's sequence can move; a reachable-but-unobserved one
    # keeps the sequence the previous build computed for it (its persisted index
    # row), which is what a full fold would leave it with.
    entity_seq = {key: min((seq_of.get(f, 0) for f in
                            (eb.posting.get("provenance") or {}).get("fetch_ids") or []),
                           default=0)
                  for key, eb in touched.items()}
    pending_rels = {_rel_manifest(layout, p) for p, _env in pending}
    survivors = _patch_index_zone(layout.index, working, entity_seq, all_keys,
                                  frozen_keys, set(touched), suppressed,
                                  pending_rels, built_at)
    _pin_referenced_keys(layout, all_keys)
    _write_readme(layout.root.parent, layout, stamps)

    # 5. The cache is the LAST write of the build (see `_write_cache`).
    # Only a RE-FOLDED entity gets a new cache entry. An entity pulled in for the
    # duplicate pass or an annotation keeps its existing one: its observations,
    # carried snapshot and bucket triple are untouched by those passes, and
    # rebuilding its entry from a disk-loaded posting would drop the fold state and
    # silently condemn it to forcing a full fold forever after.
    merged = {k: (_cache_entry(touched[k]) if k in touched else entries[k])
              for k in all_keys}
    header = dict(plan["state"])
    header["ledger_digest"] = fold_state.digest_strings(ledger.processed_fetch_ids())
    header["frozen_digest"] = plan["frozen_digest"]
    header["ann_keys"] = sorted(ann_targets)
    fold_state.save(fold_state.cache_path(layout), header, merged)
    return {"mode": "incremental", "fold": "pending-only", "pending": len(newly),
            "entities": len(all_keys), "folded": len(touched), "changed": changed,
            "suppressed": len(suppressed), "carried_from_index": len(survivors),
            **_report_collect_notes(notes)}


def _rel_manifest(layout, path) -> str:
    try:
        return str(Path(path).relative_to(layout.root))
    except ValueError:
        return str(path)


def _patch_index_zone(index_root: Path, working: dict, entity_seq: dict, all_keys: set,
                      frozen_keys: set, touched: set, suppressed: list,
                      pending_rels: set, built_at: str) -> dict:
    """Update the index zone in place instead of regenerating it from every entity.

    Measured choice (see docs/designs/raw-data-layer/05-incremental-build.md): the
    index files are rewritten whole, but from the PERSISTED rows rather than from
    re-reduced entities. Every file's header carries ``built_at``, which moves on
    every run that ingests a fetch, so a partitioned or row-patched index would
    still have to rewrite every file — the saving is in not re-deriving the rows,
    not in writing fewer bytes.
    """
    index_root = Path(index_root)
    header = {"_schema": INDEX_SCHEMA_VERSION, "built_at": built_at, "note": INDEX_NOTE}

    # postings.jsonl — the persisted rows this build accounts for (``all_keys``),
    # with this run's entities replacing their own. Every OTHER persisted row is
    # left to `_write_postings_index`, which is what marks and preserves the floor;
    # passing them through here would preserve them unmarked.
    persisted = _read_index_rows(index_root)
    rows = {key: row for key, row in persisted.items() if key in all_keys}
    for key, eb in working.items():
        seq = entity_seq[key] if key in entity_seq \
            else int(persisted.get(key, {}).get("seq") or 0)
        rows[key] = _index_row(eb, seq)
    for stale in index_root.glob("*.jsonl"):
        if stale.name != "postings.jsonl":
            stale.unlink()
    survivors = _write_postings_index(index_root, rows, header, frozen_keys)

    # by-day — drop every row belonging to a re-folded entity, re-add from its new
    # event list. Idempotent by construction: a rerun re-derives the same rows.
    by_day: dict[str, list[dict]] = {}
    day_dir = index_root / "by-day"
    for path in sorted(day_dir.glob("*.jsonl")) if day_dir.is_dir() else []:
        # Tolerant read: a full regeneration simply overwrote these files, so index
        # debris must degrade (one warning, that line skipped) rather than block.
        kept = [r for r in read_jsonl(path, strict_interior=False)
                if isinstance(r, dict) and "entity" in r
                and r.get("entity") not in touched]
        by_day[path.stem] = kept
    for key in sorted(touched):
        for ev in working[key].events:
            at = ev.get("at") or ""
            day = at[:10] if len(at) >= 10 else "unknown"
            by_day.setdefault(day, []).append(
                {"entity": ev["entity"], "fetch": ev["fetch"], "type": ev["type"],
                 "at": ev.get("at"), "seq": ev.get("seq")})
    _rewrite_bucketed(day_dir, by_day, header,
                      lambda r: (r.get("at") or "", r["entity"], r["type"]))

    # triage — same shape, keyed by the manifest that produced each suppressed row.
    by_month: dict[str, list[dict]] = {}
    triage_dir = index_root / "triage"
    for path in sorted(triage_dir.glob("suppressed-*.jsonl")) if triage_dir.is_dir() else []:
        kept = [r for r in read_jsonl(path, strict_interior=False)
                if isinstance(r, dict) and "gate" in r
                and r.get("manifest") not in pending_rels]
        by_month[path.stem[len("suppressed-"):]] = kept
    for s in suppressed:
        at = s.get("at") or ""
        by_month.setdefault(at[:7] if len(at) >= 7 else "unknown", []).append(s)
    _rewrite_bucketed(triage_dir, by_month, header,
                      lambda r: (r.get("at") or "", r.get("source", ""),
                                 r.get("company", ""), r.get("title", ""),
                                 r.get("manifest", "")),
                      name=lambda b: f"suppressed-{b}.jsonl")
    return survivors


def _rewrite_bucketed(directory: Path, buckets: dict, header: dict, sort_key,
                      name=lambda b: f"{b}.jsonl") -> None:
    """Rewrite one bucketed index directory; an emptied bucket loses its file.

    A full regeneration only writes buckets that have rows, so an emptied bucket
    must be removed here too or the two paths would disagree by one stale file.
    """
    for bucket, rows in buckets.items():
        path = Path(directory) / name(bucket)
        if not rows:
            if path.exists():
                path.unlink()
            continue
        rows.sort(key=sort_key)
        out = [serialization.dumps_jsonl_line(header)]
        out += [serialization.dumps_jsonl_line(r) for r in rows]
        atomic_write_text(path, "".join(out))


def _index_zone_files(index_root: Path) -> set:
    """Every generated index-zone file EXCEPT ``postings.jsonl``.

    The postings index is excluded because it is the durable floor: it is read for
    survivors and then replaced wholesale, never removed.
    """
    root = Path(index_root)
    out = {p for p in root.glob("*.jsonl") if p.name != "postings.jsonl"}
    for sub in ("by-day", "triage"):
        out |= set((root / sub).glob("*.jsonl"))
    return out


def _regen_index_zone(index_root: Path, entities, entity_seq, suppressed, built_at,
                      tombstoned=()) -> dict:
    """Regenerate the whole index zone (postings + by-day + triage) wholesale.

    "Wholesale" means the postings-index union computed by :func:`_write_index`
    (entities ∪ the pre-existing index-only survivors the floor contributes), not a
    bare rewrite from ``entities`` alone — the committed index is a durable floor,
    never dropped merely because this build's derived/raw don't cover every
    historical key. ``postings.jsonl`` is deliberately NOT unlinked here: the floor
    is read from the live file, and the write below replaces it wholesale anyway.
    Returns the survivor rows the floor contributed.

    WRITE FIRST, then remove the difference. ``by-day/`` and ``triage/`` used to be
    ``rmtree``d before ``_write_index`` ran, so any failure inside the write —
    ENOSPC is the audit's demonstration — left them missing until a later build
    regenerated them, while ``--rebuild`` (which builds the whole index into
    ``index.building`` and swaps) kept them throughout. The hole was transient, not
    permanent: ``postings.jsonl`` was already excluded, and the crash leaves the
    write-ahead marker that forces the next build to regenerate both directories.
    Transient is still a gap the rebuild path does not have, and closing it costs
    one extra listing of two directories.
    """
    index_root = Path(index_root)
    before = _index_zone_files(index_root)
    survivors, written = _write_index(index_root, entities, entity_seq, built_at,
                                      tombstoned)
    written |= _write_suppressed(index_root, suppressed, built_at)
    for stale in sorted(before - written):
        stale.unlink()
    # A wholesale regeneration with nothing to bucket leaves no directory at all —
    # that is what `--rebuild` (writing into a fresh aside) produces, and the two
    # paths must not disagree by one empty directory.
    for sub in ("by-day", "triage"):
        d = index_root / sub
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return survivors


def build_rebuild(layout, registry) -> dict:
    _recover_swap_remnants(layout)  # before ANY read of the live zones
    stamps = _stamps()
    ledger = BuildLedger(layout.build_ledger)
    blobstore = BlobStore(layout.blobs)
    manifests = list(iter_manifests(layout))
    pending = pending_manifests(layout, ledger)
    _record_pending(layout, ledger, pending)
    # A rebuild replaces derived+index wholesale; the old fold state describes the
    # generation being discarded, so it is dropped up-front and rewritten only if
    # the rebuild reaches the end. A crashed rebuild therefore leaves no cache at
    # all — the next build re-derives from raw.
    fold_state.discard(fold_state.cache_path(layout))
    fold_state.mark_incomplete(fold_state.incomplete_path(layout), "rebuild")
    (entities, suppressed, entity_seq, groups, seq_of, index_survivors, frozen_keys,
     notes) = _build_entities(
        layout, registry, stamps, manifests=manifests, blobstore=blobstore)

    _check_case_collisions(layout.derived, entities)
    _verify(entities, layout)           # annotation-orphan hard-fail before any swap
    _verify_schemas(entities, entity_seq, index_survivors)  # schema + line counts
    _spot_equivalence(entities, groups, seq_of, stamps)

    # Build ASIDE into fresh dirs, then atomically swap. The dirs are created up
    # front, not left to the first write: a build that materializes ZERO entities
    # writes no derived file, and `_swap_dir` would then raise FileNotFoundError on
    # its second rename — after the first had already moved the live `derived/` to
    # `derived.old`, leaving the zone unavailable until some later build recovered
    # the remnant. Zero entities is reachable (an empty store; a sweep whose every
    # row is suppressed; a checkout holding only the committed index), and a store
    # with nothing to derive is not an error.
    derived_new = layout.derived.with_name(layout.derived.name + ".building")
    index_new = layout.index.with_name(layout.index.name + ".building")
    for d in (derived_new, index_new):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    # The aside is freshly created, so the snapshot is empty and the sweep is a
    # no-op — a rebuild cannot inherit a stale partition. Passed anyway so no write
    # path can be written without one.
    aside_partitions = _partition_index(derived_new)
    for eb in entities.values():
        _write_entity(derived_new, eb, only_if_changed=False,
                      partitions=aside_partitions)
    # Entity-count check: exactly one derived posting per materialized entity.
    written = len(list((derived_new / "postings").rglob("posting.yaml")))
    if written != len(entities):
        raise BuildError(f"entity count mismatch: wrote {written} posting.yaml "
                         f"file(s) for {len(entities)} entities")
    built_at = _index_built_at(ledger)
    # Writes into the ASIDE dir; `_write_postings_index` reads the floor from the
    # live `index/` regardless, so the swap commits entities ∪ survivors.
    index_survivors, _written = _write_index(index_new, entities, entity_seq,
                                             built_at, frozen_keys)
    _write_suppressed(index_new, suppressed, built_at)

    _swap_dir(layout.derived, derived_new)
    _swap_dir(layout.index, index_new)
    _pin_referenced_keys(layout, entities)
    _write_readme(layout.root.parent, layout, stamps)
    _write_cache(layout, entities, _store_state(manifests, blobstore, registry),
                 ledger, _frozen_digest(layout))
    fold_state.clear_incomplete(fold_state.incomplete_path(layout))
    return {"mode": "rebuild", "entities": len(entities),
            "suppressed": len(suppressed),
            "events": sum(len(e.events) for e in entities.values()),
            "carried_from_index": len(index_survivors),
            **_report_collect_notes(notes)}


def _spot_equivalence(entities, groups, seq_of, stamps) -> None:
    """Verify ``_reduce`` is observation-ORDER-INDEPENDENT for a sample of keys.

    Re-reduces sampled keys from the already-parsed ``groups`` — once in canonical
    order and once shuffled — and requires byte-identical results. This is the
    determinism property incremental==rebuild depends on (a delta reorders which
    manifests arrive first), checked cheaply without a second full raw re-parse.

    Sampled from ``entities``: a key whose every present observation is already
    accounted for by a frozen snapshot materializes from that snapshot instead, and
    has no unseeded reduction to compare.
    """
    for key in sorted(k for k in groups if k in entities)[:5]:
        forward = serialization.dumps_yaml(_reduce(key, groups[key], seq_of, stamps).posting)
        shuffled = serialization.dumps_yaml(
            _reduce(key, list(reversed(groups[key])), seq_of, stamps).posting)
        if forward != shuffled:
            raise BuildError(f"non-deterministic reduce (order-dependent) for {key}")


def _recover_swap_remnant(current: Path) -> bool:
    """Restore a crashed swap: ``current`` absent + ``current.old`` present → rename back.

    ``_swap_dir`` opens a sub-millisecond window between its two renames in which the
    zone lives ONLY as ``<zone>.old``. A process killed there (SIGKILL, OOM, power)
    leaves exactly that state, and ``<zone>.old`` is then the only copy of the
    committed index — which is the store's durable floor (rows whose raw blobs were
    pruned and whose derived is gone exist nowhere else).

    ``current.exists()`` is the exact discriminator: a completed swap always leaves
    ``current`` present, so a present backup beside an ABSENT current can only be a
    crash remnant, and the correct action is to restore it, never to delete it. Call
    this under the builder lock BEFORE anything reads the live zone — a build that
    reads the floor as empty writes an index without it, and the swap that follows
    would then discard the remnant that still held those rows.
    """
    backup = current.with_name(current.name + ".old")
    if backup.exists() and not current.exists():
        backup.rename(current)
        return True
    return False


def _recover_swap_remnants(layout) -> None:
    """Restore any crashed-swap remnant in the zones ``_swap_dir`` touches."""
    for zone in (layout.derived, layout.index):
        if _recover_swap_remnant(zone):
            print(f"build_postings: recovered {zone.name} from {zone.name}.old "
                  f"(a previous build was killed mid-swap)", file=sys.stderr)


def _swap_dir(current: Path, new: Path) -> None:
    """Replace ``current`` with ``new`` (build-aside swap), smallest window possible.

    A directory swap cannot be a single atomic rename, so there is an unavoidable
    sub-millisecond window between the two renames where ``current`` is absent. The
    stale backup is removed BEFORE the swap so the window is exactly two back-to-back
    renames; readers tolerate a momentary missing index per the degrade-don't-block
    rule (a cold read behaves as if the store were empty, never an error).

    A crash remnant is restored first, so the up-front ``rmtree`` can only ever clear
    a backup left beside a LIVE ``current`` — i.e. a genuinely stale one.
    """
    _recover_swap_remnant(current)
    backup = current.with_name(current.name + ".old")
    if backup.exists():
        shutil.rmtree(backup)  # cleared up-front → swap is just two renames
    if current.exists():
        current.rename(backup)      # window opens
    new.rename(current)             # window closes (back-to-back)
    if backup.exists():
        shutil.rmtree(backup)


def build_opinions_only(layout, registry) -> dict:
    """Re-run classifiers over STORED facts (no raw re-read); print the diff."""
    _recover_swap_remnants(layout)  # before ANY read of the live zones
    stamps = _stamps()
    postings_root = layout.derived / "postings"
    diffs = {"visa": {}, "workplace": {}, "level": {}}
    changed_entities = 0
    entities_for_index = {}
    entity_seq = {}
    ledger = BuildLedger(layout.build_ledger)
    seq_of = _seq_map(ledger)
    conflicts_path = layout.state / "annotation-conflicts.jsonl"
    # This rewrites `posting.yaml` in place without touching the fold cache. On
    # success that is sound (nothing it rewrites is cached), but a half-finished
    # run leaves entities no later incremental build would visit — so it takes the
    # same write-ahead marker, and an interruption costs one full fold that repairs
    # them from raw.
    fold_state.mark_incomplete(fold_state.incomplete_path(layout), "opinions-only build")
    if postings_root.is_dir():
        for pyaml in sorted(postings_root.rglob("posting.yaml")):
            data = serialization.loads_yaml(pyaml.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            jd_text = _read_derived_text(pyaml.parent / "jd.md")  # bytes, as the fold
            old = data.get("opinions") or {}
            from_id = (data.get("provenance") or {}).get("fetch_ids", [""])[-1]
            new = _opinions(data.get("title", ""), data.get("location", ""),
                           jd_text, (data.get("facts") or {}).get("workplace_raw"),
                           from_id, stamps)
            # A human annotation still WINS over any re-derived opinion.
            human_facts = (data.get("human") or {}).get("facts") or {}
            if human_facts:
                _overlay_annotation(new, human_facts, conflicts_path, data.get("key", ""))
            entity_changed = False
            for field, subkey in (("visa", "label"), ("workplace", "value"),
                                  ("level", "value")):
                ov = (old.get(field) or {}).get(subkey)
                nv = (new.get(field) or {}).get(subkey)
                if ov != nv:
                    diffs[field][(ov, nv)] = diffs[field].get((ov, nv), 0) + 1
                    entity_changed = True
            if entity_changed or old != new:
                data["opinions"] = new
                atomic_write_text(pyaml, serialization.dumps_yaml(data))
                if entity_changed:
                    changed_entities += 1
            # rebuild index from the re-opinioned entities
            eb = EntityBuild(data["key"], pyaml.parent.parent.name, data, jd_text, {}, [])
            entities_for_index[data["key"]] = eb
            entity_seq[data["key"]] = min(
                (seq_of.get(fid, 0) for fid in (data.get("provenance") or {}).get("fetch_ids", [])),
                default=0)
    built_at = _index_built_at(ledger)
    survivors = {}
    if entities_for_index:
        # The rows come from `derived/` alone, so an entity whose raw AND derived are
        # both gone contributes none — `_write_postings_index` is what keeps its index
        # row alive. Same tombstone set as every other path, so the key set this
        # leaves behind is the one a build would.
        survivors, _written = _write_index(layout.index, entities_for_index,
                                           entity_seq, built_at,
                                           set(load_frozen_facts(layout)))
    fold_state.clear_incomplete(fold_state.incomplete_path(layout))
    _print_opinion_diff(diffs, changed_entities)
    return {"mode": "opinions-only", "changed": changed_entities,
            "carried_from_index": len(survivors), "diffs": diffs}


def _print_opinion_diff(diffs: dict, changed_entities: int) -> None:
    print(f"opinions-only: {changed_entities} posting(s) re-labeled")
    for field in ("visa", "workplace", "level"):
        for (ov, nv), n in sorted(diffs[field].items(), key=lambda kv: (-kv[1], str(kv[0]))):
            print(f"  {n} posting(s) changed {field} {ov}→{nv}")


# ── CLI ──────────────────────────────────────────────────────
def _resolve_root(arg: str | None) -> Path | None:
    if arg:
        return Path(arg).expanduser().resolve()
    return config.data_root()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", default=None,
                        help="store data root (default: config.data_root())")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rebuild", action="store_true",
                      help="full build-aside + verify + atomic swap")
    mode.add_argument("--opinions-only", action="store_true",
                      help="re-run classifiers over stored facts; print the diff")
    parser.add_argument("--registry", default=None,
                        help="companies.yaml path (default: skill registry)")
    args = parser.parse_args(argv)

    data_root = _resolve_root(args.data_root)
    if data_root is None:
        print("store not configured (set paths.data_root or JOBHUNT_DATA_ROOT); "
              "nothing to build.")
        return 0

    layout = domain_layout(data_root, DOMAIN)
    layout.state.mkdir(parents=True, exist_ok=True)
    registry = load_registry(args.registry)

    try:
        with DomainLock(layout.lock_path()):
            if args.rebuild:
                summary = build_rebuild(layout, registry)
            elif args.opinions_only:
                summary = build_opinions_only(layout, registry)
            else:
                summary = build_incremental(layout, registry)
    except LockContention as exc:
        print(f"build_postings: {exc}", file=sys.stderr)
        return 3
    except (BuildError, AnnotationOrphanError) as exc:
        print(f"build_postings: VERIFY FAILED — {exc}", file=sys.stderr)
        return 2

    parts = ", ".join(f"{k}={v}" for k, v in summary.items() if k != "diffs")
    print(f"build_postings: {parts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
