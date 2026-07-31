# Eval result — company-research

| Field | Value |
|-------|-------|
| Skill | `company-research` |
| Canary set | `evals/canaries/company-research.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `48f9b46a366e` |
| Model version | `claude-opus-5` |
| Config mode | examples fallback — `JOBHUNT_CONFIG` pinned to a detached worktree's `config.example.yaml`, no overlay |
| Date | `2026-07-31` |
| Judge | manual, against `expected_behavior` per `evals/rubrics/judging.md`, plus independent source spot-checks (below) |

## Why this run exists

Three behavioural edits to `SKILL.md` + `reference.md`, all under `evals/README.md`'s
MUST-run list: a new hard gate (the Maturity gate), a new routine-path branch (company scope
when no application record exists), and a reroute of how much of `reference.md` is read. Well
over the ~20-changed-instruction-line size guideline as well.

## Safety setup — where the runs resolved

Canary prompts persist output to `config.companies_root()`, and under the example config that
is `examples/companies/` — **untracked but not git-ignored**, so a run in the primary checkout
leaves stageable files in the public tree. Each canary therefore ran in its own detached
worktree under the session scratchpad, with `JOBHUNT_CONFIG` pinned to that worktree's
`config.example.yaml`. Resolution was printed and confirmed before any run started:

```
$ JOBHUNT_CONFIG=<scratch>/cr_wt_<id>/config.example.yaml python -c "...config.companies_root()"
<id> -> companies_root: <scratch>/cr_wt_<id>/examples/companies
<id> -> applications  : <scratch>/cr_wt_<id>/examples/applications
$ ls -a <scratch>/cr_wt_ai | grep -E "^(config.yaml|private)$"
clean: no config.yaml, no private/
```

After all runs, the primary checkout still has no `examples/companies/` at all. No run could
write into the owner's tree.

Each run was **pinned to one context** — no research subagents. That is a deliberate change
from the 2026-07-30 run, whose record flagged that two canaries fanned out and spent ~1M
tokens apiece, and asked whether the set should pin subagent count. It should; the canary
file's `default_setup` now says so.

## Which canaries were run, and why those

| Canary | What of this diff it can detect | Run? |
|---|---|---|
| `cr-ai-strategy` | the Maturity gate, on its own subject file (`06`) | yes |
| `cr-full-research-structure` | company scope end-to-end + `06` maturity + the scoped read | yes |
| `cr-question-bank` | the `09` -> `10` dangling-link rule + company scope + the scoped read | yes |
| `cr-moat-5whys` | the scoped read + maturity tags carried into `05` evidence | yes |
| `cr-product-cold-reader` | nothing — `02` is untouched by all three edits | no |
| `cr-honest-scaffolding-fictional` | nothing — it is the one canary WITH an application record, and no product to date | no |

Four of six. As on 2026-07-30, the claim being made is "the canaries that could detect this
change pass", not "all canaries pass".

## Per-canary results

Token / tool-call / wall-clock figures are the **harness's own per-agent counters**.
`evals/README.md` step 5 says to read them from `logs/metrics.jsonl` via
`automation/metrics/report.py --by-sha`; that file does not exist in this repo and the command
reports `No session metrics found`, so the harness counters are used instead and labelled as
such. The Phase 3 metrics hooks are not emitting — worth its own ticket.

| Canary id | rubric_pass | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|---|---|---|---|---|
| `cr-moat-5whys` | **1** | 150,978 | 964 | 65 | Maturity tags carried into moat evidence; a 13-month private beta correctly downgraded a moat verdict from "their new moat" to "not yet a moat" |
| `cr-question-bank` | **1** | 146,931 | 813 | 51 | Linked forward with `(not yet written)` as instructed; took company scope; found 3 defects in the new text |
| `cr-ai-strategy` | **1** | 210,443 | 1,547 | 99 | 22 products staged from quotable sentences; 6 filed `Maturity unverified`; found a 27.9-month open beta inside a GA product |
| `cr-full-research-structure` | **1** | 266,824 | 2,178 | 102 | All 17 files + README; company scope followed verbatim; found the broken grep recipe |

Pass rate: **4/4**. Cost of this round: 775,176 tokens; with the two re-runs below, **1,199,553
tokens for the whole gate** — roughly what a single canary cost on 2026-07-30 before the
one-context pin.

## Efficiency vs. the 2026-07-30 run

| Canary | tokens then -> now | wall_clock then -> now | tool_calls then -> now |
|---|---|---|---|
| `cr-moat-5whys` | ~125k -> 150,978 (**+21%**) | 721 -> 964 (**+34%**) | 32 -> 65 (**+103%**) |
| `cr-question-bank` | ~1.0M -> 146,931 (**-85%**) | 1,767 -> 813 (**-54%**) | ~305 in 5 contexts -> 51 in 1 (**-83%**) |
| `cr-full-research-structure` | ~1.2M -> 266,824 (**-78%**) | 3,221 -> 2,178 (**-32%**) | ~123 + 4 subagents -> 102 in 1 context |
| `cr-ai-strategy` | no baseline — not run on 2026-07-30 | — | — |

Movements in both directions, and only one of them is about this diff.

**`cr-moat-5whys` regressed and the diff explains it.** The Maturity gate costs two fetches per
product capability used as moat evidence, and `05`'s Evidence bullet now requires that tag. The
run staged six capabilities, so roughly a dozen extra fetches. +21% tokens is a real cost, not a
blow-up, and it is the price of what the gate buys — in this very run it is what turned "the AI
toll booth is their new moat" into "not yet a moat: thirteen months in private beta". Recorded
as an **accepted regression**, not a clean pass.

**The two large improvements are NOT this diff.** They are the one-context pin. Nothing in these
edits reduces fan-out; the harness constraint did. Anyone comparing against these rows must hold
the pin constant or the numbers are meaningless. What the pin does establish, and the previous
record asked for, is that these canaries do not need to fan out: the full-folder canary produced
all 17 files in one context for 267k tokens against 1.2M across four subagents, and
`cr-full-research-structure`'s own report attributes its remaining misses (no conference talks,
no HN/Reddit, no computed market cap) to the token cap rather than to the skill.

## Did the Maturity gate actually work?

That is the one question this branch exists to answer, so it is recorded separately from the
rubric bookkeeping. Across the two runs that wrote `06`, the gate staged **22 products** — every
one with a quotable sentence and a URL behind it. Concretely, it:

- **rediscovered the failure that filed the original task**, independently: AI Search,
  `[open beta since 2025-04-07 — 15.8 months]`, from the pricing docs **body**
  (*"During the open beta, AI Search is free within these limits"*) — the exact page class the
  skill previously never named;
- **found a longer one nobody had reported**: BYO LoRA on Workers AI,
  `[open beta since 2024-04-02 — 27.9 months]`, sitting *inside* a GA product. That is why the
  gate now says to classify a sub-feature in its own right;
- **refused the three trap signals by name, in the output file**: AI Gateway's "Available on
  all plans", Attribution's "available to all Bot Management customers", and the absence of a
  badge on a docs page — each explicitly declined as evidence of GA rather than silently used;
- **hedged where it should have.** Six products went under `Maturity unverified` with the URLs
  checked. Zero open- or private-beta products appeared under "Already shipped" in either run.
- **changed a downstream judgment.** In `cr-moat-5whys` the 13-month private beta on the
  pay-per-crawl product is the stated reason its moat verdict is "not yet a moat — a
  well-positioned option" instead of the confident framing the company's own materials support.

The hedging cost the task warned about is real and visible: six `Maturity unverified` entries in
one file, at least two of which (`Precursor`, the Agents SDK) the run itself says are unverified
because it did not fetch the launch post, not because the post is silent. That is the trade —
the gate converts "confidently wrong" into "visibly unfinished", and unfinished is recoverable.

## Judge spot-checks (independent of the runs' own reports)

The `cr-ai-strategy` rubric now requires the judge to verify named GA claims against the
vendor's own launch posts rather than trust the run. Three were checked directly:

- **Workers AI, claimed `[GA 2024-04-02]`** — launch post body: *"our Workers AI inference
  platform is now Generally Available. After months of being in open beta…"*. Correct. The same
  post says *"BYO LoRAs is in open beta as of today"*, which is why the gate now says to
  classify a sub-feature in its own right.
- **Pay Per Crawl, claimed `[beta since 2025-07-01 — ~13 months]`** — launch post body: *"Pay
  per crawl, in private beta, is our first experiment in this area."* Correct.
- **AI Search, the product the original task reported as fifteen months into open beta** —
  docs pricing page body: *"During the open beta, AI Search is free within these limits."*
  Correct, and the same page's plan-entitlement wording is the trap the gate now names.

The Pay Per Crawl grep also returned the blog's tag cloud (containing the bare word "Beta")
before the real sentence — a live false positive, which is why `reference.md` says to read what
the grep returns in context rather than classify off a keyword hit.

## What the runs found in the skill — ten defects, all in text this branch added

Every canary passed, and between them they reported **ten defects in the instructions this
branch had just written**. That is the argument for running the gate rather than reasoning about
the diff: the run exercises the skill, not the change. All ten are fixed in commit `2a9ab0b9`.

**1. The maturity grep recipe was broken, and it failed toward a false hedge.**
`reference.md`'s `llms-full.txt` recipe returned **zero hits** on a file containing the decisive
sentence three times. `.` does not match a newline in `grep -E`, those mirrors are hard-wrapped
at ~31k lines, and a 140+140-character window essentially never fits on one line. Reproduced
directly by the judge:

```
$ curl -s -L ".../ai-search/llms-full.txt" | grep -o -i -E ".{140}(beta|preview|generally available).{140}" | wc -l
0
$ curl -s -L ".../ai-search/llms-full.txt" | grep -c -i beta
3
```

Under the gate's own rule a zero-hit grep is the `Ambiguous` rung, so **the documented command
would have filed a sixteen-month open-beta product as "maturity unverified"** — a manufactured
false hedge produced by the tooling the gate depends on. It is the mirror image of the four
wrong "shipped" calls this branch exists to prevent, and it was one run's noticing that a 1.1 MB
file returned nothing that caught it. Fixed with the missing `tr '\n' ' '` plus a self-check:
if `grep -c` is non-zero while the windowed grep is empty, the command is wrong, not the
evidence.

**2. The Maturity gate did not cover `09`.** Its scope named `06`, `04` and `05`. But `09` is
where the candidate *says* "you've shipped X" to X's own engineer. `cr-question-bank` applied
the gate there on its own judgment; the skill now says it.

**3. A sixth pointer, and it conflicted.** `09`'s prose carried an inline *"see `reference.md`
§ Why-This-Company Template"* while the Trigger below said *"read ONLY § Question Bank
examples"*. `cr-question-bank` followed the narrower one and **wrote `09`'s required pitch
without ever seeing the template that defines its shape** — a real cost, not a hypothetical.
The scoped-read fix was incomplete.

**4. "Nothing asks you to read `reference.md` end to end" was an overclaim.**
`cr-full-research-structure` showed why: a full-folder run fires *every* per-file pointer, and
the union of those pointers is the rest of the file. The tiering buys `SKILL.md` budget headroom
and saves tokens only on single-file requests. Both files now say that instead of implying
otherwise.

**5. The role family may not exist on the ATS board.** The canary's company has no req titled
"Senior Software Engineer, Platform"; it has ~10 platform-adjacent reqs under four different
organizational readings of the word. The run built a four-readings table and `[JD-dependent]`-
tagged the choice, entirely unguided. Now instructed: enumerate the closest real reqs, name the
ambiguity, never invent a posting.

**6. "the role family named in the request"** had no fallback when the request names none —
which is exactly what the `cr-question-bank` prompt does.

**7. "Produce the whole folder anyway"** read as mandating a full folder even for a single-file
request. Both single-file canaries resolved it sensibly; neither was told to.

**8. The ladder had no staleness clause.** A docs body refreshed *after* the last beta statement
and silent on stage left one product permanently pinned to an eleven-month-old beta claim a
fresher page declined to repeat. Now its own `Ambiguous` case.

**9. A stage word can be a false positive.** A bare "Beta" appears in nav lists and in the
vendor's blog tag cloud — the judge's own spot-check hit the tag cloud before the real
sentence. The rung now requires the word to sit in a sentence about that product.

**10. Dates and sub-features.** A docs GA banner establishes the *stage* but often carries no
date; a dated changelog entry was the decisive artifact more often than the launch post; and a
GA product routinely carries beta sub-features (one run found a 27.9-month open beta inside
one). All three are now in the gate.

Two further findings are about the eval scaffolding rather than the skill and are fixed in the
canary file: `default_setup` claimed the output path is git-ignored (it is untracked, not
ignored — a run in the primary checkout leaves stageable files), and it did not pin subagent
count. `LESSONS.md`'s stale two-group question-bank list now defers to `SKILL.md`'s three.

**Left open, deliberately:** `reference.md`'s fetch recipes hardcode `.venv/bin/python`, which
does not exist in a detached worktree, so every run substituted a path. That is the repo-wide
convention from `AGENTS.md` and a worktree artifact rather than a skill defect — but it does
mean the documented recipes are not copy-pasteable in the environment the evals prescribe.
Worth its own ticket. So is the absent `logs/metrics.jsonl`.

## Post-run delta and the re-run

The ten fixes landed after the runs, in commit `2a9ab0b9`. Most are narrowing clarifications
that name behaviour a run already exhibited. Four are genuinely behavioural — the corrected grep
recipe, the gate covering `09`, the `09` Trigger naming a second reference section, and the new
`Ambiguous` staleness rung — so a written rationale would not have been enough.

**`cr-ai-strategy` and `cr-question-bank` were therefore re-run against the fixed head**
(`2a9ab0b95166`), in fresh detached worktrees with the same isolation. Between them they cover
all four behavioural fixes: the grep recipe and the ladder's new rungs land on `cr-ai-strategy`,
the `09` scope and Trigger land on `cr-question-bank`.

### Re-run results (head `2a9ab0b95166`)

| Canary id | rubric_pass | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|---|---|---|---|---|
| `cr-question-bank` (re-run) | **1** | 192,607 | 1,194 | 57 | Reports **no contradiction** about how much of `reference.md` to read, or about which sections `09` needs — the thing the re-run existed to check. Applied the maturity gate to `09` (20 products staged) because the scope line now says to. Produced one file, disambiguated the role family from four real req families. |
| `cr-ai-strategy` (re-run) | **1** | 231,770 | 1,429 | 77 | **The corrected fetch recipes were run verbatim and all three returned output — "no zero-hit-on-a-page-that-contains-a-stage-word failure occurred", and "the `tr` is genuinely load-bearing".** 25-product maturity ledger; 5 under `Maturity unverified` |

Re-run pass rate: **2/2**. Both re-runs and all four first-round runs pass: **6/6 overall**.

The `cr-ai-strategy` re-run is the row that matters most, because it re-tests the broken grep
against the same page that exposed it. It also caught a genuinely hard case unaided: one product's
changelog entry reads GA-shaped ("rolling out to all customers starting today") while its blog
post says "free to use until our **GA release later this year**" — classified pre-GA, correctly,
on the strength of the second sentence.

The `cr-question-bank` re-run confirms all four `09`-side fixes landed, and its maturity work is
the clearest evidence the gate transfers: it tagged the AI-gateway product
`[maturity unverified]` on the grounds that its pricing page says only *"available to use on all
plans"* — a plan-entitlement line — which is the exact trap class the gate was written to refuse.

It reported four smaller gaps, all fixed in the same follow-up commit and **not** re-run a third
time (see the rationale below): a `09`-only run is told "always produce `03`, `05`, `06`, `09`,
`10`" in the same Rules block that says a single-file request produces one file (the "always"
line is now scoped to a full-folder run); `09` had no `Level, scope & team fit` group for step 3
to hang its `Scope:` line on (both that group and `Product & platform depth` are now in the
required list); the pointer sentence said `09`'s Trigger sits "under that file's template" when
`09` has guidance, not a template; and nothing said where the maturity evidence goes, so the run
invented an evidence table (now required by name).

The `cr-ai-strategy` re-run reported two more, also fixed in the same commit:

- **A real collision between rungs 1 and 4 of the ladder.** One product satisfied both at once —
  a dated beta sentence, and a docs body refreshed three months later that is silent on stage.
  "Stop at the first match" says rung 1 wins; rung 4's text says the opposite. The run followed
  first-match, classified it beta, **and wrote a caveat block giving the candidate the safe
  sentence to say out loud** — which is the behaviour the gate wants, arrived at unaided. Rung 4
  now states that it overrides rung 1 and prescribes exactly that output.
- **The launch-post grep produced a false "Beta" on 100% of one vendor's posts**, because the
  blog renders its ~1,500-entry tag list (containing a bare `Beta` tag, and a
  `General Availability` tag) into every page. Fixed by matching stage *phrases* rather than the
  bare word and dropping windows containing 5+ consecutive Title-Case words — a run of
  Title-Case terms is a tag list, never a sentence. Verified by the judge on three posts:

  ```
  guardrails post (genuinely silent):  0 hits   <- was 1 false positive
  pay-per-crawl post:                  2 hits   <- both real "in private beta" sentences
  ai-gateway GA post:                  1 hit    <- the real "General Availability" sentence
  ```

- One finding was **declined**: nav/sidebar stage pills stay non-authoritative. The run noted
  the rule is conservative — it pushed a visibly "Beta"-pilled product into `Maturity unverified`
  — and that is the trade this deliverable asked for. A pill is now recorded as corroboration in
  the ledger, but still cannot establish a stage alone, because it renders from front-matter and
  goes stale silently.

**Why no third round:** the two re-runs resolved every remaining item correctly on their own —
they produced the missing group headings, the evidence table, and the ambiguity caveat block
unprompted. The post-re-run edits codify behaviour a measured run already exhibited rather than
changing it, and the one that is not codification (the grep hardening) was verified directly by
the judge against three live pages with before/after hit counts, which is stronger evidence than
another canary would give. `Eval gate: post-re-run edits are codification of observed behaviour
plus a judge-verified grep fix, ~20 instruction lines, no gate added or weakened.`

## Verdict

- **Regression:** PASS — 4/4 on the pre-fix head, 2/2 on the fixed head, **6/6 overall**.
  Every `expected_behavior` bullet that could detect this diff held, and the two new maturity
  bullets held under independent source verification rather than on the runs' own say-so.
- **Efficiency:** one accepted regression (`cr-moat-5whys`, +21% tokens / +34% wall clock /
  +103% tool calls), attributable to the Maturity gate's extra fetches and judged proportionate
  to what it buys. No blow-up. The two large improvements are the one-context pin, not the diff.
- The `cr-question-bank` specificity bullet ("**each** question names a SPECIFIC product, repo,
  blog post, competitor, or customer") is judged **held** rather than failed: 24/24 questions in
  the three deep groups name something specific, and the ~9 that do not are in the
  `For the Recruiter (logistics)` and process groups that `SKILL.md` itself requires and that
  cannot name a product. None is generic curiosity, which is the bullet's operative test. This
  is a judgment call and is recorded as one; the same reading was applied on 2026-07-30.
