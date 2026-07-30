#!/usr/bin/env python3
"""Reconciler — mechanical referee for the repo's process-layer invariants.

Validates the message-queue/, tasks/, memory/, history/, and docs/roadmap/
structures against their schemas (single source of truth: ``templates/``), and
the derived skill manifests against ``skills/*/SKILL.md`` frontmatter (single
source of truth for visibility). Instructions are wishes; this check is the
guarantee — it runs from the pre-commit hook and CI, and violations can be filed
as repair items the next session picks up.

Usage:
    reconcile.py --check                  # exit 1 on findings, print them
    reconcile.py --check --file-retries   # also (re)file findings into
                                          #   message-queue/needs-agent/retries/
                                          #   and GC cleared reconciler items
    reconcile.py --check --require-roots  # maintainer checkout: ALSO fail when a
                                          #   process root is missing (see below)
    reconcile.py --fix-index              # regenerate memory/index.md

Design rules:
  * stdlib only — must run on a bare clone;
  * every check NO-OPS if its folder is absent, so any subset of the
    process folders can be adopted or deleted — and because the PUBLIC export
    ships none of message-queue/, tasks/, memory/, docs/roadmap/, history/, closing
    that no-op would turn the exported repo's CI red. ``--require-roots`` is the
    opt-in maintainer-checkout assertion that they are all present; it is wired
    into the pre-commit hook, never into CI;
  * checks validate the PUBLIC tree only (the private overlay mirror is its
    own repo with its own lifecycle);
  * to change a file format, change ``templates/`` AND the matching check
    here in the same commit.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RETRIES_DIR = REPO_ROOT / "message-queue/needs-agent/retries"
RECONCILER_SIGNATURE = "by reconcile"

TASK_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
STATUS_DIRS = ("0_backlog", "1_in-progress", "2_blocked", "3_in-review", "4_done")


@dataclass(frozen=True)
class Finding:
    check: str
    subject: str  # repo-relative path
    message: str

    def __str__(self) -> str:
        return f"[{self.check}] {self.subject}: {self.message}"


def _rel(p: Path) -> str:
    return p.relative_to(REPO_ROOT).as_posix()


def _items(folder: Path) -> list[Path]:
    """Markdown items in a queue folder (READMEs and non-md files excluded)."""
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir()
        if p.suffix == ".md" and p.name != "README.md" and p.is_file()
    )


def _has_key(text: str, key: str) -> bool:
    """A bold-key line like ``- **Key**: value`` (tolerates a trailing ? in the key)."""
    return re.search(
        rf"^- \*\*{re.escape(key)}\??\*\*\s*:", text, flags=re.MULTILINE
    ) is not None


def _require_keys(path: Path, keys: list[str], check: str,
                  findings: list[Finding], extra_line: str | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [k for k in keys if not _has_key(text, k)]
    if missing:
        findings.append(Finding(check, _rel(path), f"missing required key(s): {', '.join(missing)}"))
    if extra_line and extra_line not in text:
        findings.append(Finding(check, _rel(path), f"missing required line: {extra_line!r}"))


# ── checks ───────────────────────────────────────────────────────────────────

def check_queue_schema() -> list[Finding]:
    """Every message-queue item carries its queue's required keys (templates/queue/)."""
    findings: list[Finding] = []
    mq = REPO_ROOT / "message-queue"
    if not mq.is_dir():
        return findings
    for item in _items(mq / "needs-human/decisions"):
        _require_keys(item, ["Status", "Filed"], "queue-schema", findings,
                      extra_line="**Your answer:**")
    for item in _items(mq / "needs-human/clarifications"):
        _require_keys(item, ["Status", "Assumption", "Matters-by", "Filed"],
                      "queue-schema", findings, extra_line="**Your answer:**")
    for item in _items(mq / "needs-human/reviews"):
        _require_keys(item, ["Filed", "Look at", "Why you might care", "If you do nothing"],
                      "queue-schema", findings)
    for item in _items(mq / "needs-agent/retries"):
        _require_keys(item, ["Status", "Filed", "Check", "Subject"],
                      "queue-schema", findings)
    # needs-agent/requests/ is deliberately format-free.
    return findings


def check_task_structure() -> list[Finding]:
    """Task folders are well-named and carry the files their status requires."""
    findings: list[Finding] = []
    tasks = REPO_ROOT / "tasks"
    if not tasks.is_dir():
        return findings
    for status in STATUS_DIRS:
        sdir = tasks / status
        if not sdir.is_dir():
            continue
        for entry in sorted(sdir.iterdir()):
            if entry.name in {".gitkeep", "README.md"} or entry.name.startswith("."):
                continue
            if not entry.is_dir():
                findings.append(Finding("task-structure", _rel(entry),
                                        "loose file in a status folder — tasks are folders"))
                continue
            if not TASK_ID_RE.match(entry.name):
                findings.append(Finding("task-structure", _rel(entry),
                                        "folder name must be YYYY-MM-DD-<kebab-slug>"))
            task_md = entry / "task.md"
            if not task_md.is_file():
                findings.append(Finding("task-structure", _rel(entry), "missing task.md"))
                continue
            _require_keys(task_md, ["Priority", "Area", "Source"], "task-structure", findings)
            text = task_md.read_text(encoding="utf-8")
            if status != "0_backlog" and not _has_key(text, "Claimed-by"):
                findings.append(Finding("task-structure", _rel(task_md),
                                        f"tasks in {status} must carry a Claimed-by key"))
            if status in ("3_in-review", "4_done") and not (entry / "verification.md").is_file():
                findings.append(Finding("task-structure", _rel(entry),
                                        f"{status} requires verification.md (real command output)"))
    return findings


def check_memory_schema() -> list[Finding]:
    """Memory entries carry the keys their zone's template requires."""
    findings: list[Finding] = []
    memory = REPO_ROOT / "memory"
    if not memory.is_dir():
        return findings
    for item in _items(memory / "decisions"):
        _require_keys(item, ["Status", "Date"], "memory-schema", findings)
    for item in _items(memory / "known-issues"):
        _require_keys(item, ["Status", "Severity"], "memory-schema", findings)
    for item in _items(memory / "facts"):
        _require_keys(item, ["Filed", "Source"], "memory-schema", findings)
    lessons = memory / "lessons"
    if lessons.is_dir():
        for item in sorted(lessons.rglob("*.md")):
            if item.name == "README.md":
                continue
            _require_keys(item, ["Filed", "Source"], "memory-schema", findings)
    return findings


def _generated_index() -> str:
    """Deterministic memory/index.md content (one line per entry, by zone)."""
    memory = REPO_ROOT / "memory"
    lines = [
        "<!-- GENERATED by automation/reconcile/reconcile.py --fix-index; do not hand-edit. -->",
        "# memory/ index",
        "",
    ]
    for zone in ("decisions", "known-issues", "facts", "lessons"):
        zdir = memory / zone
        if not zdir.is_dir():
            continue
        entries = sorted(p for p in zdir.rglob("*.md") if p.name != "README.md")
        if not entries:
            continue
        lines.append(f"## {zone}")
        lines.append("")
        for p in entries:
            title = p.stem
            for raw in p.read_text(encoding="utf-8").splitlines():
                if raw.startswith("# "):
                    title = raw[2:].strip()
                    break
            lines.append(f"- `{_rel(p)}` — {title}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def check_memory_index() -> list[Finding]:
    """memory/index.md matches what --fix-index would generate."""
    memory = REPO_ROOT / "memory"
    if not memory.is_dir():
        return []
    index = memory / "index.md"
    expected = _generated_index()
    if not index.is_file():
        return [Finding("memory-index", _rel(index),
                        "missing — run reconcile.py --fix-index")]
    if index.read_text(encoding="utf-8") != expected:
        return [Finding("memory-index", _rel(index),
                        "stale — run reconcile.py --fix-index")]
    return []


def check_handover_present() -> list[Finding]:
    """Every conversation folder contains a handover.md."""
    findings: list[Finding] = []
    conversations = REPO_ROOT / "history/conversations"
    if not conversations.is_dir():
        return findings
    for entry in sorted(conversations.iterdir()):
        if entry.is_dir() and not (entry / "handover.md").is_file():
            findings.append(Finding("handover-present", _rel(entry),
                                    "missing handover.md (template: templates/handover.md)"))
    return findings


def check_skill_manifests() -> list[Finding]:
    """Every skill manifest agrees with its SKILL.md ``visibility:`` frontmatter.

    ``.claude-plugin/marketplace.json`` and the ``.claude/skills`` /
    ``.cursor/skills`` compat symlink trees are DERIVED surfaces; the exporter
    derives its public-skill list from the same frontmatter at runtime. They
    disagreed for months, so a skill that existed had never shipped. Regenerate
    with ``automation/publish/sync_skill_manifests.py``.
    """
    findings: list[Finding] = []
    skills = REPO_ROOT / "skills"
    if not skills.is_dir():
        return findings
    publish = REPO_ROOT / "automation" / "publish"
    if str(publish) not in sys.path:
        sys.path.insert(0, str(publish))
    import sync_skill_manifests  # noqa: E402  (stdlib-only sibling module)

    for subject, message in sync_skill_manifests.findings(REPO_ROOT):
        findings.append(Finding("skill-manifests", subject, message))
    return findings


def check_roadmap_fresh() -> list[Finding]:
    """docs/roadmap/current-state.md exists alongside desired-state.md and is dated."""
    findings: list[Finding] = []
    roadmap = REPO_ROOT / "docs" / "roadmap"
    if not roadmap.is_dir():
        return findings
    current = roadmap / "current-state.md"
    if not current.is_file():
        findings.append(Finding("roadmap-fresh", _rel(current), "missing"))
    elif "Last-updated" not in current.read_text(encoding="utf-8"):
        findings.append(Finding("roadmap-fresh", _rel(current),
                                "missing a Last-updated line"))
    return findings


CHECKS = {
    "queue-schema": check_queue_schema,
    "task-structure": check_task_structure,
    "memory-schema": check_memory_schema,
    "memory-index": check_memory_index,
    "handover-present": check_handover_present,
    "roadmap-fresh": check_roadmap_fresh,
    "skill-manifests": check_skill_manifests,
}

# The folder whose absence makes each check no-op (see the module docstring: that
# no-op is DELIBERATE — the published tree ships none of message-queue/, tasks/,
# memory/, docs/roadmap/ or history/, so closing it would turn the exported repo's CI
# red). --require-roots is the maintainer-checkout opposite: assert they are all
# here, so a botched move cannot quietly disarm a check. Plain --check is
# unchanged and still no-ops.
CHECK_ROOTS = {
    "queue-schema": "message-queue",
    "task-structure": "tasks",
    "memory-schema": "memory",
    "memory-index": "memory",
    "handover-present": "history/conversations",
    "roadmap-fresh": "docs/roadmap",
    "skill-manifests": "skills",
}


def check_required_roots() -> list[Finding]:
    """--require-roots only: every root a check silently no-ops without exists."""
    findings: list[Finding] = []
    for root in sorted(set(CHECK_ROOTS.values())):
        if (REPO_ROOT / root).is_dir():
            continue
        checks = ", ".join(sorted(c for c, r in CHECK_ROOTS.items() if r == root))
        findings.append(Finding(
            "require-roots", root,
            f"missing — {checks} would silently no-op (plain --check tolerates this "
            f"by design; --require-roots does not)"))
    return findings


# ── retry filing ─────────────────────────────────────────────────────────────

def _retry_name(f: Finding) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f.subject.lower()).strip("-")
    return f"{f.check}--{slug}.md"


def file_retries(findings: list[Finding], today: str) -> None:
    """(Re)file one retry item per finding; GC cleared reconciler-authored items.

    The queue folder is created only when there is something to file. It used to
    be mkdir'd unconditionally, so a clean run in a repo that had deliberately
    deleted ``message-queue/`` silently re-created the queue it had dropped —
    which then also re-armed ``queue-schema`` on a tree that opted out of it.
    """
    if not findings and not RETRIES_DIR.is_dir():
        return  # nothing to file, and no queue to GC — do not conjure one
    if findings:
        RETRIES_DIR.mkdir(parents=True, exist_ok=True)
    wanted = {_retry_name(f): f for f in findings}
    for f in findings:
        path = RETRIES_DIR / _retry_name(f)
        body = (
            f"# {f.check} finding on {f.subject}\n\n"
            f"- **Status**: open\n"
            f"- **Filed**: {today}, {RECONCILER_SIGNATURE}\n"
            f"- **Check**: {f.check}\n"
            f"- **Subject**: {f.subject}\n\n"
            f"## Finding\n\n{f.message}\n"
        )
        if not path.is_file() or path.read_text(encoding="utf-8") != body:
            path.write_text(body, encoding="utf-8")
    for existing in _items(RETRIES_DIR):
        if existing.name in wanted:
            continue
        if RECONCILER_SIGNATURE in existing.read_text(encoding="utf-8"):
            existing.unlink()  # the finding cleared; the queue holds only live items


# ── entry point ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="run all checks; exit 1 on findings")
    parser.add_argument("--file-retries", action="store_true",
                        help="with --check: file findings into needs-agent/retries/ and GC cleared items")
    parser.add_argument("--require-roots", action="store_true",
                        help="maintainer checkout only: also assert every process root exists "
                             "(plain --check no-ops on a missing root, by design)")
    parser.add_argument("--fix-index", action="store_true", help="regenerate memory/index.md")
    parser.add_argument("--today", default=None,
                        help="override the Filed date for retry items (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    if args.fix_index:
        index = REPO_ROOT / "memory/index.md"
        index.write_text(_generated_index(), encoding="utf-8")
        print(f"wrote {_rel(index)}")
        if not args.check:
            return 0

    if not args.check and not args.fix_index and not args.require_roots:
        parser.print_help()
        return 2

    findings: list[Finding] = []
    n_checks = len(CHECKS)
    if args.require_roots:
        findings.extend(check_required_roots())
        n_checks += 1
    for name, fn in CHECKS.items():
        findings.extend(fn())

    if args.file_retries:
        from datetime import date
        today = args.today or date.today().isoformat()
        file_retries(findings, today)

    if findings:
        print(f"reconcile: {len(findings)} finding(s)")
        for f in findings:
            print(f"  {f}")
        return 1
    print(f"reconcile: OK ({n_checks} checks clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
