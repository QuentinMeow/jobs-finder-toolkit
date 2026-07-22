"""Compile a distilled *tailoring card* from the candidate profile + baseline + story bank.

Drafting agents otherwise read the full profile/baseline (~17 KB) plus the whole
story bank (~24 KB) at full fidelity on every application, regardless of need. This
script distills the deterministic, always-needed context into one small card so the
drafting agent reads the card first and opens the full sources only when a pointer or
the JD demands a deep dive (see the resume-writer SKILL.md workflow).

Inputs (via the vendored config accessors — self-contained skill, no repo-root imports):
  * profile markdown  — ``config.profile_md_path()``
  * baseline yaml      — ``config.baseline_path()``
  * story bank         — ``interviews/behavioral-story-bank/`` under the OVERLAY ROOT,
                         derived as ``config.applications_root().parent`` — NOT the config
                         file's directory. In the real deployment ``config.yaml`` sits at the
                         repo root while the private overlay is mounted at ``private/``; the
                         applications root (``private/applications``) is what locates the
                         overlay, so its parent (``private/``) is the overlay root and the
                         story bank lives at ``private/interviews/behavioral-story-bank/``.
                         (An overlay-resident ``config.yaml`` resolves to the same place.)
                         With no ``config.yaml`` present the config falls back to the tracked
                         example config, whose applications root is ``examples/applications``
                         → the Jordan Rivers ``examples/`` fixture ships no story bank, and
                         the digest then says so gracefully.

Output: ``<applications_root>/0_profile/tailoring-card.md`` (applications root from
config). The card carries, in order: a generated-from header (config-relative source
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
from resume_schema import ResumeSchemaError, normalize_resume  # noqa: E402

CEILING_BYTES = 8192          # ~2k tokens target ceiling for the card
BYTES_PER_TOKEN = 4           # est. tokens = bytes / 4 (repo-wide convention)
STORY_BANK_REL = "interviews/behavioral-story-bank"
CARD_REL = "0_profile/tailoring-card.md"
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
    """Return raw bullet lines for the Approved / Weak / Never lists in ``## Skills``."""
    out: dict[str, list[str]] = {"Approved": [], "Weak": [], "Never": []}
    in_skills = False
    current: str | None = None
    for line in profile_md.splitlines():
        if line.startswith("## "):
            in_skills = line.strip().lower().startswith("## skills")
            current = None
            continue
        if not in_skills:
            continue
        if line.startswith("### "):
            head = line[4:].strip().lower()
            current = next((k for k in out if head.startswith(k.lower())), None)
            continue
        if current and line.lstrip().startswith("- "):
            out[current].append(line.rstrip())
    return out


_NUM_PATTERNS = [
    re.compile(r"\d[\d,]*(?:\.\d+)?\s?[MKB]\+?", re.I),      # 50M+, 1.5K
    re.compile(r"\d+(?:\.\d+)?%"),                            # 40%
    re.compile(r"\d+(?:st|nd|rd|th)\s+percentile", re.I),    # 99th percentile
    re.compile(r"\d+\+?\s+years?", re.I),                     # 8+ years
    re.compile(r"under\s+\w+\s+seconds?", re.I),             # under two seconds
    re.compile(r"\d+\+"),                                     # 30+, 8+
]


def _key_numbers(text: str) -> list[str]:
    """Distinct headline metrics found in the summary + experience bullets, in order."""
    spans: list[tuple[int, int, str]] = []
    for pat in _NUM_PATTERNS:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end(), m.group().strip()))
    # Longest-at-a-position first so "8+ years" wins over the nested "8+".
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int, str]] = []
    for start, end, txt in spans:
        if any(ks <= start and end <= ke for ks, ke, _ in kept):
            continue
        kept.append((start, end, txt))
    seen: set[str] = set()
    out: list[str] = []
    for _, _, txt in sorted(kept, key=lambda s: s[0]):
        key = txt.lower()
        if key not in seen:
            seen.add(key)
            out.append(txt)
    return out[:12]


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

    L.append("## Skills gate")
    L.append("")
    L.append("**Approved** (use freely):")
    L.extend(skills["Approved"] or ["- (none listed)"])
    L.append("")
    L.append("**Weak** (include ONLY when a JD explicitly names the term):")
    L.extend(skills["Weak"] or ["- (none listed)"])
    L.append("")
    L.append("**Never** — BLOCKLIST. These must NEVER appear anywhere on the resume "
             "(verbatim and complete; a blocklist is never summarized):")
    L.extend(skills["Never"] or ["- (none listed)"])
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
    # The story bank lives beside the applications tree in the private overlay, NOT
    # under the config file's directory: in the real deployment config.yaml sits at the
    # repo root while the overlay is mounted at private/. Derive the overlay root from
    # the applications root (private/applications → private/) so the bank resolves the
    # same whether config.yaml is at the repo root or inside the overlay. config_dir is
    # kept only for absolute-free, config-relative display of the profile/baseline/card.
    overlay_root = config.applications_root().parent
    return (
        config.profile_md_path(),
        config.baseline_path(),
        overlay_root / STORY_BANK_REL,
        config_dir,
        config.applications_root() / CARD_REL,
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
