#!/usr/bin/env python3
"""search-recall-audit — random-sample raw JDs + deterministic gate trace.

This is the executable half of the ``search-recall-audit`` skill (router:
``skills/search-recall-audit/SKILL.md``). It supports a three-step loop for
checking whether the job-search pipeline is silently MISSING roles it should
surface (recall) or KEEPING roles it should drop (precision):

  corpus   snapshot -> a greppable JSONL + a key-free full-JD line file + a
           deterministic coverage index (what we already considered/drafted/applied).
  sample   grep keyword COMBOS across the ENTIRE JD (title + company + location +
           full description — never title-only), randomly sample a few per combo,
           and write one self-contained JD file per pick (full text + coverage
           pre-check) for an AI agent to judge.
  trace    run the job-search pipeline's OWN content gates (title/location/visa/
           experience/quality) on chosen postings and report the FIRST drop gate +
           location evidence — the deterministic root-cause step that turns an AI
           agent's "looks missed" into "dropped at gate X (correctly / not)".

Design notes
------------
* This is an automation-layer QA tool, so — like the gardener — it is allowed to
  reach the pipeline: it imports ``config`` from ``automation/shared`` and imports
  the job-search skill's ``scoring``/``snapshot``/``posting_identity`` modules
  (white-box, because the whole point is to introspect that skill's gates). It
  never imports repo-root Python and never mutates any tracked file.
* All output lands under a GITIGNORED scratch dir (default
  ``local/search_recall_audit/``) — never the repo root or a tracked/product folder.
* Coverage matching uses the pipeline's OWN URL canonicalizer
  (``posting_identity.canonicalize_url``), NOT a naive query-string strip, so a
  distinct ``?gh_jid=`` posting is never falsely reported as "already covered".
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
for p in (REPO_ROOT / "automation" / "shared", _JS, _JS / "_vendor"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import yaml  # noqa: E402
import config  # noqa: E402  (automation/shared/config.py)

DEFAULT_OUT = REPO_ROOT / "local" / "search_recall_audit"

# Sensible default keyword combos (each = AND of terms, matched anywhere in the
# JD). Tunable via --combo; keep them aligned with the profile's target roles.
DEFAULT_COMBOS = [
    ["software engineer", "remote"],
    ["kubernetes", "remote"],
    ["platform engineer", "remote"],
    ["ai infrastructure", "remote"],
    ["site reliability", "remote"],
    ["distributed systems", "remote"],
    ["compute platform"],
    ["developer productivity"],
    ["developer experience"],
]


# ── shared helpers ───────────────────────────────────────────────────────────
def _norm_company(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def canon(url: str) -> str:
    """Pipeline-faithful URL canonicalization + a safe extra step.

    Uses the pipeline's own ``posting_identity.canonicalize_url`` (keeps real
    query params like ``gh_jid``, strips tracking), then de-duplicates IDENTICAL
    ``(key, value)`` query pairs. That last step is always semantics-preserving
    (``?a=1&a=1`` == ``?a=1``) and makes matching robust to the upstream
    duplicated-``gh_jid`` quirk (see the known-issue) — without touching the
    pipeline's versioned canonicalizer.
    """
    try:
        import posting_identity
        import urllib.parse
        c = posting_identity.canonicalize_url(url or "")
        parts = urllib.parse.urlsplit(c)
        seen: list[tuple[str, str]] = []
        for kv in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
            if kv not in seen:
                seen.append(kv)
        q = urllib.parse.urlencode(seen)
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, q, ""))
    except Exception:
        return (url or "").split("#")[0].rstrip("/").lower()


def default_snapshot(profile: str) -> Path:
    return REPO_ROOT / "local" / "search_cache" / f"{profile}-stage1-latest.json"


def resolve_profile_name(name: str | None) -> str:
    if name:
        return name
    try:
        return config.default_profile()
    except Exception:
        return "default"


def load_snapshot(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"snapshot not found: {path}\n"
                 f"Run a job-search first, or pass --snapshot PATH.")
    return json.loads(path.read_text())


# ── coverage index (what we already considered / drafted / applied) ──────────
def build_coverage() -> dict:
    root = Path(config.applications_root())
    cov = {"log": [], "folders": [], "canon_urls": [], "companies": []}
    urls: set[str] = set()
    companies: set[str] = set()

    log_path = Path(config.applications_log_path())
    if log_path.exists():
        data = yaml.safe_load(log_path.read_text()) or {}
        for e in data.get("postings") or []:
            if not isinstance(e, dict):
                continue
            cu = canon(e.get("url"))
            cn = _norm_company(e.get("company"))
            cov["log"].append({"company": e.get("company"), "role": e.get("role"),
                               "status": e.get("status"), "slug": e.get("slug"),
                               "url": e.get("url"), "canon_url": cu})
            if cu:
                urls.add(cu)
            if cn:
                companies.add(cn)

    for d in sorted(root.glob("[0-9]_*")):
        if not d.is_dir() or d.name.endswith("_profile") or "discoveries" in d.name:
            continue
        for meta_path in sorted(d.glob("*/meta.yaml")):
            try:
                m = yaml.safe_load(meta_path.read_text()) or {}
            except (OSError, yaml.YAMLError):
                continue
            entry = {"slug": meta_path.parent.name, "status_dir": d.name,
                     "canon_urls": [], "companies": []}
            jobs = m.get("jobs") or ([{"url": m.get("url")}] if m.get("url") else [])
            base_co = _norm_company(m.get("company"))
            if base_co:
                entry["companies"].append(base_co)
                companies.add(base_co)
            for j in jobs:
                if not isinstance(j, dict):
                    continue
                cu = canon(j.get("url"))
                if cu:
                    entry["canon_urls"].append(cu)
                    urls.add(cu)
                cn = _norm_company(j.get("company"))
                if cn:
                    entry["companies"].append(cn)
                    companies.add(cn)
            cov["folders"].append(entry)

    cov["canon_urls"] = sorted(urls)
    cov["companies"] = sorted(companies)
    return cov


def coverage_for(rec: dict, cov: dict) -> dict:
    cu = canon(rec.get("url"))
    cn = _norm_company(rec.get("company"))
    return {
        "exact_url_already_considered": cu in set(cov["canon_urls"]),
        "log_entries_same_company": [x for x in cov["log"]
                                     if _norm_company(x["company"]) == cn],
        "folders_same_company": [f for f in cov["folders"] if cn in f["companies"]],
    }


# ── subcommand: corpus ───────────────────────────────────────────────────────
def cmd_corpus(args) -> None:
    profile = resolve_profile_name(args.profile)
    snap_path = (default_snapshot(profile) if args.snapshot in (None, "latest")
                 else Path(args.snapshot))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = load_snapshot(snap_path)
    postings = data["postings"]

    with (out / "postings.jsonl").open("w") as fh:
        for i, r in enumerate(postings):
            r = dict(r)
            r["_idx"] = i
            fh.write(json.dumps(r, default=str) + "\n")

    # Key-free, tab-separated, one line per posting. Columns:
    # idx | company | title | location | remote | FULL-description (flattened).
    # Grepping this line = grepping the ENTIRE JD, never title-only.
    with (out / "search_lines.txt").open("w") as fh:
        for i, r in enumerate(postings):
            desc = re.sub(r"\s+", " ", r.get("description") or "")
            cols = [str(i), r.get("company") or "", r.get("title") or "",
                    r.get("location") or "", str(r.get("remote") or ""), desc]
            fh.write("\t".join(c.replace("\t", " ") for c in cols) + "\n")

    cov = build_coverage()
    (out / "coverage_index.json").write_text(json.dumps(cov, indent=1))

    print(f"corpus: {len(postings)} postings from {snap_path.name} "
          f"(fetched {data.get('fetched_at')})")
    print(f"  wrote postings.jsonl, search_lines.txt (full-JD grep), coverage_index.json -> {out}")
    print(f"  coverage: {len(cov['log'])} log rows, {len(cov['folders'])} folders, "
          f"{len(cov['canon_urls'])} canon URLs, {len(cov['companies'])} companies")


# ── subcommand: sample ───────────────────────────────────────────────────────
def _combo_matches(line: str, terms: list[str]) -> bool:
    low = line.lower()
    return all(t.lower() in low for t in terms)


def cmd_sample(args) -> None:
    out = Path(args.out)
    lines_path = out / "search_lines.txt"
    if not lines_path.exists():
        sys.exit(f"missing {lines_path} — run `corpus` first.")
    lines = lines_path.read_text().splitlines()
    postings = {}
    for ln in (out / "postings.jsonl").read_text().splitlines():
        r = json.loads(ln)
        postings[r["_idx"]] = r

    combos = [c.split(",") for c in args.combo] if args.combo else \
             [list(c) for c in DEFAULT_COMBOS]
    combos = [[t.strip() for t in c if t.strip()] for c in combos]

    cov = json.loads((out / "coverage_index.json").read_text())
    cov_url_set = set(cov["canon_urls"])

    selected: list[int] = []
    picks_rows: list[dict] = []
    for ci, terms in enumerate(combos):
        # Seed with a STRING (deterministic across processes; a tuple's __hash__
        # is per-process randomized for strings and would break reproducibility).
        rng = random.Random(f"{args.seed}:{ci}:{','.join(terms)}")
        matched = [ln for ln in lines if _combo_matches(ln, terms)]
        rng.shuffle(matched)
        taken = 0
        for ln in matched:
            idx = int(ln.split("\t", 1)[0])
            if idx in selected:
                continue
            rec = postings[idx]
            cvg = coverage_for(rec, cov)
            if args.uncovered_only and cvg["exact_url_already_considered"]:
                continue
            selected.append(idx)
            picks_rows.append({"combo": "+".join(terms), "idx": idx,
                               "company": rec.get("company"), "title": rec.get("title"),
                               "location": rec.get("location"),
                               "url_covered": cvg["exact_url_already_considered"]})
            taken += 1
            if taken >= args.per_combo:
                break

    jds_dir = out / "jds"
    jds_dir.mkdir(parents=True, exist_ok=True)
    for idx in selected:
        r = postings[idx]
        cvg = coverage_for(r, cov)
        body = [
            f"# JD idx={idx}", "",
            f"- company: {r.get('company')}", f"- title: {r.get('title')}",
            f"- location: {r.get('location')}", f"- remote_flag: {r.get('remote')}",
            f"- url: {r.get('url')}", f"- posted_at: {r.get('posted_at')}",
            f"- source: {r.get('source')}", "",
            "## Deterministic coverage pre-check (canonicalized-URL match; verify anyway)",
            f"- exact_url_already_considered: {cvg['exact_url_already_considered']}",
            f"- log_entries_same_company: {json.dumps(cvg['log_entries_same_company'])}",
            f"- folders_same_company: {json.dumps(cvg['folders_same_company'])}",
            "", "## Full JD text", "",
            r.get("description") or "(no description)",
        ]
        (jds_dir / f"{idx}.md").write_text("\n".join(body))

    (out / "selection_summary.json").write_text(json.dumps(picks_rows, indent=1))
    print(f"sample: {len(selected)} unique JDs across {len(combos)} combos "
          f"(per_combo={args.per_combo}, seed={args.seed}, whole-JD grep) -> {jds_dir}")
    for row in picks_rows:
        title = (row["title"] or "")[:52]
        print(f"  [{row['combo']:<28}] idx={row['idx']:>5} covered={str(row['url_covered']):>5}  "
              f"{row['company']} :: {title}")


# ── subcommand: trace ────────────────────────────────────────────────────────
GATES = ["posting_quality", "title", "location", "visa", "experience"]


def cmd_trace(args) -> None:
    import scoring
    import snapshot
    import search_jobs

    profile = search_jobs.load_yaml(
        search_jobs.resolve_profile(resolve_profile_name(args.profile)))
    profile.setdefault("visa", {})

    prof = resolve_profile_name(args.profile)
    snap_path = (default_snapshot(prof) if args.snapshot in (None, "latest")
                 else Path(args.snapshot))
    data = load_snapshot(snap_path)

    want_idx = set(args.idx or [])
    want_url = {canon(u) for u in (args.url or [])}
    rows = {}
    for i, d in enumerate(data["postings"]):
        if i in want_idx or (want_url and canon(d.get("url")) in want_url):
            rows[i] = d
    if not rows:
        sys.exit("no matching postings for the given --idx / --url in this snapshot.")

    for i in sorted(rows):
        d = rows[i]
        p = snapshot.posting_from_dict(d)
        p.filter_assessments, p.review_reasons = {}, []
        res = {
            "posting_quality": scoring.posting_quality_ok(p),
            "title": scoring.title_ok(p, profile),
            "location": scoring.location_ok(p, profile),
            "visa": scoring.visa_ok(p, profile),
            "experience": scoring.experience_ok(p, profile),
        }
        first_drop = next((g for g in GATES if not res[g]), None)
        la = p.filter_assessments.get("location", {})
        print(f"\n=== idx {i}: {p.company} :: {p.title}")
        print(f"    location={p.location!r} remote={p.remote!r} source={p.source}")
        for g in GATES:
            print(f"    {g:16} -> {'PASS' if res[g] else 'DROP'}")
        print(f"    location: category={la.get('category')} decision={la.get('decision')} "
              f"workplace={la.get('workplace')} evidence={la.get('evidence')}")
        if p.review_reasons:
            print(f"    review_reasons: {p.review_reasons}")
        print(f"    >>> FIRST DROP GATE: {first_drop or 'NONE — passes all content gates (surfaced)'}")


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="search-recall-audit: sample raw JDs + trace pipeline gates")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="scratch output dir (gitignored)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("corpus", help="snapshot -> JSONL + full-JD grep lines + coverage index")
    c.add_argument("--profile", default=None)
    c.add_argument("--snapshot", default="latest", help="'latest' or a path")
    c.set_defaults(func=cmd_corpus)

    s = sub.add_parser("sample", help="grep combos across the WHOLE JD, random-sample")
    s.add_argument("--combo", action="append",
                   help="comma-joined AND terms, e.g. --combo 'kubernetes,remote' (repeatable)")
    s.add_argument("--per-combo", type=int, default=2)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--uncovered-only", action="store_true",
                   help="skip picks whose exact URL is already considered")
    s.set_defaults(func=cmd_sample)

    t = sub.add_parser("trace", help="run the pipeline's own gates on chosen postings")
    t.add_argument("--idx", type=int, action="append", help="snapshot index (repeatable)")
    t.add_argument("--url", action="append", help="posting URL (repeatable)")
    t.add_argument("--profile", default=None)
    t.add_argument("--snapshot", default="latest")
    t.set_defaults(func=cmd_trace)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
