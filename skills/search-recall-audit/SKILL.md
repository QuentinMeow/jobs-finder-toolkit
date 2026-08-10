---
name: search-recall-audit
visibility: public
description: Audit the job-search pipeline for silent misses — randomly sample raw job postings from a search snapshot (grepping the ENTIRE JD, never title-only), fan them out to AI subagents that judge each against the active profile's requirements and check whether an application was generated, then deterministically trace every apparent miss to the exact pipeline gate that dropped it. Use when the user asks to audit/spot-check job-search recall or precision, "did we miss any jobs", "why didn't we surface <role>", "sample some raw JDs and verify them", "check the pipeline is catching what it should", or wants to validate a filter change. Findings become tickets; the content gates are never changed on a hunch.
---

# Search-Recall-Audit — is the pipeline missing roles it should surface?

The `job-search` pipeline filters ~12k raw postings down to a ranked shortlist.
This skill answers: **is that filtering correct — are we silently dropping roles
that match the candidate, or keeping roles we shouldn't?** It does so by
randomly sampling raw postings, having AI agents judge them against the *active
profile's* requirements (the same gates `job-search` enforces), checking coverage
against the applications pipeline, and then **deterministically tracing** every
apparent miss to the exact gate — so an AI "looks missed" becomes "dropped at
gate X (correctly, or a real bug)".

It is a **QA harness, not a fixer**: it produces evidence + tickets. A filter
change is a separate, human-reviewed edit to `job-search` — never made on a hunch.

## When to Use

- "Audit / spot-check job-search recall (or precision)." · "Did we miss any jobs?"
- "Why didn't we surface `<role/company>`?" · "Sample some raw JDs and verify them."
- After changing a `job-search` gate/profile — validate it didn't regress recall.
- Periodic confidence check that the pipeline is catching what it should.

## Guardrails (inviolable)

- **Grep the ENTIRE JD, never title-only.** The sampler matches keyword combos
  across company + title + location + full description. This is deliberate: a
  role whose *title* misses the include-list but whose *body* is clearly in-scope
  is a title-gate false-negative — a real recall risk the audit must be able to find.
- **Never fabricate a miss or a fix.** An AI "MISSED" verdict is a *hypothesis*
  until the deterministic `trace` confirms which gate acted and whether it was
  right. Do not change `job-search` logic unless `trace` shows a genuine defect;
  fabricating a "fix" for correct behavior violates the AGENTS.md no-fabrication rule.
- **Surfaced ≠ drafted.** A matching role with no application may simply have been
  surfaced but not selected for drafting, or suppressed by the 7-day
  recently-searched window — both expected, not bugs. `trace` + the coverage
  pre-check distinguish these.
- **Read-only on the pipeline & the repo.** The tool imports `job-search`'s gates
  white-box and reads the applications log/folders; it MUTATES nothing tracked.
  All artifacts land in the gitignored `local/search_recall_audit/`.
- **Findings go to the PRIVATE mirror.** Tickets naming real employers / the
  candidate's applied-to companies violate the public leak rule — file them under
  `private/tasks/0_backlog/` and `private/memory/known-issues/` (copy the schema
  from `templates/`), never the public `tasks/` / `memory/`.
- **Subagent budget:** at most 8 subagents total per request (AGENTS.md). Always use `.venv/bin/python`.

## Models (read before fanning out)

- **Matching (step 2)** is a parallel judgment task → use **`claude-sonnet-5-thinking-high`** subagents (divide-and-conquer).
- **Tracing (step 3)** is deterministic (the `trace` command) — no model needed. When a miss is genuinely ambiguous and needs deep artifact reading, use the strongest **available** subagent model. Note: **Opus 4.x is typically NOT available as a subagent model** — do that reasoning in the parent (which is Opus-class) rather than silently substituting a different model, or tell the user which models are available.

## Workflow

### Step 1 — Build the corpus (deterministic)
Turns the latest pre-filter snapshot into a greppable corpus + a coverage index.
```bash
.venv/bin/python automation/search-recall-audit/audit.py corpus
# defaults: --profile <config default> --snapshot latest (local/search_cache/<profile>-stage1-latest.json)
```
Writes (to `local/search_recall_audit/`): `postings.jsonl`, `search_lines.txt` (one
key-free line per posting = the whole JD, grep-friendly), and `coverage_index.json`
(canonicalized-URL + company index of everything already considered/drafted/applied).
If there is no snapshot, run a `job-search` first (or pass `--snapshot PATH`).

### Step 2 — Sample + AI-verify (divide-and-conquer)
Randomly sample a few postings per keyword combo, **grepping the whole JD**:
```bash
.venv/bin/python automation/search-recall-audit/audit.py sample --per-combo 2
# custom combos (repeatable, comma = AND): --combo 'kubernetes,remote' --combo 'san francisco,platform engineer'
# --uncovered-only skips picks whose exact URL is already considered
```
Each pick becomes `local/search_recall_audit/jds/<idx>.md` (full JD + a coverage
pre-check). Then split the picks across **Sonnet-5 subagents** and give each the
**canonical prompt below**, verbatim, with its batch of JD file paths. Collect the
per-JD verdicts (match? covered? verdict).

<details><summary>Canonical match+coverage prompt (copy verbatim per batch)</summary>

> You are auditing whether a job-hunting pipeline correctly surfaced job postings.
> Judge each JD against the requirements below, then verify coverage. Never
> fabricate — if the JD does not state something, say "unstated".
>
> **A posting MATCHES only if ALL hold** (the specifics below mirror the public
> `example` profile — when auditing a real profile, substitute ITS `titles`,
> `location`, `max_years_experience`, and `visa.policy`):
> 1. **TITLE** contains an include-term from the profile's `titles.include`
>    (example profile: software engineer, backend / back end engineer, full stack,
>    platform engineer, infrastructure(-engineer), distributed systems, site
>    reliability / reliability engineer, cloud engineer, api / services engineer)
>    AND NO term from `titles.exclude` (example: manager, director, head of, vp,
>    intern, new grad, sales, marketing, recruiter, designer, data scientist,
>    research scientist). Exception: "member of technical staff" is an IC title and
>    is KEPT (it is in `exclude_neutralize`). Staff/Staff+/Principal/entry/new-grad
>    fall outside a mid–senior target band → exclude.
>    **`titles.exclude` is NOT the only hard title drop.** `scoring.assess_title`
>    also hard-drops a title that hits its generic non-technical-occupation
>    lexicon (sales / marketing / recruiting / finance / legal / clinical /
>    education) while carrying no engineering role noun — so a drop you cannot
>    explain from `titles.exclude` is not automatically a bug. That lexicon is
>    SKIPPED for a title the profile's own `titles.include` cleanly names (a match
>    on a broad-domain token alone — infrastructure / platform / compute — does not
>    count as naming it). Always confirm the actual gate with `trace` in Step 3
>    rather than reasoning from the two lists alone.
>    **Special recall flag:** if the TITLE would FAIL the include-list but the JD
>    BODY is clearly an in-scope IC role for the profile, flag it as
>    `TITLE_GATE_FALSE_NEGATIVE` (a real recall risk).
> 2. **LOCATION** (when the profile is `us_only`): EITHER an office in one of the
>    profile's preferred metros (example persona: San Francisco, New York, Boston,
>    Austin) OR **fully US-remote**. CRITICAL: **hybrid or on-site in a US city that
>    is NOT one of the profile's preferred metros does NOT match** — it requires
>    being in that city. A foreign location fails even if "remote". Multi-location
>    passes if ANY listed location satisfies the rule. Judge from the JD TEXT, not
>    just a flag.
> 3. **YOE**: fails only if a stated minimum is ABOVE the profile's
>    `max_years_experience` cap (if the profile sets one; otherwise YOE never fails).
> 4. **VISA** (example policy `exclude_negative`): fails only if the JD EXPLICITLY
>    denies sponsorship. Generic "must be authorized to work in the US" is NOT a denial.
>
> **Coverage:** each JD file has a canonicalized-URL coverage pre-check.
> `exact_url_already_considered: True` ⇒ COVERED. Otherwise compare the
> same-company log/folder entries by role: same/near-identical role ⇒ COVERED
> (name the slug+status); only a DIFFERENT role ⇒ this specific role is NOT covered.
> You may read the applications skip-log (`config.applications_jsonl_path()`) and the
> `config.applications_root()/<N>_*/` folders to confirm. Do NOT modify anything.
>
> **Output per JD:** `idx`, `company/title`, `requirements_match: yes|no|borderline`,
> `gate_results` (title/location/yoe/visa, each pass/fail + why), `covered: yes|no`
> + evidence, `verdict: CORRECTLY_EXCLUDED | CORRECTLY_COVERED | MISSED | BORDERLINE`,
> `one_line_reason`. End by listing any `MISSED` idx.

</details>

### Step 3 — Trace every apparent miss (deterministic root-cause)
For each `MISSED`/`BORDERLINE` idx (or URL), run the pipeline's OWN gates:
```bash
.venv/bin/python automation/search-recall-audit/audit.py trace --idx 8283 --idx 9469
# or --url '<posting url>' (repeatable). --idx is most robust (from the sample output).
```
It prints, per posting, PASS/DROP for `posting_quality`/`title`/`location`/`visa`/
`experience`, the **first drop gate**, and the location assessment (category /
decision / workplace / evidence). Interpretation:
- **FIRST DROP GATE: location → other_us/foreign** on a hybrid/on-site non-preferred
  city ⇒ the AI over-matched; the pipeline was **correct**. (This is the #1 cause
  of false "misses" — see LESSONS.)
- **NONE — passes all gates** ⇒ the role IS surfaced. If it has no application, it
  was not drafted (selective) or suppressed by recently-searched — not a filter bug.
- A gate dropping a role the JD clearly satisfies ⇒ a **genuine defect** worth a fix.
- To confirm a role is surfaced/ranked, cross-check with a full
  `search_jobs.py --refilter latest --include-recent --include-considered --max-per-company 0 --top-k 20000 --json-out <path>`.

### Step 4 — File findings (never silently fix)
- **Genuine gate defect** → `private/memory/known-issues/<slug>.md` (schema:
  `templates/memory/known-issue.md`) with the failing `trace` output; propose the
  fix but leave the `job-search` edit as a separate human-reviewed change.
- **Audit summary / leads** (undrafted-but-matching roles, over-matches to watch)
  → `private/tasks/0_backlog/<YYYY-MM-DD>-<slug>/task.md` (schema `templates/task/task.md`).
- Confirm the reconciler stays green: `.venv/bin/python automation/reconcile/reconcile.py --check`.

## Variant — Field-fidelity audit (generated fields vs raw source)

A sibling harness that answers a different question: **does a GENERATED field
faithfully represent the RAW source payload** (not "did we miss a role")? It
targets the `location` string the gate reads — the failure mode is a parser that
drops or mangles source geography (slashes, `Austin/NYC`, ISO codes, a country in
a separate `address`/`allLocations` field), so the gate decides on a lossy string.

```bash
# 1. Re-run the SAME parsers the builder uses over the raw zone; compare generated
#    location vs every raw location field (dedup by blob sha). Writes local/ only.
.venv/bin/python automation/search-recall-audit/field_fidelity.py corpus
# 2. Curate/sample cases (weighted to flagged) for AI verification.
.venv/bin/python automation/search-recall-audit/field_fidelity.py sample --n 30
# 3. Re-parse ONE entity deterministically to root-cause a flagged case. Takes STORE
#    ENTITY KEYS (repeatable), not the `<source>-<native_id>` case-file name from step 2.
.venv/bin/python automation/search-recall-audit/field_fidelity.py check --key <entity-key>
# 4. Escape hatch: list weird-format postings (review reason weird_location_format) as AI TODOs.
.venv/bin/python automation/search-recall-audit/field_fidelity.py todo
```

`corpus` flags are `dropped_raw_token`, `gate_decision_flip`, `duplicated_country`,
`weird_separator` and `truncated_location_list` — the last fires on an `and N more`
tail (Workday ships one `locationsText`, `"Austin, TX and 3 more"`, copied verbatim
into `location`): raw and generated are the SAME lossy string, so no drop is
detectable and the loss is the board's, not the parser's. Treat it as known-lossy at
source, never as a faithful copy.

Design (owner-approved 2026-07-25): **fix KNOWN formats in code, escalate WEIRD
ones — never fold noisy fields.** Verify flags with **`composer-2.5`** subagents
(judge each generated-vs-raw case: FAITHFUL / KNOWN_FORMAT_DROP / NOISY_FIELD /
WEIRD_UNRESOLVABLE), then have **`gpt-5.6-sol`** subagents implement confirmed
parser fixes + tests. Key gotcha: **do NOT naively fold every raw location field**
— greenhouse `offices[]` is a company-wide office list that contradicts the role's
`location.name` (NOISY_FIELD). Weird strings (region buckets "West"/"Central") get
a `weird_location_format` review reason → `review`, never a silent guess. Same
guardrails as above (QA harness, read-only pipeline, local/ artifacts, private
findings, ≤8 subagents). See LESSONS "Field-fidelity" + known-issue
`location-field-fidelity-parser-drops.md`.

## Files

| Path | Purpose |
|------|---------|
| `skills/search-recall-audit/SKILL.md` | This router + the canonical match prompt |
| `skills/search-recall-audit/LESSONS.md` | Hard-won edge cases (hybrid-metro over-match, whole-JD grep, gh_jid URL dup, field-fidelity) |
| `automation/search-recall-audit/audit.py` | Recall/precision: `corpus` / `sample` / `trace` (imports `job-search` gates white-box; writes only to `local/`) |
| `automation/search-recall-audit/field_fidelity.py` | Field-fidelity: `corpus` / `sample` / `check` / `todo` (generated `location` vs raw source; writes only to `local/`) |
| `local/search_recall_audit/`, `local/field_fidelity_audit/` | Gitignored run artifacts (corpus, cases, selection summary, `location_todo.jsonl`) |
