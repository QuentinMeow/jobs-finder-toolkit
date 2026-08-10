# Triage index for the 69 open issues filed 2026-08-03

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: orchestrated triage session 2026-08-09 — seven parallel review agents,
  one per subsystem, each verifying reproduction at HEAD rather than trusting the filing
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Give every one of the 69 issues opened on 2026-08-03 a verified verdict, so that later
sessions act on evidence instead of re-reading the tracker. Work that shipped on
2026-08-09 is marked SHIPPED; everything else carries a reason it did not.

## Context

All 69 issues were filed on one day by an automated audit. Roughly 50 commits landed
afterwards, so currency could not be assumed. Each issue was checked against the code at
HEAD, and where cheap, reproduced by running the real function rather than reading it.

**Four filings are materially wrong, and acting on them as written wastes a session:**

| Issue | What the filing says | What is actually true |
|---|---|---|
| #276 | Broad US location overrides onsite city requirements | The headline was **already fixed before the issue was filed** — the guard landed in `9778181`, an ancestor of the commit the issue cites. Only three narrower residuals survive. |
| #251 | `max_years_experience` hard cap is ignored | The cap works. A regex backtrack grades the commonest English phrasing ("10+ years **of** experience") as tool-specific, so only that class escapes. |
| #292 | Filtering is CPU-bound in `_repeated_line_hits` / `re.sub` | Measured: that path is **3.5%** of runtime. The real hotspot is `_bounded_phrase_matches` at **64%** (217s of a 337s run). Implementing the filed suggestion produces no visible gain. |
| #293 | Aggregator normalization welds one job's title to another's body | Disproven by repro — `fetch_jobspy` binds every field from one row. **But a real chimera exists elsewhere**, in the store builder (`build_postings.py:450` vs `:534`), which the audit never found. |

Two more are premise errors of a softer kind: **#247** says a shipped audit gate is red; the
gate is `--check` and it is green at 94/94 (exit 1 on a live snapshot is that tool's documented
contract). **#304** attributes three failed repair waves to the repo; those were the audit
agent's own uncommitted attempts — the repo's 8 real repair commits failed for a different and
better-documented reason.

**The cross-cutting insight**: several issues are one defect seen from different ends.
The location cluster is almost entirely one function (`assess_location`). The YOE cluster is
one parser. #292 and #231 are the same hotspot. #293's real cause and #252 are the same
shared-URL defect. Fixing them as filed would mean nine patches where four belong.

## Verdict index

Legend — **SHIPPED**: landed 2026-08-09. **DEFER**: real, not this budget. **DECISION**:
needs the owner, filed in `message-queue/needs-human/decisions/`. **CLOSE**: no code change
is correct.

### Location gate — `automation/shared/location.py` (9)

| # | Verdict | Note |
|---|---|---|
| 255 | SHIPPED | `require_match` and `us_only` were conjoined, so the shipped default profile dropped every non-preferred US city — including `Manhattan, NY` — while its own comment promised the opposite. Highest recall recovery in the batch. |
| 276 | SHIPPED (residual) | Headline already fixed pre-filing. Residual: `jd_remote_role` matched the negated label `Remote Position: No` and read it as a remote grant; `100% onsite` matched no rule at all. |
| 237 | SHIPPED (part) | Headline is intended behaviour — an onsite-from-city prior. Real gap: `work from home` / `WFH` matched no remote rule. |
| 240 | SHIPPED | `--check-metadata --check-locations` silently never ran the location half; an unconditional `sys.exit()` made the branch unreachable. |
| 297 | DEFER | Residency parsing is positive-only, so "remote across the US **except** NY/Bay Area" reads as an unqualified match. Same root cause as #242 — fix once, not twice. Ambiguous clauses must route to review: "except where prohibited by law" and Colorado/NYC pay-disclosure boilerplate would otherwise eat good roles. |
| 242 | DEFER | Same root cause as #297. |
| 301 | DEFER | A "four weeks per year of remote work" perk fires the fully-remote rule and manufactures a conflict. Outcome is a review-queue burial, not a drop. |
| 262 | DEFER | US-or-Canada remote lands in review by deliberate design; low volume, recoverable. |
| 273 | DECISION | Preferred metros do not include suburbs (Cambridge, Bellevue, Redmond rejected). The premise is right and the casualties are real, but a suburb alias table encodes a per-candidate commute judgement into public tooling. **#255's fix defuses most of the blast radius on its own** — re-measure before building anything. |

### Sponsorship / visa — `automation/shared/job_metadata.py` (5)

| # | Verdict | Note |
|---|---|---|
| 231 | SHIPPED | ~890s of CPU per stage-1 run: `visa_ok` computed the same assessment twice, and 100% of it is discarded when the profile does not need sponsorship. **The issue's own proposed fix is unsafe** — gating on a sponsorship signal word silently downgrades five settled citizenship denials to `unknown`, and no test would catch it. |
| 238 | SHIPPED (part a) | Bounded denial gaps: `cannot sponsor or support visa transfers`, `without the need for sponsorship`, `Citizenship required: Yes`. Part (b) — a separate work-authorization axis — is DEFER. |
| 265 | SHIPPED | A JD accepting H-1B transfers while denying new petitions was dropped **silently under both policies**, even though `visa_tags()` already computed `h1b_transfer_friendly` and threw it away. The only silent false negative in the batch. |
| 233 | DEFER | Positive-wording coverage. The one-line fix is a trap: it needs `_SPONSOR_STRONG_POSITIVE`, which bypasses the immigration-context gate and reopens the event-sponsorship false positive. Recall-only impact; cut first. |
| 304 | DEFER → design | All 16 cited sentences reproduce. But it prescribes a proposition-parsing rewrite of the most safety-critical function in the repo, which has already oscillated through three revisions. Not a 12-hour task. |

### Title filtering / scoring — `skills/job-search/scripts/scoring.py` (10)

| # | Verdict | Note |
|---|---|---|
| 232 | DECISION-gated | A hardcoded 7-family occupation lexicon runs **before** the user's explicit `titles.include`, so no include phrase survives for sales, finance, customer success, clinical, design, or recruiting. Verified across all six. |
| 256 | DECISION | The mirror inversion: a broad `word_filter` token reverses the user's explicit `titles.exclude`. Two owner-level decisions collide and a passing test encodes the doc-violating side. |
| 298 | DEFER | `Front-End Engineer` misses a `front end engineer` include; `normalize()` deletes `&`, so `fp&a analyst` can never match `FP&A Analyst`. Fix in `term_matches`, never in `normalize()`. |
| 234 | DEFER | 20 minutes: add one fictional corpus case for the manager-product review class, which a mandatory gate currently flags as unknown. Pair with the location variant already in the backlog. |
| 278 | DEFER | The per-employer cap backfills by design, but the report header prints an unconditional guarantee it does not make. Fix the label, keep the backfill. |
| 279 | CLOSE (parts 1-2) | Already triaged as accepted and documented in `common.py`. Part 3 is real and belongs to the precedence work. |
| 274 | DEFER | `_BROAD_DOMAIN_TOKENS` is a closed 25-token set, so `automation`/`quality`/`performance` skip the guard entirely. **L effort and the only fix here that can destroy recall** — needs a frozen fixture and a measured before/after. |
| 267 | DEFER | Same defect as #274. Merge the tickets. |
| 254 | CLOSE as split | Its three causes belong to #256, #274, and profile-authoring docs. The reporter retracted one central claim. |
| 291 | DEFER | Keyword scoring rewards explicitly negated domains. `assess_sponsorship`'s negation machinery is the reusable idiom. |

### JD parsing / profile modelling (11)

| # | Verdict | Note |
|---|---|---|
| 249 | SHIPPED | One missing character. `_source_text` unescaped `\+` and `\$` but not `\-`, so JobSpy's `1\-3 years` parsed as **min 3** — a range ceiling became its floor. |
| 251 | SHIPPED | See premise correction above. Also propagates the review verdict so an over-cap row stops being silently promoted. |
| 264 | SHIPPED (parts) | `$30/hour` rendered identically to `$30k`; a salary written with cents parsed as nothing at all. Spelled-out numbers deferred. |
| 283 | SHIPPED (safe half) | `min_base`/`min_total` are declared in both shipped profiles and read by **nothing** — verified repo-wide. Made visible rather than implemented: a comp floor built on today's parser would drop every role whose pay merely failed to parse. |
| 286 | SHIPPED | `experience_ok` is the only one of five gates that discards its tri-state, so an over-cap posting entered the **main** shortlist with no recorded evidence. The repo's own audit tool documents the correct behaviour three files away. |
| 257 | DEFER | A smaller high-confidence specialty clause deletes a larger medium-confidence primary. Largely self-heals once #251 lands — re-measure first. |
| 260 | DEFER | `18 Kubernetes clusters` becomes `18 K` in the tailoring card, which is the default context for every resume generation. A **fabrication vector**: an agent can read "18 K" as 18,000. Cheapest real win left. |
| 261 | DEFER | `skills_diff` queues URLs and the employer's own name as candidate skills. |
| 272 | DEFER | The highest-value deferred item on the resume side: a `Never: CI/CD` entry does not match the phrase `CI/CD`, so the tool **pressures a novice into broadening a truthful claim** (`Java basics` → `Java`) to clear a blocking prompt. Runs against the fabrication guardrail. |
| 287 | CLOSE → document | A feature request with no defect behind it. Document that manager eligibility is a named manual check. |
| 288 | DEFER | A registered nurse is rendered as `entry (L3.0-L3.8)` on a Google IC ladder. Display-layer only. Retitle: it is occupation-neutrality, not managers. |
| 296 | CLOSE | The claimed contradiction does not exist — one signal is a FAIL, the other a WARN, and the reporter's own run exited successfully. One doc line. |

### Sources / store / dedup (12)

| # | Verdict | Note |
|---|---|---|
| 293 | SHIPPED (real cause) | Filed cause disproven; the genuine chimera is in the store builder and was reproduced end-to-end. |
| 292 | SHIPPED (via #231) | Same hotspot. See premise correction above. |
| 306 | SHIPPED | `company_tags: []` was indistinguishable from unset and polled all 162 boards. |
| 289 | SHIPPED | A valid tag whose rows are all batched resolves to zero with an error that cannot distinguish it from an unknown tag. |
| 248 | SHIPPED | Both shipped profiles teach `sites:`; the planner reads `reliable_sites`. A user asking for Indeed silently gets Google too. |
| 252 | SHIPPED (URL half) | The shared generic URL is the precondition for #293's chimera. Mojibake repair deferred. |
| 236 | DEFER | SmartRecruiters stops at 100 — 262 of 362 postings never reach matching. **Land after the perf fix**: 362 postings means 362 sequential unbatched detail fetches. |
| 235 | DEFER | 196 postings lost to un-retried 429s. Needs `http_get_json` to start surfacing status codes; two tests pin the current no-retry behaviour. |
| 281 | DECISION | 83 duplicate-body rows in one 460-row snapshot (18%). But the requested fix fights `dedupe`'s documented design. Exact-body-same-company collapse is safe; cross-company staffing collapse is the owner's call. |
| 271 | DEFER + decision | Postings that say "NOT A REAL JOB" pass the quality gate — but that gate is documented as a *template* detector and never receives `company`. Turning it into a general junk gate is a scope change. |
| 299 | DEFER | A dead Greenhouse page is judged only by byte count, so a "No job found" shell counts as a successful JD. Needs one network check first. |
| 230 | DEFER | `company_roles --jd` cannot disambiguate identical titles; the ambiguity error prints the same string N times. |

### Reports / artifacts / auditability (12)

| # | Verdict | Note |
|---|---|---|
| 244 | SHIPPED | `write_review_report` called `path.unlink(missing_ok=True)`: a refilter with zero review rows **deleted the previous run's review artifact**. Also, the discoveries Markdown collided on date+profile, and on the refilter path could overwrite *yesterday's* report. |
| 258 | SHIPPED | The report sliced company, title, location and rationale mid-word with no ellipsis — and the mismatch warnings are appended last, so they are exactly what falls off. |
| 259 | SHIPPED | The persistent report never named the review artifact; the path existed only in transient stdout. |
| 253 | SHIPPED | `420 preserved… of which 561 were kept` — one counter is per raw posting, the other post-dedupe and post-cap. |
| 245 | SHIPPED (part) | Not data loss: the snapshot retains full text. The artifact just never said the field was a preview or where the full JD lives. |
| 246 | DEFER | Cap overflow is counted but persisted nowhere. Do not raise the cap — the queue is flooded by rows the location classifier fails to reject. Fix the cause. |
| 284 | DEFER | Refilter nulls **every** `store_key`, and the skill tells users to refilter before acting. Read-only fix. |
| 285 | DEFER | Unknown profile keys are silently ignored, so `max_required_years` disables the YOE cap with no warning. |
| 269 | DECISION | Negative-score rows are labelled matches. There is no score floor anywhere. A threshold is a recall gate in disguise and must be measured, not guessed. |
| 243 | DECISION | Contradicts an owner decision made 2026-08-02. The real finding is scope: widening applies to aggregator rows whose employers are never in the company log, making `--max-age-days` inert repo-wide rather than board-scoped. |
| 247 | CLOSE + split | Premise wrong (see above). Split out the real content: bare foreign city/country names, `USCA`/`AMER` short-forms, ATS placeholders, and `Vancouver, WA` misclassified as mixed US/foreign. |
| 286 | SHIPPED | Listed under JD parsing above. |

### Onboarding / setup / leak guard (10)

| # | Verdict | Note |
|---|---|---|
| 307 | SHIPPED | **The most serious issue in the set.** 17 of the 40 most common US surnames produce false violations on a clean tree (King 496 files, Ross 325, Green 271). The guard runs on pre-commit and pre-push, so such a user cannot commit at all — and their only escapes are `--no-verify` (forbidden) or deleting their identity from config, **which disarms the guard entirely**. A false-positive bug that drives users into the fail-open state. |
| 228 | SHIPPED | `python3 -m venv` exits 0 on Python 3.7 and the failure surfaces much later as a confusing dependency error. |
| 280 | SHIPPED | Both documented create-profile destinations are absent on a fresh clone. |
| 282 | SHIPPED | The quickstart's first command does not parse in zsh — `<owner>` is read as an input redirection. |
| 268 | SHIPPED | A public-only search already works via the tracked profile fallback; nothing said so. |
| 229 | SHIPPED | The JD digest derived the title from the body, so a marketing paragraph became the title — and the seniority classifier ran on it, reading a Senior role as `unknown`. |
| 241 | SHIPPED | The resume extractor silently dropped contact lines with no parseable email — phone-only, portfolio-only, and `github.com/<user>` lines all returned empty with exit 0. |
| 263 | DEFER | Sparse resumes have no documented truthful fallback for a quantified cover letter, so the pressure resolves toward inventing a number. Three sentences, but it is a harness edit that costs a canary run — fold into the next resume-writer change. |
| 290 | DEFER | `open to remote candidates` and `Posting Type: Remote` are ignored as uncorroborated hints. This is the location module's highest-churn surface; do it with a frozen matrix, not in a mixed batch. |
| 239 | DEFER | No path from an existing resume to the three required artifacts. Genuinely L, and multi-column/table resumes hard-fail with no next step. |

## Definition of done

- Every issue above has a verdict recorded here. **Done** as of 2026-08-09.
- Each DEFER has a backlog task or is named in an existing one.
- Each DECISION has an item in `message-queue/needs-human/decisions/`.
- The four premise corrections are carried into whatever PR or comment touches those issues,
  so nobody re-implements the wrong fix.

## Human questions / additional tasks

Nothing pending beyond the DECISION items filed alongside this index.
