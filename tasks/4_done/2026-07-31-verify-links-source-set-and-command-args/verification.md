# Verification — 2026-07-31-verify-links-source-set-and-command-args

## The measurement (2026-08-02, tracked `*.md` only)

```
$ git grep -h -oE '\-m unittest discover -s [^ `"]+' -- '*.md' | wc -l
     125
$ git grep -h -oE '\-m unittest discover -s [^ `"]+' -- '*.md' | sort -u | wc -l
      17
```

The 17 distinct paths, with existence checked one at a time (`[ -d "$p" ]`):

```
MISSING  <dir>
MISSING  <each
MISSING  <path>
MISSING  <scratch>/ci_wt/automation/shared/tests
EXISTS   automation/gardener/tests
EXISTS   automation/hooks/tests
EXISTS   automation/publish/tests
EXISTS   automation/reconcile/tests
EXISTS   automation/search-recall-audit/tests
EXISTS   automation/shared/tests
EXISTS   skills/application-tracker/scripts/tests
EXISTS   skills/behavioral-interview-prep/scripts/tests
EXISTS   skills/email-assistant/scripts/tests
EXISTS   skills/github-workflow/scripts/tests
EXISTS   skills/job-search/scripts/tests
MISSING  skills/outlook-email-assistant/scripts/tests
EXISTS   skills/resume-writer/scripts/tests
```

**5 nonexistent, not 6**: four are literal placeholders and exactly one is a real stale path.
Where each lives, and which tier `verify_links.py` puts its SOURCE document in:

| Nonexistent path | Where it is written | Tier | Would it fail a gate? |
|---|---|---|---|
| `<dir>` | this task's own `task.md:28`, quoting the shape | `plan` at measurement time (`tasks/0_backlog/`); `record` now that this closure moved it to `tasks/4_done/` | no, either way |
| `<path>` | same file, `:34` and `:51` | same | no, either way |
| `<each suite>` | `tasks/4_done/2026-07-31-four-gates-that-inspected-nothing/verification.md:276` | `record` | no — permitted, never fatal |
| `<scratch>/ci_wt/automation/shared/tests` | `tasks/4_done/2026-07-31-company-key-guard-is-not-transitive/verification.md:155` | `record` | no — permitted |
| `skills/outlook-email-assistant/scripts/tests` | `tasks/4_done/2026-07-22-application-progress-calendar/verification.md:33` | `record` | no — permitted |

Tiers per `verify_links.py`'s own docstring: `record` is "dated testimony whose rewriting
would falsify it (`history/`, `memory/decisions/`, `evals/results/`, `tasks/4_done/`) —
PERMITTED: counted and listed every run, never repaired, never fatal"; `plan` covers
`tasks/0_backlog/` and is ADVISORY.

## Why the work is not worth doing — the closing paragraph the task asks for

Arming `-m unittest discover -s <path>` would cost a new argument parser in pass 4, its own
test suite, and a permanent widening of the exclusion that keeps this gate from crying wolf.
What it would buy, measured rather than guessed: **zero new gate failures and one advisory
line**. Every path that does not exist today sits in a document the checker is forbidden to
fail on — three in dated `tasks/4_done/` records and two in the plan tier — and the single
genuinely stale one (`skills/outlook-email-assistant/scripts/tests`, from before the skill was
renamed to `email-assistant`) is inside a `verification.md` that records what a session
actually ran on 2026-07-22. Rewriting that line to name today's directory would falsify the
record, which is precisely why `tasks/4_done/` is the `record` tier. So the check's one true
finding is a finding nobody is allowed to act on.

The shape is also self-limiting in a way the parent task could not know without measuring: 12
of the 17 distinct paths are the repo's own test directories, and those are already covered —
a moved test directory breaks every `python <script>.py` reference and every markdown link to
it, both of which pass 4 and the link pass already read. The argument form adds a third
detector for a failure the first two catch.

**Decision: do not arm it.** Re-open only if a moved test directory is ever shown to have
survived both existing detectors and misled someone — which is the same evidence bar part 2
of this task set for the `.py`-docstring question.

## Part 2 — the docstring decision stands

`_instruction_files()` still enumerates `git ls-files '*.md'` plus the overlay's; no Python
file is read as a reference source. The 2026-07-31 decision ("out of scope, source set stays
`*.md`") is left standing and no evidence of a real miss appeared. No code changed, so the
docstring needs no amendment.

## Gate

```
$ .venv/bin/python automation/gardener/verify_links.py --require-roots --no-overlay   # EXIT=0
  references: 0 broken of 2989 verified · 38 advisory · 125 permitted · 1323 refs NOT verified in this tree
  OK: 2989 references, the skill symlinks and the vendored copies verified.
```
