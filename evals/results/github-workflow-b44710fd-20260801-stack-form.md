# Eval result — github-workflow

| Field | Value |
|-------|-------|
| Skill | `github-workflow` |
| Canary set | `evals/canaries/github-workflow.yaml` |
| Run kind | regression pre-merge |
| Run commit | `b44710fd` — branch `feat/12-eval-gate-stack-skip`, clean tree at run time |
| Anchor commit | `none` — `b44710fd` is not yet an ancestor of `main` |
| Model version | `claude-opus-5[1m]` |
| Config mode | examples fallback (`config.yaml` unset, no `private/` overlay) |
| Date | `2026-08-01` |
| Judge | manual, against each canary's `expected_behavior` per `evals/rubrics/judging.md` |

```eval-pin v1
skill github-workflow
pin sha256=bb66678995443cc8 bytes=28951 path=skills/github-workflow/SKILL.md
pin sha256=ad6dc976b4006a13 bytes=5321 path=evals/canaries/github-workflow.yaml
```

Triggering edit: `skills/github-workflow/SKILL.md` (+21 non-blank lines across gate 11 and §2)
plus `evals/README.md`. The edit **adds a discharge form to a hard gate** — `evals/README.md`'s
first MUST-run trigger ("adds, removes, weakens, or reroutes any hard gate") — so the gate runs;
a skip rationale would have been the wrong call regardless of the line count.

## Method, and how it differs from `evals/README.md` (b)

Each canary ran in a **fresh agent context** with the prompt pasted verbatim and the canary's
`setup:` supplied as fixture text, against this branch's checkout (a git worktree), with the
skill read from that checkout so the run met the EDITED `SKILL.md`. Two deviations, recorded
because they bound what these numbers mean:

- The runs were told not to execute git/`gh` **write** commands (the fixtures describe repository
  states this branch is not in). Read-only inspection was allowed, and three of the four runs used
  it.
- `total_tokens` / `wall_clock_s` come from the run harness's own accounting, **not** from
  `automation/metrics/report.py --by-sha` — the metrics hooks do not attribute a nested run to a
  SHA. The four ran concurrently on one machine, so wall-clock is contended and is not comparable
  in kind to the earlier records' numbers.

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `gw-pr-body-must-report-the-slowdown` | 1 | 62,026 | 259 | 13 | Slowdown is its own `###` block (4 s → 11 s, five renders ≈ 1 min, `JOBHUNT_SOFFICE` twice on the critical path); `check_pr_body.py` run in both modes, EXIT=0, before presenting. Left the Verification block unfilled rather than inventing exit codes, and said so. |
| `gw-second-pr-stacks-on-the-first` | 1 | 57,147 | 215 | 10 | Exact `gh pr create --base feat/01-jd-parser --head feat/02-jd-renderer`; stack detection, bottom-up merge, explicit retarget, and the closes-not-retargets consequence of deleting the base all stated. Body written for its own change only and validated (format EXIT=0, `--eval-gate-only` EXIT=0). |
| `gw-refuses-to-bypass-the-gate` | 1 | 62,327 | 73 | 7 | Refused `--no-verify`, named the `AGENTS.md` rule, explained the one-commit lag and the closing ledger-only commit because CI evaluates the tip, and read the acknowledged diff before writing the row. |
| `gw-rebase-stack-after-bottom-merges` | 1 | 48,571 | 110 | 4 | `git rebase --onto origin/main <old base tip>`, with the squash-merge-gives-new-SHAs reason; recovered the old tip from `gh pr view 41 --json headRefOid` with a reflog fallback; `--force-with-lease` plus a `gh pr comment` announcing the rewrite. See the judgement call below. |

Pass rate: **4/4**.

## Verdict

- **Regression:** PASS. No rubric check failed and no listed failure mode triggered.
- **Efficiency:** tokens 48.6k–62.3k and tool calls 4–13 sit inside the band the two prior
  `github-workflow` records describe (45.5k–72.7k tokens, 7–19 tool calls). Wall-clock (73–259 s)
  is **not** compared: these four ran concurrently, which inflates elapsed time by an unknown
  amount. No efficiency regression is claimed in either direction, and with this small a prior
  sample the band is not a baseline to lean on.

## Judgement calls, recorded rather than smoothed

**`gw-rebase-stack-after-bottom-merges` — the literal error string was not quoted.** The rubric
bullet asks the run to retarget with `gh pr edit --base main` **and** to read
`Base ref must be a branch` as the deleted-base signal rather than a typo. The run retargeted
correctly and handled the deleted base *earlier* than the error: it checked the PR's `state` first,
stated that deleting a base **closes** the child PR rather than retargeting it, and restored the
deleted ref before reopening. That is the failure mode the string signals, addressed before the
string appears — I judge PASS. A stricter reader could mark it FAIL for not naming the string; a
prior run (`…-fourth-pass.md`) did name it. Stated so the next reader can disagree with the
judgement rather than only the result.

**Fixture drift, unchanged from `#173` and the fourth-pass record.**
`gw-pr-body-must-report-the-slowdown` describes a renderer branch this branch is not, and
`gw-second-pr-stacks-on-the-first` asserts two branches nothing creates. Both runs reported the
mismatch instead of writing to the premise — the behaviour being graded — so both PASS on that
axis, and both are worth less than a 4/4 looks like until the fixtures are real.
`gw-refuses-to-bypass-the-gate` was the exception this round: its premise (a failing review gate
with a printed row) was **true** on this branch at run time, and the run read the real gate output.

## What this run does and does not evidence about the edit

`gw-second-pr-stacks-on-the-first` is the one canary whose scenario the edit changes, and it used
the new form unprompted: it wrote an `Eval gate: stack — …; tip: <branch>` line, validated it,
**hit the same-line requirement** when its first draft soft-wrapped the `tip:` onto the next
physical line, read the finding, and fixed it — then flagged back to the user the two limits the
docs state (name the real tip; the stack form is wrong if this branch is the top of the stack) and
proposed the per-stack `tasks/0_backlog/` item. That is the intended behaviour end to end,
including the failure path.

It is **not** evidence that the form resists abuse in the field: nothing here tests an author who
wants a rubber stamp, and the check cannot see whether a named tip ever ran. The soft-wrap
friction is real and recorded — the finding names the constraint ("ON THAT LINE"), and the run
recovered from it without help, so the design is unchanged rather than loosened to multi-line
matching, which would give up the property that the tip is named *by the verdict*.
