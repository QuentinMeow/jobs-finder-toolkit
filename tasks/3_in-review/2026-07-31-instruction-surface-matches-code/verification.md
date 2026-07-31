# Verification — 2026-07-31-instruction-surface-matches-code

Real output only. Home paths are redacted to `<repo-root>`.

## 1. The gate the table omitted, and the conditional flags

```
$ grep -n 'require-roots\|verify_links\|reconcile.py' automation/hooks/pre-commit
129:    "$PY" automation/reconcile/reconcile.py --check --require-roots
132:    "$PY" automation/reconcile/reconcile.py --check
153:    "$PY" automation/gardener/verify_links.py --require-roots --no-overlay
156:    "$PY" automation/gardener/verify_links.py

$ sed -n '127p;151p' automation/hooks/pre-commit
if [ -d private ]; then
if [ -d private ]; then
```

Both flags are branch-conditional, and `verify_links.py` had no row in the table at all.
CI runs the same two checkers deliberately WITHOUT `--require-roots`:

```
$ grep -n 'reconcile.py --check\|verify_links.py\|check_mail_safety\|instruction_budget' .github/workflows/ci.yml
106:        run: python automation/reconcile/reconcile.py --check
119:        run: python automation/gardener/verify_links.py
168:        run: python automation/metrics/instruction_budget.py --strict
```

(plus the mail gate at ci.yml:93-96). Four gates that the old table implied were hook-only
now run in CI too.

## 2. The two undocumented gardener routines

```
$ .venv/bin/python automation/gardener/gardener.py --help | sed -n '10,20p'
Routines:
    expire-discoveries   move discovery scans past their TTL to archive/ (--apply)
    compact-logs         prune stale search-log rows / rebuild derived log (--apply)
    lessons-report       flag stale + near-duplicate LESSONS entries (report-only)
    card-staleness       flag the tailoring card when its sources drifted (report-only)
    skill-drift          flag baseline skills not in the profile's canonical lists (report-only)
    verify-links         check referenced paths + symlinks + vendor drift (exit 1 on break)
    self-measure         recompute the pipeline funnel + memory metrics (--apply writes yaml)
    store-report         raw-data-layer store health (sizes/blobs/locks/validate; report-only)
```

Eight dispatchable; the skill documented six. `--all`'s order and the report-only flags come
from the code, not the help text:

```
$ sed -n '41,54p' automation/gardener/gardener.py
ROUTINES = {
    "expire-discoveries": (lambda apply: expire_discoveries.run(apply), True),
    "compact-logs": (lambda apply: compact_logs.run(apply), True),
    "lessons-report": (lambda apply: lessons_report.run(), False),
    "card-staleness": (lambda apply: card_staleness.run(), False),
    "skill-drift": (lambda apply: skill_drift.run(), False),
    "store-report": (lambda apply: store_report.run(), False),
    "verify-links": (lambda apply: verify_links.run(), False),
    "self-measure": (lambda apply: self_measure.run(apply), True),
}
# Order used by --all (verify-links last so its exit code is the overall gate).
ALL_ORDER = ["self-measure", "expire-discoveries", "compact-logs",
             "lessons-report", "card-staleness", "skill-drift", "store-report",
             "verify-links"]
```

*(Still eight as of this PR. Later in the same stack a ninth, `roadmap-staleness`, was added
when the roadmap's age moved out of the reconciler's gate — so the two blocks above are the
state at this branch's head, not at the stack's, and the `sed` line offsets shifted with it.)*

Accessors and exit codes as documented in the new rows:

```
$ grep -n 'config\.' automation/gardener/skill_drift.py automation/gardener/store_report.py
automation/gardener/skill_drift.py:6:The baseline resume (``config.paths.baseline_yaml``) is the master a tailored resume
automation/gardener/skill_drift.py:157:    return find_drift(config.baseline_path(), config.profile_md_path())
automation/gardener/store_report.py:240:    root = config.data_root()

$ sed -n '256,262p' automation/gardener/store_report.py
            rc = 1  # a corrupt blob / schema violation is a real integrity failure
    print("\n  store-report is READ-ONLY (the gardener never prunes; run "
          "automation/store/gc_store.py --execute to act on retention).")
    return rc
```

*(Corrected 2026-07-31: the `grep` block above first showed two hits. The real command emits
three — the docstring mention at `skill_drift.py:6` was dropped. It changes nothing about the
conclusion, but a transcript that cannot be reproduced is not evidence.)*

```
$ .venv/bin/python automation/gardener/gardener.py skill-drift --apply | head -1
note: 'skill-drift' is report-only; --apply has no effect.
```

## 3. Public-skill count

```
$ .venv/bin/python automation/publish/sync_skill_manifests.py --check
skill manifests in sync (11 public skill(s): application-tracker, ask-me-anything,
behavioral-interview-prep, company-research, email-assistant, gardener, github-workflow,
interview-calendar, job-search, resume-writer, search-recall-audit)

$ grep -rn 'eight public' docs/ README.md AGENTS.md CONTRIBUTING.md skills/ evals/
(no output)
```

## 4. The orphan directory was contentless and unreferenced

```
$ find .cursor/skills/github-manager -print          # before removal
.cursor/skills/github-manager
.cursor/skills/github-manager/logs

$ git ls-files .cursor/skills/github-manager
(no output — untracked)

$ git check-ignore -v .cursor/skills/github-manager
(no output — not ignored either; it was simply never added)
```

The only live reference was the manifest-sync test fixture, renamed in this branch. Every
other hit is a dated record in `tasks/4_done/`.

The manifest sync ignoring it is deliberate, not a gap:

```
$ sed -n '232,241p' automation/publish/sync_skill_manifests.py
def _managed_links(host_dir: Path) -> dict[str, str]:
    """Entries under ``host_dir`` this tool owns: symlinks into ``../../skills/``.

    An entry that is not a symlink, or a symlink pointing somewhere else, belongs
    to someone else and is never touched or reported — a third-party skill
    installed into the same host directory, or a PRIVATE skill's git-ignored
    runtime link into ``PRIVATE_SKILL_TARGET_PREFIX``. Ownership is decided by the
    TARGET, so a private skill and a public one can even share a name without
    either tool fighting the other.
    """
```

Same rule keeps a reconciler-driven `sync()` from deleting the git-ignored runtime links into
`../../private/skills/`. No check added.

## 5. The four wrong instructions

Search profiles — the code refuses what the docs told an agent to do:

```
$ sed -n '211,236p' skills/job-search/scripts/search_jobs.py
def profile_search_dirs() -> list[Path]:
    """Directories a bare ``--profile`` label is resolved against, in order.

    The candidate's OWN profiles live in the private overlay
    (``config.search_profiles_dir()``) and are searched FIRST, so a personal label
    wins over a same-named public file. ...
    A configured profiles dir that resolves INSIDE the public ``skills/`` tree is
    dropped: ...
```

Company behavioural answers — the tree, checked with counts and shapes only:

```
$ find private/companies -path '*/derived/*' -name '*.md' | wc -l
      19
$ ls private/me/interviews/question-bank/ | grep -cv '^_general_\|^README.md$\|^sources$\|^tests$'
0
```

Every file in the question bank is `_general_*` (plus README/sources/tests); the 19
company-prefixed answers are under the company folders, exactly as
`memory/decisions/interview-material-moves-by-company-only.md` records. The SKILL.md said
to keep them in the question bank "instead of a separate company folder".

Status folders:

```
$ sed -n '29,38p' automation/shared/layout.py
# applications/ (0_profile/, 1_discoveries/) is a support folder, not a status.
STATUS_DIRS = {
    "drafted": "6_drafted",
    "applied": "5_applied",
    "in_progress": "4_in_progress",
    "rejected": "3_rejected",
    "ignored": "2_ignored",
}
```

Five statuses; `AGENTS.md` claimed the range `0_profile`...`6_drafted` twice.

## 6. Gates

Full gate script (mirrors `.github/workflows/ci.yml` plus the plan's gate command), run on the
branch tip after the closing ledger-only commit:

```
$ zsh <scratchpad>/gate.sh
===== gates =====
PASS  vendor-drift
PASS  byte-compile
PASS  reconcile
PASS  leak-guard
PASS  review-gate
PASS  instruction-budget
PASS  verify-links
PASS  mail-safety
===== unit suites =====
PASS  tests:reconcile
PASS  tests:gardener
PASS  tests:hooks
PASS  tests:shared
PASS  tests:publish
PASS  tests:store-example
PASS  tests:resume-writer
PASS  tests:job-search
PASS  filter-variants
PASS  tests:app-tracker
PASS  tests:github-wf
===== export dry-run =====
PASS  export-strict

ALL GREEN
```

Budget headroom after the edits (no file moved tier):

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict | grep -E 'AGENTS.md|github-workflow|gardener|ask-me|job-search/SKILL|behavioral.*SKILL|^OK'
AGENTS.md                                              318  25299     6324        500      ok
skills/ask-me-anything/SKILL.md                        260  16385     4096        600      ok
skills/behavioral-interview-prep/SKILL.md              491  25762     6440        600      ok
skills/gardener/SKILL.md                                93   7605     1901        600      ok
skills/github-workflow/SKILL.md                        340  18161     4540        600      ok
skills/job-search/SKILL.md                             317  24563     6140        600      ok
OK: all instruction files within budget.
```

## 7. Eval gate

One skill edit is more than cosmetic (`behavioral-interview-prep`); the calls are recorded per
skill in the PR body. No canary set exists for `gardener`, so its edit is a recorded-rationale
skip by rule (`evals/README.md`: "An edit to either is therefore always a 'skip with a recorded
one-line rationale'").
