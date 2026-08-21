"""Compile a distilled *tailoring card* from the candidate profile + baseline + story bank.

Drafting agents otherwise read the full profile/baseline (~17 KB) plus the whole
story bank (~24 KB) at full fidelity on every application, regardless of need. This
script distills the deterministic, always-needed context into one small card so the
drafting agent reads the card first and opens the full sources only when a pointer or
the JD demands a deep dive (see the resume-writer SKILL.md workflow).

Inputs (via the vendored config accessors — self-contained skill, no repo-root imports):
  * profile markdown  — ``config.profile_md_path()``
  * baseline yaml      — ``config.baseline_path()``
  * story bank         — ``config.story_bank_path()``: ``me/interviews/story-bank/``
                         under the OVERLAY ROOT — NOT the config file's directory. In the
                         real deployment ``config.yaml`` sits at the repo root while the
                         private overlay is mounted at ``private/``, so the bank resolves to
                         ``private/me/interviews/story-bank/``. (An overlay-resident
                         ``config.yaml`` resolves to the same place.) The gardener's
                         card_staleness routine reads the SAME accessor — if the two ever
                         disagreed, the card would carry zero stories and a valid sha256.
                         With no ``config.yaml`` present the config falls back to the tracked
                         example config, whose applications root is
                         ``examples/me/applications``
                         → the Jordan Rivers ``examples/`` fixture ships no story bank, and
                         the digest then says so gracefully.

Output: ``config.tailoring_card_path()`` (``<candidate_dir>/tailoring-card.md``, i.e.
``<applications_root>/0_profile/`` by default).
The card carries, in order: a generated-from header (config-relative source
paths, each source's SHA-256, and a UTC-ISO generation timestamp); identity/locked
fields, target roles, and key numbers; the three skills lists (Approved/Weak may be
compact, but the **Never blocklist is included verbatim and complete** — a blocklist is
never summarized); a per-story digest; and a footer stating the card is derived and the
full profile / story bank win on any conflict.

The card is a DERIVED artifact — the header's source hashes make staleness detectable:
  * ``--check`` recomputes the current source hashes against an existing card's header and
    exits non-zero listing the changed sources (used by the gardener staleness routine).
  * default (build) mode REFUSES to overwrite a card whose sources have NOT changed
    (no-op protection) unless ``--force`` — and always rebuilds when they have changed.

Usage:
    .venv/bin/python skills/resume-writer/scripts/build_tailoring_card.py
    .venv/bin/python skills/resume-writer/scripts/build_tailoring_card.py --check
    .venv/bin/python skills/resume-writer/scripts/build_tailoring_card.py --force

Stdout on build: the card path, its byte count, and estimated tokens (bytes / 4). If the
card exceeds the ~8 KB ceiling it prints one extra WARN line.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path

import yaml

# Self-contained skill: put this folder + its _vendor/ on sys.path so `import config`
# resolves to the vendored copy of the pure toolkit config loader (never repo-root
# Python). See AGENTS.md -> "Sharing Code Across Skills".
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

import config  # noqa: E402  (import after sys.path bootstrap, by design)
# One reader for the profile's '## Skills' boundary, shared with check.py's gate
# and the gardener's skill-drift report (automation/shared/profile_skills.py).
# This file used to locate the section with its own line scan, so a profile
# heading the three disagreed about would put a DIFFERENT vocabulary in the card
# than the render gate enforces — including a silently empty Never blocklist,
# which this card is required to carry verbatim and complete.
from profile_skills import skills_section, subsection_bullets  # noqa: E402
from resume_schema import ResumeSchemaError, normalize_resume  # noqa: E402

CEILING_BYTES = 8192          # ~2k tokens target ceiling for the card
BYTES_PER_TOKEN = 4           # est. tokens = bytes / 4 (repo-wide convention)
# DISPLAY key only — the literal string the card header records for the story-bank
# hash line (and the "no story bank found at ..." hint). It is part of the stored card
# FORMAT, so it must stay byte-identical to automation/gardener/
# card_staleness.py's copy or every existing card reads as stale. The story bank's
# on-disk LOCATION comes from config.story_bank_path().
# The DISPLAY key a card records beside the story bank's sha256 — the location
# itself comes from config.story_bank_path(). Both this file and its twin
# (build_tailoring_card.py / card_staleness.py) must carry the SAME literal:
# change one and not the other and every card reads permanently stale while the
# hash and the on-disk path are both correct. Workspace phase 5 moved the bank
# to me/interviews/story-bank, keeping the leaf name so the 33 sibling-relative
# source_stories refs inside the question bank resolve unedited.
STORY_BANK_REL = "me/interviews/story-bank"
BUILD_CMD = "skills/resume-writer/scripts/build_tailoring_card.py"

# Parses one header "source" line: ``- `<display path>` sha256:<64 hex>`` (any trailing
# annotation such as "(0 stories)" is ignored). Only the header emits this exact shape.
SOURCE_LINE_RE = re.compile(r"- `([^`]+)` sha256:([0-9a-f]{64})")


# ── hashing ──────────────────────────────────────────────────
def _file_sha(path: Path) -> str:
    """SHA-256 of a file's bytes; the empty-input digest when the file is absent."""
    data = path.read_bytes() if path.is_file() else b""
    return hashlib.sha256(data).hexdigest()


def _story_files(story_dir: Path) -> list[Path]:
    return sorted(story_dir.glob("*.md")) if story_dir.is_dir() else []


def _story_bank_hash(story_dir: Path) -> str:
    """Aggregate SHA-256 over the sorted story files (name + bytes).

    One hash over the whole bank makes any add / remove / edit detectable by
    ``--check`` and the gardener without listing every file in the header.
    """
    h = hashlib.sha256()
    for f in _story_files(story_dir):
        h.update(f.name.encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


# ── path display (absolute-free, config-relative) ────────────
def _display_path(p: Path, config_dir: Path) -> str:
    """A config-relative, absolute-free display path (never a home/absolute path)."""
    p = p.resolve()
    for base in (config_dir.resolve(), Path(config.REPO_ROOT).resolve()):
        try:
            return p.relative_to(base).as_posix()
        except ValueError:
            continue
    return p.name


# ── profile / baseline parsing ───────────────────────────────
def _section(md: str, heading_prefix: str) -> list[str]:
    """Body lines under the first ``## `` heading that starts with ``heading_prefix``."""
    out: list[str] = []
    in_sec = False
    for line in md.splitlines():
        if line.startswith("## "):
            in_sec = line.startswith(heading_prefix)
            continue
        if in_sec:
            out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _parse_skills(profile_md: str) -> dict[str, list[str]]:
    """Raw bullet lines for the Approved / Weak / Never lists in ``## Skills``.

    Thin wrapper over the shared reader so the card, the render gate and the
    gardener all find the section by the same rule.
    """
    return subsection_bullets(profile_md)


# ── key numbers ──────────────────────────────────────────────
# A metric is a NUMERIC CORE plus, where the core carries no unit of its own, a
# TAIL of one to three unit/noun words ("18 Kubernetes clusters", "54 minutes").
#
# The cores are precision-first because the card is the DEFAULT context for every
# resume draft and check.py cannot catch a wrong unit — the digits are real, so a
# corrupted unit ships as a silent overclaim. The pattern this replaced matched
# ``\d[\d,]*(?:\.\d+)?\s?[MKB]\+?`` case-INSENSITIVELY, so the magnitude suffix
# bound to the first letter of the FOLLOWING WORD: "18 Kubernetes clusters" became
# "18 K" (read back as 18,000 — a 1000x overclaim) and "54 minutes" became "54 m",
# while the metrics that actually mattered ("120 services", "14 APIs", "1,200 to
# 430 pages") were dropped entirely (issue #260). A magnitude suffix therefore now
# binds only when it is really a magnitude: it must be uppercase or attached to the
# digits, and it must not be followed by another letter or digit.
MAX_KEY_NUMBERS = 12

_SP = r"[ \t]"        # never \s — a tail must not cross a line break and glue the
                      # next bullet's opening words onto this bullet's number.
_NUM = r"\$?\d+(?:,\d{3})*(?:\.\d+)?"
_START = r"(?<![A-Za-z0-9.])"   # not mid-token ("p99") and not mid-version ("v1.2.3")

# Words that can never be a metric's unit or noun; they terminate a tail. "per" is
# deliberately absent — it is allowed only BETWEEN tail words ("120 requests per
# second"), never as the last one.
_TAIL_STOPWORDS = (
    "a an and or the of to in into on at by for from with within without across "
    "after before between during over under up via than that which while when "
    "where as but so if then plus about around near until since is are was were "
    "be been being has have had will would can could may might do does did "
    "it its we our us they their them he she his her i you your my this these "
    "those each every all both more most less fewer other others another such same"
).split()
# A tail word is at least two characters: a lone letter is a list marker ("tier 3
# B, C"), never a unit — that is the very confusion this module must not make.
_TAIL_WORD = (r"(?!(?i:%s)\b)[A-Za-z][A-Za-z0-9]+(?:[./+#'-][A-Za-z0-9]+)*"
              % "|".join(sorted(_TAIL_STOPWORDS, key=len, reverse=True)))
_TAIL = rf"(?:{_SP}+(?:(?i:per){_SP}+)?{_TAIL_WORD}){{1,3}}"
_TAIL_OPT = rf"(?:{_TAIL})?"

# Rank = job-search value. Selection and display order follow it, so when a source
# offers more than MAX_KEY_NUMBERS metrics the headline ones survive the cut.
_HEADLINE, _SCOPE, _QUANTITY, _BARE = 0, 1, 2, 3

# (rank, pattern, year_guard) — year_guard drops a core that is a bare 4-digit year
# ("2019 to 2022" is a date range, not a metric).
_NUM_PATTERNS: list[tuple[int, re.Pattern[str], bool]] = [
    # 40%, 99.95%
    (_HEADLINE, re.compile(_START + r"\d+(?:,\d{3})*(?:\.\d+)?%"), False),
    # $1.2M, 3.5K users, 50M+ daily events — suffix attached to the digits.
    (_HEADLINE, re.compile(_START + _NUM + r"[KMBkmb]\+?(?![A-Za-z0-9])" + _TAIL_OPT),
     False),
    # "50 M requests" — a SPACED magnitude must be uppercase and carry a unit noun,
    # so "tier 3 B, C" is not read as 3 billion.
    (_HEADLINE, re.compile(_START + _NUM + _SP + r"[KMB]\+?(?![A-Za-z0-9])" + _TAIL),
     False),
    # 1,200 to 430 pages / 120 – 45 seconds
    (_HEADLINE, re.compile(_START + _NUM + rf"(?:{_SP}+(?i:to){_SP}+|{_SP}*[–—→]{_SP}*)"
                           + _NUM + _TAIL_OPT), True),
    # 8+ years
    (_SCOPE, re.compile(_START + r"\d+(?:,\d{3})*\+?" + _SP + r"+(?i:years?)"), False),
    # 99th percentile
    (_SCOPE, re.compile(_START + r"\d+(?i:st|nd|rd|th)" + _SP + r"+(?i:percentile)"),
     False),
    # under two seconds
    (_SCOPE, re.compile(r"\b(?i:under)" + _SP + r"+\w+" + _SP + r"+(?i:seconds?)"), False),
    # 18 Kubernetes clusters / 54 minutes / 120 services / 14 APIs — a plain count
    # is kept only WITH its unit, so a bare, meaningless "18" is never emitted.
    (_QUANTITY, re.compile(_START + _NUM + r"\+?" + _TAIL), True),
    # 30+ — last resort when the number carries no unit at all.
    (_BARE, re.compile(_START + r"\d+(?:,\d{3})*\+"), False),
]

_BARE_YEAR_RE = re.compile(r"(?:19|20)\d{2}(?![\d,.])")

# A trailing adverb describes the verb, not the unit ("50M+ daily events reliably").
# Frequency words are exempt — "daily"/"monthly" ARE part of what is counted.
_ADVERB_TAIL_RE = re.compile(
    r"(?:[ \t]+(?!(?:daily|weekly|biweekly|monthly|quarterly|yearly|annually|hourly"
    r"|nightly)\b)[A-Za-z]+ly)+$", re.I)


def _is_bare_year(text: str) -> bool:
    """True when the metric's leading number is a plain 4-digit calendar year."""
    if text.startswith("$"):
        return False
    return bool(_BARE_YEAR_RE.match(text))


def _trim_adverb_tail(text: str) -> str:
    """Drop a trailing adverb, but never trim a metric down to a bare number."""
    trimmed = _ADVERB_TAIL_RE.sub("", text)
    return trimmed if re.search(r"[A-Za-z%]", trimmed) else text


def _key_numbers(text: str) -> list[str]:
    """Distinct metrics, highest job-search value first.

    Every emitted metric keeps the unit or noun that gives it meaning — a number
    is never separated from what it counts, and a unit is never inferred from a
    neighbouring word (see the pattern notes above).
    """
    text = text.replace("**", "")   # bold markup must not split a number from its unit
    spans: list[tuple[int, int, int, str]] = []
    for rank, pat, year_guard in _NUM_PATTERNS:
        for m in pat.finditer(text):
            txt = _trim_adverb_tail(m.group().strip())
            if year_guard and _is_bare_year(txt):
                continue
            spans.append((m.start(), m.end(), rank, txt))
    # Highest-ranked reading of a position first ("8+ years" beats the plain-count
    # reading "8+ years building scalable"), then the longest.
    spans.sort(key=lambda s: (s[0], s[2], -(s[1] - s[0])))
    kept: list[tuple[int, int, int, str]] = []
    for start, end, rank, txt in spans:
        # Overlapping spans are competing readings of the same number; the first
        # (highest-ranked, longest) wins and the rest are dropped.
        if any(start < ke and ks < end for ks, ke, _, _ in kept):
            continue
        kept.append((start, end, rank, txt))
    seen: set[str] = set()
    out: list[str] = []
    for _, _, _, txt in sorted(kept, key=lambda s: (s[2], s[0])):
        key = txt.lower()
        if key not in seen:
            seen.add(key)
            out.append(txt)
    return out[:MAX_KEY_NUMBERS]


def _numbers_text(baseline: dict, profile_md: str) -> str:
    parts = list(baseline.get("summary_bullets") or [])
    try:
        employers = normalize_resume(baseline)["employers"]
    except ResumeSchemaError:
        employers = []
    for employer in employers:
        parts.extend(employer.get("bullets") or [])
        for proj in employer.get("projects") or []:
            parts.extend(proj.get("bullets") or [])
    parts.extend(_section(profile_md, "## Career Summary"))
    return "\n".join(parts)


# ── story-bank digest ────────────────────────────────────────
def _story_title_summary(path: Path) -> tuple[str, str]:
    title: str | None = None
    summary: str | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            if title is None:
                title = s.lstrip("#").strip()
            continue
        if summary is None:
            summary = re.sub(r"[*_`>]", "", s).strip()
        if title is not None and summary is not None:
            break
    if not title:
        title = path.stem.replace("-", " ").replace("_", " ").strip().title()
    if not summary:
        summary = "(no summary line)"
    if len(summary) > 140:
        summary = summary[:137].rstrip() + "…"
    return title, summary


def _story_digest(story_dir: Path, config_dir: Path) -> list[str]:
    files = _story_files(story_dir)
    if not files:
        return [f"No story bank found at `{STORY_BANK_REL}/` (the public example "
                "fixture ships none). Pull real, traceable detail from the full "
                "profile instead."]
    out = []
    for f in files:
        title, summary = _story_title_summary(f)
        rel = _display_path(f, config_dir)
        out.append(f"- **{title}** — {summary} Read the full story "
                   f"(`{rel}`) when the JD emphasizes {title.lower()}.")
    return out


# ── source manifest (header + staleness) ─────────────────────
def compute_sources(profile_path: Path, baseline_path: Path, story_dir: Path,
                    config_dir: Path) -> list[tuple[str, str, str]]:
    """Ordered ``(display_path, sha256, annotation)`` triples for the card's sources."""
    n = len(_story_files(story_dir))
    return [
        (_display_path(profile_path, config_dir), _file_sha(profile_path), ""),
        (_display_path(baseline_path, config_dir), _file_sha(baseline_path), ""),
        (STORY_BANK_REL + "/", _story_bank_hash(story_dir),
         f"({n} stor{'y' if n == 1 else 'ies'})"),
    ]


def parse_header_sources(card_text: str) -> dict[str, str]:
    """Map ``display_path -> sha256`` recorded in an existing card's header."""
    return {m.group(1): m.group(2) for m in SOURCE_LINE_RE.finditer(card_text)}


def changed_sources(current: list[tuple[str, str, str]], recorded: dict[str, str]) -> list[str]:
    """Display paths whose current hash differs from (or is absent in) the header."""
    cur = {disp: sha for disp, sha, _ in current}
    changed = [d for d, sha in cur.items() if recorded.get(d) != sha]
    changed += [d for d in recorded if d not in cur]
    return sorted(set(changed))


# ── card assembly ────────────────────────────────────────────
def build_card(profile_path: Path, baseline_path: Path, story_dir: Path,
               config_dir: Path, now: dt.datetime) -> str:
    profile_md = (profile_path.read_text(encoding="utf-8", errors="replace")
                  if profile_path.is_file() else "")
    baseline: dict = {}
    if baseline_path.is_file():
        try:
            baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) or {}
            baseline = normalize_resume(baseline)
        except (yaml.YAMLError, ResumeSchemaError):
            baseline = {}

    name = (baseline.get("name") or config.candidate_name() or "Candidate").strip()
    contact = (baseline.get("contact_line") or config.contact_line() or "").strip()
    education = (baseline.get("education_line") or "").strip()
    employers = baseline.get("employers") or []
    projects = [
        p.get("title", "").strip()
        for employer in employers
        for p in (employer.get("projects") or [])
        if p.get("title")
    ]
    skills = _parse_skills(profile_md)
    key_nums = _key_numbers(_numbers_text(baseline, profile_md))
    target_role = config.title_slug().replace("_", " ").strip()
    role_desc = " ".join(x.strip() for x in _section(profile_md, "## Role Description")).strip()
    summary_bullets = baseline.get("summary_bullets") or []
    sources = compute_sources(profile_path, baseline_path, story_dir, config_dir)

    L: list[str] = []
    L.append(f"# Tailoring Card — {name}")
    L.append("")
    L.append(f"_Generated {now.strftime('%Y-%m-%dT%H:%M:%SZ')} (UTC). Derived digest — "
             f"rebuild with `{BUILD_CMD}`._")
    L.append("")
    L.append("**Sources** (config-relative path, SHA-256):")
    L.append("")
    for disp, sha, note in sources:
        L.append(f"- `{disp}` sha256:{sha}" + (f" {note}" if note else ""))
    L.append("")

    L.append("## Identity & locked fields (never change these on the resume)")
    L.append("")
    L.append(f"- Name: {name}")
    if contact:
        L.append(f"- Contact: {contact}")
    if education:
        L.append(f"- Education: {education}")
    if employers:
        L.append("- Employers / roles / dates (count and order are locked):")
        for employer in employers:
            L.append(f"  - {employer.get('company', '')} — "
                     f"{employer.get('role', '')}, {employer.get('dates', '')} "
                     f"({employer.get('location', '')})")
    if projects:
        L.append("- Locked project titles (must match a profile `[draft]`/`[backup]` "
                 "title exactly):")
        L.extend(f"  - {t}" for t in projects)
    L.append("")

    L.append("## Target roles & framing")
    L.append("")
    if target_role:
        L.append(f"- Target title: {target_role}")
    if role_desc:
        L.append(f"- Role focus: {role_desc}")
    if summary_bullets:
        L.append("- Summary framing:")
        L.extend(f"  - {b}" for b in summary_bullets)
    L.append("")

    if key_nums:
        L.append("## Key numbers")
        L.append("")
        L.append(", ".join(key_nums))
        L.append("")

    # An empty list because the section was NOT FOUND is a different fact from an
    # empty list the profile actually declares — and on the Never BLOCKLIST the
    # difference matters, so the card never renders the two the same way.
    empty = ("- (NOT FOUND — this profile has no `## Skills` section, so this card "
             "carries NO vocabulary; treat it as unread, not as permissive)"
             if skills_section(profile_md) is None else "- (none listed)")
    L.append("## Skills gate")
    L.append("")
    L.append("**Approved** (use freely):")
    L.extend(skills["Approved"] or [empty])
    L.append("")
    L.append("**Weak** (include ONLY when a JD explicitly names the term):")
    L.extend(skills["Weak"] or [empty])
    L.append("")
    L.append("**Never** — BLOCKLIST. These must NEVER appear anywhere on the resume "
             "(verbatim and complete; a blocklist is never summarized):")
    L.extend(skills["Never"] or [empty])
    L.append("")

    L.append("## Story-bank digest")
    L.append("")
    L.extend(_story_digest(story_dir, config_dir))
    L.append("")

    L.append("---")
    L.append("")
    L.append(f"_This card is a derived digest for fast first-pass context. The full "
             f"profile (`{sources[0][0]}`) and the story bank remain the source of "
             f"truth — on any conflict, open and follow them, not this card._")
    L.append("")
    return "\n".join(L)


# ── CLI ──────────────────────────────────────────────────────
def _resolve_paths() -> tuple[Path, Path, Path, Path, Path]:
    config_dir = config.config_path().parent
    # Every product path comes from the config layer: the story bank lives under the
    # OVERLAY root (private/interviews/... — not the config file's directory, which in
    # the real deployment is the repo root), and the card lives in the candidate dir.
    # The gardener's card_staleness routine reads the same two accessors, which is what
    # keeps the recorded hashes describing the same files this script hashed. config_dir
    # is kept only for absolute-free, config-relative display of profile/baseline/card.
    return (
        config.profile_md_path(),
        config.baseline_path(),
        config.story_bank_path(),
        config_dir,
        config.tailoring_card_path(),
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report-only: recompute source hashes vs an existing card's "
                         "header; exit non-zero listing changed sources")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even when the sources have not changed (override the "
                         "no-op protection)")
    args = ap.parse_args(argv)

    profile_path, baseline_path, story_dir, config_dir, card_path = _resolve_paths()
    current = compute_sources(profile_path, baseline_path, story_dir, config_dir)
    card_disp = _display_path(card_path, config_dir)

    if args.check:
        if not card_path.is_file():
            print(f"stale: no card at {card_disp} — run the builder to create it")
            return 1
        changed = changed_sources(current, parse_header_sources(card_path.read_text()))
        if changed:
            print("stale: sources changed since the card was built:")
            for d in changed:
                print(f"  {d}")
            return 1
        print(f"current: {card_disp} matches its sources")
        return 0

    # Build mode — no-op protection unless --force or the sources actually changed.
    if card_path.is_file() and not args.force:
        changed = changed_sources(current, parse_header_sources(card_path.read_text()))
        if not changed:
            print(f"{card_disp} is already current (sources unchanged); pass --force "
                  "to rebuild.", file=sys.stderr)
            return 1

    now = dt.datetime.now(dt.timezone.utc)
    text = build_card(profile_path, baseline_path, story_dir, config_dir, now)
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(text, encoding="utf-8")

    n_bytes = len(text.encode("utf-8"))
    est_tokens = n_bytes // BYTES_PER_TOKEN
    print(f"{card_disp}  {n_bytes} bytes  ~{est_tokens} tokens")
    if n_bytes > CEILING_BYTES:
        print(f"WARN: card is {n_bytes} bytes (> {CEILING_BYTES} ceiling, "
              f"~{CEILING_BYTES // BYTES_PER_TOKEN} tokens) — tighten the digest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
