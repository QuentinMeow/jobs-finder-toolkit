# Verification — 2026-07-31-piping-a-gate-to-tail-hides-its-exit-code

All commands run on branch `wip/34-gate-exit-code-discipline` in a config-less
worktree, `zsh` 5.9, interpreter `<repo>/.venv/bin/python`. `<scratch>` is a
gitignored scratchpad path.

## 1. The defect, reproduced on a real gate

`automation/publish/check_public.py` is a mandatory gate that exits **2** in a
config-less checkout (unarmed — it refuses to certify a tree it cannot screen).
Four readings of the same run:

```
$ echo "shell = $0 ; ZSH_VERSION=${ZSH_VERSION:-<unset>}"
shell = /bin/zsh ; ZSH_VERSION=5.9

--- A. the gate, run bare (ground truth) ---
$ .venv/bin/python automation/publish/check_public.py >/dev/null 2>&1
$ echo "EXIT=$?"
EXIT=2

--- B. the mistake: piped to tail, $? read after ---
$ .venv/bin/python automation/publish/check_public.py 2>&1 | tail -3
  * export JOBHUNT_PERSONAL_TOKENS='<token>[,<token>...]' (how the exporter and CI forward it);
  * point $JOBHUNT_CONFIG at that config.yaml.
Or run the token-independent checks knowingly with --allow-unarmed.
$ echo "EXIT=$?"
EXIT=0

--- C. the bash idiom typed in zsh ---
$ .venv/bin/python automation/publish/check_public.py 2>&1 | tail -3 >/dev/null
$ echo "PIPESTATUS[0]='${PIPESTATUS[0]}'  pipestatus[1]='${pipestatus[1]}'"
PIPESTATUS[0]=''  pipestatus[1]='2'

--- D. the convention: redirect, do not pipe ---
$ .venv/bin/python automation/publish/check_public.py > <scratch>/gate.log 2>&1
$ echo "EXIT=$?"
EXIT=2
$ tail -3 <scratch>/gate.log
  * export JOBHUNT_PERSONAL_TOKENS='<token>[,<token>...]' (how the exporter and CI forward it);
  * point $JOBHUNT_CONFIG at that config.yaml.
Or run the token-independent checks knowingly with --allow-unarmed.
```

**B is the seven-of-nine failure**: a gate that exited 2 reports `EXIT=0`. **C is the
second trap**: the bash spelling expands to the empty string in zsh — not to a
warning, to *nothing*, which reads as "no problem". **D is the convention**: a
redirect is not a pipeline, so the truncated read and the true status come together.

An unplanned instance of the same bug occurred in this session's own first command:
`.venv/bin/python automation/metrics/instruction_budget.py --strict 2>&1 | tail -40`
printed `BUDGET_EXIT=0` in a worktree that has **no `.venv` at all** — the shell's
"no such file or directory" was masked by `tail`'s success.

## 2. Sweep — gate vs display

```
$ grep -rnE '\|[[:space:]]*(tail|head|grep)' skills/ automation/ docs/ CONTRIBUTING.md \
    | grep -v '_vendor/' | sort | cat -n
     1	automation/hooks/overlay-pre-commit:102:elif [ -f "$toolkit_recon" ] && "$PY" "$toolkit_recon" --help 2>/dev/null | grep -q -- '--root'; then
     2	automation/hooks/overlay-pre-commit:144:            | grep -E "^${store_re}/[^/]+/(raw|derived|state)/" || true)"
     3	automation/hooks/overlay-pre-commit:151:            printf '%s\n' "$tracked" | grep -qxF "$p" && continue
     4	automation/hooks/overlay-pre-commit:185:n_files="$(printf '%s\n' "$staged" | grep -c . || true)"
     5	automation/hooks/overlay-pre-commit:187:    | awk '{print $4}' | grep -Ev '^0+$' \
     6	automation/hooks/overlay-pre-commit:200:    die "    git diff --cached --stat | tail -1"
     7	automation/hooks/pre-commit:31:staged_private="$(git diff --cached --name-only --diff-filter=ACMRT | grep '^private/' || true)"
     8	docs/handbook/application-folders.md:17:| `applications/6_drafted/` | tailored, awaiting the user's review/decision | created here by the resume-writer skill |
     9	skills/company-research/reference.md:48:  | grep -o -i -E ".{140}$STAGE.{140}" | grep -v -E "$NAV"
    10	skills/company-research/reference.md:54:curl -s -L -A "Mozilla/5.0" "<docs-overview-url>" | .venv/bin/python -c "$STRIP" | grep -o -i -E ".{140}(beta|preview|early access|experimental|generally available).{140}"
    11	skills/company-research/reference.md:61:curl -s -L "<docs-root>/llms-full.txt" | tr '\n' ' ' | grep -o -i -E ".{140}(beta|preview|generally available).{140}" | head
    12	skills/job-search/reference.md:47:curl -s "https://boards-api.greenhouse.io/v1/boards/<guess>/jobs" | head -c 200
    13	skills/job-search/reference.md:48:curl -s "https://api.ashbyhq.com/posting-api/job-board/<guess>"    | head -c 200
    14	skills/job-search/scripts/build_postings.py:748:   tail -n +2 {data_root}/{DOMAIN}/index/postings.jsonl | grep -i '"company":"<name>"'
```

**14 hits. 0 gates. 14 display / probe / false positive — all left unchanged.**

| # | Verdict | Why |
|---|---------|-----|
| 1 | probe, correct | A capability test (`--help` mentions `--root`?). `grep`'s status **is** the intended answer; the gate itself runs unpiped on the next line. |
| 2, 4, 5, 7 | display | Text extraction ending in `\|\| true` — the status is deliberately discarded, and the value flows to a later `if`. |
| 3 | display | A membership test inside a loop; `grep`'s own status is the question. |
| 6 | display | A string inside a `die` message — advice printed for a human, never executed. |
| 8 | false positive | A markdown table row. The `\|` is a column separator and "tailored" contains "tail". |
| 9–13 | display | Web probes (`curl … \| grep`, `curl … \| head -c 200`) whose exit status is meaningless. |
| 14 | display | A hint string printed by `build_postings.py` for a human to paste. |

The before/after diff on gate invocations is therefore **empty**: nothing in the
tracked tree needed changing. Widening the sweep confirms it:

```
$ grep -rnE '\|[[:space:]]*(tail|head|grep|tee|wc|sed|awk)' .github/
(no output — the authoritative CI gate list contains no pipe of any kind)

$ grep -n '^set \|set -' automation/hooks/*
automation/hooks/pre-push:33:set -e
automation/hooks/overlay-pre-commit:37:set -e
automation/hooks/overlay-pre-push:29:set -e
automation/hooks/pre-commit:24:set -e

$ grep -n '"\$PY" automation' automation/hooks/pre-commit
86:"$PY" automation/publish/check_public.py --staged --allow-unarmed
99:"$PY" automation/publish/review_gate.py
102:"$PY" automation/vendoring/sync_vendored.py --check
105:"$PY" automation/shared/mail/check_mail_safety.py \
118:"$PY" automation/metrics/instruction_budget.py --strict
129:    "$PY" automation/reconcile/reconcile.py --check --require-roots
132:    "$PY" automation/reconcile/reconcile.py --check
153:    "$PY" automation/gardener/verify_links.py --require-roots --no-overlay
156:    "$PY" automation/gardener/verify_links.py
```

Every hook gate is invoked bare under `set -e`. This matters for the choice of
convention: the hooks are `#!/bin/sh`, where `set -o pipefail` is **not** portable,
so a repo-wide `pipefail` rule could not have covered them anyway.

## 3. Enforcement — measured, then declined

The idea was a `verify_links.py` rule flagging a documented command that is not the
last stage of a pipeline. Measured with the checker's own fence reader and invocation
parser (`_iter_fences` / `_logical_lines` / `_parse_invocation`), so the count is what
the rule would really see:

```
$ .venv/bin/python <scratch>/probe_piped_cmds.py
python invocations found in shell fences: 342
NON-FINAL pipeline segments (a piped command): 9

[reference] skills/email-assistant/SKILL.md:159
            … status.py --update-job <slug> "<role-match>" <applied|in_progress|rejected>
[reference] skills/email-assistant/SKILL.md:162
            … status.py --update <slug> <applied|in_progress|rejected>
[reference] skills/job-search/reference.md:76
            … company_roles.py --company <Name> --ats <greenhouse|ashby|lever|smartrecruiters>
[plan     ] tasks/0_backlog/2026-07-31-piping-a-gate-to-tail-hides-its-exit-code/task.md:22
            .venv/bin/python …/validate_filter_variants.py ... | tail -5
[plan     ] tasks/3_in-review/…-four-gates-that-inspected-nothing/verification.md:107
            $ … verify_links.py --no-overlay --list-unrecognised | sed -n '/unrecognised-roo…
[plan     ] tasks/3_in-review/…-instruction-surface-matches-code/verification.md:35
            $ … gardener.py --help | sed -n '10,20p'
[plan     ] tasks/3_in-review/…-instruction-surface-matches-code/verification.md:92
            $ … gardener.py skill-drift --apply | head -1
[plan     ] tasks/3_in-review/…-instruction-surface-matches-code/verification.md:227
            $ … instruction_budget.py --strict | grep -E 'AGENTS.md|github-workflow|…'
[plan     ] tasks/3_in-review/…-job-metadata-company-key-helper-collides/verification.md:87
            .venv/bin/python <scratchpad>/level_corpus.py $f | tail -1; done
```

Nine hits, **zero of them the defect**:

- The three **REFERENCE-tier** hits — the tier where a finding hard-fails the
  pre-commit hook — are all false positives. The `|` is inside a placeholder
  (`<applied|in_progress|rejected>`), not a pipe. A gate whose only hard-failing
  findings are false is a nuisance gate, and `verify_links.py`'s own docstring says
  why that is fatal: *"a checker that cries wolf gets switched off — after which it
  protects nothing."*
- Five are legitimate display pipes (`--help | sed`, `--apply | head -1`,
  `--strict | grep`) in dated records, where a finding is advisory anyway.
- The ninth is this task file quoting the bug it exists to report.

Distinguishing display from gate needs a gate registry the repo does not have.
Decisive point: **the checker reads tracked markdown; the defect lives in ad-hoc
shell an agent types into a tool call**, which no tracked-file checker can see. Not
built, and no follow-up task filed — a task to build a checker already measured as a
nuisance would be noise.

## 4. Gates on this branch

Run with everything staged (`git add -A`), so the new files are tracked and therefore
actually inspected — an unstaged run reads the old file set and proves less.

```
$ .venv/bin/python automation/gardener/verify_links.py --require-roots --no-overlay
  references: 0 broken of 2620 verified · 42 advisory · 108 permitted · 1212 refs NOT verified in this tree (classes above)
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync

  OK: 2620 references, the skill symlinks and the vendored copies verified.
$ echo "EXIT=$?"
EXIT=0
```

2598 verified on the branch point, 2620 with this change staged: the new backticked
paths in `AGENTS.md` and the ~20 commands quoted in this file are all checked, and the
fenced-command pass still parses every one of them (0 broken).

```
$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (10 checks clean)
$ echo "EXIT=$?"
EXIT=0
```

Intermediate state, kept as evidence the reconciler really inspects this task: with
the folder moved to `3_in-review/` but before `verification.md` existed, the same
command returned

```
reconcile: 1 finding(s)
  [task-structure] tasks/3_in-review/2026-07-31-piping-a-gate-to-tail-hides-its-exit-code: 3_in-review requires verification.md (real command output)
$ echo "EXIT=$?"
EXIT=1
```

```
$ .venv/bin/python automation/metrics/instruction_budget.py --strict
FILE                                           LINES  BYTES  ~TOKENS     BUDGET  STATUS
AGENTS.md                                        335  26850     6712        500      ok
…
OK: all instruction files within budget.
$ echo "EXIT=$?"
EXIT=0
```

`AGENTS.md` 318 → 335 lines (+17), 500-line budget, 165 lines of headroom. The two
NEAR-budget files (`skills/company-research/SKILL.md`, `skills/job-search/LESSONS.md`)
are unchanged by this branch — no skill file was touched.

## 5. Eval gate

Not triggered: `evals/README.md` scopes the risk-based canary gate to
`skills/<skill>/{SKILL.md,LESSONS.md,reference.md}`, and this branch changes none of
them. The only instruction file touched is `AGENTS.md`, plus this task's own files.

That is a consequence of the routing decision, not the reason for it: the rule was put
in `AGENTS.md` because the defect appeared across two skills' runs and `AGENTS.md`'s
own Folder-Scoped Context section reserves hard invariants for the contract. A
job-search-specific pointer *would* have been a gate reroute and would have required a
canary run; it was rejected on the merits, and the saving is disclosed here rather
than left implicit.
