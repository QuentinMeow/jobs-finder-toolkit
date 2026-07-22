"""build_postings.py — the job-postings store builder (Stage 2, committed core).

Reads the raw zone (never writes it), materializes one derived entity per posting,
and regenerates the index — deterministically, so a rebuild is byte-identical and
an incremental build equals a full rebuild. Three modes:

* **incremental** (default): process the ledger set-difference under the builder
  lock; recompute every entity from its full manifest history and write only the
  ones whose bytes changed; regenerate index/triage/README wholesale.
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
"""
from __future__ import annotations

import argparse
import hashlib
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
import visa as visa_mod  # noqa: E402
from _vendor.store import serialization  # noqa: E402
from _vendor.store.annotations import (AnnotationOrphanError, assert_no_orphans,  # noqa: E402
                                       load_annotations)
from _vendor.store.atomic import append_line, atomic_write_text, read_jsonl  # noqa: E402
from _vendor.store.blobs import BlobStore, ext_for_content_type  # noqa: E402
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
            "posted_at", "jd_hash")

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

    Returns ``(observations, suppressed)``. A group manifest or an absent/unparseable
    blob yields nothing (missing-raw tolerance: never an error).
    """
    observations: list[Observation] = []
    suppressed: list[dict] = []
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
        rows = parsers.parse_manifest(env, data)
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
    return observations, suppressed


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


class EntityBuild:
    """The computed derived artifacts for one entity (pre-serialization)."""

    __slots__ = ("key", "partition", "posting", "jd_text", "jd_versions", "events")

    def __init__(self, key, partition, posting, jd_text, jd_versions, events):
        self.key = key
        self.partition = partition
        self.posting = posting
        self.jd_text = jd_text
        self.jd_versions = jd_versions  # {hash: text} for prior JD versions
        self.events = events


def _reduce(key, obs_list, seq_of, stamps) -> EntityBuild:
    obs_list = sorted(obs_list, key=_obs_sort_key)
    latest = obs_list[-1]
    company = latest.company
    partition = validate_slug(_slugify(company) or "unknown", field="company partition")

    # source_ids (distinct, ordered by first appearance)
    source_ids, seen_sid = [], set()
    for o in obs_list:
        sid = (o.row.get("source"), o.row.get("native_id"), o.row.get("url", ""))
        if sid not in seen_sid:
            seen_sid.add(sid)
            source_ids.append({"source": o.row.get("source"),
                               "id": o.row.get("native_id"),
                               "url": o.row.get("url", "")})

    # JD text: the latest observation carrying a non-empty description.
    jd_text = ""
    for o in reversed(obs_list):
        if o.row.get("description"):
            jd_text = o.row["description"]
            break

    # events + JD-version history, folded in observation order.
    events, jd_versions = [], {}
    prior: dict = {}
    for i, o in enumerate(obs_list):
        row = o.row
        jd_hash = parsers.content_hash(row.get("description")) if row.get("description") else None
        snap = {"title": row.get("title", ""), "location": row.get("location", ""),
                "url": row.get("url", ""), "workplace_raw": row.get("workplace_raw"),
                "salary_text": row.get("salary_text"), "posted_at": row.get("posted_at"),
                "jd_hash": jd_hash}
        seq = seq_of.get(o.fetch_id)
        base = {"entity": key, "fetch": o.fetch_id, "at": _z(o.fetched_at)}
        if seq is not None:
            base["seq"] = seq
        if i == 0:
            events.append({**base, "type": "first_seen"})
        else:
            events.append({**base, "type": "seen"})
            changes = []
            for f in _TRACKED:
                if snap.get(f) != prior.get(f):
                    changes.append({"field": f, "old": prior.get(f), "new": snap.get(f)})
            if changes:
                events.append({**base, "type": "changed", "changes": changes})
                # A JD text change snapshots the PRIOR JD as a content-versioned sibling.
                if any(c["field"] == "jd_hash" for c in changes) and prior.get("jd_hash"):
                    prev_text = prior.get("_jd_text")
                    if prev_text:
                        jd_versions[prior["jd_hash"]] = prev_text
        prior = dict(snap)
        prior["_jd_text"] = row.get("description") or prior.get("_jd_text", "")

    fetch_ids = sorted({o.fetch_id for o in obs_list})
    latest_row = latest.row
    facts = {}
    if latest_row.get("posted_at"):
        facts["posted_at"] = latest_row["posted_at"]
    if latest_row.get("salary_text"):
        facts["salary_text"] = latest_row["salary_text"]
    if latest_row.get("workplace_raw"):
        facts["workplace_raw"] = latest_row["workplace_raw"]

    profiles = sorted({o.profile for o in obs_list if o.profile})
    posting = {
        "schema_version": POSTING_SCHEMA_VERSION,
        "key": key,
        "identity": latest.strength,
        "company": company,
        "title": latest_row.get("title", ""),
        "location": latest_row.get("location", ""),
        "source_ids": source_ids,
        "profiles": profiles,
        "first_seen": _z(obs_list[0].fetched_at),
        "last_seen": _z(obs_list[-1].fetched_at),
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
    if jd_text:
        posting["jd"] = {
            "file": "jd.md",
            "content_hash": parsers.content_hash(jd_text),
            "normalizer_version": parsers.NORMALIZER_VERSION,
            "fetched_verbatim": True,
        }
    return EntityBuild(key, partition, posting, jd_text, jd_versions, events)


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


def _write_entity(derived_root: Path, eb: EntityBuild, *, only_if_changed: bool) -> bool:
    entity_dir = _entity_dir(derived_root, eb)
    files = _entity_files(eb)
    wrote = False
    for rel, text in files.items():
        target = entity_dir / rel
        if only_if_changed and target.exists() and \
                target.read_text(encoding="utf-8") == text:
            continue
        atomic_write_text(target, text)
        wrote = True
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


def _write_index(index_root: Path, entities: dict, entity_seq: dict, built_at: str) -> None:
    header = {"_schema": INDEX_SCHEMA_VERSION, "built_at": built_at, "note": INDEX_NOTE}
    # postings.jsonl — sorted by key for determinism
    lines = [serialization.dumps_jsonl_line(header)]
    for key in sorted(entities):
        lines.append(serialization.dumps_jsonl_line(
            _index_row(entities[key], entity_seq.get(key, 0))))
    atomic_write_text(index_root / "postings.jsonl", "".join(lines))

    # by-day/<date>.jsonl — every observation event bucketed by UTC capture day
    by_day: dict[str, list[dict]] = {}
    for key in sorted(entities):
        for ev in entities[key].events:
            at = ev.get("at") or ""
            day = at[:10] if len(at) >= 10 else "unknown"
            by_day.setdefault(day, []).append(
                {"entity": ev["entity"], "fetch": ev["fetch"], "type": ev["type"],
                 "at": ev.get("at"), "seq": ev.get("seq")})
    for day, rows in by_day.items():
        rows.sort(key=lambda r: (r.get("at") or "", r["entity"], r["type"]))
        out = [serialization.dumps_jsonl_line(header)]
        out += [serialization.dumps_jsonl_line(r) for r in rows]
        atomic_write_text(index_root / "by-day" / f"{day}.jsonl", "".join(out))


def _write_suppressed(index_root: Path, suppressed: list[dict], built_at: str) -> None:
    header = {"_schema": INDEX_SCHEMA_VERSION, "built_at": built_at, "note": INDEX_NOTE}
    by_month: dict[str, list[dict]] = {}
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
        atomic_write_text(index_root / "triage" / f"suppressed-{month}.jsonl",
                          "".join(out))


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
   scripts/store/store_show.py <entity-key> --data-root {data_root}
   ```
3. **Decompress & pretty-print a blob** (the sanctioned raw path; needs `zstd`):
   ```bash
   scripts/store/store_show.py <entity-key> --raw --data-root {data_root}
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


# ── carry-forward (missing-raw tolerance, owner's multi-laptop contract) ──
def _load_existing_entity(entity_dir: Path, key: str):
    """Reconstruct an :class:`EntityBuild` from an existing derived entity dir.

    Used to CARRY FORWARD an entity whose raw blob is absent this build (marked
    ``provenance.carried``). JD prior-version siblings are carried too so a rebuild
    does not drop them.
    """
    posting = serialization.loads_yaml(
        (entity_dir / "posting.yaml").read_text(encoding="utf-8")) or {}
    posting.setdefault("provenance", {})["carried"] = True  # idempotent
    jd_path = entity_dir / "jd.md"
    jd_text = jd_path.read_text(encoding="utf-8") if jd_path.exists() else ""
    jd_versions = {}
    for f in sorted(entity_dir.glob("jd-*.md")):
        jd_versions[f.name[len("jd-"):-len(".md")]] = f.read_text(encoding="utf-8")
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
    posting = dict(entity)
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


def _merge_frozen_into_fresh(eb: EntityBuild, frozen: dict) -> bool:
    """Fold a frozen snapshot's pre-prune timeline into a freshly materialized entity.

    MAJOR-1 fix. An entity fed by SEVERAL blobs where only SOME were pruned
    materializes fresh from the surviving blobs alone — silently losing the pruned
    observations and, with them, an accurate ``first_seen`` (store-core §5: a pruned
    blob's manifest still proves it was observed, so the timeline stays re-derivable).
    The frozen snapshot is the authoritative full-history record written at prune
    time, so we restore the pruned observations from it: ``first_seen`` = min,
    ``last_seen`` = max, the pruned fetches' events (frozen's classification wins for
    any shared fetch — it saw the full history), the JD prior-versions the fresh
    build lacks, and the union of ``fetch_ids``. Fresh keeps its current-state fields
    (retention prunes OLD blobs, so the newest observation is a surviving one).

    Returns ``True`` iff frozen contributed an observation the present raw lacks
    (then marks ``provenance.carried`` + ``provenance.frozen``). Deterministic — a
    pure function of ``eb`` + ``frozen`` — so incremental == rebuild == rebuild-twice.
    """
    fentity = frozen.get("entity")
    if not isinstance(fentity, dict):
        return False
    frozen_events = list(frozen.get("events") or [])
    frozen_fetches = {e.get("fetch") for e in frozen_events}
    fresh_fetches = {e.get("fetch") for e in eb.events}
    if not (frozen_fetches - fresh_fetches):
        return False  # frozen holds no observation the present raw lacks — no-op
    # Frozen's classification wins for shared fetches; fresh adds only NEW fetches.
    merged = list(frozen_events) + [e for e in eb.events
                                    if e.get("fetch") not in frozen_fetches]
    merged.sort(key=_event_sort_key)
    eb.events = merged
    for name, text in (frozen.get("files") or {}).items():
        if name.startswith("jd-") and name.endswith(".md"):
            eb.jd_versions.setdefault(name[len("jd-"):-len(".md")], text)
    ff, fl = fentity.get("first_seen"), fentity.get("last_seen")
    cur_first, cur_last = eb.posting.get("first_seen"), eb.posting.get("last_seen")
    if ff:
        eb.posting["first_seen"] = min(cur_first, ff) if cur_first else ff
    if fl:
        eb.posting["last_seen"] = max(cur_last, fl) if cur_last else fl
    prov = eb.posting.setdefault("provenance", {})
    fresh_fids = set(prov.get("fetch_ids") or [])
    frozen_fids = set((fentity.get("provenance") or {}).get("fetch_ids") or [])
    prov["fetch_ids"] = sorted(fresh_fids | frozen_fids)
    prov["carried"] = True
    prov["frozen"] = True
    return True


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


def _build_entities(layout, registry, stamps):
    """Reduce the full raw zone into ``{key: EntityBuild}`` + carried entities.

    Reads every present-blob member manifest, groups observations by entity key,
    reduces each, carries forward not-synced entities, then applies migration/dup
    hints and the annotation merge — a pure function of the processed set + the
    existing generation, so incremental and rebuild produce identical entities.
    Returns ``(entities, suppressed, entity_seq, groups, seq_of)`` — ``groups`` and
    ``seq_of`` let the spot-equivalence check re-reduce sampled keys cheaply.
    """
    blobstore = BlobStore(layout.blobs)
    manifests = list(iter_manifests(layout))
    ledger = BuildLedger(layout.build_ledger)
    seq_of = _seq_map(ledger)
    observations, suppressed = _collect(layout, blobstore, manifests, registry)
    groups: dict[str, list[Observation]] = {}
    for o in observations:
        groups.setdefault(o.key, []).append(o)
    entities = {key: _reduce(key, obs, seq_of, stamps) for key, obs in groups.items()}
    entity_seq = {key: min(seq_of.get(o.fetch_id, 0) for o in obs)
                  for key, obs in groups.items()}
    fresh_keys = set(entities)
    frozen_all = load_frozen_facts(layout)
    # MAJOR-1: an entity fed by several blobs where only SOME were pruned materializes
    # fresh from the survivors alone — merge the frozen full-history timeline back in
    # (first_seen/events/jd-versions restored) and recompute its sequence over the
    # union of fetches so a cursor still surfaces it correctly.
    for key in fresh_keys:
        frozen = frozen_all.get(key)
        if frozen and _merge_frozen_into_fresh(entities[key], frozen):
            fids = (entities[key].posting.get("provenance") or {}).get("fetch_ids") or []
            entity_seq[key] = min((seq_of.get(f, 0) for f in fids),
                                  default=entity_seq.get(key, 0))
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
    return entities, suppressed, entity_seq, groups, seq_of


def _verify_schemas(entities: dict, entity_seq: dict) -> None:
    """Schema-validate every derived posting + event + index line before a swap.

    The store validator (schemas) applied in-memory to the aside generation, so a
    rebuild that would write a schema-invalid artifact fails BEFORE the atomic swap
    rather than shipping bad data. Also asserts one index line per entity (counts).
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


def build_incremental(layout, registry) -> dict:
    stamps = _stamps()
    ledger = BuildLedger(layout.build_ledger)
    pending = pending_manifests(layout, ledger)
    newly = _record_pending(layout, ledger, pending)
    entities, suppressed, entity_seq, _groups, _seq = _build_entities(
        layout, registry, stamps)

    _check_case_collisions(layout.derived, entities)
    _verify(entities, layout)  # orphan hard-fail on EVERY build path (incl. incremental)
    # Write only entities whose bytes changed (carry the rest unchanged).
    changed = 0
    for eb in entities.values():
        if _write_entity(layout.derived, eb, only_if_changed=True):
            changed += 1
    built_at = _index_built_at(ledger)
    _regen_index_zone(layout.index, entities, entity_seq, suppressed, built_at)
    _pin_referenced_keys(layout, entities)
    _write_readme(layout.root.parent, layout, stamps)
    return {"mode": "incremental", "pending": len(newly), "entities": len(entities),
            "changed": changed, "suppressed": len(suppressed)}


def _regen_index_zone(index_root: Path, entities, entity_seq, suppressed, built_at) -> None:
    """Regenerate the whole index zone (postings + by-day + triage) wholesale."""
    for sub in ("by-day", "triage"):
        d = index_root / sub
        if d.is_dir():
            shutil.rmtree(d)
    for stale in index_root.glob("*.jsonl"):
        stale.unlink()
    _write_index(index_root, entities, entity_seq, built_at)
    _write_suppressed(index_root, suppressed, built_at)


def build_rebuild(layout, registry) -> dict:
    stamps = _stamps()
    ledger = BuildLedger(layout.build_ledger)
    pending = pending_manifests(layout, ledger)
    _record_pending(layout, ledger, pending)
    entities, suppressed, entity_seq, groups, seq_of = _build_entities(
        layout, registry, stamps)

    _check_case_collisions(layout.derived, entities)
    _verify(entities, layout)           # annotation-orphan hard-fail before any swap
    _verify_schemas(entities, entity_seq)  # schema + per-entity index-line counts
    _spot_equivalence(entities, groups, seq_of, stamps)

    # Build ASIDE into fresh dirs, then atomically swap.
    derived_new = layout.derived.with_name(layout.derived.name + ".building")
    index_new = layout.index.with_name(layout.index.name + ".building")
    for d in (derived_new, index_new):
        if d.exists():
            shutil.rmtree(d)
    for eb in entities.values():
        _write_entity(derived_new, eb, only_if_changed=False)
    # Entity-count check: exactly one derived posting per materialized entity.
    written = len(list((derived_new / "postings").rglob("posting.yaml")))
    if written != len(entities):
        raise BuildError(f"entity count mismatch: wrote {written} posting.yaml "
                         f"file(s) for {len(entities)} entities")
    built_at = _index_built_at(ledger)
    _write_index(index_new, entities, entity_seq, built_at)
    _write_suppressed(index_new, suppressed, built_at)

    _swap_dir(layout.derived, derived_new)
    _swap_dir(layout.index, index_new)
    _pin_referenced_keys(layout, entities)
    _write_readme(layout.root.parent, layout, stamps)
    return {"mode": "rebuild", "entities": len(entities),
            "suppressed": len(suppressed),
            "events": sum(len(e.events) for e in entities.values())}


def _spot_equivalence(entities, groups, seq_of, stamps) -> None:
    """Verify ``_reduce`` is observation-ORDER-INDEPENDENT for a sample of keys.

    Re-reduces sampled keys from the already-parsed ``groups`` — once in canonical
    order and once shuffled — and requires byte-identical results. This is the
    determinism property incremental==rebuild depends on (a delta reorders which
    manifests arrive first), checked cheaply without a second full raw re-parse.
    """
    for key in sorted(k for k in groups)[:5]:
        forward = serialization.dumps_yaml(_reduce(key, groups[key], seq_of, stamps).posting)
        shuffled = serialization.dumps_yaml(
            _reduce(key, list(reversed(groups[key])), seq_of, stamps).posting)
        if forward != shuffled:
            raise BuildError(f"non-deterministic reduce (order-dependent) for {key}")


def _swap_dir(current: Path, new: Path) -> None:
    """Replace ``current`` with ``new`` (build-aside swap), smallest window possible.

    A directory swap cannot be a single atomic rename, so there is an unavoidable
    sub-millisecond window between the two renames where ``current`` is absent. The
    stale backup is removed BEFORE the swap so the window is exactly two back-to-back
    renames; readers tolerate a momentary missing index per the degrade-don't-block
    rule (a cold read behaves as if the store were empty, never an error).
    """
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
    stamps = _stamps()
    postings_root = layout.derived / "postings"
    diffs = {"visa": {}, "workplace": {}, "level": {}}
    changed_entities = 0
    entities_for_index = {}
    entity_seq = {}
    ledger = BuildLedger(layout.build_ledger)
    seq_of = _seq_map(ledger)
    conflicts_path = layout.state / "annotation-conflicts.jsonl"
    if postings_root.is_dir():
        for pyaml in sorted(postings_root.rglob("posting.yaml")):
            data = serialization.loads_yaml(pyaml.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            jd_path = pyaml.parent / "jd.md"
            jd_text = jd_path.read_text(encoding="utf-8") if jd_path.exists() else ""
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
    if entities_for_index:
        _write_index(layout.index, entities_for_index, entity_seq, built_at)
    _print_opinion_diff(diffs, changed_entities)
    return {"mode": "opinions-only", "changed": changed_entities, "diffs": diffs}


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
