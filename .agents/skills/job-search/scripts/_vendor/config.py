"""Load the job-hunt configuration (candidate identity, paths, policies).

The toolkit keeps all candidate-specific values OUT of the code and in a
git-ignored ``config.yaml`` at the repo root. This module discovers, loads, and
caches that config and exposes typed accessors so the rest of the toolkit never
hardcodes a name, contact line, filename stem, or profile path.

Discovery order (first match wins):
    1. ``$JOBHUNT_CONFIG``   — explicit path from the environment (if it exists)
    2. nearest ``config.yaml`` walking UP from ``Path.cwd()``, then UP from this
       file's directory
    3. ``<repo_root>/config.example.yaml`` — the tracked, neutral placeholder

Paths in the config are interpreted RELATIVE TO THE CONFIG FILE'S directory and
resolved to absolute ``Path`` objects.

Config schema::

    candidate:
      name: "Full Name"
      contact_line: "City, ST • email • linkedin"
      name_slug: "First_Last"          # filename-safe person part
      title_slug: "Software_Engineer"  # filename-safe role part
    paths:
      profile_md: "relative/path.md"
      baseline_yaml: "relative/path.yaml"
      reference_docx: "relative/path.docx"
      company_levels_yaml: "relative/path.yaml"
      applications_root: "applications"
      discoveries_dir: "applications/1_discoveries"
    job_search:
      default_profile: "default"
    location_policy:
      metro: [City, ...]          # preferred-metro tokens (candidate-specific)
      remote_tokens: [...]        # OPTIONAL; if omitted use location.py defaults
      us_remote_regions: [...]    # OPTIONAL; if omitted use location.py defaults
      allow_us_remote: true
      us_only: true

The filename stems are composed from ``name_slug`` / ``title_slug`` via
``layout.compose_stem`` so they carry an optional target-position label suffix.
"""

import os
import sys
from functools import lru_cache
from pathlib import Path

import yaml

# config.py lives in scripts/shared/, alongside layout.py. Make sure this folder
# is importable so ``import layout`` resolves even when config is imported from a
# context that didn't inject the shared/ bucket onto sys.path.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import layout  # noqa: E402  (import after sys.path bootstrap, by design)

# config.py lives in scripts/shared/, so the repo root is three parents up.
REPO_ROOT = _HERE.parent.parent

CONFIG_FILENAME = "config.yaml"
EXAMPLE_CONFIG = REPO_ROOT / "config.example.yaml"
ENV_VAR = "JOBHUNT_CONFIG"


def _find_config_path() -> Path:
    """Locate the active config file per the documented discovery order."""
    # 1. Explicit path from the environment.
    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p
    # 2. Nearest config.yaml walking up from cwd, then from this file's directory.
    for start in (Path.cwd(), _HERE):
        for parent in (start, *start.parents):
            candidate = parent / CONFIG_FILENAME
            if candidate.exists():
                return candidate
    # 3. Fallback to the tracked example config.
    return EXAMPLE_CONFIG


@lru_cache(maxsize=1)
def _load() -> tuple[Path, dict]:
    """Return (config_path, config_dict), cached for the process lifetime."""
    path = _find_config_path()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    return path, data


def config_path() -> Path:
    """Absolute path of the config file that was loaded."""
    return _load()[0]


def _config() -> dict:
    return _load()[1]


def _config_dir() -> Path:
    return _load()[0].parent


# ── candidate identity ───────────────────────────────────────
def _candidate() -> dict:
    return _config().get("candidate") or {}


def candidate_name() -> str:
    return str(_candidate().get("name", ""))


def contact_line() -> str:
    return str(_candidate().get("contact_line", ""))


def name_slug() -> str:
    return str(_candidate().get("name_slug", ""))


def title_slug() -> str:
    return str(_candidate().get("title_slug", ""))


# ── output filename stems (composed from the identity slugs) ──
def resume_stem(label: str = "") -> str:
    """Rendered-resume output stem, with an optional target-position suffix."""
    return layout.compose_stem(f"{name_slug()}_{title_slug()}_Resume", label)


def cover_stem(label: str = "") -> str:
    """Cover-letter output stem, with an optional target-position suffix."""
    return layout.compose_stem(f"{name_slug()}_Cover_Letter", label)


def application_stem(label: str = "") -> str:
    """Bundled application .txt stem, with an optional target-position suffix."""
    return layout.compose_stem(f"{name_slug()}_{title_slug()}_Application", label)


# ── paths (resolved relative to the config file's directory) ──
def _paths() -> dict:
    return _config().get("paths") or {}


def _resolve(value: str | None, default: str) -> Path:
    """Resolve a config-relative path (or default) to an absolute Path."""
    p = Path(value or default)
    if p.is_absolute():
        return p
    return (_config_dir() / p).resolve()


def profile_md_path() -> Path:
    return _resolve(_paths().get("profile_md"),
                    "examples/profile/profile.example.md")


def baseline_path() -> Path:
    return _resolve(_paths().get("baseline_yaml"),
                    "applications/0_profile/baseline.yaml")


def reference_docx_path() -> Path:
    return _resolve(_paths().get("reference_docx"),
                    "examples/templates/reference.example.docx")


def company_levels_path() -> Path:
    """Reusable company-level/compensation cache.

    Real job hunts keep this beside the candidate profile by default so dated
    compensation research remains private. The tracked example config points to
    a fictional example cache explicitly.
    """
    configured = _paths().get("company_levels_yaml")
    if configured:
        return _resolve(configured, "examples/profile/company-levels.example.yaml")
    return profile_md_path().parent / "company-levels.yaml"


def applications_root() -> Path:
    return _resolve(_paths().get("applications_root"), "applications")


def discoveries_dir() -> Path:
    return _resolve(_paths().get("discoveries_dir"), "applications/1_discoveries")


# ── job-search + location policy ─────────────────────────────
def default_profile() -> str:
    js = _config().get("job_search") or {}
    return str(js.get("default_profile", "default"))


def location_policy() -> dict:
    """The location-matching policy for location.py's classifiers.

    Returns a dict with ``metro`` / ``remote_tokens`` / ``us_remote_regions`` lists
    (``None`` when the config omits an optional key so location.py falls back to its
    module defaults) plus the ``allow_us_remote`` / ``us_only`` booleans (defaulting
    to True).
    """
    lp = _config().get("location_policy") or {}

    def _list(key):
        val = lp.get(key)
        return list(val) if val else None

    return {
        "metro": _list("metro"),
        "remote_tokens": _list("remote_tokens"),
        "us_remote_regions": _list("us_remote_regions"),
        "allow_us_remote": lp.get("allow_us_remote", True),
        "us_only": lp.get("us_only", True),
    }
