<!--
Per-machine result (network/board state + local model dependent). Per-SHA token metrics from
`automation/metrics/report.py --by-sha` are NOT available for this run — the canaries ran as fresh
top-level sessions in separate detached checkouts, whose usage the metrics hook does not write to
this checkout's metrics log. Efficiency below is the harness's own per-session telemetry, supplied
with the runs, not self-reported by the runs.
Employer names are redacted to `<company>` — the results tree is public.
-->
# Eval result — job-search

| Field | Value |
|-------|-------|
| Skill | `job-search` |
| Canary set | `evals/canaries/job-search.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `70a620f32968` ("Give the ATS-API JD path a digest mode") — **not resolvable from merged history; see the provenance note below.** |
| Model version | `claude-opus-5` — the five runs and this judgement |
| Config mode | examples fallback (`config.yaml` unset → `config.example.yaml`, fictional persona, `example` profile) |
| Date | `2026-07-31` |
| Judge | judge subagent (`claude-opus-5`), per `evals/rubrics/judging.md` — every `expected_behavior` bullet an independent pass/fail check, all must hold, a listed `failure_mode` = automatic fail |

## Commit-pin provenance — added 2026-07-31, read before citing this record

**`70a620f32968` is not an ancestor of the merged history.** It exists only on the
pre-rebase branch `wip/07-company-roles-jd-digest`; `git branch -a --contains 70a620f32968`
names that branch and nothing else, and `git merge-base --is-ancestor 70a620f32968 HEAD`
is false at the stack tip `40871e6`. The landed equivalent is **`1e4b7c1`** (same title,
PR #152), which sits *later* in the stack than this record. This file's name retains the
pre-rebase SHA; it has not been renamed, so that the record keeps a stable identity.

**The runs do not bound the merged skill surface, and this is not a bookkeeping detail.**
`git diff --stat 70a620f32968 1e4b7c1 -- skills/job-search/{SKILL,LESSONS,reference}.md`
gives 3 files, **88 changed lines** (SKILL.md 39, reference.md 38, LESSONS.md 11) — the
instruction files these canaries actually route on. Anyone treating this as a gate at head
needs a re-run; treat it as evidence about `70a620f32968`'s behaviour only.

What *is* verified: the two downstream fixes this record credits are both in merged
history and are both ancestors of the tip — `9778181` ("Stop printing 'no' for a location
verdict that said 'review'") and `c055e3b` ("Point one company's registry entry at the
board that exists"). The rubric-provenance claim below also holds: `9778181` is the only
commit between `70a620f32968` and the tip that touches `evals/canaries/job-search.yaml`,
and it changes it by +4/−1.

### Update — 2026-08-01, after the stack merged into `main`

The note above was written at stack tip `40871e6`, which is now an ancestor of `main`
(`a4e5b3d`). Re-verified against merged history; three things changed, one of them
material.

**1. The commit is no longer local-only.** `70a620f32968` is still **not** an ancestor
of `main` — that part stands. But when the stack merged, every feature branch was
removed from the remote, and this record's only evidence survived on a single
unpushed local branch. It has been pushed and now exists at
**`origin/wip/07-company-roles-jd-digest`**. Before that push, one `git branch -D` or
one lost clone would have made this record permanently uncheckable.

**2. The landed equivalent is confirmed in `main`.** `git merge-base --is-ancestor`
now returns true for `1e4b7c1` (the landed equivalent, PR #152), `9778181` and
`c055e3b` (the two downstream fixes this record credits). Every claim in the note
above holds post-merge.

**3. The drift this record warns about has more than doubled.** Recomputed against
merged `main`:

```
git diff --stat 70a620f32968 main -- skills/job-search/{SKILL,LESSONS,reference}.md
  3 files changed, 193 insertions(+), 52 deletions(-)
```

**245 changed lines**, against the **88** measured when the note was written. These are
the instruction files the canaries route on. The note's conclusion — *treat this as
evidence about `70a620f32968`'s behaviour only, not as a gate at head* — is now
substantially stronger than when it was written, not weaker. A re-run at a commit that
is actually in `main` is filed as
`tasks/0_backlog/2026-08-01-re-run-job-search-canaries-at-a-merged-commit/`.

## Method

Five live runs, one per canary, each a **fresh session with a clean context** in its own detached
checkout at `70a620f32968`. Each was given the canary's verbatim user prompt and the repo — **not**
the rubric — so routing and behaviour were genuinely under test. Network live (Stage 1, keyless).
Each wrote a run record; the records are session scratch, not tracked.

The judge did not perform the runs. Where a record asserts something a bullet checks, the assertion
was corroborated against surviving artifacts or the source at the tested SHA (see **Evidence
discipline**).

## Rubric provenance — read before reading the table

`evals/canaries/job-search.yaml` was **strengthened after the tested SHA**. Commit `9778181`
("Stop printing 'no' for a location verdict that said 'review'"), downstream in this same stack,
rewrote `js-single-company-location-verdict`: bullet 2 went from "`--match-only` shows only
policy-matching roles" to "…drops definite non-matches and KEEPS review rows", a new REVIEW-honesty
bullet was added, and two failure modes were appended. Canaries 1–4 are byte-identical at both SHAs.

Scoring below uses the bullets **in force at `70a620f32968`**, because scoring a run against a spec
written after it — describing a fix made after it, prompted by it — measures nothing. The post-fix
reading of canary 5 is reported alongside, since that is the reading the next runner will use.

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `js-core-shortlist` | 1 | 126,422 | 1,224 | 29 | All 5 bullets hold, artifact-verified. Ran `search_jobs.py --profile example` (11,637 fetched → 40 kept); discoveries file written to the configured dir with every required field per row; chat claims trace to artifact rows; handed off to resume-writer without tailoring. |
| `js-visa-require-positive` | 1 | 144,463 | 2,097 | 66 | All 4 bullets hold. `require_positive` applied (artifact header confirms; 55 rows, all `yes`), warned the filter is brutal, refused to widen, labels stated advisory. **Caveat:** relayed an unverified "≈477 explicit denials" census to the user — see Defect F. Highest tool-call count; ~10 min burned on a cancelled comparison run + 3 dead background tasks (self-reported). |
| `js-mts-not-staff` | 1 | 165,119 | 1,512 | 57 | All 3 bullets hold, artifact-verified: MTS kept at rank 18 as `senior (L5.0-L5.8)`, **zero** staff-band rows in 40, and the word-vs-rung distinction explained with the cost disclosed (39 dual-level reqs dropped, offered back). Highest token count; one unrequested extra refilter sweep against `token_saving`'s "no unprompted extra sweeps". |
| `js-recency-vs-research-window` | **0** | 113,712 | 752 | 33 | **FAIL — bullet 3.** Filter correctly applied and no window conflation, but the answer never tells the user posting-age filtering is off by default. Detail below. |
| `js-single-company-location-verdict` | 1 | 125,218 | 577 | 28 | All 4 bullets in force at this SHA hold; no failure mode observed. Under the **post-fix** rubric the run's own behaviour still meets every behavioural bullet — only the tooling clause fails, and that is Defect C, fixed downstream by `9778181`. Cheapest run of the five and the one that exercised the diff under test. |

Pass rate: `4/5`.

## The one failure, in full

**`js-recency-vs-research-window`, bullet 3:** *"Notes that posting age is off by default and this
run is the explicit 'last N days' case."*

The second conjunct holds — the answer says *"you asked for 3 days explicitly"*. The first does not
appear anywhere in the delivered answer. The run read the profile (which ships `max_age_days: null`)
and its own generated report header reads `Filters: posting age ≤ 3.0 days`, but the user is never
told that a normal search applies **no** age filter and that this window is opt-in. Grepping the
record for `default` / `max_age` / `opt-in` returns only command text and an unrelated
decision-file "default path". By contrast `js-mts-not-staff`, which had no such bullet, volunteered
exactly the missing sentence: *"The example profile has no posting-age filter, so this is every
currently-open matching role."*

Bullets 1 and 2 of that canary hold and are verified: the artifact header records the applied
window, all 30 rows are ≤ 2.8 d, and nothing in the run confuses posting age with the 7-day
company re-search window. Neither listed failure mode occurred. Per the rubric's no-partial-credit
rule, one missed conjunct is a fail.

This is a communication miss, not a filtering miss, and it is **orthogonal to the diff under
test** — the branch changes the `company_roles.py --jd` digest path, not the recency path or any
text describing it.

## Verdict

- **Regression:** FAIL on `js-recency-vs-research-window` (bullet 3), PASS on the other four.
  **Not merge-blocking for this diff.** The failing check is unrelated to the change under test;
  the change's own surface was exercised by `js-single-company-location-verdict`, where the digest
  produced the `Available Locations:` line that caught a tooling false positive the run would
  otherwise have relayed. The fail is real and should be closed (a one-line prompt in
  `skills/job-search/SKILL.md` or `LESSONS.md` stating that posting age is opt-in, then a re-run of
  that canary alone) — it should not be waved through as a near-miss.
- **Efficiency:** no evidence of a regression caused by this branch; the numbers are not
  like-for-like against the last agent baseline. See below.

## Efficiency vs baseline

Nearest prior agent baseline is `evals/results/job-search-5732ec0499a6-20260721-jd-digest.md`
(2026-07-21, `claude-sonnet-5`, canaries run as **subagents**).

| Canary id | tokens now / baseline | tool_calls now / baseline | wall_clock_s now / baseline |
|-----------|----------------------|---------------------------|-----------------------------|
| `js-core-shortlist` | 126,422 / ~62,728 | 29 / 10 | 1,224 / ~144 |
| `js-visa-require-positive` | 144,463 / ~75,617 | 66 / 18 | 2,097 / ~164 |
| `js-mts-not-staff` | 165,119 / ~84,559 | 57 / 30 | 1,512 / ~348 |
| `js-recency-vs-research-window` | 113,712 / ~54,466 | 33 / 9 | 752 / ~105 |
| `js-single-company-location-verdict` | 125,218 / ~57,974 | 28 / 15 | 577 / ~157 |

Median ≈ 2.0× tokens, 2.9× tool calls, 7.2× wall clock. **Do not read that as a blow-up.** Three
things changed at once: the model (sonnet → opus 5), the harness (subagent telemetry → full
top-level sessions that read the whole contract, ran the boot ritual, and wrote a long run record —
all eval overhead the baseline never paid), and the depth (several runs did unrequested verification
passes over full JD bodies). A token comparison across that is uninterpretable, and no conclusion
about the skill's cost is drawn from it. A future gate on this skill needs a matched protocol.

What **is** attributable, from the runs' own disclosures: `js-visa-require-positive` burned ~10 min
of wall clock on a comparison run it then cancelled plus three dead background tasks;
`js-mts-not-staff` ran an extra unrequested refilter sweep; `js-single-company-location-verdict`
fetched one company's board seven times before caching, against the skill's "respect the sources"
guardrail. Roughly a quarter of the two most expensive runs is self-inflicted.

## Environmental degradation — recorded, not scored

Every one of the five runs hit the same dead board: a registered company's Greenhouse endpoint
returning **HTTP 404**, 1 source error out of 109 tasks, that company contributing zero postings.
This is a **data-source defect, not the skill failing its rubric**, and it is already fixed
downstream in this stack by `c055e3b` ("Point one company's registry entry at the board that
exists"), which repoints the row from `greenhouse` to `ashby`. No canary result was changed by it,
and every run named it to the user rather than rounding "1 source error" to nothing. No rate
limiting, no empty responses, no throttling was observed in any run.

## Defects the runs surfaced

Worth as much as the pass/fail verdict — this is what the run bought.

- **A. Registered board returns 404** (all five runs). Stale ATS token in
  `skills/job-search/companies.yaml`. Fixed downstream by `c055e3b`.
- **B. Sponsorship classifier inverts explicit denials** (`js-visa-require-positive`). Under
  `--visa-policy require_positive`, negated sentences score as explicit **offers**. Reproduced
  independently by the judge against `automation/shared/job_metadata.py`: *"We do not currently
  offer visa sponsorship for this role"*, *"We are not able to offer visa sponsorship…"* and
  *"no H1-B visa sponsorship available"* each return `likely` / `decision=match` /
  `confidence=high`. Market-wide the run put it at ~28 of 430 `likely` labels. The delivered
  shortlist was unaffected (the run hand-checked its positives). The run escalated the existing
  known-issue and filed a task.
- **C. Location verdict prints `review` as a confident `no`** (`js-single-company-location-verdict`).
  Confirmed in the source at the tested SHA: `shown = [r for r in rows if r["match"]] if
  args.match_only else rows` drops review rows entirely under `--match-only`, and
  `flag = "MATCH" if r["match"] else "no   "` renders the ones that survive as rejections; `--json`
  omits `decision`/`workplace`/`review_reasons`. On the canary's company that hid 225 undecidable
  rows. Fixed downstream by `9778181`, which also strengthened this canary.
- **D. Salary parsed as a three-digit low against a six-digit high** (`js-mts-not-staff`): one
  posting yields `{'min': 240, 'max': 175000, 'confidence': 'high'}`. A `high` confidence on that
  shape would propagate into `meta.yaml` at handoff. Related, from `js-core-shortlist`: three rows
  reported salary `?` while the JD body plainly stated a band — an extractor gap, not a guess, and
  the run recovered the bands by reading the JDs and labelled their provenance.
- **E. Two filter-variant shapes with no deterministic label.** `validate_filter_variants.py` exits
  **1** on the same two signatures in all four search runs — an ambiguous `…, Ads Manager`
  product-suffix title and a run-together `USCA` location string. Both route to `review` rather than
  being silently dropped, and neither reached any shortlist, so no result is affected; but the
  mandatory gate is red for every user until the shapes are labelled and a corpus regression added.
- **F. (New, judge-verified) Export-control boilerplate reads as an explicit sponsorship denial.**
  Not reported by any run. `js-visa-require-positive` relayed "≈477 postings explicitly deny
  sponsorship, one `<company>` accounting for 285 of them" without checking a single one.
  `js-single-company-location-verdict` independently saved five JDs from that same company; the only
  sponsorship-adjacent sentence in any of them is *"…without sponsorship for an export license"* —
  an export-control clause, not an immigration statement. Judge probe against
  `automation/shared/job_metadata.py`: that sentence returns `unlikely` / `decision=no_match` /
  `confidence=high`, i.e. an explicit denial. The literal phrase LESSONS names ("must be authorized
  to work in the United States") is handled correctly (`unknown` / `review`), which is why
  `js-visa-require-positive` still passes its bullet 2 — but the classifier has a second, opposite
  failure to B, and one company's entire board is mislabelled by it. Under `require_positive` this
  changes no result (denials and unknowns are both dropped); under the default `exclude_negative`
  it would drop that company's whole board.

## Cross-run observations

- **All four runs that ran the filter-variant gate misread its exit code the same way** — piping to
  `tail` and reading `$?` as the script's status, printing a reassuring `EXIT=0` for a gate that
  exits 1. All four caught it and re-ran; every one flagged it in its own record. Four for four is
  a pattern, not four accidents, and the near-miss is that a silent gate would have been reported
  as passing.
- **The same red gate was handled four different ways**: one filed a retry item, one filed a backlog
  task, one filed nothing and recorded it only in an uncommitted handover, one filed the unrelated
  sponsorship defect instead. Nothing in the skill says what to do when a mandatory gate is red but
  the finding is out of scope for the user's question.
- **Honesty was consistently good.** Every record volunteered its own mistakes, its judgement calls
  against the letter of the contract, and the limits of its verification. Two runs disclosed that
  they nearly shipped a wrong claim. Per the rubric that honesty is neither credit nor debit — it is
  what made this judgement possible at all, since the unflattering parts were checkable.
- One run reports that its first handover draft named employers and live postings in a tracked
  `history/` file, that both the leak guard and the review gate reported clean on it (the guard
  scans tracked files; the company detector needs an overlay index that is absent in a public-only
  checkout), and that it rewrote the file by hand. Outside this canary set's rubric, worth a look.

## Evidence discipline — what the judge verified independently

Corroborated, not taken on the records' word: the discoveries artifacts of runs 1–4 survive and were
read directly (row counts 40 / 55 / 40 / 30; the header's `Filters:` line; the full column set
`# | Score | Company | Title | Level (Google eq.) | YOE | Salary | Loc/Remote | Age | Visa | Source |
Why | Link`; `?` used for unstated facts; the MTS row present and level-tagged `senior`; zero
staff-band rows; all 55 `require_positive` rows labelled `yes`); the chat claims of run 1 were traced
back to specific artifact rows; run 5's saved JDs were read for the `Available Locations:` lines
behind its false-positive and false-negative findings; the `company_roles.py` behaviour and the
canary file's own history were read at the tested SHA via `git show`; and Defects B and F were
reproduced against `automation/shared/job_metadata.py` in this worktree.

Not verifiable and therefore not credited as fact: the market-wide census numbers in run 2 (11,638
postings, 430/477 label counts) and run 5's recovery statistics over 285 postings — both rest on
one-off probe scripts over a live board that has since moved on. Nothing in the pass/fail table
depends on them. Every canary had enough evidence to judge; none was scored on testimony alone.

## A/B section

Not applicable — run kind is `regression pre-merge`, not A/B. No variants, no paired runs, no
quality comparison, and therefore no significance claim.

### Update — 2026-08-02: the branch is now a tag

`wip/07-company-roles-jd-digest` no longer exists. `70a620f32968` is now held by the annotated tag
**`archive/jd-digest-70a620f`**, local and on `origin`. Nothing about this record's evidence changed —
`git show 70a620f32968` still works, and `git tag --contains 70a620f32968` names that tag — but the
ref is no longer shaped like work in progress, because it never was: it is an archive.

The owner asked for a repository with one long-lived branch. A branch implies something is being
built on it; a tag says "this is kept so it can be read". The two earlier notes above still stand
unchanged, including the warning that this record bounds `70a620f32968`'s behaviour only.

Whether to drop the ref altogether is still open:
`message-queue/needs-human/decisions/delete-the-company-roles-jd-digest-wip-branch.md`. Deleting the
tag would make this record permanently uncheckable, which is exactly what PR #182 was written to
prevent, so nothing here has been decided on the owner's behalf.
