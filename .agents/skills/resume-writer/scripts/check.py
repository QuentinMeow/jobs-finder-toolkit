"""Validate a tailored resume against the baseline, the profile, and format rules.

Guards every automated rewrite so the output stays a faithful, one-page,
correctly-formatted variant of the approved baseline resume:

- Identity fields (name, contact, education, employer/role/dates) are locked
  to config.paths.baseline_yaml — a tailored resume may never change them.
- Project titles must be real projects from the candidate profile
  (config.paths.profile_md) ([draft] or [backup]) — no invented or renamed projects.
- Skill items must be in the profile's Approved list, or in the Weak list (presented
  to users as Weak or Selective) with an explicit mention in the application's job
  description(s); 'Never' list items may not appear anywhere on the resume. Unknown
  skills fail with a prompt to categorize them. Job-description text is read from
  every JD-<job-title>.md file under the application's source/ subfolder
  (concatenated for validation).
- Structure: summary count follows the approved baseline; each employer has
  direct role bullets and/or named projects; project-focused resumes may remove
  only one project as a last resort for page fit.
- Bullet/title lengths bounded so nothing wraps past 2 lines.
- Rendered PDF must be exactly one page with extractable text AND fill the page —
  a large blank band at the bottom fails, so the resume never looks unfinished.
- Cover letters map one-to-one to JDs: one bundled ..._Application_<role>.txt per
  role in meta.yaml (a `jobs:` list or the single top-level `role`). Each COVER LETTER
  section must read as professional prose: a salutation and sign-off, at least two
  developed main paragraphs (60-180 words each), and a 200-450-word body — telegraphic/
  fragment or too-short letters fail.

Usage (accepts the app folder, or the source/tailored.yaml path):
    python .agents/skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/
    python .agents/skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/source/tailored.yaml
    python .agents/skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/source/tailored.yaml --pdf "applications/6_drafted/<slug>/<RESUME_STEM>.pdf"

Exit code 0 = all checks pass, 1 = at least one failure.
render.py runs these checks automatically after rendering.
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

# Self-contained skill: this script lives in the resume-writer skill's scripts/
# folder alongside its _vendor/ copies of the pure toolkit modules. Put both the
# script folder and its _vendor/ on sys.path so `import config` / `from layout
# import ...` / `import location` resolve to the vendored copies and sibling
# scripts (e.g. cover_letter) import directly.
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

# Pure application-folder layout helpers (no candidate identity) live in
# layout.py; the candidate-identity-derived values (baseline/profile paths and
# filename stems) live in config.py, backed by the git-ignored config.yaml.
# Re-export both here so existing `from check import <name>` importers keep
# working unchanged (render.py, cover_letter.py, status.py).
import config
from config import application_stem, cover_stem, resume_stem  # noqa: F401  (re-exported)
from job_metadata import validate_meta
from layout import (SOURCE_DIRNAME, _stem, application_dir,  # noqa: F401  (re-exported)
                    application_roles, compose_stem, find_jd_files, meta_path,
                    slugify_label, source_dir, tailored_path)
from resume_schema import ResumeSchemaError, normalize_resume

# Baseline + profile locations now come from config (config.yaml holds the real
# values, so runtime behavior is unchanged).
DEFAULT_BASELINE = config.baseline_path()
DEFAULT_PROFILE = config.profile_md_path()

# Output filename stems shared across scripts, now derived from config but kept
# under their historical module-level names for backward compatibility:
# RESUME_STEM: rendered resume DOCX + PDF (imported by render.py and status.py).
# COVER_STEM: the cover-letter DOCX/PDF the resume-writer generates.
# APPLICATION_STEM: the single bundled plain-text file (cover letter + why this
#   company/role + past-experience answers) kept at the application-folder root
#   for copy-paste into portals.
RESUME_STEM = config.resume_stem()
COVER_STEM = config.cover_stem()
APPLICATION_STEM = config.application_stem()

# ── Format rules (tune here) ──────────────────────────────
SUMMARY_BULLET_COUNT = 3
PROJECT_COUNT_RANGE = (4, 6)          # compatibility fallback without a baseline
DIRECT_BULLETS_RANGE = (1, 6)
BULLETS_PER_PROJECT = (1, 4)
BULLET_CHAR_RANGE = (45, 215)         # ~2 rendered lines max at current font
TITLE_MAX_CHARS = 95                  # must stay on one line
REWORDED_WARN_RATIO = 0.6             # warn if >60% of bullets differ from baseline

# ── Bottom-of-page fill (tune here) ───────────────────────
# A one-page resume should FILL the page — a big blank band at the bottom looks
# unfinished. Measured as inches of whitespace from the page's bottom edge up to
# the lowest text baseline (the top margin is ~0.6in, so these thresholds still
# leave a healthy bottom margin). Fix a too-blank resume by lengthening bullets
# with real, traceable detail (aim for ~2 rendered lines each) and by KEEPING
# every project — never drop a project just to tailor. Drop a project only when
# the content genuinely overflows one page.
RESUME_BOTTOM_BLANK_WARN_IN = 1.1     # warn: a little sparse at the bottom
RESUME_BOTTOM_BLANK_FAIL_IN = 1.5     # fail: clearly too blank at the bottom

# ── Cover-letter rules (enforced on the bundled Application .txt) ──────────
# The cover letter must read as professional, full-sentence prose — never
# telegraphic keyword fragments. It needs at least COVER_MAIN_MIN_COUNT
# well-developed "main" paragraphs (the mandated two: interest + company/product
# understanding, and a unique personal strength), each within
# COVER_MAIN_WORD_RANGE words, and a total body length within
# COVER_TOTAL_WORD_RANGE. Short salutation/closing lines don't count as main
# paragraphs. See .agents/skills/resume-writer/SKILL.md ("COVER LETTER section").
COVER_MAIN_WORD_RANGE = (60, 180)     # per main paragraph (target ~80-140)
COVER_MAIN_MIN_COUNT = 2              # at least two developed main paragraphs
COVER_TOTAL_WORD_RANGE = (200, 450)   # whole letter body (target ~250-400)
COVER_PLACEHOLDER_RE = re.compile(
    r"to be written|\bTODO\b|\bTBD\b|<[^>]{2,30}>|\byour company\b", re.I)
COVER_LOGISTICS_RE = re.compile(
    r"\bH-1B\b|\bH1B\b|visa sponsorship|need\b[^.]*\bsponsorship", re.I)

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _norm(text: str) -> str:
    """Normalize for comparison: strip bold markers, unify dashes/quotes/spaces, lowercase."""
    t = BOLD_RE.sub(r"\1", text or "")
    t = t.replace("–", "-").replace("—", "-").replace("‑", "-")
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip().lower()


def _plain(text: str) -> str:
    """Strip bold markers only (for length counting)."""
    return BOLD_RE.sub(r"\1", text or "")


def _employers(data: dict) -> list:
    try:
        return normalize_resume(data)["employers"]
    except ResumeSchemaError:
        return []


def parse_profile_titles(profile_text: str) -> set:
    """Project titles declared as '#### [draft|backup] Title' in the profile."""
    return {
        _norm(m.group(2))
        for m in re.finditer(r"^####\s*\[(draft|backup)\]\s*(.+)$", profile_text, re.M)
    }


def parse_profile_project_owners(profile_text: str) -> dict[tuple[str, str], set[str]]:
    """Project titles grouped by the profile employer/role that owns them.

    Profiles with only a flat/global project list continue to use
    ``parse_profile_titles``.  Multi-employer profiles gain the stronger guard
    that an otherwise-valid project cannot silently move to another job.
    """
    owners: dict[tuple[str, str], set[str]] = {}
    current: tuple[str, str] | None = None
    for line in profile_text.splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()
            # Remove the trailing dates/location block as a whole; locations
            # such as ``Remote (US)`` contain nested parentheses.
            identity = re.sub(r"\s+\(.*\)\s*$", "", heading)
            match = re.match(r"(.+?)\s+[—–-]\s+(.+?)$", identity)
            if match:
                current = (_norm(match.group(1)), _norm(match.group(2)))
                owners.setdefault(current, set())
            else:
                current = None
            continue
        match = re.match(r"^####\s*\[(draft|backup)\]\s*(.+)$", line)
        if current and match:
            owners[current].add(_norm(match.group(2)))
    return owners


def _split_items(line: str) -> list:
    """Split a comma-separated skill line, keeping parenthesized groups intact."""
    return [t.strip() for t in re.split(r",\s*(?![^()]*\))", line) if t.strip()]


def parse_skill_lists(profile_text: str) -> tuple:
    """Parse (approved, weak, never) skill token lists from the '## Skills' section.

    The section has '### Approved', '### Weak', '### Never' subsections whose
    bullet lines look like '- Label: item, item, item (a, b), item'.
    """
    m = re.search(r"^## Skills\s*$(.*?)(?=^## )", profile_text, re.M | re.S)
    section = m.group(1) if m else ""

    def sub_tokens(header):
        mm = re.search(rf"^### {header}\b[^\n]*\n(.*?)(?=^### |\Z)",
                       section, re.M | re.S)
        if not mm:
            return []
        tokens = []
        for line in mm.group(1).splitlines():
            line = line.strip().lstrip("-").strip()
            if not line or line.startswith("("):  # placeholder/comment lines
                continue
            if ":" in line:
                line = line.split(":", 1)[1]
            tokens.extend(_split_items(line))
        return tokens

    return sub_tokens("Approved"), sub_tokens("Weak"), sub_tokens("Never")


class Checker:
    def __init__(self):
        self.failures = []
        self.warnings = []

    def fail(self, msg):
        self.failures.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def check_application_metadata(c: Checker, app_dir: Path):
    """Require structured job facts for each posting represented by meta.yaml."""
    path = meta_path(app_dir)
    if not path.exists():
        c.fail(f"meta.yaml not found: {path}")
        return
    try:
        meta = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        c.fail(f"Could not read meta.yaml: {exc}")
        return
    if not isinstance(meta, dict):
        c.fail("meta.yaml must contain a YAML mapping")
        return
    for error in validate_meta(meta, app_dir=app_dir):
        c.fail(f"meta.yaml: {error}")


def check_role_filename_collisions(c: Checker, app_dir: Path):
    """Fail before two role labels normalize to the same output filename."""
    seen: dict[str, str] = {}
    for role in application_roles(app_dir):
        slug = slugify_label(role)
        if slug in seen:
            c.fail(
                f"Role filename collision: {seen[slug]!r} and {role!r} both "
                f"normalize to {slug!r}")
        else:
            seen[slug] = role


def check_locked_fields(c: Checker, data: dict, baseline: dict):
    for field in ("name", "contact_line", "education_line"):
        if _norm(data.get(field, "")) != _norm(baseline.get(field, "")):
            c.fail(f"Locked field '{field}' differs from baseline: "
                   f"{data.get(field)!r} != {baseline.get(field)!r}")

    emps, base_emps = _employers(data), _employers(baseline)
    if len(emps) != len(base_emps):
        c.fail(f"Employer count changed: {len(emps)} vs baseline {len(base_emps)}")
        return
    for emp, base in zip(emps, base_emps):
        for field in ("company", "role", "dates", "location"):
            if _norm(emp.get(field, "")) != _norm(base.get(field, "")):
                c.fail(f"Locked employer field '{field}' differs from baseline: "
                       f"{emp.get(field)!r} != {base.get(field)!r}")


def check_titles(c: Checker, data: dict, allowed_titles: set,
                 owners: dict[tuple[str, str], set[str]] | None = None):
    for emp in _employers(data):
        employer_key = (_norm(emp.get("company", "")), _norm(emp.get("role", "")))
        for proj in emp.get("projects", []):
            title = proj.get("title", "")
            if title and _norm(title) not in allowed_titles:
                c.fail(f"Project title not found in profile (no renaming/inventing): {title!r}")
            elif title and owners and employer_key in owners:
                if _norm(title) not in owners[employer_key]:
                    c.fail(
                        f"Project {title!r} does not belong to "
                        f"{emp.get('company', '')} — {emp.get('role', '')} in the profile")


_SKILL_ALIASES = {
    "golang": "go",
    "k8s": "kubernetes",
    "nodejs": "node.js",
    "postgres": "postgresql",
    "amazon web services": "aws",
}


def _skill_key(text: str) -> str:
    key = _norm(text).strip()
    key = re.sub(r"\s+", " ", key)
    return _SKILL_ALIASES.get(key, key)


def _skill_keys(text: str) -> set[str]:
    """Expand ``AWS (Lambda, SQS)`` without treating bare AWS as selective."""
    normalized = _norm(text).strip()
    match = re.fullmatch(r"(.+?)\s*\(([^()]*)\)", normalized)
    if not match:
        key = _skill_key(normalized)
        keys = {key} if key else set()
        if key.startswith(("aws ", "gcp ", "azure ")):
            keys.add(key.split(" ", 1)[1])
        return keys

    base = _skill_key(match.group(1))
    members = {
        _skill_key(member)
        for member in re.split(r"[,/]", match.group(2))
        if member.strip()
    }
    keys = set(members)
    keys.update(f"{base} {member}" for member in members)
    # A profile category such as AWS (Lambda, SQS) deliberately does not make
    # bare AWS selective; a resume token with parentheses likewise represents
    # the nested service, not just the parent platform.
    return keys


def _in_list(tok: str, skill_list: list[str] | str) -> bool:
    """Exact skill membership with a few deliberate aliases, never substrings."""
    if isinstance(skill_list, str):
        candidates = _split_items(skill_list)
    else:
        candidates = skill_list
    targets = _skill_keys(tok)
    allowed = {
        key
        for candidate in candidates
        for key in _skill_keys(candidate)
    }
    return bool(targets & allowed)


def _mentioned_in_jd(tok: str, jd_text: str) -> bool:
    """Return true only for a boundary-aware, non-negated JD mention."""
    jd_text = _norm(jd_text)
    variants = _skill_keys(tok)
    variants.update(
        alias
        for key in list(variants)
        for alias, canonical in _SKILL_ALIASES.items()
        if canonical == key
    )
    if "node.js" in variants:
        variants.update({"nodejs", "node js"})
    if "postgresql" in variants:
        variants.add("postgres")

    for variant in sorted(variants, key=len, reverse=True):
        pieces = [re.escape(piece) for piece in re.split(r"[\s.]+", variant) if piece]
        if not pieces:
            continue
        pattern = r"(?<![a-z0-9])" + r"[\s.]*".join(pieces) + r"(?![a-z0-9])"
        for match in re.finditer(pattern, jd_text):
            before = jd_text[max(0, match.start() - 45):match.start()]
            after = jd_text[match.end():match.end() + 45]
            negated_before = re.search(
                r"\b(?:no|not|without)\b[^.;:\n]{0,30}$", before)
            negated_after = re.match(
                r"\s*(?:is|are|experience\s+is)?\s*"
                r"(?:not|isn't|isn’t|aren't|aren’t)\s+"
                r"(?:required|needed|necessary)", after)
            if not negated_before and not negated_after:
                return True
    return False


def check_skills(c: Checker, data: dict, approved: list, weak: list, jd_text: str | None):
    skills = data.get("skills", [])
    if not skills:
        c.fail("No skills section in tailored.yaml")
        return
    for entry in skills:
        for tok in _split_items(entry.get("items", "")):
            if _in_list(tok, approved):
                continue
            if _in_list(tok, weak):
                # Weak/Selective skills are allowed only when the JD mentions them
                if jd_text is None:
                    c.warn(f"Weak/Selective skill {tok!r} used but no JD file (jd.md / JD-*.md) "
                           "found to verify JD mention")
                elif not _mentioned_in_jd(tok, jd_text):
                    c.fail(f"Weak/Selective skill {tok!r} used but the JD does not mention it "
                           "(Weak/Selective skills require an explicit JD mention)")
                continue
            c.fail(f"Skill {tok!r} is not in the profile's Approved or Weak lists — "
                   "collect the complete uncategorized-skill queue, then batch-ask the user "
                   "one question per skill: Never (never include in any resume), Weak or "
                   "Selective (only with an explicit JD mention), Approved (include in most "
                   "resumes, if not all), or Other (clarify before categorizing)")


def _all_resume_text(data: dict) -> str:
    """All human-visible resume text, normalized, for blocklist scanning."""
    parts = [data.get(k, "") for k in ("name", "contact_line", "education_line")]
    parts += data.get("summary_bullets", [])
    for entry in data.get("skills", []):
        parts.append(entry.get("items", ""))
    for emp in _employers(data):
        parts.extend(emp.get(field, "") for field in ("company", "role", "dates", "location"))
        parts.extend(emp.get("bullets", []))
        for proj in emp.get("projects", []):
            parts.append(proj.get("title", ""))
            parts.extend(proj.get("bullets", []))
    return _norm(" • ".join(parts))


def check_never_skills(c: Checker, data: dict, never: list):
    """The Never list may not appear anywhere on the resume — skills line or bullets."""
    text = _all_resume_text(data)
    for tok in never:
        bare = re.sub(r"\s*\(.*?\)", "", _norm(tok)).strip()
        if bare and re.search(rf"(?<![a-z0-9]){re.escape(bare)}(?![a-z0-9])", text):
            c.fail(f"Blocklisted skill {tok!r} (profile 'Never' list) appears in the resume")


def check_structure(c: Checker, data: dict, baseline: dict | None = None):
    n = len(data.get("summary_bullets", []))
    expected_summary = (
        len(baseline.get("summary_bullets", []))
        if baseline is not None else SUMMARY_BULLET_COUNT
    )
    if n != expected_summary:
        c.fail(f"Summary must have exactly {expected_summary} bullets to match "
               f"the approved baseline, found {n}")

    employers = _employers(data)
    if not employers:
        c.fail("Resume must contain at least one employer")
        return

    total_projects = 0
    for index, emp in enumerate(employers, start=1):
        direct = emp.get("bullets", [])
        projects = emp.get("projects", [])
        total_projects += len(projects)
        label = (f"employer {index} ({emp.get('company') or '?'})")
        if not direct and not projects:
            c.fail(f"{label} must have direct bullets and/or named projects")
        if direct:
            lo, hi = DIRECT_BULLETS_RANGE
            if not lo <= len(direct) <= hi:
                c.fail(f"{label} has {len(direct)} direct bullets (allowed {lo}-{hi})")
        blo, bhi = BULLETS_PER_PROJECT
        for proj in projects:
            nb = len(proj.get("bullets", []))
            if not blo <= nb <= bhi:
                c.fail(f"Project {proj.get('title', '?')!r} has {nb} bullets "
                       f"(allowed {blo}-{bhi})")

    if baseline is None:
        # Compatibility for direct unit callers that do not supply the approved
        # baseline. The real workflow always takes the baseline-aware path below.
        project_only = all(not emp.get("bullets") for emp in employers)
        if project_only:
            lo, hi = PROJECT_COUNT_RANGE
            if not lo <= total_projects <= hi:
                c.fail(f"Total project count {total_projects} outside allowed range {lo}-{hi}")
        return

    base_employers = _employers(baseline)
    if len(base_employers) == len(employers):
        for index, (base_emp, emp) in enumerate(
                zip(base_employers, employers), start=1):
            base_direct = base_emp.get("bullets", [])
            direct = emp.get("bullets", [])
            label = f"employer {index} ({emp.get('company') or '?'})"
            if base_direct and not direct:
                c.fail(
                    f"{label} dropped all direct role bullets from the approved baseline")
            if len(direct) > len(base_direct):
                c.fail(
                    f"{label} added direct role bullets: {len(direct)} vs "
                    f"baseline {len(base_direct)}")
    base_projects = sum(len(emp.get("projects", [])) for emp in base_employers)
    if base_projects:
        # A one-project reduction is the documented last resort for page fit.
        # Tailoring may swap a project but must not silently add more projects.
        minimum = max(0, base_projects - 1)
        if not minimum <= total_projects <= base_projects:
            c.fail(
                f"Total project count {total_projects} must stay within "
                f"{minimum}-{base_projects} from the approved baseline")


def check_lengths(c: Checker, data: dict):
    lo, hi = BULLET_CHAR_RANGE

    def _check_bullet(text, where):
        length = len(_plain(text))
        if length > hi:
            c.fail(f"{where}: bullet too long ({length} > {hi} chars): {text[:60]!r}...")
        elif length < lo:
            c.fail(f"{where}: bullet too short ({length} < {lo} chars): {text!r}")
        elif length > hi - 15:
            c.warn(f"{where}: bullet near length limit ({length}/{hi} chars)")

    for b in data.get("summary_bullets", []):
        _check_bullet(b, "summary")
    for emp in _employers(data):
        for b in emp.get("bullets", []):
            _check_bullet(b, f"employer {emp.get('company', '?')!r}")
        for proj in emp.get("projects", []):
            title = proj.get("title", "")
            if len(_plain(title)) > TITLE_MAX_CHARS:
                c.fail(f"Project title too long ({len(_plain(title))} > {TITLE_MAX_CHARS}): {title!r}")
            for b in proj.get("bullets", []):
                _check_bullet(b, f"project {title[:40]!r}")


def check_bold_markers(c: Checker, data: dict):
    """Reject unmatched ``**`` markers that would leak into the DOCX."""
    fields: list[tuple[str, str]] = []
    fields.extend(("summary", text) for text in data.get("summary_bullets", []))
    for emp in _employers(data):
        where = f"employer {emp.get('company', '?')!r}"
        fields.extend((where, text) for text in emp.get("bullets", []))
        for proj in emp.get("projects", []):
            fields.append((f"project title {proj.get('title', '')!r}", proj.get("title", "")))
            fields.extend(
                (f"project {proj.get('title', '?')!r}", text)
                for text in proj.get("bullets", []))
    for where, text in fields:
        if text.count("**") % 2:
            c.fail(f"{where}: unmatched '**' bold marker")


def check_drift(c: Checker, data: dict, baseline: dict):
    """Warn when too many bullets were reworded — 'slight changes' is the goal."""
    base_bullets = {_norm(b) for b in baseline.get("summary_bullets", [])}
    for emp in _employers(baseline):
        base_bullets.update(_norm(b) for b in emp.get("bullets", []))
        for proj in emp.get("projects", []):
            base_bullets.update(_norm(b) for b in proj.get("bullets", []))

    total, reworded = 0, 0
    for b in data.get("summary_bullets", []):
        total += 1
        reworded += _norm(b) not in base_bullets
    for emp in _employers(data):
        for b in emp.get("bullets", []):
            total += 1
            reworded += _norm(b) not in base_bullets
        for proj in emp.get("projects", []):
            for b in proj.get("bullets", []):
                total += 1
                reworded += _norm(b) not in base_bullets

    if total:
        ratio = reworded / total
        note = f"{reworded}/{total} bullets differ from baseline ({ratio:.0%})"
        if ratio > REWORDED_WARN_RATIO:
            c.warn(f"{note} — exceeds {REWORDED_WARN_RATIO:.0%}; tailoring should be lighter-touch")
        else:
            c.warn(note) if reworded else None


def check_cover_letter(c: Checker, app_dir: Path, label: str = ""):
    """Validate the bundled Application .txt's COVER LETTER section.

    Enforces professional, full-sentence prose over telegraphic fragments:
    a salutation and sign-off, at least COVER_MAIN_MIN_COUNT developed main
    paragraphs (each within COVER_MAIN_WORD_RANGE words), and a total body
    length within COVER_TOTAL_WORD_RANGE. A missing letter is only a warning so
    resume-only drafts still validate.
    """
    # Lazy import to avoid a circular import (cover_letter imports from check).
    try:
        from cover_letter import cover_letter_text, parse_cover_letter
    except ImportError:
        c.warn("cover_letter module unavailable — skipping cover-letter checks")
        return

    where = f" for {label!r}" if label else ""
    body = cover_letter_text(app_dir, label)
    if body is None:
        c.warn(f"no bundled {application_stem(label)}.txt (COVER LETTER section) found"
               f"{where} — every JD needs its own cover letter")
        return

    parsed = parse_cover_letter(body)
    if not parsed["salutation"]:
        c.fail(f"cover letter{where} has no salutation (expected 'Dear <Company> Hiring Team,')")
    if not parsed["closing"]:
        c.fail(f"cover letter{where} has no sign-off (expected 'Sincerely,' + name)")

    counts = [len(p.split()) for p in parsed["paragraphs"]]
    total = sum(counts)
    lo, hi = COVER_MAIN_WORD_RANGE
    mains = [w for w in counts if lo <= w <= hi]
    if len(mains) < COVER_MAIN_MIN_COUNT:
        c.fail(f"cover letter{where} needs ≥{COVER_MAIN_MIN_COUNT} developed main paragraphs "
               f"of {lo}-{hi} words (found {len(mains)}; paragraph word counts {counts}). "
               "Write full-sentence paragraphs — one expressing interest and understanding "
               "of the company/product, one showing a unique personal strength.")
    tlo, thi = COVER_TOTAL_WORD_RANGE
    if not (tlo <= total <= thi):
        c.fail(f"cover letter{where} body is {total} words — outside the {tlo}-{thi} range "
               "(target ~250-400). Expand thin paragraphs or trim padding.")
    if COVER_PLACEHOLDER_RE.search(body):
        c.fail(f"cover letter{where} contains placeholder text (e.g. 'to be written', TODO) — "
               "write the real content")
    if COVER_LOGISTICS_RE.search(body):
        c.warn(f"cover letter{where} mentions visa/sponsorship in the body — keep logistics out "
               "of the persuasive paragraphs (use the dedicated portal field instead)")


def _bottom_blank_inches(page) -> float | None:
    """Inches of whitespace from the page's bottom edge to the lowest text baseline.

    Uses pypdf's text visitor to collect the device-space y of every non-empty
    text run, composing the current transformation matrix (cm) with the text
    matrix (tm) so rotated/translated content is measured correctly. A large
    value means the resume ends high on the page (too much blank at the bottom).
    Returns None when no text can be located.
    """
    ys: list[float] = []

    def visitor(text, cm, tm, font_dict, font_size):
        if text and text.strip():
            ys.append(cm[1] * tm[4] + cm[3] * tm[5] + cm[5])

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return None
    if not ys:
        return None
    return min(ys) / 72.0


def check_pdf(c: Checker, pdf_path: Path, data: dict):
    try:
        from pypdf import PdfReader
    except ImportError:
        c.warn("pypdf not installed — skipping PDF checks (pip install pypdf)")
        return
    reader = PdfReader(str(pdf_path))
    if len(reader.pages) != 1:
        c.fail(f"PDF is {len(reader.pages)} pages — must be exactly 1. "
               "Shorten bullets first; only drop a project as a last resort.")
    text = "".join(page.extract_text() or "" for page in reader.pages)
    if len(text) < 500:
        c.fail("PDF has almost no extractable text — render is likely broken/garbled")
    name = _plain(data.get("name", ""))
    if name and name.split()[0].lower() not in text.lower():
        c.fail(f"Name {name!r} not found in PDF text — render is likely broken")
    rendered = _norm(text)
    for emp in _employers(data):
        for label, value in (
                ("company", emp.get("company", "")),
                ("role", emp.get("role", ""))):
            if value and _norm(value) not in rendered:
                c.fail(f"Employer {label} {value!r} not found in PDF text")
        for project in emp.get("projects", []):
            title = project.get("title", "")
            if title and _norm(title) not in rendered:
                c.fail(f"Project title {title!r} not found in PDF text")

    # Bottom-of-page fill: only meaningful on a single page.
    if len(reader.pages) == 1:
        gap = _bottom_blank_inches(reader.pages[0])
        if gap is not None:
            if gap > RESUME_BOTTOM_BLANK_FAIL_IN:
                c.fail(f"Resume looks too blank at the bottom (~{gap:.1f}in of trailing "
                       f"whitespace, limit {RESUME_BOTTOM_BLANK_FAIL_IN:.1f}in). Fill the page: "
                       "lengthen bullets with real, traceable detail (aim for ~2 rendered lines "
                       "each) and keep every project — never drop a project to fix blank space.")
            elif gap > RESUME_BOTTOM_BLANK_WARN_IN:
                c.warn(f"Resume is a little sparse at the bottom (~{gap:.1f}in trailing "
                       "whitespace); consider lengthening bullets so the page fills more fully "
                       "(keep all projects).")


def run_checks(yaml_path: Path, pdf_path: Path | None = None,
               baseline_path: Path = DEFAULT_BASELINE,
               profile_path: Path = DEFAULT_PROFILE) -> bool:
    """Run all checks. Prints results; returns True if everything passed."""
    c = Checker()
    try:
        with open(yaml_path) as f:
            raw_data = yaml.safe_load(f)
        data = normalize_resume(raw_data)
    except (OSError, yaml.YAMLError) as exc:
        c.fail(f"Could not read tailored resume YAML: {exc}")
        data = None
    except ResumeSchemaError as exc:
        for error in exc.errors:
            c.fail(f"tailored.yaml: {error}")
        data = None

    try:
        with open(baseline_path) as f:
            raw_baseline = yaml.safe_load(f)
        baseline = normalize_resume(raw_baseline)
    except (OSError, yaml.YAMLError) as exc:
        c.fail(f"Could not read baseline YAML: {exc}")
        baseline = None
    except ResumeSchemaError as exc:
        for error in exc.errors:
            c.fail(f"baseline: {error}")
        baseline = None

    try:
        profile_text = profile_path.read_text()
    except OSError as exc:
        c.fail(f"Could not read candidate profile: {exc}")
        profile_text = ""

    if data is None or baseline is None:
        for msg in c.failures:
            print(f"  FAIL: {msg}")
        print(f"  → {len(c.failures)} check(s) FAILED — fix tailored.yaml and re-render")
        return False

    jd_files = find_jd_files(application_dir(yaml_path))
    try:
        jd_text = _norm("\n\n".join(
            p.read_text(encoding="utf-8", errors="strict") for p in jd_files)
        ) if jd_files else None
    except (OSError, UnicodeError) as exc:
        c.fail(f"Could not read job description: {exc}")
        jd_text = None
    approved, weak, never = parse_skill_lists(profile_text)

    check_locked_fields(c, data, baseline)
    check_titles(
        c,
        data,
        parse_profile_titles(profile_text),
        parse_profile_project_owners(profile_text),
    )
    check_skills(c, data, approved, weak, jd_text)
    check_never_skills(c, data, never)
    check_structure(c, data, baseline)
    check_lengths(c, data)
    check_bold_markers(c, data)
    check_drift(c, data, baseline)
    app_dir = application_dir(yaml_path)
    check_application_metadata(c, app_dir)
    check_role_filename_collisions(c, app_dir)
    # One cover letter per JD/role (one-to-one). Validate every role's bundled
    # ..._Application_<role>.txt; fall back to the single unlabeled bundle when
    # meta.yaml carries no role info (legacy folders / resume-only drafts).
    roles = application_roles(app_dir) or [data.get("target_position", "")]
    for role in roles:
        check_cover_letter(c, app_dir, role)
    if pdf_path is not None and Path(pdf_path).exists():
        check_pdf(c, Path(pdf_path), data)
    elif pdf_path is not None:
        c.warn(f"PDF not found at {pdf_path} — skipping PDF checks")

    for w in c.warnings:
        print(f"  WARN: {w}")
    for msg in c.failures:
        print(f"  FAIL: {msg}")
    if c.failures:
        print(f"  → {len(c.failures)} check(s) FAILED — fix tailored.yaml and re-render")
        return False
    print(f"  ✓ all checks passed ({len(c.warnings)} warning(s))")
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate a tailored resume")
    parser.add_argument("yaml_path", help="Path to tailored.yaml")
    parser.add_argument("--pdf", default=None,
                        help=f"Path to rendered PDF (default: the sibling {RESUME_STEM}[_<position>].pdf if present)")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    args = parser.parse_args()

    yaml_path = Path(args.yaml_path)
    if yaml_path.is_dir():
        yaml_path = tailored_path(yaml_path)
    if args.pdf:
        pdf_path = Path(args.pdf)
    else:
        # Resolve the resume PDF at the application-folder root, honoring an
        # optional target-position suffix (tailored.yaml `target_position`) so
        # labeled renders validate too.
        label = ""
        try:
            with open(yaml_path) as f:
                label = (yaml.safe_load(f) or {}).get("target_position", "")
        except (OSError, yaml.YAMLError):
            pass
        pdf_path = application_dir(yaml_path) / f"{resume_stem(label)}.pdf"

    ok = run_checks(yaml_path, pdf_path,
                    Path(args.baseline), Path(args.profile))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
