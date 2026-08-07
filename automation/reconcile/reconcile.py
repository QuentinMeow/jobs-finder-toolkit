#!/usr/bin/env python3
"""Reconciler — mechanical referee for the repo's process-layer invariants.

Validates the message-queue/, tasks/, memory/, history/, and docs/roadmap/
structures against their schemas (single source of truth: ``templates/``), and
the derived skill manifests against ``skills/*/SKILL.md`` frontmatter (single
source of truth for visibility). It also holds ONE privacy invariant the leak
guard structurally cannot hold — that the published company registry carries no
personal ``blacklist:`` row (``check_public_registry_blacklist``) — because the
leak guard matches identity tokens and an employer's name is not one.
Instructions are wishes; this check is the guarantee — it runs from the
pre-commit hook and CI, and violations can be filed as repair items the next
session picks up.

Usage:
    reconcile.py --check                  # exit 1 on findings, print them
    reconcile.py --check --file-retries   # also (re)file findings into
                                          #   message-queue/needs-agent/retries/
                                          #   and GC cleared reconciler items
    reconcile.py --check --require-roots  # maintainer checkout: ALSO fail when a
                                          #   process root is missing (see below)
    reconcile.py --fix-index              # regenerate memory/index.md
    reconcile.py --check --root PATH      # check the tree at PATH instead of this
                                          #   checkout (benchmark fixtures)

Design rules:
  * stdlib only — must run on a bare clone;
  * every check NO-OPS if its folder is absent, so any subset of the
    process folders can be adopted or deleted — and because the PUBLIC export
    ships none of message-queue/, tasks/, memory/, docs/roadmap/, history/, closing
    that no-op would turn the exported repo's CI red. ``--require-roots`` is the
    opt-in maintainer-checkout assertion that they are all present; it is wired
    into the pre-commit hook, never into CI;
  * ``--root`` rebinds :data:`REPO_ROOT` (and :data:`RETRIES_DIR`) ONCE, in
    :func:`main`, before any check runs. Every check reads the module global at
    call time, so none of them needed a change — and with the flag ABSENT not one
    byte of behaviour moves, which is the only acceptable shape for a file that
    runs from pre-commit and CI on every commit in the repo. The flag exists so a
    benchmark fixture (``automation/evals/reconciliation_fixture.py``) is judged by
    the REAL reconciler instead of a simulation of it; nothing automated passes it;
  * checks validate the PUBLIC tree only (the private overlay mirror is its
    own repo with its own lifecycle) — with ONE declared exception,
    ``check_company_index``, which reads the owner's company index because a
    check nobody is forced to run is the failure mode this module exists to fix.
    Three things bound that exception to the maintainer's own machine: it no-ops
    unless ``private/market/`` is present, ``--require-roots`` never asserts a
    private root, and ``file_retries`` never writes a private subject into the
    tracked retry queue;
  * to change a file format, change ``templates/`` AND the matching check
    here in the same commit.
"""
from __future__ import annotations

import argparse
import datetime
import importlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RETRIES_DIR = REPO_ROOT / "message-queue/needs-agent/retries"
RECONCILER_SIGNATURE = "by reconcile"

TASK_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
STATUS_DIRS = ("0_backlog", "1_in-progress", "2_blocked", "3_in-review", "4_done")

# ``- **Last-updated**: 2026-07-30`` and the plainer forms of the same line.
#
# The gardener's ``roadmap-staleness`` routine imports this regex and
# :func:`parse_last_updated` rather than carrying its own copy, so the gate and the
# reminder can never disagree about which line carries the date or how it is read.
_LAST_UPDATED_RE = re.compile(
    r"^\s*[-*]?\s*\**Last-updated\**\s*:\s*(?P<date>\S+)", re.MULTILINE)

# The owner's company index lives under this root. It is the only PRIVATE root any
# check names; ``company_index.DEFAULT_REL`` is the single source for the file path
# itself, and a test pins this to be its parent.
COMPANY_INDEX_ROOT = "private/market"

# The tracked PUBLIC company registry. It and the git-ignored blacklist overlay
# share ONE entry schema, so a personal skip rule written here works exactly as if
# it were in the overlay — which is precisely why nothing downstream ever notices.
PUBLIC_REGISTRY_REL = "skills/job-search/companies.yaml"

# ``blacklist`` used as a YAML key: block style (``  blacklist: reason``) and the
# flow style every row of that file actually uses (``{name: X, blacklist: reason}``).
_BLACKLIST_KEY_RE = re.compile(r"(?:^|[\s{,])blacklist\s*:")

# ``automation/shared`` resolved from THIS FILE rather than from REPO_ROOT: the tests
# point REPO_ROOT at a throwaway tree, but the sibling package's location is a
# property of this file, not of the tree under inspection.
_SHARED_DIR = Path(__file__).resolve().parents[1] / "shared"


@dataclass(frozen=True)
class Finding:
    check: str
    subject: str  # repo-relative path
    message: str

    def __str__(self) -> str:
        return f"[{self.check}] {self.subject}: {self.message}"


def _rel(p: Path) -> str:
    return p.relative_to(REPO_ROOT).as_posix()


def _rel_safe(p: Path) -> str:
    """``_rel`` for a path that may sit outside the repo.

    The overlay can be configured anywhere, and printing the absolute fallback
    would put the maintainer's home directory in the output; the tail is enough to
    identify the file.
    """
    try:
        return _rel(p)
    except ValueError:
        return "/".join(p.parts[-3:])


def _shared_import(name: str):
    """Import a module from ``automation/shared/``.

    Only ever called BELOW a check's ``is_dir()`` guard, so this module keeps its
    stdlib-only-on-a-bare-clone contract (module docstring, "Design rules"). Same
    sys.path-insert-then-import shape as :func:`check_skill_manifests`.
    """
    if str(_SHARED_DIR) not in sys.path:
        sys.path.insert(0, str(_SHARED_DIR))
    return importlib.import_module(name)


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
        # A decision ships merged and unanswered, so its default path is what runs in
        # main meanwhile. The two cost keys make that default reviewable rather than
        # implicit; without them the queue cannot be ranked (see the queue's README).
        _require_keys(item,
                      ["Status", "Filed", "Default path", "Cost if wrong",
                       "Safe to merge because"],
                      "queue-schema", findings, extra_line="**Your answer:**")
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
    # Resolved from THIS FILE, never from REPO_ROOT: under --root, REPO_ROOT is
    # the tree being INSPECTED, and importing the checker out of it would let an
    # inspected tree ship its own verdict — a fixture carrying this file would
    # certify itself clean. The tree under test is passed as an argument instead.
    publish = Path(__file__).resolve().parents[1] / "publish"
    if str(publish) not in sys.path:
        sys.path.insert(0, str(publish))
    import sync_skill_manifests  # noqa: E402  (stdlib-only sibling module)

    for subject, message in sync_skill_manifests.findings(REPO_ROOT):
        findings.append(Finding("skill-manifests", subject, message))
    return findings


def roadmap_current_state() -> Path:
    """The roadmap file whose ``Last-updated`` line both readers parse."""
    return REPO_ROOT / "docs" / "roadmap" / "current-state.md"


def parse_last_updated(text: str) -> tuple[str | None, datetime.date | None]:
    """``(raw, date)`` for a document's ``Last-updated`` line.

    ``raw`` is None when the line is absent; ``date`` is None when the raw string is
    not an ISO date. Shared with the gardener's ``roadmap-staleness`` routine so the
    two never disagree about what the date IS before they disagree about what to do
    with it.
    """
    match = _LAST_UPDATED_RE.search(text)
    if match is None:
        return None, None
    raw = match.group("date").strip("`*_")
    try:
        return raw, datetime.date.fromisoformat(raw)
    except ValueError:
        return raw, None


def check_roadmap_dated(today: datetime.date | None = None) -> list[Finding]:
    """current-state.md exists beside desired-state.md and carries a WELL-FORMED date.

    The check used to test that the STRING ``Last-updated`` appeared anywhere in the
    file. It never read the date, so ``Last-updated: whenever`` passed. It now parses
    it — and it deliberately stops there. AGE IS NOT CHECKED HERE.

    Why the split. This function runs from ``automation/hooks/pre-commit`` and CI, so
    everything it can find blocks every commit in the repo. That is the right cost for
    a MALFORMED roadmap — a missing ``desired-state.md`` (the gap between the two files
    is the backlog's source, so one alone is not a roadmap), an unparseable date, or a
    future date, which is the one way to defeat an age check by typing a date nobody
    can age past. Each is a defect in the file that the committing agent introduced or
    can fix in seconds.

    An OLD date is different in kind: nothing is wrong with the file, somebody just has
    not groomed it lately, and that is unrelated to whatever the current commit does.
    Wiring it here turned a grooming reminder into an outage — with a 30-day window and
    a roadmap dated 2026-07-31, every commit in the repo would have started failing on
    2026-08-31 until somebody re-dated a planning document, including a one-line fix to
    an unrelated script. Staleness therefore lives in the gardener's report-only
    ``roadmap-staleness`` routine (``automation/gardener/roadmap_staleness.py``), which
    is where this repo already puts age flags: stale LESSONS, a drifted tailoring card,
    expired discovery scans. It surfaces the same fact, on a weekly sweep, to a human
    who can act on it, and it blocks nothing.
    """
    findings: list[Finding] = []
    roadmap = REPO_ROOT / "docs" / "roadmap"
    if not roadmap.is_dir():
        return findings
    desired = roadmap / "desired-state.md"
    if not desired.is_file():
        # Named in this function's contract since it was written, never checked.
        findings.append(Finding("roadmap-dated", _rel(desired), "missing"))
    current = roadmap / "current-state.md"
    if not current.is_file():
        findings.append(Finding("roadmap-dated", _rel(current), "missing"))
        return findings

    raw, stamp = parse_last_updated(current.read_text(encoding="utf-8"))
    if raw is None:
        findings.append(Finding("roadmap-dated", _rel(current),
                                "missing a Last-updated line"))
    elif stamp is None:
        findings.append(Finding(
            "roadmap-dated", _rel(current),
            f"Last-updated: {raw!r} is not an ISO date (YYYY-MM-DD)"))
    elif ((today or datetime.date.today()) - stamp).days < 0:
        findings.append(Finding(
            "roadmap-dated", _rel(current),
            f"Last-updated: {raw} is in the future — a date nobody can go stale past "
            f"is not a freshness claim"))
    return findings


def company_index_findings(index_path: Path,
                           applications_root: Path | None) -> list[Finding]:
    """Index integrity + key resolution, given explicit paths.

    Split out of :func:`check_company_index` so the tests can drive it against a
    throwaway tree without a config.

    TWO FINDING FAMILIES, and the DIRECTION of the second is load-bearing:

      1. **index integrity** — every ``company_index.lint`` pair, adapted;
      2. **key resolution** — every ``company_key`` written in a ``meta.yaml``
         names a key that exists in the index. ``meta.yaml -> index``, NEVER the
         reverse. A key with zero applications is a legitimate state (a company
         researched after recruiter contact but never applied to), and the reverse
         check would turn the reconciler red the moment the owner deletes an
         application folder — which AGENTS.md explicitly reserves to them.

    **Coverage is deliberately NOT a finding.** "Every meta.yaml has a
    ``company_key``" is a number ``status.py --company-keys`` prints, never a gate:
    new applications are scaffolded without a key by design, so gating it would
    block unrelated public commits made between scaffolding and keying.
    """
    findings: list[Finding] = []
    if not index_path.exists() and not index_path.is_symlink():
        # The root exists but the index has not been built yet. That is the same
        # "not adopted" state as an absent root, and it is what lets this public
        # check merge before the owner's private half exists.
        #
        # Tested with ``exists()``, NOT ``is_file()``: a directory or a dangling
        # symlink at this path is not a regular file either, and reading it as "not
        # adopted yet" made this check return clean while applications carried keys.
        # ``read_raw`` raises OSError on one, which lands in the handler below —
        # the same place a ``chmod 000`` file already landed.
        return findings

    # Deliberately function-local: reconcile.py must import stdlib only on a bare
    # clone, and this line is unreachable without the overlay (module docstring).
    import yaml
    company_index = _shared_import("company_index")
    index_rel = _rel_safe(index_path)

    try:
        raw = company_index.read_raw(index_path)
    except (yaml.YAMLError, OSError) as exc:
        return [Finding("company-index", index_rel, f"unreadable: {exc}")]

    for subject, message in company_index.lint(raw):
        findings.append(Finding("company-index", index_rel, f"{subject}: {message}"))

    index = company_index.from_raw(raw)
    if applications_root is None or not applications_root.is_dir():
        return findings

    for meta in sorted(applications_root.rglob("meta.yaml")):
        try:
            text = meta.read_text(encoding="utf-8")
        except OSError:
            continue
        if "company_key" not in text:
            continue          # cheap prefilter: most files never carry the field
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            continue          # meta.yaml's own schema is job_metadata's business
        if not isinstance(data, dict):
            continue
        key = data.get("company_key")
        if key is None:
            continue          # unkeyed is legitimate: coverage is measured, not gated
        subject = _rel_safe(meta)
        # Shape first, membership second, and the shape test is ``company_index.KEY_RE``
        # itself — the same regex ``job_metadata._validate_company_key`` restates. Before
        # this, ``key.strip()`` accepted ``"acme-labs\n"`` here and the value fell through
        # to the membership test, which called a MALFORMED key a MISSING one and told the
        # owner to add the newline to their index.
        if not isinstance(key, str) or not company_index.KEY_RE.match(key):
            findings.append(Finding(
                "company-index", subject,
                f"company_key must be a lowercase company-index key "
                f"([a-z0-9-], starting with a letter or digit), got {key!r}"))
        elif key not in index:
            findings.append(Finding(
                "company-index", subject,
                f"company_key {key!r} is not a key in {index_rel} — add it there, "
                "or correct the application"))
    return findings


def check_company_index() -> list[Finding]:
    """The owner's company index is consistent, and every company_key resolves.

    NO-OPS when ``private/market/`` is absent — the normal case in the published
    tree, in CI, and in any contributor checkout without the overlay. The ``yaml``
    and ``company_index`` imports live BELOW that guard so this module stays
    stdlib-only on a bare clone (module docstring, "Design rules"), which is also
    where the one private-tree exception is declared.
    """
    root = REPO_ROOT / COMPANY_INDEX_ROOT
    if not root.is_dir():
        return []

    company_index = _shared_import("company_index")
    config = _shared_import("config")
    try:
        applications_root = config.applications_root()
    except (config.ConfigNotFound, config.ConfigError):
        # No usable config: there is no applications tree to resolve keys against.
        # The index itself is still linted, which is the half that does not need one.
        applications_root = None
    return company_index_findings(REPO_ROOT / company_index.DEFAULT_REL,
                                  applications_root)


def _strip_yaml_comment(line: str) -> str:
    """The code half of a YAML line — everything before its first unquoted ``#``.

    Quote-aware on purpose: the registry's own header comments discuss ``blacklist:``
    at length, and a naive scan would flag the documentation that exists to prevent
    the very thing being checked.
    """
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


def check_public_registry_blacklist() -> list[Finding]:
    """The PUBLIC company registry carries no ``blacklist:`` row.

    A blacklist row names an employer the candidate personally refuses — their own
    current employer, a company that will not sponsor. ``skills/job-search/companies.yaml``
    is published, so such a row is a leak, and it is a leak NEITHER armed gate can
    see: the leak guard derives its tokens from the candidate's identity and a
    company name is not one, while ``registry.lint_entries`` deliberately REQUIRES a
    blacklist reason on every identity-only row (the overlay's rows use that exact
    schema), so the file lints clean either way. Four documents used to route agents
    here to write one; this check is what makes that routing fix stick.

    Lexical, not a parse: ``yaml`` is not stdlib (module "Design rules"), and a raw
    line scan cannot be talked out of a hit by an anchor, a merge key or an odd
    quoting style the way a loader's normalisation can.

    The finding names the LINE NUMBER and never the row — ``file_retries`` writes a
    finding's message into a TRACKED retry item, so quoting it would publish the
    employer this check exists to keep out.
    """
    registry = REPO_ROOT / PUBLIC_REGISTRY_REL
    if not registry.is_file():
        return []
    try:
        text = registry.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding("public-registry-blacklist", PUBLIC_REGISTRY_REL,
                        f"unreadable ({type(exc).__name__}) — cannot verify that it "
                        f"carries no personal skip rules")]
    return [
        Finding("public-registry-blacklist", PUBLIC_REGISTRY_REL,
                f"line {number} carries a `blacklist:` key. Personal skip rules "
                f"belong in the git-ignored overlay at config.blacklist_path() "
                f"(private/market/blacklist.yaml), which registry.load_registry() "
                f"merges in at load time — never in the published registry")
        for number, line in enumerate(text.splitlines(), start=1)
        if _BLACKLIST_KEY_RE.search(_strip_yaml_comment(line))
    ]


CHECKS = {
    "queue-schema": check_queue_schema,
    "task-structure": check_task_structure,
    "memory-schema": check_memory_schema,
    "memory-index": check_memory_index,
    "handover-present": check_handover_present,
    "roadmap-dated": check_roadmap_dated,
    "skill-manifests": check_skill_manifests,
    "company-index": check_company_index,
    "public-registry-blacklist": check_public_registry_blacklist,
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
    "roadmap-dated": "docs/roadmap",
    "skill-manifests": "skills",
    "company-index": COMPANY_INDEX_ROOT,
    "public-registry-blacklist": "skills",
}

# Checks whose findings name PRIVATE subjects — an application slug, a company key.
# A retry item is a TRACKED file in the public tree, so filing one of these would
# publish exactly what the leak guard exists to keep out. They are printed on the
# maintainer's machine and fixed there. See ``file_retries``.
PRIVATE_CHECKS = frozenset(
    check for check, root in CHECK_ROOTS.items() if root.startswith("private/"))


def check_required_roots() -> list[Finding]:
    """--require-roots only: every PUBLIC root a check silently no-ops without exists."""
    findings: list[Finding] = []
    for root in sorted(set(CHECK_ROOTS.values())):
        # Private roots are declared so CHECK_ROOTS stays a complete map of every
        # check, but they are never ASSERTED: this module validates the public tree,
        # and automation/hooks/pre-commit runs --require-roots whenever private/ is
        # merely mounted, so asserting one would make an overlay's shape a public
        # commit gate — and would put a private path into a public test's expected
        # output.
        if root.startswith("private/"):
            continue
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

    Findings from a :data:`PRIVATE_CHECKS` check are dropped before anything is
    written. A retry item is a TRACKED file whose name and body carry the finding's
    subject and message verbatim, so filing one would commit an application slug or
    a company key into the public tree. Those findings are printed on the
    maintainer's machine, where they are the only place they belong.
    """
    findings = [f for f in findings if f.check not in PRIVATE_CHECKS]
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
    """Entry point. Restores the module globals --root rebinds.

    Without the restore, an in-process ``main(["--root", X])`` leaves REPO_ROOT
    pointing at X for every later call in the same process — including one that
    passes no --root and would then report on X while printing OK. Callers are
    normally subprocesses, but the repo already has an in-process caller that
    mutates these globals (automation/publish/tests/test_skill_manifests.py).
    """
    global REPO_ROOT, RETRIES_DIR
    saved_root, saved_retries = REPO_ROOT, RETRIES_DIR
    try:
        return _main(argv)
    finally:
        REPO_ROOT, RETRIES_DIR = saved_root, saved_retries


def _main(argv: list[str] | None = None) -> int:
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
    parser.add_argument("--root", default=None, metavar="PATH",
                        help="check the tree at PATH instead of this checkout "
                             "(benchmark fixtures; absent => this checkout, unchanged)")
    args = parser.parse_args(argv)

    # The ONLY place --root has an effect. Rebinding here, before the first read of
    # either global, is what makes the flag's absence inert: the `if` is the whole
    # delta, and every check below is byte-for-byte the code that ran before.
    # Nothing automated passes --root — not automation/hooks/pre-commit, not
    # .github/workflows/ci.yml, not automation/gates/run_gates.py.
    if args.root is not None:
        global REPO_ROOT, RETRIES_DIR
        root = Path(args.root).expanduser().resolve()
        if not root.is_dir():
            print(f"reconcile: --root {args.root!r} is not a directory", file=sys.stderr)
            return 2
        # --file-retries GARBAGE-COLLECTS items out of RETRIES_DIR, which --root
        # repoints into the inspected tree — so the combination DELETES files in
        # a directory the operator merely asked to look at. Agents never delete
        # owner data, so the combination is refused outright.
        #
        # --fix-index is deliberately still allowed: it writes one generated file
        # (memory/index.md) into a tree the operator named explicitly, destroys
        # nothing, and is how the benchmark fixture's closeout stage is driven.
        if args.file_retries:
            print("reconcile: --root cannot be combined with --file-retries — that "
                  "would delete queue items inside the inspected tree", file=sys.stderr)
            return 2
        # A directory that is not a process tree must not report "OK (9 checks
        # clean)". Every check returns no findings when its root is absent, so
        # an empty directory — or $HOME — used to come back green: a gate that
        # says OK for a tree it never looked at.
        if not any((root / rel).exists() for rel in set(CHECK_ROOTS.values())):
            print(f"reconcile: --root {args.root!r} contains none of "
                  f"{', '.join(sorted(set(CHECK_ROOTS.values())))} — refusing to "
                  f"report a clean tree it never inspected", file=sys.stderr)
            return 2
        REPO_ROOT = root
        RETRIES_DIR = REPO_ROOT / "message-queue/needs-agent/retries"

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
