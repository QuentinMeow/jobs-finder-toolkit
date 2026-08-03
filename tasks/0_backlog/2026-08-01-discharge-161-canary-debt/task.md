# Discharge PR #161's undischarged `behavioral-interview-prep` canary gate

- **Priority**: P1 (this round)
- **Area**: benchmarks
- **Source**: PR #161 (`feat/27-answer-bank-render-target`), merged as part of the 46-PR stack;
  gate defined in `evals/README.md` ("The eval-gated-merge rule (risk-based)")
- **Claimed-by**:

## Goal

Run and record the `behavioral-interview-prep` canary set against the tree PR #161 shipped, so
the skill's eval-gated-merge obligation is discharged instead of silently owed. Do **not** run the
canaries as part of filing this task — that is deliberately left for whoever claims it, since it
costs real tokens/time and this is a paperwork gap, not an emergency.

## Context

PR #161 (branch `feat/27-answer-bank-render-target`) edits
`skills/behavioral-interview-prep/SKILL.md` (commit `ac34371`, "Route a company-prefixed answer to
the company folder"):

```
-**Known gap, do not paper over it:** `answer_bank.py --render` still writes every output beside
-its source's parent, i.e. back into `question-bank/<slug>.md`. So a rendered company answer lands
-in the wrong tree today and must be moved to the company's `derived/` folder afterwards. ...
+`answer_bank.py render` files each alias in its own tree: `_general_*` beside the source's parent,
+a company-prefixed alias in `config.companies_root()/<key>/derived/`. The company folder must
+already exist — a missing one is a FAIL naming the key, never an invented folder. Nothing moves
+after a render.
```

This is not a wording fix — it changes what the generator does and where files land, i.e. it
**"changes step semantics ... or deliverables"**, one of `evals/README.md`'s explicit **MUST run**
triggers for the risk-based eval gate (the other listed triggers — gate/guardrail changes,
file-tier restructuring, >~20 changed instruction lines — don't apply here; this one does, on its
own). The PR's own commit message says nothing about the eval gate, and no
`Eval gate: skipped — <rationale>` line exists in the branch history I could find. The most recent
recorded run for this skill, `evals/results/behavioral-interview-prep-70d79c6e812e-2026-07-23.md`,
predates the branch (2026-07-23) and does not cover this change.

**This is the other half of an already-filed task.** `tasks/4_done/2026-07-31-answer-bank-renders-company-answers-into-the-question-bank/task.md`
describes the exact same generator fix and lists its own last Definition-of-done bullet as:
*"Canaries for `behavioral-interview-prep` run and are recorded (`evals/README.md`) — this is a
behavioural edit, and it also covers the path corrections that skipped ahead of it."* Every other
bullet in that task's Definition of done already appears implemented in PR #161's diff (the
routing change, the "Known gap" paragraph removed, the `§ File Location` caveat removed). Only the
canary-run bullet is unchecked and unrecorded. Whoever claims either task should check the other —
running the canaries here likely closes that task's last open item too, but this task is scoped
to the canary run only; it does not re-verify the code change itself.

**One thing to flag, not fix**: commit `ac34371`'s message says *"DO NOT MERGE until
examples-reshape-seven-calls.md D5 is answered ... D5's default path is that the piece is
dropped."* That D5 question is already tracked in
`tasks/0_backlog/2026-08-01-post-merge-decision-triage/task.md` (row 13,
`examples-reshape-seven-calls.md`). This task does not duplicate it — it is only about the canary
debt.

## What is owed

One recorded canary run for `evals/canaries/behavioral-interview-prep.yaml` (5 canaries: `bp-story-bank-file`, `bp-story-revision-credibility`, `bp-story-to-question-mapping`,
`bp-tell-me-about-yourself`, `bp-company-principles`) against the branch/SHA that carries PR
#161's change, filed in `evals/results/`.

## Exact command to discharge it

There is no single automated "run all canaries" script in this repo — `evals/README.md`'s method
(b) (manual in Claude Code) is what applies here, since no skill-creator harness run has been
recorded for this skill either. Per `evals/README.md` § "How to run a canary":

1. Confirm the SHA under test (the commit that lands PR #161's `SKILL.md`/`answer_bank.py` change
   on the branch that will actually ship — re-derive it at claim time, since the stack merge may
   have re-written it).
2. For each of the 5 canary ids in `evals/canaries/behavioral-interview-prep.yaml`: open a fresh
   session, apply the canary's `setup` (examples-fallback config unless the canary is marked
   `requires_overlay: true`), paste its `prompt` verbatim, and judge the transcript against its
   `expected_behavior` using the shared discipline in `evals/rubrics/judging.md`.
3. Pull efficiency numbers for the run's SHA:
   ```
   .venv/bin/python automation/metrics/report.py --by-sha
   ```
4. Every canary's `rubric_pass` must hold, and no efficiency metric may show a large regression
   (`evals/README.md` § "The eval-gated-merge rule").

## Where the run must be recorded

Copy `evals/results/TEMPLATE.md` to
`evals/results/behavioral-interview-prep-<12-char-sha>-<YYYY-MM-DD>.md` and fill it: skill,
canary set path, run kind = "regression pre-merge" (it is being run after the fact, against
already-merged code — say so in the Notes/Verdict rather than mis-labeling it a baseline), the
SHA, model version, config mode, date, judge, the per-canary `rubric_pass`/efficiency table, pass
rate, and a PASS/FAIL verdict. If any canary fails, the finding routes back to
`tasks/4_done/2026-07-31-answer-bank-renders-company-answers-into-the-question-bank/task.md`
(reopen/amend it) rather than being fixed inline here — this task's scope is discharging the
measurement, not the code.

## Definition of done

- [ ] All 5 `behavioral-interview-prep` canaries run against the PR #161 SHA and judged per
      `evals/rubrics/judging.md`.
- [ ] Efficiency numbers pulled via `automation/metrics/report.py --by-sha` for that SHA.
- [ ] Result filed at `evals/results/behavioral-interview-prep-<sha>-<date>.md` from
      `evals/results/TEMPLATE.md`, verdict recorded.
- [ ] If PASS: note it against `tasks/4_done/2026-07-31-answer-bank-renders-company-answers-into-the-question-bank/task.md`'s
      last Definition-of-done bullet. If FAIL: file the regression against that same task rather
      than opening a new one.
