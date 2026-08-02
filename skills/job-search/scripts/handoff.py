#!/usr/bin/env python3
"""Bridge ranked search results into scaffolded application folder(s).

Usage:
  .venv/bin/python skills/job-search/scripts/handoff.py \
      --json <search.json> \
      (--select <"rank N" | "rank N,M,P" | "Company" | "Company/Title"> | --all) \
      [--split] [--applications-root DIR] [--status-dir 6_drafted] \
      [--research-date YYYY-MM-DD] [--skip-jd-fetch] \
      [--allow-location-mismatch] [--report REPORT.json]

``search.json`` is what ``search_jobs.py --json-out`` writes: a list of posting
records (``JobPosting.to_dict()``), score-ranked. This tool takes the selected
row(s) and does the deterministic, transcription-error-prone folder setup so the
drafting agent can start at gap analysis instead of re-transcribing ~10 fields.

**One folder per company by default.** When a selection spans several postings at
the same company (``--select "Company"``, a multi-rank ``--select "rank N,M"``, or
``--all``), they are GROUPED into ONE application folder with a multi-entry
``jobs:`` list — one resume per company, one ``JD-<title>.md`` + one cover letter
per posting — matching the resume-writer "one resume, multiple roles" default.
Pass ``--split`` to force the old one-folder-per-posting layout (the divergent-
roles path — use it when a company's roles are too different for one honest
resume). A single ``--select "rank N"`` / ``--select "Company/Title"`` always
produces exactly one single-role folder.

**A posting's identity is its URL, else its ``(company, title)`` pair** —
``posting_key``, the rule ``skip_log.fold_key`` already states. Two requisitions
at one employer routinely share a title, so the title alone is not an identity;
every place that has to tell two postings apart (the duplicate preflight, the
in-run register, the ``jobs[].role`` label that names each cover letter, the JD
filename, and the folder slug) resolves through that one rule.

**The duplicate preflight runs on every path**, single-``--select`` included, per
the AGENTS.md blacklist/log guardrail. A bulk run skips a duplicate and carries
on; a single explicit selection creates nothing and exits 2, naming the
``--forget-log`` tombstone that is the only real undo for a skip-log row.

For each resulting folder the tool:

1. Creates ``<applications_root>/<status-dir>/<slug>/`` per the AGENTS.md
   Application Folder Convention (``<company>-<lead role>-<YYYYMMDD>`` slug; the
   lead role is the highest-ranked posting in a grouped folder). An application
   folder is ALWAYS exactly two levels under the root — every consumer globs one
   level, so anything deeper is invisible to every tracker command. The tool
   REFUSES to overwrite an existing folder; under ``--split`` two same-title
   requisitions get distinct slugs rather than colliding with each other.
2. Saves ``source/JD-<job title>.md`` VERBATIM via the sibling ``fetch_jd`` module
   (imported, never subprocessed; exactly one fetch per posting). If a fetch fails
   the folder is still scaffolded, but the tool exits non-zero telling the agent to
   save that JD manually.
3. Writes ``meta.yaml`` (schema v6) with one ``jobs:`` entry per posting, each
   with its OWN ``role`` label: two postings that share a title get the second
   one's location appended (``Software Engineer (Austin, TX)``), because ``role``
   is the key for both per-JD artifacts — ``<COVER_STEM>_<role>`` and
   ``<APPLICATION_STEM>_<role>`` — and one cover letter per JD is a hard
   guardrail. ``validate_meta`` rejects a duplicate role, so the collision can no
   longer reach render time. Each entry carries
   over every structured fact each search row already computed — level, YOE,
   salary, workplace, sponsorship, location, URL, posted date, source channel —
   using the vendored ``metadata_editor`` (the same formatting-preserving editor
   the tracker's ``--enrich-metadata`` uses, so a later enrich is a no-op). Facts a
   row lacks are NOT invented; they are left for the tracker's
   ``status.py --enrich-metadata`` follow-up. The top-level ``company_key`` is
   always written and always EMPTY (``null``) — it is the owner's filing key, its
   index is private, and a key this script invented would not be in it; an
   explicit empty line says "unassigned" where a missing field said nothing at all.
4. Validate with the vendored ``job_metadata`` validator before exit. On failure
   the tool exits non-zero and lists what is missing.
5. Run the location-policy check against ``config.location_policy()`` (via the
   vendored ``location`` module), PER POSTING and worst-wins. The policy governs
   a posting, not a folder, so each ``jobs:`` entry is classified from its own
   ``location`` falling back to its own ``jd_file``'s ``Location:`` lines, and a
   folder holding one US and one foreign posting is a mismatch — not "OK" because
   some posting in it matched. A definite mismatch (a foreign posting or a
   non-preferred US office) LEAVES the folder on disk, prints the offending
   posting(s) BY ROLE + a remedy to stderr, and exits non-zero (code 3 on the
   single-posting path, 1 in a bulk run) unless ``--allow-location-mismatch`` is
   passed — which still REPORTS the mismatch, then proceeds. This catches a
   wrong-metro / foreign posting at handoff, before the drafting leg pays for it.
   A blank / unrecognized location is surfaced for manual review but does NOT
   block (identical to the tracker's ``review`` vs ``mismatch`` split). When
   GROUPING several postings into one company folder, postings whose SEARCH ROW
   already fails the policy are instead dropped from that folder (each reported)
   so only policy-matching roles are kept — matching the resume-writer rule "for a
   multi-role company, keep only the postings that match the policy";
   ``--allow-location-mismatch`` keeps them all. A posting the pre-filter could
   not judge (blank row location, foreign JD) blocks rather than being dropped
   after the fact: a drop is only honest when the evidence was already visible to
   the caller in the search table.

6. Append each created posting to the append-only applications skip-log
   (``applications-log.jsonl``, honouring ``--applications-root``) as the LAST
   step, through the shared ``skip_log.posting_rows`` flattening the tracker's
   ``--sync-log`` uses. Creation is the one event every application has, and
   before this the log only ever saw status TRANSITIONS — so a folder scaffolded
   and deleted before any sync left no trace and the posting resurfaced as fresh.
   ``_record_created_postings`` carries the ordering, idempotency and concurrency
   argument.

Stdout is exactly two lines: the folder path and the meta.yaml validation status.
Everything else (fetch notes, gap diagnostics, the location verdict, the skip-log
append) goes to stderr.

Self-contained: this script imports only its own sibling ``fetch_jd`` and the
vendored ``job_metadata`` / ``metadata_editor`` / ``location`` / ``skip_log`` /
``layout`` / ``config`` modules.
It never subprocesses another skill's scripts; the tracker's ``--enrich-metadata`` /
``--check-metadata`` / ``--check-locations`` remain agent-invoked follow-ups.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import yaml

# Self-contained skill: this script's own scripts/ (for the sibling fetch_jd
# module) and its vendored copies under _vendor/ go on sys.path. _vendor/ is on
# the path directly so metadata_editor can `import job_metadata` as a sibling.
_SKILL_SCRIPTS = Path(__file__).resolve().parent
_VENDOR = _SKILL_SCRIPTS / "_vendor"
for _p in (str(_SKILL_SCRIPTS), str(_VENDOR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fetch_jd  # noqa: E402  (sibling skill module)
from job_metadata import (  # noqa: E402
    APPLICATION_SCHEMA_VERSION,
    POSTING_METADATA_FIELDS,
    SPONSORSHIP_VALUES,
    WORKPLACE_VALUES,
    validate_meta,
)
from metadata_editor import plan_metadata_edit  # noqa: E402
import skip_log  # noqa: E402  (vendored: folds AND appends the applications skip-log)
from layout import (  # noqa: E402  (vendored)
    slugify_label,          # role label -> the cover-letter / bundle filename suffix
    status_label_for_dir,   # status dir -> label
)
from location import (  # noqa: E402  (vendored shared location policy)
    classify_location,
    classify_locations,
    extract_jd_locations,
    is_match,
)

DEFAULT_STATUS_DIR = "6_drafted"
LIVE_STATUS_DIRS = (
    "6_drafted", "5_applied", "4_in_progress", "3_rejected", "2_ignored",
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_RANK_RE = re.compile(r"^\s*(?:rank\s+)?(\d+)\s*$", re.I)
# A comma-separated rank list: "rank 1,3,5" or "1, 3, 5".
_RANK_LIST_RE = re.compile(r"^\s*(?:ranks?\s+)?(\d+(?:\s*,\s*\d+)*)\s*$", re.I)


# --------------------------------------------------------------------------- #
# Row selection
# --------------------------------------------------------------------------- #
def load_rows(json_path: Path) -> list[dict]:
    """Load the search-JSON list of posting records."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not read search JSON {json_path}: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise ValueError(
            f"{json_path} is not a non-empty list of postings "
            "(expected search_jobs.py --json-out output)"
        )
    rows = [row for row in data if isinstance(row, dict)]
    if not rows:
        raise ValueError(f"{json_path} contains no posting records")
    return rows


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def select_rows(rows: list[dict], selector: str) -> list[dict]:
    """Select one or more postings; return them in selection order.

    Accepted selectors:
    - ``"rank N"`` / ``"N"``          → that single posting.
    - ``"rank N,M,P"`` / ``"N,M,P"``  → those postings (grouped by company later).
    - ``"Company/Title"``             → that single posting (exact company + title).
    - ``"Company"``                   → every posting for that company (one folder).

    Grouping into folders happens downstream (``group_by_company``); this function
    only resolves the selector to a list of rows.
    """
    selector = (selector or "").strip()

    rank_list = _RANK_LIST_RE.match(selector)
    if rank_list:
        picked: list[dict] = []
        for token in re.split(r"\s*,\s*", rank_list.group(1)):
            rank = int(token)
            if not 1 <= rank <= len(rows):
                raise ValueError(
                    f"rank {rank} is out of range (1..{len(rows)} postings available)"
                )
            picked.append(rows[rank - 1])
        return picked

    if "/" in selector:
        company, title = selector.split("/", 1)
        matches = [
            row for row in rows
            if _norm(row.get("company")) == _norm(company)
            and _norm(row.get("title")) == _norm(title)
        ]
        if not matches:
            raise ValueError(
                f"no posting matches company/title {selector!r}; "
                "use the exact company and title from the search table"
            )
        if len(matches) > 1:
            raise ValueError(
                f"company/title {selector!r} matches {len(matches)} postings; "
                "select by rank instead"
            )
        return matches

    # A bare token with no '/' and not a rank is a COMPANY selector: take every
    # posting for that company (they group into one folder by default).
    company_rows = [
        row for row in rows if _norm(row.get("company")) == _norm(selector)
    ]
    if not company_rows:
        raise ValueError(
            f"--select {selector!r} is neither a rank ('rank N' / 'N,M'), a "
            "'Company/Title' pair, nor a company with postings in the search JSON"
        )
    return company_rows


def group_by_company(rows: list[dict], *, split: bool = False) -> list[list[dict]]:
    """Group selected rows into per-folder buckets.

    Default (``split=False``): ONE bucket per company — the one-folder-per-company
    default. Buckets and the rows inside them preserve first-seen (score-ranked)
    order, so bucket[0] is the company's lead role (used for the folder slug).
    ``split=True``: one bucket per posting (the divergent-roles escape hatch).
    """
    if split:
        return [[row] for row in rows]
    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        key = _norm(row.get("company"))
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    return [buckets[key] for key in order]


def posting_key(company: object, title: object, url: object) -> tuple:
    """The ONE identity a posting has: its URL, else its ``(company, title)`` pair.

    This is ``skip_log.fold_key``'s rule (``skip_log.py``: "URL when there is one,
    else the ``(company, role)`` pair… the two branches are tagged so they can
    never collide"), spelled the same way here for the same reason. A URL names
    ONE requisition; a ``(company, title)`` pair names a CLASS of them — two
    requisitions at one employer routinely share a title (one role posted in two
    metros, two teams hiring the same ladder title). So the pair is a stand-in for
    the rows an ATS gave no URL, never a second identity to check alongside the
    first: treating it as one merges two distinct postings into one, silently.

    The branches are tagged (``"url"`` / ``"pair"``) so a URL-bearing row and a
    URL-less row for the same company+title can never collapse onto each other.
    """
    normalized = _norm(url).rstrip("/")
    if normalized:
        return ("url", normalized)
    return ("pair", _norm(company), _norm(title))


def _posting_keys(root: Path, log_path: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """Collect URL and company/role duplicate keys from the skip-log and live folders.

    The log rows come from ``skip_log.read_postings`` — the append-only event log
    folded to one row per posting, in the same ``{company, slug, date, status, role,
    url}`` shape the old YAML ``postings`` list carried. This function's own ``_norm``
    and ``.rstrip("/")`` are what decide identity here and are unchanged; ``skip_log``'s
    wider normalizer dedupes lines inside the file and is never a match key.

    **Why this registers BOTH keys for a URL-bearing row and ``_register_row``
    does not.** These rows are HISTORY. A pair key off a historical row is a
    deliberate re-list heuristic: an ATS that re-posts a requisition under a new
    URL is caught by ``(company, role)`` and nothing else
    (``test_log_row_suppresses_a_re_listed_posting_by_company_and_role``). Two
    rows inside ONE search snapshot cannot be a re-list of each other — the
    snapshot holds both at once — so the in-run register has no such case to catch
    and follows ``posting_key`` exactly.
    """
    urls: set[str] = set()
    pairs: set[tuple[str, str]] = set()

    if log_path.exists():
        for posting in skip_log.read_postings(log_path):
            url = _norm(posting.get("url"))
            company = _norm(posting.get("company"))
            role = _norm(posting.get("role"))
            if url:
                urls.add(url.rstrip("/"))
            if company and role:
                pairs.add((company, role))

    for status in LIVE_STATUS_DIRS:
        status_dir = root / status
        if not status_dir.exists():
            continue
        for meta_path in status_dir.glob("*/meta.yaml"):
            try:
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            company = _norm(meta.get("company"))
            jobs = meta.get("jobs") or []
            if not jobs and meta.get("role"):
                jobs = [{"role": meta.get("role"), "url": meta.get("url")}]
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                url = _norm(job.get("url"))
                role = _norm(job.get("role"))
                if url:
                    urls.add(url.rstrip("/"))
                if company and role:
                    pairs.add((company, role))
    return urls, pairs


def _duplicate_reason(
    row: dict,
    urls: set[str],
    pairs: set[tuple[str, str]],
) -> str | None:
    url = _norm(row.get("url")).rstrip("/")
    pair = (_norm(row.get("company")), _norm(row.get("title")))
    if url and url in urls:
        return "same URL already exists in the log or a live application folder"
    if all(pair) and pair in pairs:
        return "same company and role already exists in the log or a live folder"
    return None


def _report_explicit_duplicate(row: dict, reason: str) -> None:
    """Refuse an explicitly-selected posting the preflight already knows about.

    The bulk path SKIPS a duplicate and moves on, which is right when the caller
    asked for everything on the list. An explicit ``--select`` asked for THIS
    posting, so silently doing nothing and exiting 0 is the wrong answer twice
    over: the caller is told nothing, and the preflight it just failed is the
    AGENTS.md blacklist/log guardrail, not a suggestion.

    Removing the folder is not the undo here — the applications skip-log is
    append-only and authoritative, nothing regenerates it, and an agent may not
    remove an application folder at all (AGENTS.md) — so the remedy printed is
    the tombstone, with its argument already filled in. When the duplicate is a
    LIVE folder rather than a log row, ``status.py --forget-log`` refuses and
    names the existing application instead; that refusal is the chain's terminus.
    """
    url = str(row.get("url") or "").strip()
    target = f'"{url}"' if url else f'"{row.get("company")}" "{row.get("title")}"'
    print(
        f"handoff: REFUSING to scaffold {row.get('company')} / {row.get('title')} "
        f"— skipped as a duplicate ({reason}). Nothing was created.",
        file=sys.stderr,
    )
    print(
        "handoff: if this posting really is new (a stale or wrong log row, or a "
        "different requisition that happens to share a title), append a tombstone "
        "first:",
        file=sys.stderr,
    )
    print(f"  status.py --forget-log {target}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Slugs and paths
# --------------------------------------------------------------------------- #
def slugify(text: str) -> str:
    """Lowercase, hyphen-separated, alphanumeric-only slug (per AGENTS.md)."""
    return _SLUG_RE.sub("-", str(text or "").casefold()).strip("-")


def folder_slug(company: str, role: str, date_str: str) -> str:
    """``<company>-<role>-<YYYYMMDD>`` folder slug for an application."""
    stamp = date_str.replace("-", "")
    parts = [slugify(company), slugify(role), stamp]
    return "-".join(part for part in parts if part)


def jd_filename(role: str) -> str:
    """``JD-<job title>.md`` — the exact per-posting JD file name."""
    return f"JD-{slugify(role)}.md"


def unique_jd_filename(role: str, used: set[str]) -> str:
    """A ``JD-<job title>.md`` name unique within one folder's ``source/``.

    A grouped multi-role folder can hold two postings whose titles slugify the
    same; disambiguate the collision with a ``-2``/``-3`` suffix so every posting
    keeps its own verbatim JD file. ``used`` is mutated with the returned name.
    """
    base = jd_filename(role)
    if base not in used:
        used.add(base)
        return base
    stem = base[:-3]  # strip trailing ".md"
    index = 2
    while f"{stem}-{index}.md" in used:
        index += 1
    name = f"{stem}-{index}.md"
    used.add(name)
    return name


def role_discriminator(row: dict) -> str:
    """What tells two same-title postings at one employer apart, in words.

    The posting's own location: it is the fact that actually differs between two
    requisitions sharing a title, it is true, and it is READABLE. This string ends
    up in the cover-letter filename and in the letter's target-position line, so a
    mechanical ``-2`` would put a meaningless token in front of a hiring manager.
    Empty when the row has no location, and the caller falls back to a number.
    """
    return re.sub(r"\s+", " ", str(row.get("location") or "")).strip()


def _label_key(label: str) -> str:
    """The collision domain of a role label: its cover-letter filename slug.

    ``slugify_label`` is what ``config.cover_stem`` / ``config.application_stem``
    turn a role into, so two labels collide exactly when their slugs do —
    ``check.check_role_filename_collisions`` compares the same thing at render
    time. Casefolded on top, because the filesystems this ships on are
    case-insensitive.
    """
    return slugify_label(label).casefold()


def unique_role_label(title: str, discriminator: str, used: set[str]) -> str:
    """A ``jobs[].role`` label unique within one folder; ``used`` is mutated.

    ``role`` is the key for BOTH per-JD artifacts — ``<COVER_STEM>_<role>.docx``
    / ``.pdf`` and the bundled ``<APPLICATION_STEM>_<role>.txt`` — so two postings
    sharing a label collapse two JDs onto ONE cover letter. That is the AGENTS.md
    guardrail "One cover letter per JD — no shared/boilerplate letter" broken at
    the seam that creates the folder, and it used to surface only much later, in
    ``check.check_role_filename_collisions`` during render, after the drafting
    agent had already paid for the tailoring.

    ``used`` holds ``_label_key`` values, not raw labels: the constraint is on the
    FILENAME, so ``Software Engineer`` and ``software engineer`` collide.
    """
    base = str(title or "").strip()
    for candidate in (base, f"{base} ({discriminator})".strip() if discriminator else ""):
        if candidate and _label_key(candidate) not in used:
            used.add(_label_key(candidate))
            return candidate
    index = 2
    while _label_key(f"{base} ({index})".strip()) in used:
        index += 1
    label = f"{base} ({index})".strip()
    used.add(_label_key(label))
    return label


def unique_folder_slug(
    company: str,
    role: str,
    date_str: str,
    discriminator: str,
    taken: set[str],
) -> str:
    """A folder slug this RUN has not already used; ``taken`` is not mutated.

    Only slugs this run created are consulted. A slug that exists on disk from an
    EARLIER run is refuse-to-overwrite's business and stays that way — the
    same-day rerun must keep refusing. What this fixes is ``--split``, the
    documented divergent-roles escape: two same-title requisitions both slugified
    to ``<company>-<title>-<date>``, so the second collided with a folder this
    very run had just created, and the divergent-roles path was a no-op for
    exactly the case it exists to handle. Same discriminator as the role label, so
    a folder and its cover letters agree on which requisition they are about.
    """
    base = folder_slug(company, role, date_str)
    if base not in taken:
        return base
    if discriminator:
        candidate = folder_slug(company, f"{role} {discriminator}", date_str)
        if candidate and candidate not in taken:
            return candidate
    index = 2
    while folder_slug(company, f"{role} {index}", date_str) in taken:
        index += 1
    return folder_slug(company, f"{role} {index}", date_str)


def _require_folder_under_root(folder: Path, root: Path, status_dir: str) -> None:
    """An application folder is ALWAYS exactly two levels under the root.

    Every consumer globs exactly one level — ``_posting_keys``'s
    ``status_dir.glob("*/meta.yaml")``, the tracker's folder walk — so a folder
    any deeper is invisible to ``status.py``, ``--check-locations``,
    ``--check-metadata``, ``--sync-log`` and this tool's own duplicate preflight,
    while ``mkdir(parents=True)`` creates it happily. It also poisons the
    append-only log, which nothing regenerates: ``_record_created_postings``
    derives its row from ``folder.name``, and for
    ``.../acme-backend-engineer-2026/07/31`` that is ``"31"``.

    Checking the RESULT rather than enumerating the inputs is deliberate. A
    ``--research-date`` typo is the documented way in (argparse now rejects it at
    the boundary too) and ``--status-dir`` is the other, but the invariant is the
    thing worth stating, and it holds for any future caller of ``_run_group``.
    """
    resolved = folder.resolve()
    if resolved.parent.parent != root.resolve() or not resolved.name:
        raise ValueError(
            f"refusing to create {folder}: an application folder must be exactly "
            f"<applications root>/<status dir>/<slug>, and this resolves outside "
            f"{root / status_dir} — check --research-date and --status-dir for a "
            "path separator"
        )


def _applications_root(override: str | None) -> Path:
    """Applications root: the CLI override, else the vendored config default."""
    if override:
        return Path(override).expanduser().resolve()
    import config  # vendored; imported lazily so --applications-root needs no config
    return config.applications_root()


def _applications_jsonl(root: Path, override: str | None) -> Path:
    """The applications skip-log to read for the duplicate preflight.

    With ``--applications-root`` the log is composed inside that tree from the
    config module's layout CONSTANTS (reading them triggers no config load, so the
    override keeps working with no config at all); otherwise it is the configured
    ``config.applications_jsonl_path()``.

    Both branches must name the SAME file. Composing the override from the old
    ``APPLICATIONS_LOG_FILENAME`` after the log moved to JSONL would point at a name
    nothing writes: the path would simply not exist, the log half of the preflight
    would contribute nothing, and duplicate detection would silently degrade to the
    live folders alone — a fail-open with no error and no output to notice.
    ``test_handoff.py``'s fixtures never write a log, so only the dedicated
    override test below catches it.
    """
    import config  # vendored; same lazy import as _applications_root
    if override:
        return root / config.CANDIDATE_DIRNAME / config.APPLICATIONS_JSONL_FILENAME
    return config.applications_jsonl_path()


# --------------------------------------------------------------------------- #
# JD fetch (verbatim, via the sibling fetch_jd module)
# --------------------------------------------------------------------------- #
def save_jd(url: str, jd_path: Path) -> tuple[bool, str]:
    """Save the JD verbatim via fetch_jd.main; return (ok, message).

    fetch_jd owns the whole extraction/idempotency/warning path. Its stdout/stderr
    are captured so handoff.py keeps its own stdout to the two-line contract; the
    captured text is relayed to the caller for the message.
    """
    if not url:
        return False, "posting row has no URL; save the JD manually"
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fetch_jd.main([url, "--out", str(jd_path)])
    detail = (err.getvalue() or out.getvalue()).strip()
    if code != 0:
        return False, detail or f"fetch_jd failed for {url}"
    return True, detail


_STALE_LAST_SEEN_DAYS = 7


def warn_if_stale(store_key: str) -> None:
    """Warn (stderr) when the store's local last_seen for this posting is stale.

    Queries the LOCAL index by key only (no network); the store never says
    "closed", so a stale last_seen is a prompt to re-check the live board. Fully
    guarded — a disabled/missing store is silent, never an error.
    """
    if not store_key:
        return
    try:
        import config
        data_root = config.data_root()
        if data_root is None:
            return
        from _vendor.store.atomic import read_jsonl
        from _vendor.store.paths import domain_layout
        layout = domain_layout(data_root, "jobs")
        rows = read_jsonl(layout.index / "postings.jsonl")
        row = next((r for r in (rows[1:] if rows else [])
                    if r.get("key") == store_key), None)
        last_seen = row.get("last_seen") if row else None
        if not last_seen:
            return
        seen = datetime.strptime(last_seen, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - seen).days
        if age > _STALE_LAST_SEEN_DAYS:
            print(
                f"handoff: STALE — the store last observed this posting {age} days "
                f"ago (last_seen {last_seen}). The store never says 'closed'; "
                f"re-check the live board before drafting.", file=sys.stderr)
    except Exception:  # noqa: BLE001 — the staleness hint must never break handoff
        return


# --------------------------------------------------------------------------- #
# meta.yaml (schema v6)
# --------------------------------------------------------------------------- #
def carry_metadata(row: dict) -> dict:
    """Carry the row's structured metadata into the schema-v6 posting shape.

    Every one of ``POSTING_METADATA_FIELDS`` is present (the editor requires the
    full set), but values are only carried when the row actually provides them:
    an absent workplace/sponsorship becomes ``""`` and an absent level/YOE becomes
    ``{}`` — both invalid on purpose, so validation fails loud and the tracker's
    ``--enrich-metadata`` fills the gap from the JD rather than handoff inventing a
    value. ``salary_range`` is legitimately nullable (many postings state no pay).
    """
    workplace = _norm(row.get("workplace"))
    if workplace not in WORKPLACE_VALUES:
        remote = _norm(row.get("remote"))  # raw scraper flag, same value domain
        workplace = remote if remote in WORKPLACE_VALUES else ""

    sponsorship = _norm(row.get("sponsorship"))
    if sponsorship not in SPONSORSHIP_VALUES:
        sponsorship = ""

    level = row.get("job_level")
    required_yoe = row.get("required_yoe")
    salary = row.get("salary_range")
    return {
        "workplace": workplace,
        "sponsorship": sponsorship,
        "job_level": level if isinstance(level, dict) and level else {},
        "required_yoe": required_yoe if isinstance(required_yoe, dict) and required_yoe else {},
        "salary_range": salary if isinstance(salary, dict) and salary else None,
    }


def _posted_date(row: dict) -> str:
    """The posting's date (YYYY-MM-DD) from ``posted_at``, or ``""``."""
    raw = str(row.get("posted_at") or "").strip()
    return raw[:10] if raw else ""


def build_meta_bytes(
    rows: list[dict], *, roles: list[str], jd_files: list[str], research_date: str
) -> tuple[bytes, list[str]]:
    """Build meta.yaml bytes for one folder; return (bytes, editor_errors).

    ``rows`` is one folder's posting(s) — a single row for a single-role folder or
    several same-company rows for a grouped multi-role folder; ``roles`` and
    ``jd_files`` are the parallel lists of per-posting labels allocated by
    ``unique_role_label`` and ``unique_jd_filename``. ``roles`` is NOT
    ``row["title"]`` verbatim: a title is not an identity, and two postings that
    share one need distinct labels or they share a cover letter.
    Company-scope fields come
    from the lead (first) row. A scaffold (company scope + one job entry of
    descriptive fields per posting) is rendered first, then the vendored
    ``plan_metadata_edit`` inserts the five metadata fields carried from each row —
    the same formatting-preserving path the tracker uses. If a row's carried
    metadata is incomplete/invalid the editor returns the scaffold unchanged for it
    (no metadata) so the failure surfaces in validation and the tracker can enrich
    it; ``editor_errors`` explains why nothing was carried.
    """
    lead = rows[0]
    job_entries: list[dict] = []
    for row, role, jd_file in zip(rows, roles, jd_files):
        job_entry = {
            "role": role,
            "jd_file": jd_file,
            # Handoff always creates a fresh DRAFTED application; schema v6 pairs
            # that with the deterministic drafted progress summary.
            "status": "drafted",
            "progress": {"phase": "application_prep", "state": "action_required"},
            "location": str(row.get("location") or ""),
            "url": str(row.get("url") or ""),
            "posted_date": _posted_date(row),
        }
        # Durable link to the posting's store biography — COPIED verbatim from the
        # search JSON (handoff never re-derives identity). Additive optional field.
        store_key = str(row.get("store_key") or "").strip()
        if store_key:
            job_entry["store_key"] = store_key
        job_entries.append(job_entry)

    scaffold = {
        "job_metadata_schema_version": APPLICATION_SCHEMA_VERSION,
        "company": str(lead.get("company") or ""),
        # The owner's company-index key, ALWAYS written and ALWAYS empty here.
        #
        # WHY IT IS WRITTEN. Absence is invisible. Before this the field was
        # simply missing from every scaffold, so an application created today was
        # indistinguishable from one whose key someone had considered and decided
        # against — and full coverage decayed one folder at a time with nothing
        # saying so until a human happened to run
        # `status.py --company-keys`. An explicit null is the same "unkeyed"
        # state, sitting on the line where the key belongs, in the file the owner
        # already opens.
        #
        # WHY IT IS EMPTY. The index is the owner's and lives in the private
        # overlay (`private/companies/_index.yaml`), which this public script may
        # not have; and a key is OWNER-ASSIGNED — `handoff` inventing one would
        # write a key the index does not contain, which is worse than none. So
        # this never resolves anything, with or without an overlay: the output is
        # the same on the owner's machine, in CI and in a bare clone.
        #
        # WHY `null` AND NOT `""`. A null (or absent) key means UNASSIGNED and is
        # counted unkeyed by `status.py --company-keys`, skipped by the
        # reconciler's company-index check and accepted by `validate_meta`. A
        # blank string, `false`, `0` or any value carrying whitespace is
        # MALFORMED to all three. The two must never be confused, and
        # `tests/test_handoff.py::ScaffoldedCompanyKeyTests` pins that they are
        # not.
        #
        # It is ADDITIVE and stays that way: nothing here compares it, and no
        # skip, dedup, filter or coverage path reaches this function
        # (`automation/shared/tests/test_company_key_additive.py`).
        "company_key": None,
        "research_date": research_date,
        "channel": str(lead.get("source") or ""),
        "jobs": job_entries,
    }
    raw = yaml.safe_dump(
        scaffold,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    ).encode("utf-8")

    generated = {("jobs", index): carry_metadata(row)
                 for index, row in enumerate(rows)}
    plan = plan_metadata_edit(raw, generated)
    # On success output_bytes is the filled meta.yaml; on any editor error it is
    # the scaffold unchanged (fail-closed), which validation then flags.
    return plan.output_bytes, list(plan.errors)


# --------------------------------------------------------------------------- #
# Location policy gate (mirrors status.py --check-locations for one folder)
# --------------------------------------------------------------------------- #
def gather_locations(meta: dict, folder: Path) -> list[str]:
    """Every posting-location string for the scaffolded application.

    Mirrors the tracker's ``app_locations``: prefer the ``location`` recorded in
    meta.yaml (top-level, then each ``jobs:`` entry); fall back to the ``Location:``
    line(s) of any saved ``source/JD-*.md`` when meta.yaml records none.
    """
    locs: list[str] = []
    top = str(meta.get("location") or "").strip()
    if top:
        locs.append(top)
    jobs = meta.get("jobs")
    if isinstance(jobs, list):
        for job in jobs:
            if isinstance(job, dict) and str(job.get("location") or "").strip():
                locs.append(str(job["location"]).strip())
    if locs:
        return locs
    source_dir = folder / "source"
    if source_dir.is_dir():
        for jd in sorted(source_dir.glob("JD-*.md")):
            try:
                locs.extend(extract_jd_locations(jd.read_text(encoding="utf-8")))
            except OSError:
                continue
    return locs


def job_locations(job: dict, folder: Path) -> list[str]:
    """ONE posting's location string(s): its own ``location``, else its own JD's.

    ``jobs[].jd_file`` is the exact one-to-one mapping from a posting to the
    verbatim JD saved for it, and by the time the gate runs that file is on disk.
    The fallback is what catches a blank-``location`` search row: the row said
    nothing, so the pre-filter read it as ``review`` and kept it, and nothing ever
    read the ``Location: London, United Kingdom`` line sitting in the folder.
    """
    loc = str(job.get("location") or "").strip()
    if loc:
        return [loc]
    name = str(job.get("jd_file") or "").strip()
    if not name or Path(name).name != name:
        return []
    for directory in (folder / "source", folder):
        try:
            text = (directory / name).read_text(encoding="utf-8")
        except OSError:
            continue
        return extract_jd_locations(text)
    return []


class LocationReport(NamedTuple):
    """One folder's location verdict, and the postings that decided it."""
    verdict: str                              # "match" | "review" | "mismatch"
    category: str
    locations: list[str]
    offending: list[tuple[str, str, str]]     # (role, location, category)
    unclassified: list[tuple[str, str]]       # (role, location or "(none recorded)")


def check_location_policy(meta: dict, folder: Path) -> LocationReport:
    """Classify EVERY posting in the folder against ``config.location_policy()``.

    **Per posting, worst-wins.** The AGENTS.md policy governs a POSTING ("only
    draft a role whose ``location`` matches"); a folder is just the container one
    resume covers. The old rollup asked ``classify_locations`` — an ANY-matches
    rule — over the folder's POOLED location strings, which answers "could I take
    some job at this employer?" That is the right question for a single-role
    folder and the wrong one for the multi-role folder this tool now builds by
    default: one Seattle sibling made a London requisition in the same folder
    print ``location OK``, and the drafting agent then wrote a cover letter for a
    role the owner cannot take. handoff's own multi-role pre-filter already says
    per-posting is the rule ("keep only the postings that match the policy"); this
    makes the gate agree with it.

    Each posting is classified from its own ``location``, falling back to its own
    ``jd_file`` (see ``job_locations``). The folder's verdict is the WORST posting
    verdict: any definite mismatch makes the folder a mismatch, and every
    offending posting is named. ``review`` still never blocks — a genuinely
    unknown location must not stop legitimate work, which is the same
    false-positive/false-negative split the tracker draws and which
    ``test_location_unknown_is_review_not_block`` pins.

    A meta with no ``jobs:`` list at all (a legacy top-level shape) keeps the
    folder rollup: there is no posting to attribute a location to.
    """
    import config  # vendored toolkit loader (location policy)
    policy = config.location_policy()
    jobs = [job for job in (meta.get("jobs") or []) if isinstance(job, dict)]
    if not jobs:
        locs = gather_locations(meta, folder)
        category, matched = classify_locations(locs, policy)
        if matched:
            return LocationReport("match", category, locs, [], [])
        shown = " | ".join(locs) or "(none recorded)"
        if category == "unknown":
            return LocationReport("review", category, locs, [], [("", shown)])
        offending = [("", loc, classify_location(loc, policy)) for loc in locs
                     if not is_match(classify_location(loc, policy))]
        return LocationReport("mismatch", category, locs, offending, [])

    all_locs: list[str] = []
    offending: list[tuple[str, str, str]] = []
    unclassified: list[tuple[str, str]] = []
    matched_categories: list[str] = []
    mismatch_categories: list[str] = []
    for job in jobs:
        role = str(job.get("role") or "").strip() or "(unnamed posting)"
        locs = job_locations(job, folder)
        all_locs.extend(locs)
        category, matched = classify_locations(locs, policy)
        if matched:
            matched_categories.append(category)
        elif category == "unknown":
            unclassified.append((role, " | ".join(locs) or "(none recorded)"))
        else:
            mismatch_categories.append(category)
            for loc in locs:
                loc_category = classify_location(loc, policy)
                if not is_match(loc_category):
                    offending.append((role, loc, loc_category))

    if mismatch_categories:
        return LocationReport(
            "mismatch", mismatch_categories[0], all_locs, offending, unclassified)
    if unclassified:
        return LocationReport("review", "unknown", all_locs, [], unclassified)
    category = ("metro" if "metro" in matched_categories
                else matched_categories[0] if matched_categories else "unknown")
    return LocationReport("match", category, all_locs, [], [])


def report_location(
    report: LocationReport, folder: Path, *, allow_mismatch: bool
) -> bool:
    """Emit the location verdict to stderr; return True iff drafting is blocked.

    Keeps handoff's two-line stdout contract intact — every location message goes
    to stderr alongside the other diagnostics. ``match`` and ``review`` never
    block; a ``mismatch`` blocks (returns True) unless ``allow_mismatch``
    overrides it — and under that flag the mismatch is still REPORTED, because the
    flag's own help promises a warning and then proceeding, not silence.
    """
    shown = " | ".join(report.locations) if report.locations else "(none recorded)"
    if report.verdict == "match":
        print(f"handoff: location OK [{report.category}]: {shown}", file=sys.stderr)
        return False
    if report.verdict == "review":
        detail = " | ".join(
            f"{role}: {loc}" if role else loc
            for role, loc in report.unclassified) or shown
        print(
            f"handoff: location NOT classifiable [{report.category}]: {detail} — "
            "review it against the location policy manually before drafting.",
            file=sys.stderr,
        )
        return False
    # Definite mismatch (foreign / non-preferred US office), named per posting.
    detail = " | ".join(
        f"{role}: {loc} [{cat}]" if role else f"{loc} [{cat}]"
        for role, loc, cat in report.offending) or shown
    print(
        f"handoff: LOCATION POLICY MISMATCH [{report.category}] — "
        f"{len(report.offending) or 1} posting(s) in this folder are outside the "
        f"configured location policy: {detail}",
        file=sys.stderr,
    )
    for role, loc in report.unclassified:
        print(
            f"handoff: location NOT classifiable: {role}: {loc} — review it "
            "against the location policy manually.",
            file=sys.stderr,
        )
    if allow_mismatch:
        print(
            "handoff: --allow-location-mismatch set; keeping the folder and "
            "proceeding despite the mismatch.",
            file=sys.stderr,
        )
        return False
    # The remedy names only actions an AGENT may take. It used to open with "delete
    # the folder", which is the one act AGENTS.md forbids outright — application
    # folders "are removed by the USER only — never by an agent, under any
    # condition" — and the folder is deliberately left on disk for review, not as a
    # deletion cue.
    print(
        f"handoff: remedy — the folder is left on disk at {folder} for review; "
        "re-run the selection without the offending posting(s), or rerun with "
        "--allow-location-mismatch if these locations are intentional. Do NOT "
        "remove the folder: application folders are removed by the USER only, "
        "never by an agent (AGENTS.md, \"Agents never delete owner data\") — "
        "propose the removal in message-queue/needs-human/ if it should go.",
        file=sys.stderr,
    )
    return True


def row_location_verdict(row: dict) -> tuple[str, str]:
    """Classify ONE search row's location against ``config.location_policy()``.

    Returns ``(verdict, category)`` — ``"match"`` (preferred metro / US-remote),
    ``"mismatch"`` (a definite policy violation: foreign or non-preferred US
    office), or ``"review"`` (blank / unrecognized). Used by the grouping path to
    drop definite mismatches from a multi-role company folder before it is built,
    keeping only policy-matching postings.
    """
    import config  # vendored toolkit loader (location policy)
    policy = config.location_policy()
    loc = str(row.get("location") or "").strip()
    if not loc:
        return "review", "unknown"
    category = classify_location(loc, policy)
    if is_match(category):
        return "match", category
    if category == "unknown":
        return "review", category
    return "mismatch", category


# --------------------------------------------------------------------------- #
# Creation-time skip-log append
# --------------------------------------------------------------------------- #
def _record_created_postings(
    meta: dict,
    folder: Path,
    root: Path,
    args: argparse.Namespace,
    code: int,
) -> int:
    """Append this folder's postings to the append-only skip-log; return how many.

    **Why this exists.** Until it did, a posting could be worked on and then vanish
    from the log entirely: scaffold it here, decide against it the same day, delete
    the folder, and the log had never seen it — so the next search re-surfaced it
    as fresh. The status writers cover every status TRANSITION; nothing covered
    creation, which is the one event every application has.

    **Ordering: the folder is created first, this append is last.** The two crash
    residues are not symmetric. Crash after the append and before the folder, and
    the log claims a posting that was never scaffolded: job-search skips it
    forever, the symptom is a posting that silently never appears, and the only
    repair is an owner who somehow notices and runs ``--forget-log``. Crash after
    the folder and before the append, and the residue is a scaffolded folder with
    no row — visible in ``6_drafted``, still caught by the live-folder half of
    ``_posting_keys``, listed by ``status.py``, and turned into a row by the next
    ``--sync-log``. One residue is silent and permanent; the other is loud and
    self-healing. The append also states a fact ("an application folder exists for
    this posting") that is only true once the folder exists.

    **Idempotency.** A second run over the same posting never reaches this
    function — a same-day rerun hits the refuse-to-overwrite branch, and a bulk
    rerun is stopped by the duplicate preflight, which now sees this very row.
    Under ``--research-date`` a later re-scaffold does reach it, and appends one
    line because slug and date genuinely changed; the fold is last-wins, so the
    fresher row is the one every reader sees. Beyond that,
    ``skip_log.record_postings`` appends only what differs from the fold, so
    repeated identical calls write nothing.

    **Concurrency** is whatever ``skip_log.append_event`` already provides for the
    tracker: one fsync'd ``O_APPEND`` write per event, no lock. Nothing new is
    invented here — a second writer taking a lock the first one does not is not
    mutual exclusion.

    ``code`` is the exit this scaffold is about to return. Every created folder is
    recorded regardless of it (see the note below); a non-zero code additionally
    prints the un-skip command, because a folder that later goes away — and only
    the OWNER may make it go away — no longer un-skips the posting on its own.
    """
    # Must equal what ``load_application`` derives from the same slug, or the next
    # --sync-log sees a differing row and appends a redundant line for every
    # posting, forever. Same parse: <company>-<role>-YYYYMMDD.
    slug = folder.name
    stamp = slug.rsplit("-", 1)[-1]
    date = (f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
            if len(stamp) == 8 and stamp.isdigit() else "")
    rows = skip_log.posting_rows({
        "company": meta.get("company") or "",
        "slug": slug,
        "date": date,
        # The folder's derived rollup, used only for a posting with no status of
        # its own; a scaffold always writes one ("drafted").
        "status": status_label_for_dir(args.status_dir) or "",
        "jobs": meta.get("jobs") or [],
    })
    log_path = _applications_jsonl(root, args.applications_root)
    appended = skip_log.record_postings(log_path, rows, source="handoff")
    if not appended:
        return 0
    print(f"handoff: recorded {appended} posting event(s) -> {log_path}",
          file=sys.stderr)
    if code == 0:
        return appended
    # A folder the tool just told you not to draft (location mismatch, missing JD,
    # incomplete metadata) is still a considered posting, and it is the folder
    # MOST likely to be deleted — so recording it is the whole point rather than an
    # edge case. The cost is that deleting it no longer un-skips the posting, so
    # name the repair here, with the argument already filled in.
    print(
        "handoff: this scaffold is not clean, but its postings are recorded — the "
        "skip-log tracks what was CONSIDERED and the folder exists. Deleting the "
        "folder does NOT un-skip them; to surface a posting again, append a "
        "tombstone:",
        file=sys.stderr,
    )
    for row in rows:
        target = (f'"{row["url"]}"' if row["url"]
                  else f'"{row["company"]}" "{row["role"]}"')
        print(f"  status.py --forget-log {target}", file=sys.stderr)
    return appended


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _run_group(
    group: list[dict],
    args: argparse.Namespace,
    *,
    taken_slugs: set[str] | None = None,
) -> tuple[int, Path]:
    """Scaffold ONE application folder from a group of same-company posting(s).

    A single-element group is a single-role folder (unchanged behavior, including
    the definite-mismatch block that leaves the folder + exits 3). A multi-element
    group is a one-folder-per-company multi-role folder: definite location
    mismatches are dropped from it (each reported) unless
    ``--allow-location-mismatch`` is set, and the folder slug uses the lead
    (highest-ranked) posting's role.

    ``taken_slugs`` is the set of slugs THIS RUN has already built; it is mutated.
    Under ``--split`` two same-title requisitions would otherwise produce the same
    slug and the second would hit refuse-to-overwrite against its own sibling.
    """
    company = str(group[0].get("company") or "").strip()
    lead_role = str(group[0].get("title") or "").strip()
    if not company:
        raise ValueError("selected posting has no company; cannot build a folder slug")
    if not lead_role:
        raise ValueError("selected posting has no title; cannot build a folder slug")

    research_date = args.research_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    root = _applications_root(args.applications_root)
    if taken_slugs is None:
        taken_slugs = set()
    slug = unique_folder_slug(company, lead_role, research_date,
                              role_discriminator(group[0]), taken_slugs)
    folder = root / args.status_dir / slug
    _require_folder_under_root(folder, root, args.status_dir)

    if folder.exists():
        print(
            f"handoff: refusing to overwrite existing folder: {folder}",
            file=sys.stderr,
        )
        return 2, folder

    # --- multi-role location pre-filter ----------------------------------- #
    # When grouping several postings into one company folder, keep only the ones
    # that satisfy the location policy (resume-writer: "for a multi-role company,
    # keep only the postings that match the policy"). A SINGLE-role folder is not
    # pre-filtered — its definite mismatch stays a loud block (code 3) below, so an
    # explicitly selected off-policy posting is never silently dropped.
    rows = list(group)
    if len(rows) > 1 and not args.allow_location_mismatch:
        kept: list[dict] = []
        for row in rows:
            verdict, category = row_location_verdict(row)
            if verdict == "mismatch":
                print(
                    f"handoff: dropping {row.get('title')!r} from the {company} "
                    f"folder — location {str(row.get('location') or '')!r} "
                    f"[{category}] is outside the configured location policy.",
                    file=sys.stderr,
                )
                continue
            kept.append(row)
        if not kept:
            print(
                f"handoff: no {company} posting satisfies the location policy; "
                "nothing scaffolded (rerun with --allow-location-mismatch to keep "
                "them, or --split to handle roles individually).",
                file=sys.stderr,
            )
            return 3, folder
        rows = kept

    source_dir = folder / "source"
    source_dir.mkdir(parents=True, exist_ok=False)
    taken_slugs.add(slug)

    # --- per-JD labels ---------------------------------------------------- #
    # ONE allocation, then everything per-posting is derived from it: the
    # cover-letter / bundle stem (``jobs[].role``) and the verbatim JD filename.
    # Deriving them separately is what let a folder hold two disambiguated JD
    # files under one shared cover-letter stem.
    used_labels: set[str] = set()
    roles = [unique_role_label(str(row.get("title") or ""),
                               role_discriminator(row), used_labels)
             for row in rows]
    for row, role in zip(rows, roles):
        if role != str(row.get("title") or "").strip():
            print(
                f"handoff: another {company} posting in this folder already has "
                f"the title {str(row.get('title') or '')!r}; this one is labelled "
                f"{role!r} so it keeps its own cover letter and bundle (one cover "
                "letter per JD). Rename it in meta.yaml if you prefer different "
                "wording — it goes in the letter's target-position line.",
                file=sys.stderr,
            )

    # --- JD (verbatim, exactly one fetch per posting) --------------------- #
    # Fresh-JD refusal (store-is-never-verification): scaffolding without a
    # session-fresh JD is NOT allowed — the store is memory that routes attention,
    # never a substitute for the JD text you act on. A skip or a failed fetch is an
    # explicit refusal (non-zero exit); there is no override flag.
    jd_ok = True
    used_jd_names: set[str] = set()
    jd_files: list[str] = []
    for row, role in zip(rows, roles):
        jd_file = unique_jd_filename(role, used_jd_names)
        jd_files.append(jd_file)
        if args.skip_jd_fetch:
            jd_ok = False
            print(
                f"handoff: REFUSING to treat this as ready — --skip-jd-fetch means no "
                f"session-fresh JD, and the store is never a verification substitute. "
                f"Save {source_dir / jd_file} live this session before drafting.",
                file=sys.stderr,
            )
        else:
            ok, jd_msg = save_jd(str(row.get("url") or ""), source_dir / jd_file)
            if not ok:
                jd_ok = False
                print(
                    f"handoff: REFUSING to treat this as ready — no session-fresh JD "
                    f"({jd_msg}), and the store is never a verification substitute; you "
                    f"must act on the live JD text, not stored facts. The folder is "
                    f"scaffolded but NOT draftable until you save "
                    f"{source_dir / jd_file} live this session. If the page is "
                    "JS-rendered, recover the verbatim JD via `company_roles.py --jd`; "
                    "if no fetch works at all (e.g. HTTP 403), save the scraper-extracted "
                    "text with a non-verbatim provenance note (reference.md § "
                    "\"Recovering a JD when the page fetch is unusable\").",
                    file=sys.stderr,
                )
        # Stale-posting hint (local store lookup by the copied store_key; never blocks).
        warn_if_stale(str(row.get("store_key") or "").strip())

    # --- meta.yaml (schema v6, facts carried from every row) -------------- #
    meta_bytes, editor_errors = build_meta_bytes(
        rows, roles=roles, jd_files=jd_files, research_date=research_date)
    (folder / "meta.yaml").write_bytes(meta_bytes)
    for message in editor_errors:
        print(f"handoff: metadata not carried: {message}", file=sys.stderr)
    # The company key is scaffolded EMPTY on purpose (the long reason is in
    # ``build_meta_bytes``). Say so once per folder, at the moment the gap is
    # created: a coverage report read weeks later is the surface that already
    # existed, and it is the one that let coverage decay unnoticed.
    print(
        f"handoff: meta.yaml carries an empty company_key for {company!r}. It is "
        "owner-assigned and its index is private, so nothing here can resolve "
        "one: fill it in (adding the employer to the index first if it is new), "
        "or leave it null and `status.py --company-keys` keeps counting this "
        "application unkeyed.",
        file=sys.stderr,
    )

    # --- validate (vendored job_metadata) --------------------------------- #
    meta = yaml.safe_load(meta_bytes.decode("utf-8"))
    errors = validate_meta(meta, app_dir=folder)

    # --- location policy gate (per posting, worst-wins) ------------------- #
    location = check_location_policy(meta, folder)

    print(folder)
    print(f"meta.yaml: {'valid' if not errors else 'INVALID'}")
    if len(rows) > 1:
        print(
            f"handoff: grouped {len(rows)} {company} postings into one folder "
            "(one resume, a multi-role jobs: list, one cover letter per posting).",
            file=sys.stderr,
        )
    if errors:
        print("handoff: meta.yaml is not yet complete:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "handoff: run "
            "`status.py --enrich-metadata <slug>` to fill JD-derived facts, "
            "then `status.py --check-metadata`.",
            file=sys.stderr,
        )

    # Location policy gate. A definite mismatch is the highest-priority failure
    # ("do not draft this posting at all"), so it wins over an incomplete-metadata
    # / missing-JD exit; ``--allow-location-mismatch`` downgrades it to a warning.
    # For a multi-role folder the pre-filter above removed the mismatches VISIBLE
    # IN THE SEARCH ROW; this fires for a single-role folder, under
    # --allow-location-mismatch, and for a posting whose row carried no location
    # and whose fetched JD turns out to name a place outside the policy — the one
    # case the pre-filter cannot see, and the one it must not silently drop.
    location_blocked = report_location(
        location, folder, allow_mismatch=args.allow_location_mismatch)
    code = 3 if location_blocked else (0 if (errors == [] and jd_ok) else 1)

    # LAST, and only now that the folder is really on disk — see
    # ``_record_created_postings`` for why the append trails folder creation
    # rather than leading it. Every early return above this line leaves the tree
    # untouched (refuse-to-overwrite, an all-mismatch group, a slug-less row), and
    # each of them returns before this call, so nothing is recorded that was not
    # built. This is also the single funnel: ``run`` and ``_run_groups`` both
    # scaffold through ``_run_group``, so one call covers every path.
    _record_created_postings(meta, folder, root, args, code)
    return code, folder


# Exit codes _run_group returns, mapped to a bulk-report status. A location
# mismatch is auditable as its own status/count (distinct from an incomplete
# scaffold) so a run's report shows exactly why each folder is not clean. Exit 2
# (refuse-to-overwrite) has its own bucket for the same reason and a sharper one:
# it created NOTHING, so calling it an "incomplete" scaffold overstates how many
# folders exist and aims a follow-up agent at another posting's complete one.
_BULK_STATUS_BY_CODE = {0: "created", 2: "refused", 3: "location_mismatch"}


def _register_row(row: dict, urls: set[str], pairs: set[tuple[str, str]]) -> None:
    """Mark the posting this run just scaffolded — by its identity, and only that.

    ``posting_key`` decides which set the row lands in: a URL-bearing row
    registers its URL, a URL-less row registers its ``(company, title)`` pair.
    Registering BOTH — what this did before — claimed that EVERY posting at that
    company with that title was now handled, so the next group's genuinely
    distinct requisition (different URL, different city) matched the pair and was
    dropped as a "duplicate" of its own sibling: nothing scaffolded, nothing
    appended to the skip-log, exit 0, and one stderr line saying it "already
    exists in the log or a live application folder" when it existed in neither.

    ``_posting_keys`` deliberately keeps registering both keys off log and
    live-folder rows; that asymmetry is argued in its docstring.
    """
    key = posting_key(row.get("company"), row.get("title"), row.get("url"))
    if key[0] == "url":
        urls.add(key[1])
    elif all(key[1:]):
        pairs.add((key[1], key[2]))


def _run_groups(
    groups: list[list[dict]],
    args: argparse.Namespace,
    *,
    keys: tuple[set[str], set[tuple[str, str]]] | None = None,
) -> int:
    """Scaffold one folder per group (one folder per company by default).

    Duplicate preflight runs per POSTING within each group (a posting already in a
    log/live folder is skipped, never re-drafted); a group whose postings are all
    duplicates creates nothing. Each created folder's postings are then registered
    so a later group can't re-draft them. ``keys`` lets ``run`` hand over the
    preflight sets it already built for the single-posting path, so both paths
    read the log and the live folders exactly once, from the same snapshot.
    """
    root = _applications_root(args.applications_root)
    urls, pairs = keys if keys is not None else _posting_keys(
        root, _applications_jsonl(root, args.applications_root))
    report: list[dict] = []
    counts = {
        "created": 0,
        "incomplete": 0,
        "location_mismatch": 0,
        "refused": 0,
        "duplicate": 0,
        "failed": 0,
    }
    taken_slugs: set[str] = set()

    for group in groups:
        company = group[0].get("company")
        # Per-posting duplicate filter within the group.
        fresh: list[dict] = []
        for row in group:
            reason = _duplicate_reason(row, urls, pairs)
            if reason:
                counts["duplicate"] += 1
                report.append({
                    "company": row.get("company"),
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "status": "duplicate",
                    "detail": reason,
                })
                print(
                    f"handoff: skipped duplicate: "
                    f"{row.get('company')} / {row.get('title')} ({reason})",
                    file=sys.stderr,
                )
            else:
                fresh.append(row)
        if not fresh:
            continue

        try:
            code, folder = _run_group(fresh, args, taken_slugs=taken_slugs)
        except ValueError as exc:
            counts["failed"] += 1
            report.append({
                "company": company,
                "titles": [row.get("title") for row in fresh],
                "status": "failed",
                "detail": str(exc),
            })
            print(f"handoff: {company} group failed: {exc}", file=sys.stderr)
            continue

        status = _BULK_STATUS_BY_CODE.get(code, "incomplete")
        counts[status] += 1
        entry = {
            "company": company,
            "titles": [row.get("title") for row in fresh],
            "status": status,
            "exit_code": code,
        }
        # A refusal created NOTHING; ``folder`` is the PRE-EXISTING application
        # that already owns the slug, and it belongs to a different posting.
        # Reporting it under the same key every other row uses for "the folder
        # this run built" is what aims an agent working the report at the wrong
        # folder, so name it as the conflict it is.
        entry["conflicting_folder" if status == "refused" else "folder"] = str(folder)
        report.append(entry)
        if status == "refused":
            # Nothing was built and nothing was logged: this posting is still
            # unhandled, so registering it would mark it done and hide it from the
            # next run's preflight.
            continue
        # A partial scaffold (or a mismatch folder left for review) is still a live
        # folder; register its postings so a later group cannot duplicate them.
        for row in fresh:
            _register_row(row, urls, pairs)

    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps({"counts": counts, "rows": report}, indent=2),
            encoding="utf-8",
        )
    print(
        "Bulk handoff: "
        + " | ".join(f"{key}={value}" for key, value in counts.items())
    )
    # Any non-clean outcome (incomplete scaffold, location mismatch, a refusal
    # that built nothing, or a hard failure) makes the run exit non-zero.
    return 1 if (
        counts["incomplete"] or counts["location_mismatch"]
        or counts["refused"] or counts["failed"]
    ) else 0


def run(args: argparse.Namespace) -> int:
    rows = load_rows(Path(args.json).expanduser())
    selected = rows if args.select_all else select_rows(rows, args.select)
    groups = group_by_company(selected, split=args.split)
    # The duplicate preflight is hoisted here so EVERY path runs it. It used to
    # live only in ``_run_groups``, which left the three commonest single-posting
    # invocations — ``--select "rank N"`` (SKILL.md's first example),
    # ``--select "Company/Title"`` and ``--select "Company"`` for a company with
    # one posting — with no preflight at all. AGENTS.md's blacklist/log guardrail
    # is not scoped to bulk runs, and ``search_jobs.load_considered`` is only half
    # a backstop: it reads the log, never the live folders, so an application
    # folder with no log row (created before creation-time logging, or left by a
    # crash before the trailing append) re-surfaced as fresh and was drafted a
    # second time.
    root = _applications_root(args.applications_root)
    urls, pairs = _posting_keys(
        root, _applications_jsonl(root, args.applications_root))
    # A single explicitly-selected posting keeps the simple two-line stdout path
    # (folder + validation) and the loud single-role location block.
    if not args.select_all and len(selected) == 1 and len(groups) == 1:
        reason = _duplicate_reason(selected[0], urls, pairs)
        if reason:
            _report_explicit_duplicate(selected[0], reason)
            return 2
        code, _folder = _run_group(groups[0], args, taken_slugs=set())
        return code
    return _run_groups(groups, args, keys=(urls, pairs))


def _iso_date(value: str) -> str:
    """argparse ``type`` for ``--research-date``: a real ``YYYY-MM-DD``, nothing else.

    The value is joined into the folder slug WITHOUT slugifying (``slugify`` runs
    over the company and the role, never the stamp), so a separator in it becomes
    a path separator. ``2026/07/31`` — an ordinary typo for the documented format
    — buried the application two levels below where every tool globs and wrote a
    permanent skip-log row reading ``slug: "31", date: ""``. Rejecting it at the
    boundary is the cheapest place; ``_require_folder_under_root`` is the backstop.
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"must be YYYY-MM-DD (got {value!r}); it is also the folder-slug date "
            "stamp, so anything else lands the application where no tracker "
            "command can see it"
        ) from None
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Scaffold an application folder from a ranked search result.")
    ap.add_argument("--json", required=True,
                    help="search_jobs.py --json-out file (list of posting records).")
    selection = ap.add_mutually_exclusive_group(required=True)
    selection.add_argument("--select",
                           help='Which posting(s): "rank N" (1-based), a rank list '
                                '"rank N,M,P", a bare "Company" (all of that '
                                'company\'s postings → one folder), or an exact '
                                '"Company/Title" (one posting).')
    selection.add_argument("--all", dest="select_all", action="store_true",
                           help="Scaffold every row after duplicate preflight, "
                                "grouped one folder per company (see --split).")
    ap.add_argument("--split", action="store_true",
                    help="Force one folder per posting instead of the default "
                         "one-folder-per-company grouping. Use for a company whose "
                         "selected roles are too divergent for a single honest "
                         "resume (the resume-writer Path B split).")
    ap.add_argument("--applications-root", default=None,
                    help="Applications root (default: the vendored config value).")
    ap.add_argument("--status-dir", default=DEFAULT_STATUS_DIR,
                    help="Status subfolder to create the application under "
                         "(default: %(default)s — new applications are always "
                         "created in 6_drafted per the Folder Convention).")
    ap.add_argument("--research-date", default=None, type=_iso_date,
                    help="Search/handoff date YYYY-MM-DD (default: today, UTC); "
                         "also the folder-slug date stamp, so the format is "
                         "enforced.")
    ap.add_argument("--skip-jd-fetch", action="store_true",
                    help="Do not fetch the JD (offline/testing); the folder is "
                         "scaffolded but exits non-zero so the JD is saved manually.")
    ap.add_argument("--allow-location-mismatch", action="store_true",
                    help="Proceed even when the posting's location is outside the "
                         "configured location policy (foreign / non-preferred US "
                         "office). Without this flag a definite mismatch leaves the "
                         "folder on disk and exits non-zero (code 3).")
    ap.add_argument("--report", default=None,
                    help="Optional JSON report path for --all results (counts + "
                         "per-row status: created, incomplete, location_mismatch, "
                         "refused, duplicate, failed). A `refused` row carries "
                         "`conflicting_folder`, not `folder` — it built nothing.")
    args = ap.parse_args(argv)

    try:
        return run(args)
    except ValueError as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
