"""Pure application-folder layout helpers (no candidate identity, no config).

This module holds the file/folder conventions shared across the toolkit that do
NOT depend on the candidate's identity or any configuration: the ``source/``
subfolder rule, path resolution for an application folder / its ``tailored.yaml``
/ ``meta.yaml``, the per-JD role list, and the filename-slug helpers.

It is intentionally PURE — it imports only the standard library and ``yaml`` and
MUST NOT import ``config`` (config depends on this module, never the reverse).
Candidate-identity-derived values (paths, filename stems) live in ``config.py``;
``check.py`` re-exports the names from here so existing importers keep working.
"""

import re
from pathlib import Path

import yaml

# Generation inputs and intermediate artifacts (JD files, tailored.yaml, DOCX)
# live under this subfolder of every application folder. Only the final PDFs, the
# bundled application .txt, and meta.yaml stay at the application-folder root.
SOURCE_DIRNAME = "source"


def slugify_label(label: str) -> str:
    """Turn a target-position label into a filename-safe suffix.

    "Frontend Engineer" -> "Frontend_Engineer". Used to distinguish the two
    rendered resumes when one company needs divergent resumes for very different
    roles (e.g. a backend/platform role vs. a frontend web role). Returns "" for
    an empty/None label so callers fall back to the plain stem.
    """
    if not label:
        return ""
    cleaned = re.sub(r"[^0-9A-Za-z]+", " ", str(label)).strip()
    return "_".join(cleaned.split())


def _stem(base: str, label: str = "") -> str:
    slug = slugify_label(label)
    return f"{base}_{slug}" if slug else base


def compose_stem(base: str, label: str = "") -> str:
    """Compose an output-file stem from a base and an optional label suffix.

    Returns ``base`` for an empty/None label, else ``f"{base}_{slugify_label(label)}"``.
    Behaviorally identical to the internal ``_stem`` helper — the config-layer
    stem builders compose their stems through this.
    """
    return _stem(base, label)


# ── Application-folder layout (source/ subfolder) ─────────────
# An application folder looks like:
#   applications/<status>/<slug>/
#       meta.yaml
#       <RESUME_STEM>.pdf                 (final, at root)
#       <COVER_STEM>.pdf                  (final, at root)
#       <APPLICATION_STEM>.txt            (bundled cover letter + why-fit + past exp)
#       notes.md                          (optional)
#       source/
#           JD-<job-title>.md ...         (one per posting, always JD-prefixed)
#           tailored.yaml
#           <RESUME_STEM>.docx
#           <COVER_STEM>.docx
# The helpers below resolve that layout from any of: the folder, the tailored.yaml
# path, or the source/ folder itself.

def application_dir(path) -> Path:
    """Return the application-folder root for a folder / tailored.yaml / source path."""
    p = Path(path)
    if p.is_dir():
        return p.parent if p.name == SOURCE_DIRNAME else p
    if p.parent.name == SOURCE_DIRNAME:
        return p.parent.parent
    return p.parent


def source_dir(app_dir) -> Path:
    """The source/ subfolder for an application folder."""
    return Path(app_dir) / SOURCE_DIRNAME


def tailored_path(app_dir) -> Path:
    """The tailored.yaml inside an application folder's source/ subfolder."""
    return Path(app_dir) / SOURCE_DIRNAME / "tailored.yaml"


def meta_path(app_dir) -> Path:
    """The meta.yaml at an application-folder root."""
    return application_dir(app_dir) / "meta.yaml"


def application_roles(app_dir) -> list:
    """Role/job titles for a folder, one per posting — the per-JD cover-letter key.

    Reads meta.yaml: a ``jobs:`` list yields one role per entry (several postings
    covered by one resume); otherwise the single top-level ``role``. Each role maps
    one-to-one to a ``source/JD-<title>.md``, a bundled ``..._Application_<role>.txt``,
    and a rendered ``..._Cover_Letter_<role>.{docx,pdf}`` (the label slug comes from
    ``slugify_label``). Returns ``[]`` when meta.yaml carries no role info (e.g. a
    resume-only draft).
    """
    mp = meta_path(app_dir)
    if not mp.exists():
        return []
    try:
        meta = yaml.safe_load(mp.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    jobs = meta.get("jobs")
    if isinstance(jobs, list) and jobs:
        roles = [str(j.get("role", "")).strip()
                 for j in jobs if isinstance(j, dict) and j.get("role")]
        if roles:
            return roles
    role = meta.get("role")
    return [str(role).strip()] if role else []


def find_jd_files(app_dir) -> list:
    """All job-description files for an application folder.

    Naming convention (always JD-prefixed, single or multiple postings):
      - one ``JD-<job-title>.md`` per posting, in the ``source/`` subfolder.
    Returned sorted so concatenation is deterministic.
    """
    folder = source_dir(application_dir(app_dir))
    if not folder.is_dir():
        return []
    return [
        p for p in sorted(folder.glob("*.md"))
        if p.name.lower().startswith("jd-")
    ]
