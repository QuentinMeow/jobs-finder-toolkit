"""List a single company's live open roles with a location-policy verdict.

This is a targeted re-search helper: given one company (by canonical name from
``companies.yaml`` or by an explicit ``--ats``/``--token``), it fetches that
company's live ATS board and prints every open posting with the location category
from the vendored ``_vendor/location.py`` (a byte-identical copy of the toolkit's
``automation/shared/location.py`` — the same location policy the job profile enforces
via ``config.location_policy``). Use it to re-check whether a specific employer currently has any
posting that matches the location criteria — e.g. before redoing or ignoring a
drafted application.

It does NOT apply the role/seniority/visa title gate — it lists everything so a
human (or agent) can judge role fit against the active job-matching profile
(``config.job_search.default_profile``). The location verdict combines the posting's
location string with the ATS ``remote`` signal (a genuinely remote US/global role
counts as US-remote; a remote role scoped to a foreign region does not).

Examples:
    # Resolve a company already in the registry by its canonical name / alias / token
    .venv/bin/python skills/job-search/scripts/company_roles.py --name Anyscale

    # Ad-hoc company not in the registry (derive ats+token from its careers URL)
    .venv/bin/python skills/job-search/scripts/company_roles.py \
        --company CodeRabbit --ats ashby --token coderabbit

    # Only the postings that match the location rule, as JSON
    .venv/bin/python skills/job-search/scripts/company_roles.py \
        --name Sentry --match-only --json

    # Recover one JS-rendered posting's JD: save the VERBATIM text, print only the
    # ~2 KB gate digest (the same locator fetch_jd.py --digest prints)
    .venv/bin/python skills/job-search/scripts/company_roles.py \
        --name Sentry --jd "Control Plane" \
        --out applications/6_drafted/<slug>/source/JD-Control-Plane.md --digest
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
from fetch_jd import build_digest  # noqa: E402  (sibling script: the ONE digest builder)
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


def _verdict(posting) -> tuple[str, bool]:
    """Location category + match from the canonical full-evidence evaluator."""
    assessment = assess_location(
        posting.location,
        _location_policy(),
        title=posting.title,
        description=posting.description,
        workplace_hint=posting.remote,
    )
    return assessment.category, assessment.matched


def gather(entry: dict) -> list[dict]:
    """Fetch every open posting and attach a location verdict (no filtering)."""
    rows = []
    for p in fetch_company(entry):
        cat, matched = _verdict(p)
        rows.append({
            "match": matched,
            "category": cat,
            "title": p.title,
            "location": p.location,
            "remote": p.remote,
            "posted_at": p.posted_at.date().isoformat() if p.posted_at else "",
            "url": p.url,
        })
    # Matching roles first, then by title.
    rows.sort(key=lambda r: (not r["match"], r["title"].lower()))
    return rows


_NO_DESCRIPTION = "(no description returned by the ATS API)"
_NOT_SAVED = "(NOT SAVED — re-run with --out <path> to save the verbatim JD)"


def dump_jd(entry: dict, needle: str, *, digest: bool = False,
            out: Path | None = None) -> int:
    """Print the description of every posting whose title contains `needle`.

    Lets a caller capture the exact JD text for a chosen role deterministically
    (for writing source/JD-<title>.md) instead of scraping the posting page — the
    documented fallback when a board page is JavaScript-rendered.

    Three levers, all off by default (no flags => stdout is byte-identical to
    before, the full verbatim description):

    - ``out`` writes the VERBATIM description to that path (requires exactly one
      matching posting) and prints the saved path instead of the body, so the JD
      never has to travel through a reader's context to reach the file.
    - ``digest`` prints the deterministic gate locator from ``fetch_jd`` — the SAME
      builder, so both JD-recovery paths emit one format — in place of the body.
    - A description the digest would not SHRINK is passed through VERBATIM even
      with ``digest``, with the reason stated (see ``_DIGEST_MIN_BYTES``).

    The digest is a locator, never the JD. It carries every field the pipeline
    parses out of a JD body, but not the responsibilities/benefits/culture prose
    that drafting and the honesty gates need — so pair ``--digest`` with ``--out``
    for any posting you intend to keep.
    """
    needle_l = needle.lower()
    hits = [p for p in fetch_company(entry) if needle_l in (p.title or "").lower()]
    if not hits:
        print(f"# no posting title contains {needle!r}", file=sys.stderr)
        return 1
    if out is not None and len(hits) > 1:
        print(f"ERROR: --out names a single file but {len(hits)} postings match "
              f"{needle!r}: " + "; ".join(p.title for p in hits) +
              ". Narrow --jd to one posting.", file=sys.stderr)
        return 2

    dumped_bytes = 0
    for p in hits:
        cat, matched = _verdict(p)
        text = p.description or ""
        n = len(text.encode("utf-8"))
        digest_text, note = None, ""
        if digest:
            if n < _DIGEST_MIN_BYTES:
                note = (f"# JD is {n} bytes (< {_DIGEST_MIN_BYTES}) — no digest "
                        f"built; a digest of it would not be smaller.")
            else:
                try:
                    built = build_digest(
                        text, jd_path=str(out) if out else _NOT_SAVED, byte_count=n)
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
        print(f"LocationVerdict: {cat} ({'MATCH' if matched else 'no match'})")
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
                    help="Only show postings that match the configured location policy")
    ap.add_argument("--jd", metavar="TITLE_SUBSTR",
                    help="Dump the full JD text of postings whose title contains this "
                         "substring (for capturing a chosen role's JD)")
    ap.add_argument("--out", metavar="PATH",
                    help="With --jd: write the VERBATIM recovered JD to PATH instead "
                         "of printing it (parent dirs created; requires exactly one "
                         "matching posting).")
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

    if (args.out or args.digest) and not args.jd:
        print("ERROR: --out and --digest apply to --jd only.", file=sys.stderr)
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

    if args.jd:
        try:
            return dump_jd(entry, args.jd, digest=args.digest,
                           out=Path(args.out).expanduser() if args.out else None)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR fetching {entry.get('name')}: {exc}", file=sys.stderr)
            return 1

    try:
        rows = gather(entry)
    except Exception as exc:  # noqa: BLE001 — surface fetch failures clearly to the caller
        print(f"ERROR fetching {entry.get('name')}: {exc}", file=sys.stderr)
        return 1

    total = len(rows)
    matches = sum(1 for r in rows if r["match"])
    shown = [r for r in rows if r["match"]] if args.match_only else rows

    if args.json:
        print(json.dumps({"company": entry.get("name"), "total": total,
                          "matches": matches, "roles": shown}, indent=2))
        return 0

    name = entry.get("name")
    scope = " (matches only)" if args.match_only else ""
    print(f"# {name}: {total} open role(s) fetched, {matches} match "
          f"the location policy (heuristic){scope}")
    if total == 0:
        print("  (board returned 0 postings — verify the ATS token/board is reachable)")
    for r in shown:
        flag = "MATCH" if r["match"] else "no   "
        posted = f" [{r['posted_at']}]" if r["posted_at"] else ""
        print(f"{flag} {r['category']:<13} | {r['title']}{posted}")
        print(f"      loc={r['location']!r} remote={r['remote']}")
        print(f"      {r['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
