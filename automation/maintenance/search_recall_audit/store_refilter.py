#!/usr/bin/env python3
"""Re-evaluate every STORED posting against the default profile's real gates.

Read-only over the store (derived entities). Applies the SAME deterministic gates
the live pipeline uses (`scoring.py`: posting-quality, title, location, visa,
experience), then dedupes matches against the applications log, live application
folders, and the blacklist. Writes only to tmp/. This is the "re-evaluate all
jobs stored locally" step after the location-fidelity parser rebuild.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in ("skills/job-search/scripts/_vendor", "skills/job-search/scripts",
          "automation/shared"):
    sys.path.insert(0, str(ROOT / p))

import yaml  # noqa: E402
import json  # noqa: E402
import config  # noqa: E402
import scoring  # noqa: E402
from common import JobPosting  # noqa: E402
from registry import load_registry  # noqa: E402

OUT = ROOT / "tmp" / "field_fidelity_audit"
OUT.mkdir(parents=True, exist_ok=True)

profile_path = Path(str(config.__dict__.get("_", "")))  # placeholder
# Load the default profile YAML.
prof_label = config.default_profile()
prof_file = ROOT / "skills/job-search/profiles" / f"{prof_label}.yaml"
profile = yaml.safe_load(prof_file.read_text())

registry = load_registry()

data_root = Path(config.data_root())
derived = data_root / "jobs" / "derived" / "postings"


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


# ---- covered set: applications-log + live folders + blacklist ------------- #
def canon(u: str) -> str:
    u = (u or "").split("#")[0].rstrip("/")
    return u.lower()


covered_urls: set[str] = set()
covered_pairs: set[tuple[str, str]] = set()   # (company_lower, title_lower)
apps_root = Path(config.applications_root())
log_path = Path(config.applications_log_path())
if log_path.exists():
    log = yaml.safe_load(log_path.read_text()) or {}
    entries = log.get("applications") or log.get("entries") or []
    if isinstance(log, list):
        entries = log
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        for u in ([e.get("url")] + (e.get("urls") or [])):
            if u:
                covered_urls.add(canon(u))
        if e.get("company"):
            covered_pairs.add((str(e["company"]).lower(),
                               str(e.get("role") or e.get("title") or "").lower()))

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
                covered_pairs.add((comp, str(j.get("title") or j.get("role") or "").lower()))
        if m.get("url"):
            covered_urls.add(canon(m["url"]))


def is_blacklisted(company: str) -> bool:
    try:
        return bool(registry.is_blacklisted(company)[0])
    except Exception:
        return False


# ---- scan --------------------------------------------------------------- #
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

from collections import Counter  # noqa: E402
print(f"scanned {n} stored entities | profile={prof_label}")
print(f"clean MATCH: {len(clean_matches)}  (new/uncovered: {len(new_clean)})")
print(f"review-pass: {len(review_matches)}  (new/uncovered: {len(new_review)})")
print(f"covered already: {sum(1 for r in clean_matches+review_matches if r['covered'])}")
print(f"blacklisted:     {sum(1 for r in clean_matches+review_matches if r['blacklisted'])}")
print("\n=== NEW clean matches by company ===")
for c, k in Counter(r["company"] for r in new_clean).most_common():
    print(f"  {k:2}  {c}")
(OUT / "refilter_new.json").write_text(json.dumps(
    {"new_clean": new_clean, "new_review": new_review}, indent=1, default=str))
print(f"\nwrote {OUT/'refilter_new.json'}")
