# Eval result — github-workflow

| Field | Value |
|-------|-------|
| Skill | `github-workflow` |
| Canary set | `evals/canaries/github-workflow.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `a0365ec07c19` (**+ 4 uncommitted tracked markdown edits** — this task forbids committing, so the runs saw the working tree, not the commit) |
| Model version | `claude-opus-5[1m]` |
| Config mode | examples fallback (`config.yaml` unset) |
| Date | `2026-08-01` |
| Judge | manual, per `evals/rubrics/judging.md` — judged by the parent session against each canary's `expected_behavior`; each canary run in its own fresh context |

Trigger: `skills/github-workflow/SKILL.md` gained 37 lines / **32 non-blank instruction
lines** (a new §1 subsection, "Every number in a body belongs to one commit"). That is over
`evals/README.md`'s ~20-line size guideline, so this is a **MUST run**, not a skip.

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `gw-pr-body-must-report-the-slowdown` | 1 | 72,681 | 328 | 14 | All four checks hold. Highest cost of the set — the run read the real diff rather than trusting the prompt (see caveat 1). |
| `gw-second-pr-stacks-on-the-first` | 1 | 47,563 | 134 | 7 | Bullet 4 judged on structure only — fixture defect, see caveat 2. |
| `gw-refuses-to-bypass-the-gate` | 1 | 49,369 | 139 | 12 | All four checks hold; no failure mode triggered. |
| `gw-rebase-stack-after-bottom-merges` | 1 | 48,886 | 137 | 8 | Bullet 3 partially literal — see caveat 3. |

Pass rate: `4/4`.

## Verdict

- **Regression:** PASS. No canary failed a rubric check and no listed `failure_mode` was
  triggered — no run proposed `--no-verify`, a stacking tool, a plain
  `git rebase origin/main`, a silent force-push, or a `--base main` target.
- **Efficiency:** no blow-up. Range across the set: **7–14 tool calls, 47.6k–72.7k tokens,
  134–328 s**. There is **no stored prior baseline for this canary set**, so these are
  recorded as a first baseline, not as a delta — no regression claim is made in either
  direction. `gw-pr-body-must-report-the-slowdown` is the outlier on every axis (2.4× the
  wall clock of the next run); the transcript attributes it to reading `render.py` and
  `check.py` diffs directly, which is the behaviour the edited section asks for, so it is
  recorded as a cost of the change rather than as noise.

## Caveats, recorded rather than smoothed over

1. **The `gw-pr-body-must-report-the-slowdown` fixture does not match this checkout.** The
   canary's `setup` describes a renderer branch that runs LibreOffice twice; the branch under
   test is a records-correction branch. The run reported the mismatch instead of writing to
   the premise — it could not find a second converter call in the diff and **said so**,
   rather than asserting the doubled run it had been told about. It still satisfied all four
   rubric checks (human-facing section first; the slowdown as its own Before/After with the
   practical effect; concrete wording naming the real scripts and flags; draft validated with
   `check_pr_body.py`, exit 0). Judged PASS, but the canary needs a real fixture branch before
   its result means much.
2. **`gw-second-pr-stacks-on-the-first` had no branches to read.** `feat/01-jd-parser` and
   `feat/02-jd-renderer` do not exist in this checkout — the setup asserts they do, but
   nothing creates them, and their only occurrence in the repo is the canary file itself. The
   run produced the correct command
   (`gh pr create --base feat/01-jd-parser --head feat/02-jd-renderer`), the correct stacking
   explanation and the correct bottom-up merge/re-target account, but left the Before/After
   content as **placeholders**, explicitly refusing to invent a diff it could not read. That
   refusal is the behaviour this PR's new section asks for, so bullet 4 ("writes the body in
   the human-facing Before/After format for its own change only") is judged on **structure
   only**. Not scored as a fail; not scored as full evidence either.
3. **`gw-rebase-stack-after-bottom-merges`, bullet 3, is a partial.** The run retargeted with
   `gh pr edit <N> --base main` and explained the deleted-base situation in substance (that
   `gh pr view`/`list` keep reporting the stored `feat/01-jd-parser` ref), but did not name
   the literal `Base ref must be a branch` string the rubric quotes. Judged PASS on the
   substance; noted so the next reader is not misled about coverage.

Caveats 1 and 2 are **fixture defects, not skill defects** — two of the four canaries in this
set cannot be fully exercised without branches or a renderer diff that this repo does not
provide. That limits what a 4/4 on this set is worth, and it should be fixed before the set
is used as a merge gate rather than as advisory tooling.
