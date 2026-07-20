"""Shared helpers for the gardener memory-hygiene routines.

The gardener is periodic memory hygiene for this repo's agent-memory zones
(see ``AGENTS.md`` -> "Memory Map"
§5). Every routine defaults to DRY-RUN, prints a plan/diff, and NEVER deletes —
stale items are MOVED to an ``archive/`` sibling (soft-delete). ``--apply`` is an
explicit opt-in.

Dependencies: Python stdlib + ``pyyaml`` (the toolkit's one YAML dependency,
already required by ``scripts/shared/config.py`` and every skill). This module is
repo-root maintenance tooling, so — per AGENTS.md "Sharing Code Across Skills" — it
imports the canonical ``scripts/shared/config.py`` directly to resolve overlay
paths and the retention policy. It never imports skill code.
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

# scripts/maintenance/gardener/_common.py -> repo root is three parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Import the canonical config loader (path/identity/retention source of truth).
_SHARED = REPO_ROOT / "scripts" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
import config  # noqa: E402  (import after sys.path bootstrap, by design)

DESIGN_DOC = (
    "private/docs/harness-engineering-and-repo-evolution/"
    "03-folder-structure-and-memory.md"
)

# Retention defaults (see AGENTS.md "Memory Map"). Overridable via the
# optional ``retention:`` block in the active config.yaml.
RETENTION_DEFAULTS = {
    "discovery_ttl_days": 30,
    "discovery_archive_days": 14,
    "search_log_prune_days": 90,
    "lesson_confirm_days": 180,
}

_DATE_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")


def today() -> _dt.date:
    return _dt.date.today()


def retention() -> dict:
    """Return the retention policy: config ``retention:`` block over the defaults.

    Config readers ignore unknown keys, so ``retention:`` is optional. We read the
    ACTIVE config file (``config.config_path()``) directly rather than adding an
    accessor to the shared loader.
    """
    values = dict(RETENTION_DEFAULTS)
    try:
        import yaml
        data = yaml.safe_load(config.config_path().read_text()) or {}
        block = data.get("retention") or {}
        for key in RETENTION_DEFAULTS:
            if isinstance(block.get(key), int):
                values[key] = block[key]
    except Exception:
        pass
    return values


def date_from_name(name: str) -> _dt.date | None:
    """Parse the first ``YYYYMMDD`` run in a filename to a date, or None.

    Matches a leading date prefix (``20260719-...``) and also a trailing/embedded
    one (``ai-target-companies-20260716.md``); the first valid match wins.
    """
    for m in _DATE_RE.finditer(name):
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    return None


def file_age_days(path: Path, ref: _dt.date | None = None) -> tuple[int, _dt.date, str]:
    """Return ``(age_days, effective_date, source)`` for a discovery file.

    ``source`` is ``"name"`` when the date came from the filename's ``YYYYMMDD``,
    else ``"mtime"``. Age is measured against ``ref`` (default: today).
    """
    ref = ref or today()
    d = date_from_name(path.name)
    source = "name"
    if d is None:
        d = _dt.date.fromtimestamp(path.stat().st_mtime)
        source = "mtime"
    return (ref - d).days, d, source


def rel(path: Path) -> str:
    """Repo-root-relative POSIX path when possible, else the absolute path."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def print_header(title: str, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"gardener · {title} [{mode}]")
    print(f"  policy: {DESIGN_DOC}")


# ── LESSONS.md lifecycle-tag parsing (shared by lessons_report + self_measure) ──
LESSON_TAG_RE = re.compile(
    r"<!--\s*added:\s*(?P<added>[0-9-]+)\s*·\s*"
    r"last_confirmed:\s*(?P<confirmed>[0-9-]+)\s*·\s*"
    r"status:\s*(?P<status>[A-Za-z_]+)\s*-->"
)


def lessons_files() -> list[Path]:
    skills = REPO_ROOT / ".agents" / "skills"
    return sorted(skills.glob("*/LESSONS.md"))


def parse_lessons(path: Path) -> list[dict]:
    """Return one record per ``##`` section: heading, tag dates/status, bullets.

    A "bullet" is any line beginning with ``- `` (leading whitespace allowed);
    continuation lines are folded into the preceding bullet.
    """
    sections: list[dict] = []
    cur: dict | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return sections
    for line in lines:
        if line.startswith("## "):
            cur = {
                "heading": line[3:].strip(),
                "added": None,
                "confirmed": None,
                "status": None,
                "bullets": [],
            }
            sections.append(cur)
            continue
        if cur is None:
            continue
        m = LESSON_TAG_RE.search(line)
        if m:
            cur["added"] = m.group("added")
            cur["confirmed"] = m.group("confirmed")
            cur["status"] = m.group("status")
            continue
        stripped = line.lstrip()
        if stripped.startswith("- "):
            cur["bullets"].append(stripped[2:].strip())
        elif stripped and cur["bullets"] and line[:1] in " \t":
            cur["bullets"][-1] += " " + stripped
    return sections


def parse_iso(value: str | None) -> _dt.date | None:
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "the a an and or of to in on for with is are be by it its as at from not "
    "this that these those into per via use used only when than then so if "
    "each every one two both no never always via vs etc e g i".split()
)


# Bullets shorter than this (in meaningful tokens) are too small to score reliably
# — a 2-token YAML example line trivially "matches" a long lesson, so we skip them.
MIN_DUP_TOKENS = 5


def tokenize(text: str) -> set[str]:
    """Normalized token set for the duplicate heuristic (lowercase, destopped)."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 2}


def overlap(a: set[str], b: set[str]) -> float:
    """Jaccard similarity |a∩b| / |a∪b|.

    Jaccard (not the overlap coefficient) is used deliberately: it penalizes length
    mismatch, so a genuine near-duplicate scores high while a short fragment that
    merely shares domain vocabulary with a long bullet does not. Returns 0 when
    either side is below ``MIN_DUP_TOKENS`` (too small to judge).
    """
    if len(a) < MIN_DUP_TOKENS or len(b) < MIN_DUP_TOKENS:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0
