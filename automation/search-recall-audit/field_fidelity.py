#!/usr/bin/env python3
"""field-fidelity audit — is the GENERATED ``location`` field faithful to the RAW?

A sibling of ``audit.py`` (recall/precision) that asks a different question: the
job-search builder turns each raw source payload into a normalized posting whose
``location`` string the location GATE then reads. **Does that generated string
drop or mangle location information that the ORIGINAL RAW payload carried?** — the
classic failure being a multi-location role written with a slash / mixed
separators ("Austin/NYC", "SF, CA / New York, NY, Atlanta, GA") or a source
whose secondary/office locations the parser never folds in.

It is read-only on the store and the pipeline (imports the SAME per-source parsers
the builder uses, plus the SAME location classifier the gate uses), and writes
ONLY to a gitignored scratch dir (default ``local/field_fidelity_audit/``).

Subcommands
-----------
  corpus   Walk the derived store index, resolve each sampled entity's RAW blob,
           extract a per-source ``raw_location_view`` (EVERY location-bearing
           field in the raw job object) + the ``jd.md`` location lines, compare
           against the stored generated ``location``, and flag deterministic
           suspicions (dropped raw location token, gate-decision flip, weird
           format). Blobs are decompressed once and cached (many entities share
           one board blob), so a few-hundred sample is cheap.
  sample   Pick N per source (weighting the suspicious ones) and write one
           self-contained comparison file per entity for a composer subagent to
           judge: raw view + generated field + jd lines + both gate decisions.
  check    Deterministic single-entity (``--key``) re-parse: print the raw
           location fields, what the CURRENT parser generates, what is STORED,
           and the location-gate decision for each — the root-cause step that
           turns a subagent "looks dropped" into "the parser drops X".
  todo     Scan the store index/derived postings and write every
           ``weird_location_format`` review to a JSONL investigation queue.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

# ── path bootstrap (config + the job-search skill we audit) ──────────────────
def _find_repo_root(start: Path) -> Path:
    """The repo root above ``start``, found by walking UP — never by counting.

    A fixed ``parents[N]`` encodes this file's depth and breaks the moment the
    folder moves (this one already moved, from
    ``automation/maintenance/search_recall_audit/`` to
    ``automation/search-recall-audit/``). Markers, in order of authority:
    ``.git`` — the project boundary, tested with ``exists()`` because a git
    WORKTREE's ``.git`` is a FILE — then ``config.example.yaml``, the toolkit's
    tracked root marker, so a ``.git``-less export still resolves. This mirrors
    ``automation/shared/config.py``'s ``_git_boundary()``/``_repo_root()``; it
    is reproduced rather than imported because the root is what puts ``config``
    on ``sys.path`` in the first place.
    """
    for marker in (".git", "config.example.yaml"):
        for parent in (start, *start.parents):
            if (parent / marker).exists():
                return parent
    return start


REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
_JS = REPO_ROOT / "skills" / "job-search" / "scripts"
for _p in (REPO_ROOT / "automation" / "shared", _JS, _JS / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import config  # noqa: E402
import location as location_mod  # noqa: E402  (vendored gate classifier)
import posting_parsers as parsers  # noqa: E402  (the builder's own parsers)
from store import blobs as _blobs  # noqa: E402
from store import resolver, serialization  # noqa: E402
from store.manifest import iter_manifests  # noqa: E402
from store.paths import domain_layout  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "local" / "field_fidelity_audit"
DOMAIN = "jobs"

# Where each source's job list lives in its raw payload + the id field the parser
# keyed on, so we can re-find the exact raw job object for one stored entity.
_RAW_LOCATORS = {
    "greenhouse": (("jobs",), "id"),
    "ashby": (("jobs",), "id"),
    "lever": ((), "id"),  # top-level list
    "smartrecruiters": (("content",), "id"),
    "amazon": (("jobs",), "id"),
    "apple": (("res", "searchResults"), "positionId"),
    "meta": (("data", "job_search_with_featured_jobs", "all_jobs"), "id"),
    "jobicy": (("jobs",), "id"),
    "remoteok": ((), "id"),
    "themuse": (("results",), "id"),
    "workday": (("jobPostings",), None),  # id is a derived req token — match by url
}

_DESC_KEYS = ("content", "descriptionHtml", "descriptionPlain", "description",
              "additional", "additionalPlain", "jobSummary", "contents",
              "basic_qualifications", "preferred_qualifications", "jobDescription",
              "jobExcerpt")


# ── raw location extraction (per source: EVERY location-bearing field) ───────
def raw_location_view(source: str, job: dict) -> dict:
    """Pull every location-bearing field from one raw job object (no description)."""
    v: dict = {}
    if source == "greenhouse":
        v["location.name"] = (job.get("location") or {}).get("name")
        offs = job.get("offices") or []
        v["offices[].name"] = [o.get("name") for o in offs if isinstance(o, dict)]
        v["offices[].location"] = [o.get("location") for o in offs
                                   if isinstance(o, dict) and o.get("location")]
    elif source == "ashby":
        v["location"] = job.get("location")
        v["secondaryLocations[].location"] = [
            s.get("location") for s in (job.get("secondaryLocations") or [])
            if isinstance(s, dict) and s.get("location")]
        v["isRemote"] = job.get("isRemote")
        v["workplaceType"] = job.get("workplaceType")
        addr = ((job.get("address") or {}).get("postalAddress") or {})
        if addr:
            v["address"] = {k: addr.get(k) for k in
                            ("addressLocality", "addressRegion", "addressCountry")}
    elif source == "lever":
        cats = job.get("categories") or {}
        v["categories.location"] = cats.get("location")
        v["categories.allLocations"] = cats.get("allLocations")
        v["workplaceType"] = job.get("workplaceType")
        v["country"] = job.get("country")
    elif source == "apple":
        locs = job.get("locations") or []
        v["locations[].name"] = [x.get("name") for x in locs if isinstance(x, dict)]
        v["locations[].countryName"] = [x.get("countryName") for x in locs
                                        if isinstance(x, dict)]
        v["homeOffice"] = job.get("homeOffice")
    elif source == "meta":
        v["locations"] = job.get("locations")
    elif source == "smartrecruiters":
        loc = job.get("location") or {}
        v["location"] = {k: loc.get(k) for k in
                         ("city", "region", "country", "remote", "hybrid")}
    elif source == "amazon":
        v["normalized_location"] = job.get("normalized_location")
        v["city/state/country_code"] = [job.get("city"), job.get("state"),
                                        job.get("country_code")]
    elif source == "themuse":
        v["locations[].name"] = [l.get("name") for l in (job.get("locations") or [])
                                 if isinstance(l, dict)]
    elif source == "jobicy":
        v["jobGeo"] = job.get("jobGeo")
    elif source == "remoteok":
        v["location"] = job.get("location")
    elif source == "workday":
        v["locationsText"] = job.get("locationsText")
    return {k: val for k, val in v.items() if val not in (None, [], {}, "")}


# ── raw-job resolution (ONE implementation, shared by `corpus` and `check`) ───
# Sources whose ``native_id`` is DERIVED from the payload rather than read from a
# single field. The value is the PARSER'S OWN derivation, imported rather than
# re-implemented: the audit's key and the builder's key then cannot drift, and a
# rename in ``posting_parsers`` breaks this at import time instead of silently
# returning ``None`` for every job of that source.
_DERIVED_NATIVE_ID = {"workday": parsers._workday_req}


def _job_native_id(source: str, job: dict) -> str | None:
    """The identity the parser keys on — matches ``parse_*``'s ``native_id``.

    Workday's locator carries no ``id`` field because its requisition token is
    derived (``bulletFields[0]``, else the ``externalPath`` tail). That is still
    an identity, and a STABLE one: both candidates are properties of the
    requisition, not of the fetch, and it is the very token the store already
    assigned the entity (``source_ids[].id``). Returning ``None`` here left every
    id-less posting unresolvable against its own raw payload.
    """
    derive = _DERIVED_NATIVE_ID.get(source)
    if derive is not None:
        val = derive(job)
        return str(val) if val not in (None, "") else None
    _list, id_field = _RAW_LOCATORS.get(source, ((), None))
    if id_field is None:
        return None
    val = job.get(id_field)
    return str(val) if val not in (None, "") else None


def _jobs_in_payload(source: str, data) -> list[dict]:
    """Every raw job object in one decoded payload, per the source's list path."""
    if data is None or source not in _RAW_LOCATORS:
        return []
    list_path, _id_field = _RAW_LOCATORS[source]
    node = data
    for k in list_path:
        node = node.get(k, {}) if isinstance(node, dict) else {}
    return [j for j in (node if isinstance(node, list) else []) if isinstance(j, dict)]


def _raw_jobs_by_id(source: str, data) -> dict[str, dict]:
    """``native_id`` -> raw job object, keyed exactly as the parser keys its rows."""
    out: dict[str, dict] = {}
    for j in _jobs_in_payload(source, data):
        nid = _job_native_id(source, j)
        if nid is not None:
            out[nid] = j
    return out


# location tokens (lowercased words/phrases) that the gate cares about, used for a
# deterministic "did the generated field drop a raw token?" heuristic.
def _loc_tokens(text: str) -> set[str]:
    n = location_mod._normalize(text)
    # split on separators the gate keeps meaningful; keep multiword city fragments
    parts = re.split(r"[/,;|]| - |\bor\b|\band\b", n)
    out = set()
    for p in parts:
        p = p.strip(" -")
        if p and p not in {"", "us", "remote", "hybrid", "onsite"}:
            out.add(p)
    return out


def _flatten_raw_tokens(view: dict) -> set[str]:
    toks: set[str] = set()

    def walk(x):
        if isinstance(x, str):
            toks.update(_loc_tokens(x))
        elif isinstance(x, list):
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            for i in x.values():
                walk(i)

    walk(view)
    return {t for t in toks if t and not re.fullmatch(r"(true|false|onsite|remote|"
                                                      r"hybrid|united states)", t)}


def _assess(location: str, policy: dict, *, title: str = "", jd: str = "",
            workplace_hint: str = "", source: str = ""):
    """THE gate call — the exact evidence set ``scoring.location_ok`` passes.

    **Every command in this file routes through here.** A caller that omits an
    argument does not get a weaker version of the gate's decision, it gets a
    DIFFERENT one, and wrong in both directions: ``assess_location`` reads the
    title in the rejecting direction (a foreign city in the title drops a
    "Remote" posting → reported kept when the gate drops it), and the workplace
    hint is what carries a non-metro US office to ``us_remote`` (a board that
    parks "Remote" in its own field → reported dropped when the gate keeps it).
    An audit whose "gate decision" is not the gate's decision selects its own
    sample by a decision the pipeline never made, so this signature is the whole
    contract: pass what the pipeline passes.
    """
    return location_mod.assess_location(
        location,
        policy,
        title=title or "",
        description=jd or "",
        workplace_hint=str(workplace_hint or ""),
        hint_trusted=not str(source or "").startswith("jobspy:"),
    )


def _gate_decision(location: str, policy: dict, **evidence) -> dict:
    """The summary triple of :func:`_assess`, for corpus rows and ``check``."""
    a = _assess(location, policy, **evidence)
    return {"category": a.category, "decision": a.decision, "workplace": a.workplace}


# ── blob cache (decompress each board blob once) ─────────────────────────────
class _RawStore:
    def __init__(self, layout):
        self.layout = layout
        self.bs = _blobs.BlobStore(layout.blobs)
        self._cache: dict[str, object] = {}

    def job_for(self, entity: dict):
        """Return (source, raw_job_dict) for a derived entity, or (source, None)."""
        src0 = (entity.get("source_ids") or [{}])[0]
        source = src0.get("source")
        native_id = src0.get("id")
        url = src0.get("url", "")
        payload = resolver.resolve_blob(self.layout, entity)
        if not payload:
            return source, None
        sha = payload["blob"]
        ext = _blobs.ext_for_content_type(payload.get("content_type"))
        key = f"{sha}.{ext}"
        if key not in self._cache:
            try:
                if self.bs.state(sha, ext) != _blobs.PRESENT:
                    self._cache[key] = None
                else:
                    self._cache[key] = json.loads(
                        self.bs.read(sha, ext).decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                self._cache[key] = None
        data = self._cache[key]
        if data is None or source not in _RAW_LOCATORS:
            return source, None
        # Same key `corpus` builds its index with — one resolution, no drift.
        job = _raw_jobs_by_id(source, data).get(str(native_id))
        if job is not None:
            return source, job
        # Fallback for an entity whose stored id predates a parser change: match
        # the posting page by its site-relative path. An EMPTY externalPath must
        # not match (``"" in url`` is always true, which returned the first job).
        for j in _jobs_in_payload(source, data):
            ext = j.get("externalPath") or ""
            if ext and url and ext in url:
                return source, j
        return source, None


def _jd_location_lines(entity_dir: Path) -> list[str]:
    jd = entity_dir / "jd.md"
    if not jd.exists():
        return []
    text = jd.read_text(encoding="utf-8", errors="replace")
    named = location_mod.extract_jd_locations(text)
    pat = re.compile(r"\b(remote|hybrid|on-?site|located|location|relocat|"
                     r"office|based in|work from)\b", re.I)
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and pat.search(ln)]
    # de-dupe, cap, prefer the explicit "Location:" values first
    seen, out = set(), []
    for ln in [f"Location: {v}" for v in named] + lines:
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
        if len(out) >= 8:
            break
    return out


# ── corpus ───────────────────────────────────────────────────────────────────
_MAX_CONTINUATION_LINES = 4   # a real row spans a few physical lines at most


def _iter_index(layout) -> tuple[list[dict], int]:
    """Tolerant JSONL read -> ``(rows, skipped)``. **Never truncates.**

    A few legacy index rows carry an embedded newline in a scraped company name,
    so continuation lines are folded in until the buffer parses. Two rules keep
    that tolerance from eating the file:

    * A buffer is GIVEN UP on — counted, not silently swallowed — as soon as it
      cannot be a row: the next physical line opens a new object (a continuation
      never starts with ``{``), or it has absorbed more lines than any real row
      spans. Without this, one torn write glued every following line onto a
      buffer that could never parse, so ``todo`` reported a confident count over
      a truncated index and exited 0.
    * The accumulated buffer is parsed with ``strict=False``. A RAW newline
      inside a JSON string — exactly the legacy shape this reader documents — is
      a control character that ``json.loads`` rejects in its default strict mode,
      so those rows could never have parsed however many lines were folded in.

    Callers report ``skipped``: an audit tool must state that it read less than
    the whole index rather than let the reader decide silently.
    """
    rows: list[dict] = []
    skipped = 0
    buf = ""
    for ln in (layout.index / "postings.jsonl").read_text(
            encoding="utf-8", errors="replace").splitlines():
        if buf and ln.lstrip().startswith("{"):
            skipped += 1        # the pending buffer can never complete
            buf = ""
        if not ln.strip() and not buf:
            continue
        buf = f"{buf}\n{ln}" if buf else ln
        try:
            r = json.loads(buf, strict=False)
        except json.JSONDecodeError:
            if buf.count("\n") >= _MAX_CONTINUATION_LINES:
                skipped += 1
                buf = ""
            continue  # incomplete row — fold in the next physical line
        buf = ""
        if isinstance(r, dict) and r.get("key"):
            rows.append(r)
    if buf.strip():
        skipped += 1
    return rows, skipped


def _resolve_out(args) -> Path:
    """The scratch dir for ANY writing command, containment-checked.

    The module docstring states an absolute — "writes ONLY to a gitignored
    scratch dir" — and every artifact here (corpus rows, per-case Markdown, the
    todo queue) carries posting URLs and company-derived location fields out of
    the owner's store. Pointed at a tracked folder that lands in the public tree,
    and company names are not identity tokens, so the leak guard would not stop
    it. One helper, so a command cannot be added without the guard.
    """
    out = Path(args.out).expanduser().resolve()
    local_root = (REPO_ROOT / "local").resolve()
    if not out.is_relative_to(local_root):
        sys.exit(f"`{args.cmd}` output must stay under {local_root}")
    out.mkdir(parents=True, exist_ok=True)
    return out


def cmd_todo(args) -> None:
    """Write weird/unresolvable location reviews for later AI investigation."""
    out = _resolve_out(args)

    layout = domain_layout(config.data_root(), DOMAIN)
    policy = config.location_policy()
    todos: list[dict] = []
    by_source: dict[str, int] = {}

    index_rows, skipped_rows = _iter_index(layout)
    for index_row in index_rows:
        location = index_row.get("location", "") or ""
        title = index_row.get("title", "") or ""
        # Adding the raw hint/JD below can only supply a resolving signal, so use
        # the cheap index fields to avoid resolving every derived entity.
        preliminary = location_mod.assess_location(
            location, policy, title=title)
        if "weird_location_format" not in preliminary.review_reasons:
            continue

        found = resolver.load_entity(layout, index_row["key"])
        if found:
            yaml_path, entity = found
        else:
            yaml_path, entity = None, index_row

        location = entity.get("location", location) or ""
        title = entity.get("title", title) or ""
        source_ids = entity.get("source_ids") or []
        source = (
            (source_ids[0].get("source") if source_ids else None)
            or index_row.get("source")
            or "unknown"
        )
        workplace_hint = (entity.get("facts") or {}).get("workplace_raw") or ""
        description = ""
        if yaml_path is not None:
            jd_file = (entity.get("jd") or {}).get("file") or "jd.md"
            jd_path = yaml_path.parent / jd_file
            if jd_path.exists():
                description = jd_path.read_text(
                    encoding="utf-8", errors="replace")

        assessment = _assess(location, policy, title=title, jd=description,
                             workplace_hint=workplace_hint, source=source)
        if "weird_location_format" not in assessment.review_reasons:
            continue

        url = index_row.get("canonical_url") or ""
        if not url and source_ids:
            url = source_ids[0].get("url") or ""
        todos.append({
            "key": index_row["key"],
            "source": source,
            "company": entity.get("company", index_row.get("company", "")),
            "title": title,
            "location": location,
            "workplace_hint": workplace_hint,
            "url": url,
            "review_reason": "weird_location_format",
            "assessment": assessment.to_dict(),
        })
        by_source[source] = by_source.get(source, 0) + 1

    todo_path = out / "location_todo.jsonl"
    todo_path.write_text(
        "".join(json.dumps(item, default=str, sort_keys=True) + "\n"
                for item in todos),
        encoding="utf-8",
    )
    source_summary = ", ".join(
        f"{source}={count}" for source, count in sorted(by_source.items()))
    if skipped_rows:
        print(f"todo: WARNING — {skipped_rows} unparseable index row(s) skipped; "
              f"the counts below cover the rest of the index.", file=sys.stderr)
    print(f"todo: {len(todos)} weird-location postings "
          f"[{source_summary or 'none'}] from {len(index_rows)} index rows "
          f"({skipped_rows} unparseable) -> {todo_path}")


def _flags_for(gen_loc: str, dropped: list[str], flip: bool) -> list[str]:
    flags = []
    if dropped:
        flags.append("dropped_raw_token")
    if flip:
        flags.append("gate_decision_flip")
    if (gen_loc.count("United States") > 1
            or re.search(r"\b(\w+)\b of america \1\b", gen_loc, re.I)):
        flags.append("duplicated_country")
    if "  " in gen_loc or re.search(r"[A-Za-z]/[A-Za-z]", gen_loc):
        flags.append("weird_separator")
    return flags


def cmd_corpus(args) -> None:
    """Iterate the raw zone directly (dedup by blob sha), re-run the SAME parser the
    builder uses, and compare its generated ``location`` against every raw location
    field of the same job. Fast + full-scale: no per-entity glob resolution."""
    out = _resolve_out(args)
    layout = domain_layout(config.data_root(), DOMAIN)
    policy = config.location_policy()
    bs = _blobs.BlobStore(layout.blobs)

    # newest observation wins (matches the store's latest-row generated field)
    best: dict[tuple, dict] = {}
    seen_blobs: set[str] = set()
    n_manifests = n_blobs = n_rows = 0
    for _path, env in iter_manifests(layout):
        if env.get("operation") == "group" or env.get("kind") == "group":
            continue
        source = env.get("source")
        if source not in _RAW_LOCATORS:
            continue
        payload = env.get("payload")
        if not (isinstance(payload, dict) and payload.get("blob")):
            continue
        n_manifests += 1
        sha = payload["blob"]
        ext = _blobs.ext_for_content_type(payload.get("content_type"))
        if sha in seen_blobs:
            continue  # a blob's rows are identical across manifests referencing it
        seen_blobs.add(sha)
        try:
            if bs.state(sha, ext) != _blobs.PRESENT:
                continue
            data = bs.read(sha, ext)
        except Exception:  # noqa: BLE001
            continue
        n_blobs += 1
        try:
            raw_json = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            raw_json = None
        # native_id -> raw job object (for the raw_location_view), keyed by the
        # SAME helper `check` resolves with.
        job_by_id = _raw_jobs_by_id(source, raw_json)
        fetched_at = env.get("fetched_at") or ""
        for row in parsers.parse_manifest(env, data):
            n_rows += 1
            nid = row.get("native_id")
            k = (source, nid if nid is not None else row.get("url"))
            prev = best.get(k)
            if prev is not None and prev["_at"] >= fetched_at:
                continue
            job = job_by_id.get(str(nid)) if nid is not None else None
            best[k] = {"row": row, "job": job, "_at": fetched_at, "source": source}

    corpus = []
    for (source, _id), rec in best.items():
        row, job = rec["row"], rec["job"]
        gen_loc = row.get("location", "") or ""
        view = raw_location_view(source, job) if job else {}
        raw_toks = _flatten_raw_tokens(view)
        gen_toks = _loc_tokens(gen_loc)
        dropped = sorted(t for t in raw_toks - gen_toks if len(t) > 2)
        # The gate reads the title, the JD and the workplace hint too, and this
        # row already carries all three — so pass them (see `_assess`).
        evidence = {"title": row.get("title", "") or "",
                    "jd": row.get("description", "") or "",
                    "workplace_hint": row.get("workplace_raw") or "",
                    "source": source}
        g_dec = _gate_decision(gen_loc, policy, **evidence)
        union = gen_loc + "".join(" / " + t for t in dropped)
        u_dec = _gate_decision(union, policy, **evidence)
        flip = bool(dropped) and (g_dec["decision"] != u_dec["decision"])
        flags = _flags_for(gen_loc, dropped, flip)
        corpus.append({
            "source": source, "native_id": _id, "url": row.get("url", ""),
            "generated_location": gen_loc,
            "workplace_raw": row.get("workplace_raw"),
            "has_description": bool(row.get("description")),
            "raw_resolved": bool(job),
            "raw_location_view": view,
            "dropped_raw_tokens": dropped,
            "gate_generated": g_dec, "gate_if_union": u_dec,
            "flags": flags,
        })

    (out / "corpus.jsonl").write_text(
        "".join(json.dumps(c, default=str) + "\n" for c in corpus))
    flagged = [c for c in corpus if c["flags"]]
    by_flag: dict[str, int] = {}
    by_flag_src: dict[tuple, int] = {}
    for c in flagged:
        for f in c["flags"]:
            by_flag[f] = by_flag.get(f, 0) + 1
            by_flag_src[(f, c["source"])] = by_flag_src.get((f, c["source"]), 0) + 1
    n_resolved = sum(1 for c in corpus if c["raw_resolved"])
    print(f"corpus: {len(corpus)} unique postings from {n_blobs} blobs "
          f"({n_manifests} manifests, {n_rows} rows); {n_resolved} raw-resolved; "
          f"{len(flagged)} flagged -> {out}/corpus.jsonl")
    # Per-source resolution, STATED rather than inferred from a total: an
    # unresolved posting can never be flagged and `sample` filters it out, so a
    # source sitting at 0 of N is the tool reporting a whole ATS clean without
    # ever having looked at it.
    per_source: dict[str, list[int]] = {}
    for c in corpus:
        tally = per_source.setdefault(c["source"], [0, 0])
        tally[0] += 1 if c["raw_resolved"] else 0
        tally[1] += 1
    for src, (ok, total) in sorted(per_source.items()):
        note = "   <- resolves NONE of its postings" if ok == 0 and total else ""
        print(f"  raw-resolved  {src:16} {ok:5}/{total}{note}")
    for f, n in sorted(by_flag.items(), key=lambda kv: -kv[1]):
        srcs = ", ".join(f"{s}={c}" for (ff, s), c in
                         sorted(by_flag_src.items(), key=lambda kv: -kv[1])
                         if ff == f)
        print(f"  {f:22} {n:5}   [{srcs}]")


# ── sample (write per-entity comparison files for composer subagents) ────────
def cmd_sample(args) -> None:
    out = _resolve_out(args)
    corpus_path = out / "corpus.jsonl"
    if not corpus_path.exists():
        sys.exit(f"missing {corpus_path} — run `corpus` first.")
    corpus = [json.loads(ln) for ln in corpus_path.read_text().splitlines() if ln.strip()]
    rng = random.Random(args.seed)

    flagged = [c for c in corpus if c["flags"] and c["raw_resolved"]]
    clean = [c for c in corpus if not c["flags"] and c["raw_resolved"]]
    if args.source:
        flagged = [c for c in flagged if c["source"] in args.source]
        clean = [c for c in clean if c["source"] in args.source]
    rng.shuffle(flagged)
    rng.shuffle(clean)
    n_flagged = min(len(flagged), int(args.n * 0.75))
    picks = flagged[:n_flagged] + clean[:max(0, args.n - n_flagged)]

    def case_id(c: dict) -> str:
        return re.sub(r"[^A-Za-z0-9._-]", "_", f"{c['source']}-{c['native_id']}")[:80]

    jds_dir = out / "cases"
    jds_dir.mkdir(parents=True, exist_ok=True)
    for c in picks:
        body = [
            f"# Field-fidelity case: {case_id(c)} (source={c['source']})", "",
            f"- url: {c['url']}", "",
            "## GENERATED location field (what the location gate reads)",
            f"    {c['generated_location']!r}", "",
            "## RAW location fields from the ORIGINAL source payload (ground truth)",
            "```json",
            json.dumps(c["raw_location_view"], indent=2, default=str),
            "```", "",
            "## Deterministic pre-check (a hypothesis — verify against the RAW above)",
            f"- dropped_raw_tokens (heuristic): {c['dropped_raw_tokens']}",
            f"- gate on generated: {c['gate_generated']}",
            f"- gate if dropped tokens kept: {c['gate_if_union']}",
            f"- flags: {c['flags']}",
        ]
        (jds_dir / f"{case_id(c)}.md").write_text("\n".join(body))

    (out / "sample_summary.json").write_text(json.dumps(
        [{"case_id": case_id(c), "source": c["source"], "flags": c["flags"],
          "generated_location": c["generated_location"],
          "dropped_raw_tokens": c["dropped_raw_tokens"]} for c in picks], indent=1))
    print(f"sample: {len(picks)} cases ({n_flagged} flagged) -> {jds_dir}")
    for c in picks:
        print(f"  {c['source']:15} {case_id(c):44} flags={c['flags']} "
              f"loc={c['generated_location']!r}")


# ── check (deterministic single-entity re-parse root-cause) ──────────────────
def cmd_check(args) -> None:
    layout = domain_layout(config.data_root(), DOMAIN)
    policy = config.location_policy()
    raw = _RawStore(layout)
    for key in args.key:
        found = resolver.load_entity(layout, key)
        if not found:
            print(f"\n=== {key}: NO ENTITY")
            continue
        yaml_path, entity = found
        source, job = raw.job_for(entity)
        stored = entity.get("location", "") or ""
        print(f"\n=== {key}  (source={source})")
        print(f"    STORED generated location: {stored!r}")
        if job:
            print(f"    RAW location view: "
                  f"{json.dumps(raw_location_view(source, job), default=str)}")
            # what the CURRENT parser would generate now (whole-blob re-parse)
            reparsed = _reparse_one(raw, layout, entity, source)
            if reparsed is not None:
                print(f"    CURRENT parser location: {reparsed!r}")
                if reparsed != stored:
                    print("    !! parser output DIFFERS from stored (version drift)")
        else:
            print("    RAW: not resolvable (blob not-synced / id not found)")
        jd = (yaml_path.parent / "jd.md")
        jd_text = jd.read_text(errors="replace") if jd.exists() else ""
        gate = _gate_decision(
            stored, policy,
            title=entity.get("title", "") or "",
            jd=jd_text,
            workplace_hint=(entity.get("facts") or {}).get("workplace_raw") or "",
            source=source or "")
        print(f"    gate(stored): {gate}")
        print(f"    jd location lines: {_jd_location_lines(yaml_path.parent)}")


def _reparse_one(raw: _RawStore, layout, entity: dict, source: str):
    """Run the CURRENT per-source parser on the raw blob; return this entity's location."""
    if source not in parsers.SUPPORTED_SOURCES:
        return None
    src0 = (entity.get("source_ids") or [{}])[0]
    native_id, url = src0.get("id"), src0.get("url", "")
    payload = resolver.resolve_blob(layout, entity)
    if not payload:
        return None
    sha = payload["blob"]
    ext = _blobs.ext_for_content_type(payload.get("content_type"))
    if raw.bs.state(sha, ext) != _blobs.PRESENT:
        return None
    data = raw.bs.read(sha, ext)
    env = {"source": source, "request": {"url": url}}
    for row in parsers.parse_manifest(env, data):
        if str(row.get("native_id")) == str(native_id) or (url and row.get("url") == url):
            return row.get("location", "")
    return None


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="field-fidelity: generated location vs raw")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="scratch dir (gitignored)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("corpus", help="resolve raw + compare vs generated location")
    c.add_argument("--limit", type=int, default=600)
    c.add_argument("--seed", type=int, default=42)
    c.set_defaults(func=cmd_corpus, needs_store=True)

    # `sample` reads the corpus file `corpus` already wrote, never the store, so it
    # deliberately carries no `needs_store`: gating it would claim a dependency it
    # does not have.
    s = sub.add_parser("sample", help="write per-entity comparison files for subagents")
    s.add_argument("--n", type=int, default=32)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--source", action="append",
                   help="restrict to source(s), e.g. --source greenhouse (repeatable)")
    s.set_defaults(func=cmd_sample)

    t = sub.add_parser("check", help="deterministic single-entity re-parse root-cause")
    t.add_argument("--key", action="append", required=True)
    t.set_defaults(func=cmd_check, needs_store=True)

    d = sub.add_parser("todo", help="write weird-location reviews for AI follow-up")
    d.set_defaults(func=cmd_todo, needs_store=True)

    args = ap.parse_args(argv)
    # No store, no audit. ``config.data_root()`` is ``None`` BY DESIGN wherever
    # ``paths.data_root`` is unset — which is `config.example.yaml`, i.e. every
    # fresh clone and CI — and each store-reading command handed that ``None``
    # straight to ``pathlib``, so the quickstart commands died seven frames deep in
    # the stdlib. One guard, before dispatch: a new store-reading subcommand
    # declares ``needs_store=True`` beside its ``func`` instead of repeating it.
    # Non-zero, unlike the store's own gc/validate tools that exit 0 on "nothing to
    # do": this tool was ASKED for a verdict and has none, and exiting 0 would
    # report an audit that never ran as a clean one.
    if getattr(args, "needs_store", False) and config.data_root() is None:
        print(f"{args.cmd}: store not configured (set paths.data_root in config.yaml "
              f"or export JOBHUNT_DATA_ROOT) — this command reads the raw zone.",
              file=sys.stderr)
        return 2
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
