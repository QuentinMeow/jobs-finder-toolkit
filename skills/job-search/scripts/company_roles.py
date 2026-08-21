"""List a single company's live open roles with a location-policy verdict.

This is a targeted re-search helper: given one company (by canonical name from
``companies.yaml`` or by an explicit ``--ats``/``--token``), it fetches that
company's live ATS board and prints every open posting with the location category
from the vendored ``_vendor/location.py`` (a byte-identical copy of the toolkit's
``automation/shared/location.py``), applied to ``config.location_policy()``. That is the
DRAFT-time policy — the one ``handoff.py`` and ``status.py --check-locations`` enforce.
The SEARCH-time gate reads a different source: the active profile's ``location:`` block
(``scoring.location_ok``). The two can disagree, and they default differently: ``us_only``
is True when ``config.yaml`` omits it and False when the profile omits it. Use this script
to re-check whether a specific employer currently has any posting that matches the
draft-time location criteria — e.g. before redoing or ignoring a drafted application.

It does NOT apply the role/seniority/visa title gate — it lists everything so a
human (or agent) can judge role fit against the active job-matching profile
(``config.job_search.default_profile``). The location verdict combines the posting's
location string with the ATS ``remote`` signal and the JD text (a genuinely remote
US/global role counts as US-remote; a remote role scoped to a foreign region does not).

The verdict is THREE-valued, exactly as the gate itself is: ``match``, ``no_match``
and ``review``. ``review`` means the posting's fields were silent or contradictory —
most often a board that parks a workplace word ("Hybrid", "In-Office",
"Distributed") in the location field — and the role has to be read by a human.
Both the table and ``--json`` label it distinctly so it is never mistaken for a
rejection, and ``--match-only`` keeps it (it hides only definite non-matches, the
same rule ``scoring.location_ok`` applies inside the search pipeline).

Examples:
    # Resolve a company already in the registry by its canonical name / alias / token
    .venv/bin/python skills/job-search/scripts/company_roles.py --name Anyscale

    # Ad-hoc company not in the registry (derive ats+token from its careers URL)
    .venv/bin/python skills/job-search/scripts/company_roles.py \
        --company CodeRabbit --ats ashby --token coderabbit

    # Drop only the definite non-matches (keeps match + review), as JSON
    .venv/bin/python skills/job-search/scripts/company_roles.py \
        --name Sentry --match-only --json

    # Recover one JS-rendered posting's JD: save the VERBATIM text, print only the
    # ~2 KB gate digest (the same locator fetch_jd.py --digest prints)
    .venv/bin/python skills/job-search/scripts/company_roles.py \
        --name Sentry --jd "Control Plane" \
        --out applications/6_drafted/<slug>/source/JD-Control-Plane.md --digest

    # Several open requisitions share ONE title: select by URL / requisition id
    # (the `url` field --json prints), or by index from the ambiguity listing
    .venv/bin/python skills/job-search/scripts/company_roles.py \
        --name Sentry --jd-url 4512890 --out .../source/JD-Backend.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Self-contained skill: put this skill's own scripts/ on the path for sibling
# imports (registry, sources) and the vendored copy under _vendor/. Never reach
# outside the skill folder — the location rule is vendored (see _vendor/README.md).
SKILL_SCRIPTS = Path(__file__).resolve().parent
for _p in (SKILL_SCRIPTS, SKILL_SCRIPTS / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

from _vendor.location import assess_location  # noqa: E402
from common import drain_source_warnings  # noqa: E402  (the partial-fetch sink)
from fetch_jd import build_digest  # noqa: E402  (sibling script: the ONE digest builder)
from posting_identity import canonicalize_url  # noqa: E402  (the ONE URL normalizer)
from registry import load_registry  # noqa: E402
from sources import fetch_company  # noqa: E402

try:
    import config  # noqa: E402  (vendored toolkit config loader — location policy)
except Exception:  # noqa: BLE001 — standalone use without a config layer
    config = None

# ``--digest`` prints a locator only when the locator is actually SMALLER than the
# JD it summarizes; otherwise the text is passed through VERBATIM with the reason
# stated. Two checks serve that one rule: this cheap size pre-filter (the digest
# runs ~1.5-2.5 KB, so a JD under this is always cheaper read whole and is not even
# built), and a measured comparison for the dense JD — all requirements, no prose —
# whose signal lines are most of its body.
_DIGEST_MIN_BYTES = 2500


def _location_policy() -> dict | None:
    return config.location_policy() if config is not None else None


def _token_saving() -> bool:
    """True when the toolkit's token-usage dial is in its default saving mode.

    Only ever used to print a one-line discoverability HINT on stderr — the mode
    never changes which bytes this script recovers (see ``dump_jd``).
    """
    if config is None:
        return False
    try:
        return config.generation_mode() == "token_saving"
    except Exception:  # noqa: BLE001 — a config-less run simply gets no hint
        return False


def _entry_from_registry(name: str) -> dict | None:
    reg = load_registry()
    canonical = reg.canonical(name) or name
    for e in reg.entries:
        if (e.get("name") or "").strip() == canonical and e.get("ats"):
            return dict(e)
    # Fall back to a direct name match among pollable entries.
    norm = name.strip().lower()
    for e in reg.entries:
        if e.get("ats") and (e.get("name") or "").strip().lower() == norm:
            return dict(e)
    return None


def _verdict(posting):
    """The canonical full-evidence location assessment for one posting."""
    return assess_location(
        posting.location,
        _location_policy(),
        title=posting.title,
        description=posting.description,
        workplace_hint=posting.remote,
    )


# Sort key: confirmed matches, then the roles a human still has to read, then the
# definite rejections.
_DECISION_ORDER = {"match": 0, "review": 1, "no_match": 2}


def _report_source_warnings() -> None:
    """Drain and print the fetchers' "I could not inspect all of this" lines.

    ``sources.py`` records a partial detail outage ("N of M detail fetches
    failed; those postings were not inspected", a truncated listing) into a
    module-level sink. Until this call existed only ``search_jobs.py`` drained
    it, so this script printed a confident three-way tally and exited 0 with an
    empty stderr while the postings whose JD never arrived were judged on their
    office location alone — and a JD-borne US-remote grant cannot fire without
    the JD, so a genuine match reads as a definite ``no``. Call this at EVERY
    ``fetch_company`` site, immediately after the fetch, so no return path can
    skip it.
    """
    for w in drain_source_warnings():
        print(f"company_roles: WARNING — {w}", file=sys.stderr)


def gather(entry: dict) -> list[dict]:
    """Fetch every open posting and attach a location verdict (no filtering)."""
    rows = []
    postings = fetch_company(entry)
    _report_source_warnings()
    for p in postings:
        a = _verdict(p)
        rows.append({
            # `match` is the narrow boolean (decision == "match") and is NOT the
            # keep rule — read `decision` for the three-valued outcome, or a
            # `review` posting looks identical to a rejected one.
            "match": a.matched,
            "decision": a.decision,
            "category": a.category,
            "workplace": a.workplace,
            "confidence": a.confidence,
            "evidence": list(a.evidence),
            "review_reasons": list(a.review_reasons),
            "title": p.title,
            "location": p.location,
            "remote": p.remote,
            # A posting whose detail fetch failed carries no JD, so the JD-borne
            # remote grants cannot fire and its verdict rests on the office
            # location alone. That is a NOT-INSPECTED posting, not a clean `no` —
            # say so per row, since a drained warning names only a count.
            "has_description": bool((p.description or "").strip()),
            "posted_at": p.posted_at.date().isoformat() if p.posted_at else "",
            "url": p.url,
        })
    rows.sort(key=lambda r: (_DECISION_ORDER.get(r["decision"], 3),
                             r["title"].lower()))
    return rows


_NO_DESCRIPTION = "(no description returned by the ATS API)"
_NOT_SAVED = "(NOT SAVED — re-run with --out <path> to save the verbatim JD)"


# ── selecting ONE posting out of a board ─────────────────────────────────────
# Title substring used to be the only JD selector, so a board carrying several
# open requisitions under one byte-identical title could not be narrowed AT ALL:
# the error asked the user to narrow `--jd` while listing indistinguishable
# titles, and this script is the documented recovery path when a posting page is
# JavaScript-rendered. Two more selectors close that: `--jd-url` (the posting URL
# or any unique fragment of it, e.g. the requisition id — the field `--json`
# already prints for every role) and `--jd-index` (1-based, over the ORDER the
# ambiguity error prints).
#
# The order has to be the script's own, not the board's: an ATS may return the
# same requisitions in a different order on the next call, which would silently
# re-point an index at another posting. Sorting by (title, canonical URL) makes
# `--jd-index 2` mean the same posting on every run of the same board.
def _selection_order(postings):
    return sorted(postings,
                  key=lambda p: ((p.title or "").lower(), canonicalize_url(p.url)))


def _url_matches(postings, value: str):
    """Postings whose URL is ``value`` — exact first, else a URL substring.

    Exact (canonicalized) matches win outright when there are any, so pasting a
    full posting URL can never be diluted by another posting that merely contains
    it as a substring. The substring pass is what makes a bare requisition id
    ("7800568003") a usable selector.
    """
    wanted = canonicalize_url(value)
    exact = [p for p in postings if wanted and canonicalize_url(p.url) == wanted]
    if exact:
        return exact
    low = value.strip().lower()
    return [p for p in postings if low and low in (p.url or "").lower()]


def _describe_hits(hits) -> str:
    """The ambiguity listing: index + location + posted date + URL per posting.

    Printing the titles alone is what made the old error unusable — for
    same-title requisitions it repeated one string N times. These are the fields
    that actually differ.
    """
    lines = []
    for i, p in enumerate(hits, 1):
        posted = p.posted_at.date().isoformat() if p.posted_at else "?"
        lines.append(f"  [{i}] {p.title}  | loc={p.location or '?'} "
                     f"| posted={posted}\n      {p.url or '(no url)'}")
    return "\n".join(lines)


def dump_jd(entry: dict, needle: str | None, *, digest: bool = False,
            out: Path | None = None, url: str | None = None,
            index: int | None = None) -> int:
    """Print the description of every posting whose title contains `needle`.

    Lets a caller capture the exact JD text for a chosen role deterministically
    (for writing source/JD-<title>.md) instead of scraping the posting page — the
    documented fallback when a board page is JavaScript-rendered.

    Three levers, all off by default (no flags => stdout is byte-identical to
    before, the full verbatim description):

    - ``out`` writes the VERBATIM description to that path (requires exactly one
      matching posting) and prints the saved path instead of the body, so the JD
      never has to travel through a reader's context to reach the file. An empty
      description is REFUSED (rc 1), never written: a failed detail fetch must
      not truncate a JD the previous run recovered.
    - ``digest`` prints the deterministic gate locator from ``fetch_jd`` — the SAME
      builder, so both JD-recovery paths emit one format — in place of the body.
    - A description the digest would not SHRINK is passed through VERBATIM even
      with ``digest``, with the reason stated (see ``_DIGEST_MIN_BYTES``).

    The digest is a locator, never the JD. It carries every field the pipeline
    parses out of a JD body, but not the responsibilities/benefits/culture prose
    that drafting and the honesty gates need — so pair ``--digest`` with ``--out``
    for any posting you intend to keep.

    ``url`` and ``index`` are the unambiguous selectors (see ``_selection_order``):
    ``url`` keeps postings whose URL is, or contains, that value; ``index`` picks
    the Nth (1-based) of whatever survives, in the deterministic order the
    ambiguity error prints. Either may be used alone or with ``needle``.
    """
    postings = fetch_company(entry)
    _report_source_warnings()
    hits = _selection_order(postings)
    described = []
    if needle:
        needle_l = needle.lower()
        hits = [p for p in hits if needle_l in (p.title or "").lower()]
        described.append(f"--jd {needle!r}")
    if url:
        hits = _url_matches(hits, url)
        described.append(f"--jd-url {url!r}")
    criteria = " + ".join(described) or "(no selector)"
    if not hits:
        print(f"# no posting matches {criteria}", file=sys.stderr)
        return 1
    if index is not None:
        if not 1 <= index <= len(hits):
            print(f"ERROR: --jd-index {index} is out of range: {len(hits)} "
                  f"posting(s) match {criteria}.\n{_describe_hits(hits)}",
                  file=sys.stderr)
            return 2
        hits = [hits[index - 1]]
    if out is not None and len(hits) > 1:
        # Same-title requisitions are common, so "narrow --jd" is not always
        # possible — name the selectors that always are, and show the fields the
        # postings actually differ in.
        print(f"ERROR: --out names a single file but {len(hits)} postings match "
              f"{criteria}:\n{_describe_hits(hits)}\n"
              f"Select one with --jd-url <url-or-requisition-id> (the `url` field "
              f"--json prints) or --jd-index <N> from the list above.",
              file=sys.stderr)
        return 2

    dumped_bytes = 0
    for p in hits:
        a = _verdict(p)
        reasons = f" [{', '.join(a.review_reasons)}]" if a.review_reasons else ""
        text = p.description or ""
        n = len(text.encode("utf-8"))
        if out is not None and not text.strip():
            # Nothing is written until there is something to write. `out` names a
            # JD inside an application folder — owner-owned product content — and
            # the documented recovery recipe is re-run after a failed fetch, so
            # writing "" here TRUNCATES a JD that was already recovered and
            # reports it as a save. Refuse, before mkdir and before the header.
            print(f"ERROR: {p.title!r} returned no description "
                  f"{_NO_DESCRIPTION} — refusing to write {out} "
                  f"(an existing JD there is left untouched).", file=sys.stderr)
            return 1
        digest_text, note = None, ""
        if digest:
            if n < _DIGEST_MIN_BYTES:
                note = (f"# JD is {n} bytes (< {_DIGEST_MIN_BYTES}) — no digest "
                        f"built; a digest of it would not be smaller.")
            else:
                try:
                    # ``p.title`` is the ATS board's own posting title — the
                    # authoritative one, printed on the header line below. Pass it:
                    # without it the digest guesses a title off the first body line,
                    # so a JD that opens with marketing copy reports that paragraph
                    # as TITLE and classifies seniority from it.
                    built = build_digest(
                        text, jd_path=str(out) if out else _NOT_SAVED, byte_count=n,
                        title=p.title)
                except Exception as exc:  # noqa: BLE001 — recovery outranks the digest
                    # Same discipline as fetch_jd._emit_digest: a digest is a
                    # best-effort add-on, so a failure degrades to the verbatim JD
                    # rather than losing the recovery this path exists to perform.
                    built, note = None, f"# could not build the digest ({exc})."
                else:
                    m = len(built.encode("utf-8"))
                    if m < n:
                        digest_text = built
                    else:
                        note = (f"# the digest ({m} bytes) is not smaller than this "
                                f"{n}-byte JD — no digest built.")

        label = "  [DIGEST: gate locator, NOT the full JD]" if digest_text else ""
        print(f"===== {p.title} ====={label}")
        print(f"Location: {p.location}")
        print(f"Remote: {p.remote}")
        print(f"LocationVerdict: {a.category} / {a.workplace} "
              f"({a.decision}){reasons}")
        print(f"Posted: {p.posted_at.date().isoformat() if p.posted_at else ''}")
        print(f"URL: {p.url}")
        print()

        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print(f"VERBATIM JD SAVED: {out} ({n} bytes)")
            print()

        if digest_text is not None:
            print(digest_text)
        else:
            if note:
                print(note)
            if out is None:                  # with --out the verbatim JD is on disk
                print(text or _NO_DESCRIPTION)
                if not digest:
                    dumped_bytes += n
        print()

    if dumped_bytes >= _DIGEST_MIN_BYTES and _token_saving():
        # stderr only: stdout stays byte-identical to the pre-flag behavior. The
        # generation-mode dial nudges the caller toward the cheaper lever; it never
        # decides which bytes a JD-recovery path returns (see the module docstring).
        print(f"company_roles: tip — generation mode is 'token_saving' and this dump "
              f"was {dumped_bytes} bytes. `--digest` prints a ~2 KB gate locator "
              f"instead (title/level, YOE, location, sponsorship, compensation); "
              f"`--out PATH` saves the verbatim JD without printing it.",
              file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="Canonical company name/alias/token in companies.yaml")
    ap.add_argument("--company", help="Display name for an ad-hoc company (with --ats/--token)")
    ap.add_argument("--ats", help="ATS type for an ad-hoc company: greenhouse|ashby|lever|smartrecruiters|workday")
    ap.add_argument("--token", help="ATS board slug/token for an ad-hoc company")
    ap.add_argument("--host", help="Workday host (ad-hoc workday only), e.g. acme.wd1.myworkdayjobs.com")
    ap.add_argument("--site", help="Workday external site (ad-hoc workday only)")
    ap.add_argument("--terms", help="Comma-separated Workday search terms override")
    ap.add_argument("--match-only", action="store_true",
                    help="Hide only the definite non-matches; postings the policy "
                         "matches AND postings it cannot decide (review) are kept, "
                         "the same keep rule the search pipeline uses")
    ap.add_argument("--jd", metavar="TITLE_SUBSTR",
                    help="Dump the full JD text of postings whose title contains this "
                         "substring (for capturing a chosen role's JD)")
    ap.add_argument("--jd-url", metavar="URL_OR_ID",
                    help="Select the posting by its URL, or by any unique fragment of "
                         "it such as the requisition id (the `url` field --json "
                         "prints). This is the selector that works when several open "
                         "requisitions share one title. Usable alone or with --jd.")
    ap.add_argument("--jd-index", metavar="N", type=int,
                    help="Select the Nth (1-based) matching posting, in the order the "
                         "ambiguity error lists them — a stable order this script "
                         "sorts itself, not the board's response order.")
    ap.add_argument("--out", metavar="PATH",
                    help="With --jd: write the VERBATIM recovered JD to PATH instead "
                         "of printing it (parent dirs created; requires exactly one "
                         "matching posting). A posting the ATS returned no "
                         "description for is refused, not written as 0 bytes.")
    ap.add_argument("--digest", action="store_true",
                    help="With --jd: print the deterministic gate LOCATOR "
                         "(title/level, required YOE, workplace/location, "
                         "visa/sponsorship, compensation) instead of the full "
                         "description — the same digest fetch_jd.py --digest prints. "
                         "A JD under "
                         f"{_DIGEST_MIN_BYTES} bytes is printed verbatim anyway. Pair "
                         "with --out: the digest is a locator, never the JD.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = ap.parse_args()

    selecting = bool(args.jd or args.jd_url or args.jd_index is not None)
    if (args.out or args.digest) and not selecting:
        print("ERROR: --out and --digest apply to the JD selectors "
              "(--jd / --jd-url / --jd-index) only.", file=sys.stderr)
        return 2
    if args.jd_index is not None and args.jd_index < 1:
        print("ERROR: --jd-index is 1-based; N must be >= 1.", file=sys.stderr)
        return 2

    if args.name:
        entry = _entry_from_registry(args.name)
        if entry is None:
            print(f"ERROR: '{args.name}' not found as a pollable entry in companies.yaml. "
                  f"Use --company/--ats/--token for an ad-hoc board.", file=sys.stderr)
            return 2
    else:
        if not (args.ats and args.token):
            print("ERROR: provide --name, or --ats and --token for an ad-hoc board.",
                  file=sys.stderr)
            return 2
        entry = {"name": args.company or args.token, "ats": args.ats, "token": args.token}
        if args.host:
            entry["host"] = args.host
        if args.site:
            entry["site"] = args.site
    if args.terms:
        entry["search_terms"] = [t.strip() for t in args.terms.split(",") if t.strip()]

    if selecting:
        try:
            return dump_jd(entry, args.jd, digest=args.digest,
                           out=Path(args.out).expanduser() if args.out else None,
                           url=args.jd_url, index=args.jd_index)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR fetching {entry.get('name')}: {exc}", file=sys.stderr)
            return 1

    try:
        rows = gather(entry)
    except Exception as exc:  # noqa: BLE001 — surface fetch failures clearly to the caller
        print(f"ERROR fetching {entry.get('name')}: {exc}", file=sys.stderr)
        return 1

    total = len(rows)
    matches = sum(1 for r in rows if r["decision"] == "match")
    reviews = sum(1 for r in rows if r["decision"] == "review")
    # --match-only drops definite non-matches only. A `review` posting is one the
    # gate could not decide, so hiding it would silently bury a possible match.
    shown = ([r for r in rows if r["decision"] != "no_match"]
             if args.match_only else rows)

    if args.json:
        print(json.dumps({"company": entry.get("name"), "total": total,
                          "matches": matches, "review": reviews,
                          "roles": shown}, indent=2))
        return 0

    name = entry.get("name")
    scope = " (definite non-matches hidden)" if args.match_only else ""
    rejected = total - matches - reviews
    print(f"# {name}: {total} open role(s) fetched — location policy (heuristic): "
          f"{matches} match, {reviews} review (the posting has to be read), "
          f"{rejected} no{scope}")
    if total == 0:
        print("  (board returned 0 postings — verify the ATS token/board is reachable)")
    for r in shown:
        flag = {"match": "MATCH ", "review": "REVIEW"}.get(r["decision"], "no    ")
        posted = f" [{r['posted_at']}]" if r["posted_at"] else ""
        no_jd = "" if r["has_description"] else "  [no-JD: verdict is location-only]"
        print(f"{flag} {r['category']:<13} | {r['title']}{posted}{no_jd}")
        print(f"      loc={r['location']!r} remote={r['remote']} "
              f"workplace={r['workplace']}")
        if r["review_reasons"]:
            print(f"      review: {', '.join(r['review_reasons'])}")
        print(f"      {r['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
