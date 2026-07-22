"""Normalize resume YAML into the canonical multi-employer representation.

The resume-writer historically documented a singular ``employer`` mapping while
the renderer also accepted an undocumented ``employers`` list and ``experience``
alias.  Keeping that compatibility logic in several scripts caused the accepted
schemas to drift.  This module is the single, skill-local source of truth.

Canonical experience shape::

    employers:
      - company: Example Corp
        role: Senior Engineer
        dates: 2021 - Present
        location: Remote (US)
        bullets: []          # optional role-level achievements
        projects: []         # optional named projects with bullets

``employer`` (one mapping) and ``experience`` (a list) remain supported inputs.
Supplying more than one representation is rejected rather than guessed.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


EXPERIENCE_KEYS = ("employers", "employer", "experience")
EMPLOYER_FIELDS = ("company", "role", "dates", "location")


class ResumeSchemaError(ValueError):
    """Raised when resume YAML cannot be normalized without guessing."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _string(value: Any, where: str, errors: list[str]) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        errors.append(f"{where} must be a string")
        return ""
    return value


def _string_list(value: Any, where: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{where} must be a list of strings")
        return []
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"{where}[{index}] must be a string")
        else:
            out.append(item)
    return out


def _projects(value: Any, where: str, errors: list[str]) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{where} must be a list")
        return []
    out: list[dict] = []
    for index, item in enumerate(value):
        item_where = f"{where}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_where} must be a mapping")
            continue
        title = _string(item.get("title", ""), f"{item_where}.title", errors)
        bullets = _string_list(item.get("bullets", []), f"{item_where}.bullets", errors)
        out.append({"title": title, "bullets": bullets})
    return out


def _employer(value: Any, where: str, errors: list[str]) -> dict | None:
    if not isinstance(value, dict):
        errors.append(f"{where} must be a mapping")
        return None
    out = {
        field: _string(value.get(field, ""), f"{where}.{field}", errors)
        for field in EMPLOYER_FIELDS
    }
    out["bullets"] = _string_list(value.get("bullets", []), f"{where}.bullets", errors)
    out["projects"] = _projects(value.get("projects", []), f"{where}.projects", errors)
    return out


def schema_errors(data: Any) -> list[str]:
    """Return stable, user-facing shape errors without raising."""
    try:
        normalize_resume(data)
    except ResumeSchemaError as exc:
        return exc.errors
    return []


def normalize_resume(data: Any) -> dict:
    """Return a deep-copied resume with canonical ``employers``.

    The function validates the collection shapes used by every downstream
    script.  Semantic policy (locked fields, counts, lengths) remains check.py's
    responsibility.
    """
    if not isinstance(data, dict):
        raise ResumeSchemaError(["resume YAML root must be a mapping"])

    errors: list[str] = []
    out = deepcopy(data)

    for key in ("name", "contact_line", "education_line"):
        if key in out:
            out[key] = _string(out[key], key, errors)
    out["summary_bullets"] = _string_list(
        out.get("summary_bullets", []), "summary_bullets", errors)

    skills = out.get("skills", [])
    if isinstance(skills, dict):
        normalized_skills = []
        for label, items in skills.items():
            label_text = str(label).replace("_", " ").title()
            if isinstance(items, list):
                if not all(isinstance(item, str) for item in items):
                    errors.append(f"skills.{label} must contain only strings")
                    continue
                items_text = ", ".join(items)
            elif isinstance(items, str):
                items_text = items
            else:
                errors.append(f"skills.{label} must be a string or list of strings")
                continue
            normalized_skills.append({"label": label_text, "items": items_text})
        out["skills"] = normalized_skills
    elif isinstance(skills, list):
        normalized_skills = []
        for index, item in enumerate(skills):
            where = f"skills[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{where} must be a mapping")
                continue
            normalized_skills.append({
                "label": _string(item.get("label", ""), f"{where}.label", errors),
                "items": _string(item.get("items", ""), f"{where}.items", errors),
            })
        out["skills"] = normalized_skills
    else:
        errors.append("skills must be a list or mapping")
        out["skills"] = []

    supplied = [key for key in EXPERIENCE_KEYS if key in data and data[key] is not None]
    if len(supplied) > 1:
        errors.append(
            "resume must use exactly one experience representation; found "
            + ", ".join(supplied))

    source_key = supplied[0] if supplied else "employers"
    raw = data.get(source_key, [])
    if source_key == "employer":
        raw_employers = [raw]
    else:
        if not isinstance(raw, list):
            errors.append(f"{source_key} must be a list")
            raw_employers = []
        else:
            raw_employers = raw

    employers: list[dict] = []
    for index, item in enumerate(raw_employers):
        employer = _employer(item, f"{source_key}[{index}]", errors)
        if employer is not None:
            employers.append(employer)

    out.pop("employer", None)
    out.pop("experience", None)
    out["employers"] = employers

    if errors:
        raise ResumeSchemaError(errors)
    return out


def employers(data: Any) -> list[dict]:
    """Convenience accessor for callers that already handle schema errors."""
    return normalize_resume(data)["employers"]


def experience_bullets(data: Any) -> list[str]:
    """All direct and project bullets in display order."""
    bullets: list[str] = []
    for employer in employers(data):
        bullets.extend(employer.get("bullets", []))
        for project in employer.get("projects", []):
            bullets.extend(project.get("bullets", []))
    return bullets
