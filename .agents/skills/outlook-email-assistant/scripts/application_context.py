"""Match email cues to application folders without persisting mailbox content."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _vendor.layout import status_label_for_dir  # noqa: E402

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a", "an", "and", "application", "at", "for", "from", "in", "job", "of", "on",
    "opportunity", "position", "re", "role", "software", "the", "to", "with",
}


@dataclass(frozen=True)
class ApplicationMatch:
    score: int
    path: Path
    status: str
    company: str
    roles: tuple[str, ...]
    recruiter_email: str
    context_files: tuple[Path, ...]
    jobs: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "path": str(self.path),
            "status": self.status,
            "company": self.company,
            "roles": list(self.roles),
            "recruiter_email": self.recruiter_email,
            "context_files": [str(path) for path in self.context_files],
            "jobs": [dict(job) for job in self.jobs],
        }


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN_RE.findall(value.casefold()) if token not in STOPWORDS}


def _context_files(app_dir: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for fixed in (app_dir / "meta.yaml", app_dir / "notes.md", app_dir / "source/tailored.yaml"):
        if fixed.is_file():
            candidates.append(fixed)
    candidates.extend(sorted(app_dir.glob("*_Application_*.txt")))
    candidates.extend(sorted((app_dir / "source").glob("JD-*.md")))
    return tuple(dict.fromkeys(path.resolve() for path in candidates))


def _clean(value: Any) -> Any:
    """Strip a string value, collapsing missing/blank values to ``None``."""
    if isinstance(value, str):
        value = value.strip()
    return value or None


def _records(applications_root: Path):
    for meta_path in sorted(applications_root.glob("*/**/meta.yaml")):
        app_dir = meta_path.parent
        try:
            meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        raw_jobs = meta.get("jobs") if isinstance(meta.get("jobs"), list) else []
        jobs = [job for job in raw_jobs if isinstance(job, dict)]
        roles = tuple(str(job.get("role", "")).strip() for job in jobs)
        if not roles and meta.get("role"):
            roles = (str(meta["role"]).strip(),)
        # Per-job view for schema v4 (status/stage live on each job entry). v2/v3
        # files predate this and simply lack the keys — degrade to null, never crash.
        job_views = tuple(
            {
                "role": str(job.get("role", "")).strip(),
                "status": _clean(job.get("status")),
                "stage": _clean(job.get("stage")),
            }
            for job in jobs
        )
        folder_name = app_dir.parent.name
        yield {
            "path": app_dir.resolve(),
            "status": status_label_for_dir(folder_name) or folder_name,
            "company": str(meta.get("company", "")).strip(),
            "roles": tuple(role for role in roles if role),
            "recruiter_email": str(meta.get("recruiter_email", "")).strip(),
            "slug": app_dir.name,
            "jobs": job_views,
        }


def find_application_matches(
    applications_root: Path,
    *,
    query: str,
    sender: str = "",
    limit: int = 5,
    min_score: int = 20,
) -> list[ApplicationMatch]:
    query_folded = f"{query} {sender}".casefold()
    query_tokens = _tokens(query_folded)
    sender_folded = sender.strip().casefold()
    matches: list[ApplicationMatch] = []
    for record in _records(applications_root):
        company = record["company"]
        roles = record["roles"]
        recruiter = record["recruiter_email"]
        searchable = " ".join((company, *roles, record["slug"]))
        overlap = query_tokens & _tokens(searchable)
        score = len(overlap) * 5
        if company and company.casefold() in query_folded:
            score += 40
        if sender_folded and recruiter and sender_folded == recruiter.casefold():
            score += 100
        sender_domain = sender_folded.rpartition("@")[2].split(".")[0]
        if sender_domain and sender_domain in _tokens(company):
            score += 20
        # Role words alone are too generic across a large application fleet.
        # Require a company/domain/recruiter signal or several independent cues.
        if score < min_score:
            continue
        matches.append(
            ApplicationMatch(
                score=score,
                path=record["path"],
                status=record["status"],
                company=company,
                roles=roles,
                recruiter_email=recruiter,
                context_files=_context_files(record["path"]),
                jobs=record["jobs"],
            )
        )
    matches.sort(key=lambda match: (-match.score, match.company.casefold(), str(match.path)))
    return matches[: max(1, min(int(limit), 20))]
