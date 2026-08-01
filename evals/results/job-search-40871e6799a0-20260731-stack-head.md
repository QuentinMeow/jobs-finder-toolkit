<!--
Per-machine result (network/board state + local model dependent). Per-SHA token metrics from
`automation/metrics/report.py --by-sha` are NOT available: the canaries ran as fresh top-level
sessions in separate detached checkouts, whose usage the metrics hook does not write to this
checkout's metrics log. Efficiency below is the harness's own per-session telemetry, supplied with
the runs, not self-reported by the runs.
Employer names are redacted to `<company>` and absolute paths to `<repo-root>` — the results tree
is public.
-->
# Eval result — job-search

| Field | Value |
|-------|-------|
| Skill | `job-search` |
| Canary set | `evals/canaries/job-search.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `40871e6799a0` (tip of a 28-PR stack; "Acknowledge 9d31abec in the review ledger") |
| Model version | `claude-opus-5` — the five runs and this judgement |
| Config mode | examples fallback (`config.yaml` unset → `config.example.yaml`, fictional persona, `example` profile) |
| Date | `2026-07-31` |
| Judge | judge subagent (`claude-opus-5`), per `evals/rubrics/judging.md` — every `expected_behavior` bullet an independent pass/fail check, all must hold, a listed `failure_mode` = automatic fail, borderline → FAIL |

## Method

Five live runs, one per canary, each a **fresh session with a clean context** in its own detached
checkout at `40871e6799a0`. Each was given the canary's verbatim user prompt and the repo — **not**
the rubric — so routing and behaviour were genuinely under test. Network live (Stage 1, keyless).
Each wrote a run record; the records are session scratch, not tracked.

This is the **second run of this set on the same day**. The first ran at `70a620f32968`, before the
sponsorship, location, handoff and registry commits in this stack landed, and is recorded at
[`job-search-70a620f32968-20260731-jd-digest-gate.md`](job-search-70a620f32968-20260731-jd-digest-gate.md)
(4/5). A paired before/after on the same five prompts is the most useful thing this run produces and
has its own section below.

The judge performed none of the runs. Where a record asserts something a bullet checks, the
assertion was corroborated against surviving artifacts or against the source at the tested SHA (see
**Evidence discipline**).

## Why this run was required

The stack edits the instruction corpus, not just code: `skills/job-search/SKILL.md` (+63/−…),
`LESSONS.md`, and `reference.md` all changed between the two SHAs, well past the ~20-line
behavioural threshold in `evals/README.md`. It also rewrites the scripts underneath them —
`build_postings.py`, `handoff.py`, `common.py`, `scoring.py`, `company_roles.py`, `sources.py` and
`automation/shared/job_metadata.py` among 68 files. So this is a gating run, not an optional one.

## Rubric provenance

`js-single-company-location-verdict` was **strengthened inside this stack** (commit `9778181`).
Confirmed by diffing the canary file across the range: bullet 2 went from "`--match-only` shows only
policy-matching roles" to "…drops definite non-matches and KEEPS review rows", a REVIEW-honesty
bullet was inserted, and two failure modes were appended. Canaries 1–4 are byte-identical at both
SHAs.

Unlike the previous record — which had to score a run against the rubric in force *before* the fix —
this run is judged against the strengthened bullets, because they are the bullets in force at the
tested SHA and the run was executed after the fix.

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes (which check failed / efficiency flag) |
|-----------|-------------------|--------------|--------------|------------|----------------------------------------------|
| `js-core-shortlist` | 1 | 143,145 | 1,042 | 43 | All 5 bullets hold, artifact-verified. Ran `search_jobs.py --profile example` (11,683 fetched → 40 kept, then a 60-day refilter → 60). Discoveries file carries the full column set incl. `Source`/`Link`; six chat rows traced to artifact rows field-for-field; the two roles quoted without a URL are backed by saved verbatim JD digests. Handed off without tailoring. **Note:** the chat tables omit `score` and the Google-equivalent band and never name the report path — see the reading note below. |
| `js-visa-require-positive` | 1 | 158,592 | 2,992 | 53 | All 4 bullets hold; no failure mode. `require_positive` genuinely applied and genuinely returned **zero** (`matches-h1b.json` is an empty list). The run reported the real answer instead, from live JD reads, labelled advisory. The judgement this turns on is argued in full below. Most expensive run in wall clock: a 300 s timeout, a backgrounded probe and six live JD fetches. |
| `js-mts-not-staff` | 1 | 175,479 | 1,451 | 48 | All 3 bullets hold, artifact-verified: 40 rows, and the **only** row in the whole shortlist containing `staff`/`principal`/`distinguished`/`fellow` is the MTS role at rank 18, level-tagged `senior (L5.0-L5.8)`. Zero staff-band rows. The word-vs-rung distinction is explained, with the 18 excluded dual-level reqs offered back and the policy question filed. Highest token count of the five. |
| `js-recency-vs-research-window` | **0** | 134,189 | 691 | 45 | **FAIL — bullet 3**, the same bullet and the same conjunct as the previous run. Filter correctly applied (header `posting age ≤ 3.0 days`, 34 rows, every age ≤ 2.6 d) and no window conflation, but the answer never tells the user posting-age filtering is off by default. Detail below. |
| `js-single-company-location-verdict` | 1 | 139,200 | 738 | 46 | All 5 bullets hold against the **strengthened** rubric; neither new failure mode observed. Kept every review row, read the postings behind them, promoted 4 review rows to matches and **rejected 3 of the tool's 4 matches** after reading their JDs. Etiquette flag: hit one public board 8 times for a one-company question. |

Pass rate: `4/5`.

### A reading note that decides two bullets

Canary 1's bullets 3 and 4 enumerate fields (`source`, `url`, `score`, Google-equivalent level) that
appear in the generated discoveries report but not in the run's chat tables. Bullet 2 explicitly
requires **both** a written report and an in-chat presentation, so the field checks are judged
against the composite output, not the chat alone. Under a chat-only reading no run could pass either
bullet, which would make the checks unfalsifiable. This is the same reading the previous record
used, applied here for comparability — but it is worth noting that a user who reads only the chat
gets 6 of the 8 named fields and is never pointed at the file holding the other two.

## The one failure, in full

**`js-recency-vs-research-window`, bullet 3:** *"Notes that posting age is off by default and this
run is the explicit 'last N days' case."*

The second conjunct holds — the answer repeatedly frames the result as "your window" (e.g. a flagged
posting is "66 days old and outside your window entirely"). The first does not appear anywhere. The
delivered answer was grepped exhaustively for `by default`, `opt-in`, `off unless`, `normal`,
`usually`, `unless`, and for every line mentioning age/window/recent/posted: the only "normal" in the
answer is about visa labels. The user is never told that a routine search applies **no** age filter
and that this window is opt-in — which is the whole point of the bullet, since a user who does not
know the default cannot know what they just narrowed.

Bullets 1 and 2 hold and are artifact-verified: the report header records `posting age ≤ 3.0 days`,
all 34 rows are ≤ 2.6 d, and nothing in the run confuses posting age with the 7-day company
re-search window. Neither listed failure mode occurred. Per the no-partial-credit rule, one missed
conjunct is a fail.

Two things make this worse than a near-miss rather than better. It is the **same failure as the
previous run**, and the stack in between rewrote both `SKILL.md` and `LESSONS.md` without closing
it. And once again the canary that has no such bullet volunteered the exact missing sentence:
`js-mts-not-staff`'s answer opens its caveats with *"Posting-age filtering is off by default, so some
rows are old."* The information is clearly available to the model; nothing in the instruction corpus
attaches it to the prompt that asks for it.

## Paired before/after — `70a620f32968` → `40871e6799a0`

| Canary id | Before | After | Verdict |
|-----------|--------|-------|---------|
| `js-core-shortlist` | 1 | 1 | **Held.** Same shape of run, same artifact quality. Both runs also overwrote the discoveries product with a wider refilter; both disclosed it. |
| `js-visa-require-positive` | 1 | 1 | **Held on the rubric, regressed underneath.** Before: 55 rows, all labelled `yes`. After: **0 rows**. The bullets survive only because the run refused to let "0" stand and went and found the real answer. See Defect A. |
| `js-mts-not-staff` | 1 | 1 | **Held, marginally improved.** Both kept MTS and shipped zero staff-band rows. This run additionally probed the *family* and found a second spelling the neutralize list does not cover (Defect E) — a finding the earlier run never reached. |
| `js-recency-vs-research-window` | 0 | 0 | **Held — still failing, same bullet, same conjunct.** Not touched by the stack in either direction. |
| `js-single-company-location-verdict` | 1 (old rubric) | 1 (new, stricter rubric) | **Improved.** The tooling defect that forced the earlier run to be scored on the pre-fix rubric is fixed and judge-verified: `--json` now emits `decision`, `workplace`, `review_reasons` and `category` per row, and `--match-only` keeps review rows. The run cleared two bullets and two failure modes that did not exist at the earlier SHA. |

Pass rate is 4/5 at both SHAs, but the composition is not the same: one canary's underlying tool got
materially better, one canary's underlying tool got materially worse, and the failing canary is
untouched.

## The judgement this set turns on

`js-visa-require-positive` delivered a shortlist that **did not come out of the filter the user asked
for**. The filter returned zero. Argued both ways, because it is the closest call in the set:

**For a fail.** Bullet 1 says the run applies `require_positive` "so only postings with an EXPLICIT
sponsorship signal pass". The rows actually delivered did not pass it — they were graded `unclear`
and dropped. On the strictest reading, the run substituted its own judgement for the gate on an
immigration-facing question, which is the one place a heuristic should not be overridden by an agent.

**For a pass, which is the verdict.** Four things decide it. (1) The filter *was* applied, not
widened: `matches-h1b.json` is an empty list, and the run verified in source that the flag was not a
silent no-op before believing its own zero. (2) The rows were not padded from the diagnostic
`exclude_negative` pass the run also ran — judge-verified: that pass produced 200 rows, **zero** of
them from the employer the answer delivers, all labelled `unclear`. Nothing from the wider pass
reached the user. (3) The label was never presented as authoritative: the answer states the tool
grades this employer `unclear`, quotes the verbatim JD sentence it read instead, and says the
detection is "a text heuristic and is advisory". (4) The alternative — reporting "0 roles" to a user
who needs H-1B while holding a live JD that reads *"Visa sponsorship: We do sponsor visas!"*,
verified on two separate postings — would violate the repo's honesty-over-optimization guardrail to
satisfy a filter the judge has now independently confirmed is broken. No listed failure mode fires.

The failure here belongs to the classifier, not to the run. It is recorded as Defect A.

## Verdict

- **Regression:** FAIL on `js-recency-vs-research-window` (bullet 3), PASS on the other four. 4/5.
- **Does this block the merge? No — conditionally.** The rubric fail is a pre-existing communication
  miss, unchanged in either direction by this stack, not a correctness or safety failure, and
  orthogonal to every file the stack touched. Efficiency shows no blow-up. The stack's own surface —
  the single-company location verdict — measurably improved against a *stricter* rubric, and the
  sponsorship classifier's two most dangerous failures at the previous SHA are fixed.
  **The condition:** Defect A (`require_positive` now returns nothing on a live 11.7k-posting market
  where it returned 55 rows one SHA earlier) must be filed before merge, because `--visa-policy
  require_positive` is a documented user-facing flag that the SKILL still tells users to reach for.
  Merging with it unfiled would ship a flag that silently answers "there are none".
- **Follow-ups that should not be waved through:** the recency bullet needs one line in
  `skills/job-search/SKILL.md` or `LESSONS.md` stating that posting age is opt-in, then a re-run of
  that canary alone. Defects B–E below each want a ticket.

## Efficiency vs the previous run

Like-for-like: same five prompts, same model, same harness shape, same night, 22 hours apart.

| Canary id | tokens (now / before) | Δ | tool_calls | wall_clock_s |
|-----------|----------------------|-----|-----------|--------------|
| `js-core-shortlist` | 143,145 / 126,422 | +13.2% | 43 / 29 | 1,042 / 1,224 |
| `js-visa-require-positive` | 158,592 / 144,463 | +9.8% | 53 / 66 | 2,992 / 2,097 |
| `js-mts-not-staff` | 175,479 / 165,119 | +6.3% | 48 / 57 | 1,451 / 1,512 |
| `js-recency-vs-research-window` | 134,189 / 113,712 | +18.0% | 45 / 33 | 691 / 752 |
| `js-single-company-location-verdict` | 139,200 / 125,218 | +11.2% | 46 / 28 | 738 / 577 |

Median token delta **+11.2%** (totals 750,605 / 674,934, also +11.2%). Tool calls +10.3% in total,
median +12 calls but with two canaries *down*. Wall clock is flat at the median (−61 s) and +12.2% in
total, essentially all of it one canary's 300 s timeout plus a backgrounded probe.

**This is not a blow-up and does not block the merge.** An ~11% band across five live-network runs of
this shape is inside the noise the runs themselves document: this set fetched roughly the same corpus
(11,682–11,683 postings) but spent its extra calls on self-inflicted work each record discloses —
one board fetched 8 times for a single-company question, one probe re-written twice after its regex
was wrong, one 300 s classifier sweep over 11,683 full JD bodies that had to be re-scoped. Roughly a
tenth of the two most expensive runs is attributable to that rather than to the skill.

## Defects the runs surfaced

Worth as much as the pass/fail verdict — this is what the run bought. A–C were reproduced by the
judge; D–E were verified in the artifacts and the shipped config.

- **A. A regression this stack introduced: an explicit offer with a scope limit now grades
  `unclear`.** Judge-reproduced by running `assess_sponsorship` from both SHAs side by side on the
  same six phrases:

  | phrase | `70a620f32968` | `40871e6799a0` |
  |---|---|---|
  | explicit offer + scope limit (*"We do sponsor visas! However, we aren't able to … for every role"*) | `match` / `likely` / high | **`review` / `unknown` / low** ← regression |
  | plain offer | `match` / `likely` | `match` / `likely` |
  | *"Limited immigration sponsorship may be available"* | `match` / `likely` / high | `match` / `likely` / high |
  | work-authorization boilerplate | `review` / `unknown` | `review` / `unknown` |
  | explicit denial | `match` / `likely` / high | **`no_match` / `unlikely` / high** ← fixed |
  | export-control clause | `no_match` / `unlikely` / high | **`review` / `unknown` / low** ← fixed |

  All three changes come from one commit in this stack, `86a18e0` ("Stop reading a refusal to sponsor
  as an offer to sponsor"), which introduced both the `sponsorship.negated_offer.*` and the
  `sponsorship.non_immigration.export_control` rules. It fixed Defects B and F of the previous record
  — a denial read as an offer, and an export-control clause read as an immigration denial — and in
  doing so made an offer sitting next to its own scope limit read as *"Conflicting sponsorship offer
  and denial language."* Net effect on the canary: `require_positive` went from 55 rows to 0 on a
  comparable market scan. The new error is the conservative direction (drops a real offer) where the
  old one was the dangerous direction (surfaced a denier as a sponsor), so this is not a straight
  downgrade — but the flag is now unusable in practice and its documentation does not say so. Note
  the untouched row: a doubly-hedged *"Limited immigration sponsorship may be available"* still
  grades `likely`/high, which `LESSONS.md` says must land `unclear`. The two error directions remain
  swapped.

- **B. A "remote" role bolted to a single metro scores as open US-remote.** Judge-reproduced against
  `automation/shared/location.py` at this SHA: a posting whose ATS location is the bare workplace word
  `Hybrid` and whose JD says *"This is a remote role but the location requirement is that you reside
  in the Boston, MA region"* returns `decision=match`, `category=us_remote`, `confidence=high`, with
  evidence `('location_hybrid', 'jd_remote_role', 'jd_remote_over_bare_workplace_tag',
  'remote_eligible')`. The rule that lets a JD remote grant override a bare workplace tag never reads
  the residency clause that follows it. Three of the four roles `<company>`'s board returned as
  confident matches are this shape; the run caught all three by reading the JDs and excluded them.
  Filed by the run as a backlog task.

- **C. A bare `remote` location passes as US for a foreign employer.** Judge-reproduced:
  `assess_location("remote", …)` with a foreign employer and no US token anywhere returns
  `decision=match`, `category=us_remote`, `confidence=high`, evidence `('location_remote',
  'ats_hint_remote', 'remote_eligible')` — against a policy with `us_only: true`. Confirmed in the
  delivered artifact: rank 19 of the 3-day shortlist is a European employer whose entire location
  field is the word `remote`. The run found it in its own low-score tail, told the user to discard it,
  and recorded it against an existing known-issue whose sketched fix does not cover it (that fix keys
  on a foreign token in the *title*; this title carries no geography at all).

- **D. One company's whole engineering board is invisible to market search.** `<company>` parks a
  workplace word where the location belongs on **221 of 285** open roles (`Hybrid` 143, `In-Office`
  46, `Distributed` 28, plus combinations), verified in the run's saved JSON. Every one becomes
  `review` with reason `workplace_tag_without_geography` and never reaches a ranked shortlist:
  judge-verified that **all three** market searches in this set (canaries 1, 3 and 4 — 60, 40 and 34
  rows) contain **zero** rows from that employer, while its board carries roles that are dead-centre
  matches for the profile. The geography is present in the JD body under `Available Locations:` /
  `Location:` / `Position Location:`; nothing in the pipeline reads it. An existing backlog item
  covers the JD-body-declared-location problem; the market-search blindness it causes is not
  quantified there.

- **E. The title-neutralize list covers one spelling of an IC title family.** The shipped
  `skills/job-search/profiles/example.yaml` has exactly one `exclude_neutralize` entry, `member of
  technical staff`. `<company>` also posts *"Member of Data Staff (…)"* — the same construction, the
  same IC meaning — and it is not covered. This does not bite the shipped profile (which has no
  `staff` exclude), but it bites the moment a user asks to keep out staff-and-above, which is
  precisely this canary's prompt: the run's own hard exclude deleted both rows until it noticed,
  added the spelling and refiltered. The neutralize list needs the family, not the instance.

## Cross-run observations

- **Three of five runs mangled a gate's exit code the same way.** `${PIPESTATUS[0]}` is bash; this
  shell is zsh, where the array is `$pipestatus` and 1-indexed, so the expansion prints an empty
  string. One run also echoed `$?` after a `for` loop (reporting `echo`'s status, discarding three
  real exit codes) and after a `grep | head` (reporting `head`'s 0 while the grep's real 1 *was* the
  finding). All three caught it and disclosed it. Three for five, on top of four for four in the
  previous run, is seven for nine across two independent sets: **this is a finding about the
  instructions, not about the agents.** `AGENTS.md`'s "Shell & Paths" convention names zsh and the
  quoting hazard but says nothing about the exit-code idiom, and a backlog item already exists
  (`tasks/0_backlog/2026-07-31-piping-a-gate-to-tail-hides-its-exit-code/`) — one run cited it and
  still had to be careful by hand. The near-miss is constant: a silent gate reported as passing.
- **Every search run shipped over a red mandatory gate, and all of them said so.**
  `validate_filter_variants.py` exited 1 in all four search runs (the same three unlabeled structural
  shapes: a bare-city location, a `USCA` location literal, a product-suffix title). None did the
  classifier work `SKILL.md` requires "before relying on that filter"; each verified instead that the
  flagged shapes could not have changed its answer, told the user the gate was red, and filed or
  extended a ticket. That is a defensible call made four times independently — but the skill still
  does not say what to do when a mandatory gate is red and the finding is out of scope for the user's
  question, so the four runs resolved it four slightly different ways. This is the second run in a row
  where that gap shows.
- **Real employer names reached tracked paths in three of five runs.** New or modified files under
  `tasks/`, `history/` and `message-queue/needs-human/decisions/` in three worktrees name live
  employers; the runs that explicitly set out to avoid it (`js-visa-require-positive`'s decision item,
  `js-single-company-location-verdict`'s task) succeeded, but the latter's *handover* names the
  company despite its record claiming the specifics live "only in this record and in gitignored
  `local/`". Nothing was committed, and the leak guard would not have caught it — company names are
  not identity tokens. Outside this canary set's rubric; the same observation appears in the previous
  record, so it is now a pattern.
- **Honesty was again uniformly good.** Every record volunteers its own wrong turns: an analysis run
  against a field truncated to 400 characters and thrown away; a snapshot misread as classifier
  output and corrected before it reached a conclusion; a regex that counted a single senior-staff rung
  as a dual-level req and reported 191 where the truth was 49; a piped digest read that attributed one
  posting's locations to another and would have dropped a genuine match. Per the rubric that honesty
  is neither credit nor debit — but it is what made this judgement checkable, because the unflattering
  parts came with commands attached.

## Evidence discipline — what the judge verified independently

Corroborated, not taken on the records' word:

- **Artifacts read directly.** All four discoveries reports survive (60 / 200 / 40 / 34 rows) and were
  read: header `Filters:` lines (`posting age ≤ 60.0 days`, `≤ 3.0 days`, `any (not filtered)`), the
  full column set `# | Score | Company | Title | Level (Google eq.) | YOE | Salary | Loc/Remote | Age |
  Visa | Source | Why | Link`, `?` used for unstated facts. Six of `js-core-shortlist`'s chat rows were
  traced to artifact rows field-for-field (level, YOE, salary band, age, visa) and matched; the two
  roles it quoted without a URL were checked against its saved JD digests, which contain the exact
  `Available Locations:` and years-of-experience lines it reported. `js-mts-not-staff`'s 40 rows were
  grepped for all four staff-band rungs: one hit, the MTS role at rank 18, tagged `senior`.
  `js-recency-vs-research-window`'s 34 ages were extracted and are all ≤ 2.6 d.
  `js-visa-require-positive`'s `matches-h1b.json` is an empty list, and its diagnostic 200-row pass was
  loaded and confirmed to contain zero rows from the delivered employer, all `unclear`.
- **Source read at the tested SHA.** `company_roles.py`'s docstring and `--json` row schema (the
  previous record's Defect C is fixed); `apply_visa_policy`'s docstring, which now documents the
  silent-no-op trap both runs independently rediscovered; `scoring.visa_ok`; the shipped profile's
  `exclude_neutralize`; `location.py`'s `jd_remote_over_bare_workplace_tag` branch.
- **Behaviour reproduced.** The sponsorship classifier at both SHAs on six phrases (Defect A table);
  `assess_location` on four shapes (Defects B and C); the canary file's own diff across the range.
- **Repo gates re-run in this worktree.** `reconcile.py --check` → `OK (9 checks clean)`;
  `verify_links.py` → `OK: 2552 references, the skill symlinks and the vendored copies verified`
  (0 broken); `instruction_budget.py --strict` → exit 0, all instruction files within budget
  (`skills/job-search/LESSONS.md` flagged NEAR at 146/160 lines — advisory, and worth knowing before
  the next edit to it).

**Claims that could not be substantiated (6), none of which changes a verdict:**

1. `js-visa-require-positive`'s record states it disclosed the diagnostic `exclude_negative` pass "in
   the answer". Grepped: the string appears nowhere in the reproduced answer. **Refuted, not merely
   unverified** — the disclosure exists only in the record. The bullet still holds because no result
   from that pass reached the user (verified above).
2. `js-single-company-location-verdict`'s record states the named company's specifics live "only in
   this record and in gitignored `local/`". Its tracked handover names the company. **Refuted.**
3. That run's market census (0 of 222 review rows naming a policy metro; the city-mention
   distribution) rests on its own probe scripts over a live board. The 285 / 4 / 222 / 59 decision
   counts and the review-reason breakdown *are* verified from the saved JSON; the per-row JD
   extraction is not.
4. `js-visa-require-positive`'s market-wide census (11,474 `unclear` / 207 `no` / 2 `yes`; the 400-,
   499- and 1,634-posting probe counts; "61 US engineering roles") — one-off scripts over a snapshot
   that has since moved on. Not required by any bullet.
5. `js-mts-not-staff`'s drop census (1,089 hard drops, 1,004 leading-position, 85 needing eyes, 49
   true dual-level reqs, 26 US-eligible, 18 clean matches) — its own audit script. The delivered
   shortlist, which is what the bullets check, is verified.
6. `js-recency-vs-research-window`'s observation that the validator's age replay gates the location
   audit but not the title audit — the run itself labels this an observation, not a diagnosis, and did
   not read the validator source. Neither did the judge.

Every canary had enough evidence to judge; none was scored on testimony alone.

## A/B section

Not applicable — run kind is `regression pre-merge`, not A/B. No variants, no paired runs, no blind
quality comparison, and therefore no significance claim. The before/after table above is a
same-prompt regression comparison against a named earlier SHA, not a matched-pair A/B, and the
efficiency deltas in it carry no significance claim either.

## Stage row

Not applicable — this is not a stage A/B row (`evals/protocols/stage-benchmarks.md`).
