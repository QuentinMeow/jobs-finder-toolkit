#!/usr/bin/env python3
"""Re-evaluate every STORED posting against the default profile's real gates.

Read-only over the store (derived entities). Applies the SAME deterministic gates
the live pipeline uses (`scoring.py`: posting-quality, title, location, visa,
experience), then dedupes matches against the applications log, live application
folders, and the blacklist. Writes only to local/. This is the "re-evaluate all
jobs stored locally" step after the location-fidelity parser rebuild.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path


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


ROOT = _find_repo_root(Path(__file__).resolve().parent)
for p in ("skills/job-search/scripts/_vendor", "skills/job-search/scripts",
          "automation/shared"):
    sys.path.insert(0, str(ROOT / p))

import yaml  # noqa: E402
import json  # noqa: E402
import config  # noqa: E402
import scoring  # noqa: E402
import skip_log  # noqa: E402  (automation/shared/skip_log.py — folds the skip-log)
from common import JobPosting  # noqa: E402
from registry import load_registry  # noqa: E402
from search_jobs import resolve_profile  # noqa: E402

OUT = ROOT / "local" / "field_fidelity_audit"


def load_entity(posting_yaml: Path) -> JobPosting | None:
    try:
        p = yaml.safe_load(posting_yaml.read_text())
    except Exception:
        return None
    if not isinstance(p, dict):
        return None
    src = (p.get("source_ids") or [{}])[0]
    jd_file = posting_yaml.parent / (p.get("jd", {}) or {}).get("file", "jd.md")
    desc = jd_file.read_text(errors="replace") if jd_file.exists() else ""
    facts = p.get("facts") or {}
    return JobPosting(
        source=src.get("source", ""),
        company=p.get("company", ""),
        title=p.get("title", ""),
        url=src.get("url", ""),
        location=p.get("location", "") or "",
        remote=facts.get("workplace_raw"),
        posted_at=facts.get("posted_at"),
        description=desc,
    )


def gate_decisions(jp: JobPosting) -> dict:
    """Run the real gates; return per-gate pass + overall classification."""
    # posting quality (unfilled ATS templates)
    pq = scoring.assess_posting_quality(jp.title, jp.description)
    title_pass = scoring.title_ok(jp, profile)
    loc_pass = scoring.location_ok(jp, profile)
    visa_pass = scoring.visa_ok(jp, profile)
    exp_pass = scoring.experience_ok(jp, profile)
    t = jp.filter_assessments.get("title", {})
    lc = jp.filter_assessments.get("location", {})
    all_pass = (pq["decision"] != "no_match" and title_pass and loc_pass
                and visa_pass and exp_pass)
    clean = (all_pass and t.get("decision") == "match"
             and lc.get("decision") == "match")
    return {
        "pq": pq["decision"], "title": t.get("decision"),
        "location": lc.get("decision"), "visa": visa_pass, "exp": exp_pass,
        "workplace": jp.workplace, "visa_label": jp.visa_label,
        "review_reasons": jp.review_reasons,
        "all_pass": all_pass, "clean_match": clean,
    }


# ---- covered set: applications skip-log + live folders + blacklist -------- #
def canon(u: str) -> str:
    u = (u or "").split("#")[0].rstrip("/")
    return u.lower()


def build_covered(log_path: Path,
                  apps_root: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """(covered URLs, covered ``(company, title)`` pairs) — skip-log + live folders.

    The log half of this used to read ``log["applications"]`` / ``log["entries"]``,
    keys the applications log has never carried: its only writer emits
    ``{generated, count, postings}``. Both lookups returned ``[]`` on every run, so
    the log contributed NOTHING and "covered" meant "has a live folder" — which
    reports every posting whose folder the owner had since deleted as an uncovered
    new match. Reading the folded skip-log is what the surrounding code always
    claimed to do.

    Rows arrive from ``skip_log.read_postings`` in the ``{company, slug, date,
    status, role, url}`` shape and are pushed through THIS module's ``canon`` at the
    boundary — ``canon`` strips the fragment, which ``skip_log.norm_url``
    deliberately does not, and the store URLs on the other side of the comparison
    are canon'd the same way.
    """
    covered_urls: set[str] = set()
    covered_pairs: set[tuple[str, str]] = set()   # (company_lower, title_lower)

    if log_path.exists():
        for e in skip_log.read_postings(log_path):
            url = e.get("url")
            if url:
                covered_urls.add(canon(url))
            if e.get("company"):
                covered_pairs.add((str(e["company"]).lower(),
                                   str(e.get("role") or "").lower()))

    for status in ("6_drafted", "5_applied", "4_in_progress", "3_rejected",
                   "2_ignored", "1_discoveries"):
        for meta in (apps_root / status).glob("*/meta.yaml"):
            try:
                m = yaml.safe_load(meta.read_text()) or {}
            except Exception:
                continue
            comp = str(m.get("company", "")).lower()
            for j in (m.get("jobs") or []):
                if isinstance(j, dict):
                    if j.get("url"):
                        covered_urls.add(canon(j["url"]))
                    covered_pairs.add(
                        (comp, str(j.get("title") or j.get("role") or "").lower()))
            if m.get("url"):
                covered_urls.add(canon(m["url"]))
    return covered_urls, covered_pairs


def is_blacklisted(company: str) -> bool:
    try:
        return bool(registry.is_blacklisted(company)[0])
    except Exception:
        return False


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface. There are no options — but ``--help`` must still answer.

    The scan below used to sit under a bare ``if __name__ == "__main__":`` with no
    parser at all, so ``--help`` did not print help: it ran the audit, and with no
    store configured it tracebacked out of ``pathlib``. A ``--help`` that crashes is
    not a help. Built in a function so importing this module still costs nothing.
    """
    return argparse.ArgumentParser(
        prog="store_refilter.py",
        description="Re-evaluate every STORED posting against the default profile's "
                    "real gates. Read-only over the store; the only writes go to "
                    f"{OUT.relative_to(ROOT).as_posix()}/.",
        epilog="Takes no options: the profile comes from config.default_profile() "
               "and the store root from paths.data_root / JOBHUNT_DATA_ROOT.")


# ---- scan ---------------------------------------------------------------- #
# Everything below runs ONLY as a script. Importing this module must not resolve a
# private path, load the registry, walk the store, or create ``local/`` output —
# otherwise the helpers above (``build_covered`` in particular) could not be unit
# tested without a real profile, a real store, and the owner's real applications.
# These stay module-level assignments rather than moving into a ``main()`` because
# ``gate_decisions`` and ``is_blacklisted`` read ``profile`` / ``registry`` as
# globals, exactly as they did before.
if __name__ == "__main__":
    from collections import Counter

    build_parser().parse_args()

    # No store means no stored postings to re-filter — a sentence, not a seven-frame
    # TypeError out of ``pathlib``. ``config.data_root()`` returns None BY DESIGN
    # when the store is unconfigured, which is the shipped example config, i.e. every
    # fresh clone and CI. Exit 0, like the store's own ``validate_store.py`` /
    # ``gc_store.py`` ("nothing to validate" / "nothing to garbage-collect"): this
    # tool hands back no verdict a caller could misread as clean, and "the store is
    # empty because there is no store" is a complete answer. ``field_fidelity.py`` in
    # this same folder deliberately exits 2 instead, and says why in its own comment:
    # it was ASKED for a verdict and has none.
    #
    # The guard runs BEFORE ``OUT.mkdir`` and before the profile/registry load, so a
    # refusal leaves no half-built output folder behind and resolves no overlay path.
    _data_root = config.data_root()
    if _data_root is None:
        print("store not configured (set paths.data_root or JOBHUNT_DATA_ROOT); "
              "nothing to re-filter.")
        raise SystemExit(0)

    OUT.mkdir(parents=True, exist_ok=True)

    # Load the default profile YAML. ``resolve_profile`` searches the overlay's
    # private profiles first and the tracked public ones second — the same order the
    # live pipeline uses, so this audit re-evaluates against the SAME gates.
    prof_label = config.default_profile()
    prof_file = resolve_profile(prof_label)
    profile = yaml.safe_load(prof_file.read_text())

    registry = load_registry()

    derived = Path(_data_root) / "jobs" / "derived" / "postings"

    covered_urls, covered_pairs = build_covered(
        Path(config.applications_jsonl_path()),
        Path(config.applications_root()),
    )

    n = 0
    clean_matches: list[dict] = []
    review_matches: list[dict] = []
    for py in derived.glob("*/*/posting.yaml"):
        n += 1
        jp = load_entity(py)
        if jp is None or not jp.title:
            continue
        # cheap title cut first (avoids full gate on obvious non-roles)
        if not scoring.title_ok(jp, profile):
            continue
        d = gate_decisions(jp)
        if not d["all_pass"]:
            continue
        rec = {
            "company": jp.company, "title": jp.title, "location": jp.location,
            "url": jp.url, "source": jp.source, "workplace": d["workplace"],
            "visa_label": d["visa_label"], "decisions": {
                "title": d["title"], "location": d["location"]},
            "review_reasons": d["review_reasons"],
            "blacklisted": is_blacklisted(jp.company),
            "covered": canon(jp.url) in covered_urls
            or (jp.company.lower(), jp.title.lower()) in covered_pairs,
        }
        (clean_matches if d["clean_match"] else review_matches).append(rec)

    (OUT / "refilter_matches.jsonl").write_text(
        "\n".join(json.dumps(r, default=str) for r in clean_matches + review_matches))

    new_clean = [r for r in clean_matches if not r["covered"] and not r["blacklisted"]]
    new_review = [r for r in review_matches if not r["covered"] and not r["blacklisted"]]

    print(f"scanned {n} stored entities | profile={prof_label}")
    print(f"clean MATCH: {len(clean_matches)}  (new/uncovered: {len(new_clean)})")
    print(f"review-pass: {len(review_matches)}  (new/uncovered: {len(new_review)})")
    print(f"covered already: "
          f"{sum(1 for r in clean_matches+review_matches if r['covered'])}")
    print(f"blacklisted:     "
          f"{sum(1 for r in clean_matches+review_matches if r['blacklisted'])}")
    print("\n=== NEW clean matches by company ===")
    for c, k in Counter(r["company"] for r in new_clean).most_common():
        print(f"  {k:2}  {c}")
    (OUT / "refilter_new.json").write_text(json.dumps(
        {"new_clean": new_clean, "new_review": new_review}, indent=1, default=str))
    print(f"\nwrote {OUT/'refilter_new.json'}")
