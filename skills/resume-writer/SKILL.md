---
name: resume-writer
visibility: public
description: Tailor resumes for ATS optimization. Use when the user asks to tailor or optimize a resume, analyze a job description for keyword fit, rewrite resume bullets, or render validated DOCX + PDF resumes and cover letters.
---

# Resume Writer Skill

## When to Use

Use this skill when the user asks to:
- Tailor or optimize a resume for a specific job
- Analyze a job description for keyword fit
- Rewrite resume bullets for a specific role

## Quickstart — one routine tailoring run

This Quickstart is the **complete routine path** for tailoring one application. Follow it top to
bottom; a routine run needs **nothing below this Quickstart** and **no file beyond the tailoring
card + baseline** except on the explicit triggers called out inline. **Token-saving defaults are
part of the routine: expect 1–2 render cycles (hard stop at 3, then report to the user rather
than looping); cap company/product research at 2 web fetches per cover letter unless the user
asks for deep research; and never re-read a file already in context.**

**Generation mode.** Read `config.generation_mode()` — `token_saving` (default) or `full`.
- **token_saving (default)** *is* the routine path written in this Quickstart — card-first context
  (not the full profile/story bank), 1–2 render cycles, ≤2 research fetches per cover letter, no
  unprompted extra work. Nothing extra to do: follow the steps as written.
- **full (opt-in)** lifts those discretionary caps — read the full profile + story bank up front,
  do deep multi-source company/product research, and take extra render/polish iterations (still
  **≤ the hard stop of 3**).
- **Hard gates are IDENTICAL in both modes and never relax:** blacklist/log/duplicate preflight,
  location gate, `meta.yaml` schema validation, `check.py`, no-fabrication, and the three-list
  skill gate run the same regardless of mode. Mode changes how much *context and iteration* you
  spend, never which *validations* run.
- A user's explicit instruction in the moment outranks the config mode (either direction). Never self-escalate to `full` — the mode changes only via config or an explicit user request.

**Default deliverables — produce all of these unless the user opts out** (e.g. "resume only"), in
`applications/6_drafted/<slug>/`: ONE tailored **resume** (DOCX in `source/`, PDF at root, covers
the whole folder); **one bundled application `.txt` per JD** at root
(`..._Application_<job title>.txt`); and **one cover letter PDF per JD** at root
(`..._Cover_Letter_<job title>.pdf`). Cover letters are one-to-one with JDs — a multi-role folder
gets a distinct, individually researched letter per posting, never one shared letter. Tell the
user which artifacts you produced and where.

**Boot reads (once, at the start — skip anything already in context):** `AGENTS.md` (guardrails:
no fabrication/consistency; scratch stays in `tmp/`, never the repo root, an application folder,
or `scripts/`; **≤ 8 subagents total per request**); `.agents/MEMORY.md` if it exists
(cross-session learnings). **The routine path does NOT read this skill's `LESSONS.md`,
`reference.md`, the `check.py` source, or the application-tracker `SKILL.md`** — open them only on
the explicit inline triggers below (`LESSONS.md` = a render/layout failure, see Step 6). In
particular, `handoff.py` already wrote a valid schema-v5 `meta.yaml`, so `status.py
--enrich-metadata`/`--check-metadata` are the only tracker follow-ups on the routine path.
**Private overrides:** if this skill folder has a `references_private/`
directory, read every file in it — those candidate-specific instructions/examples/preferences
OVERRIDE the generic examples here; when it is absent (public / example mode) use the generic
examples as-is and take all candidate specifics from `config` + the tailoring card + the profile.

### Preflight (MUST — before any `mkdir` or JD/meta write)

Do this before Step 1. If the user only wants to refresh an existing draft, edit that folder —
never create a second one.

- **Duplicate scan (hard block — zero writes on a hit).** Scan the applications log
  (`<profile-dir>/applications-log.yaml`, `<profile-dir>` = `config.applications_root()/0_profile/`)
  **and** every live folder
  `applications/{6_drafted,5_applied,4_in_progress,3_rejected,2_ignored}/<slug>/` (read each
  `meta.yaml` — company, `role` or `jobs:` entries, URLs). If this exact posting (same company +
  role, or same URL) already exists in any status folder or the log, **stop** — point the user at
  that folder and offer to refresh it instead, and do **not** `mkdir` a second folder or create a
  new dated slug for the same company+role/URL. A *new* role at an already-applied company is fine
  to proceed with. If the log might be stale, run `.venv/bin/python
  skills/application-tracker/scripts/status.py --sync-log` first, then re-read it — but
  still cross-check the live folders before creating a slug.
- **Blacklist (hard block).** Check the resolved company against the MERGED registry, not
  `companies.yaml` alone: `registry.load_registry()` merges
  `skills/job-search/companies.yaml` with the git-ignored `private/job-search/blacklist.yaml`
  overlay at load time (`skills/job-search/scripts/registry.py`). If
  `Registry.is_blacklisted(company)` reports a `blacklist:` reason (it resolves on name, aliases, or
  ATS token), do NOT create an application; tell the user it's blacklisted.
- **Location gate (hard requirement — respect the search criteria).** Confirm the posting
  satisfies `config.location_policy()` (allowed metros / US-remote / `us_only`). An on-site or
  hybrid role in a non-allowed metro with no allowed-metro office and no US-remote option, or a
  role excluded by `us_only`, does NOT meet the criteria — do not create the application (tell the
  user it was skipped for location). Record the real posting location in each `jobs:` entry's
  `location` and verify drafted folders with `.venv/bin/python
  skills/application-tracker/scripts/status.py --check-locations` (every drafted app must
  report `match`).

### Read the tailoring card FIRST (MUST)

**Read `<applications_root>/0_profile/tailoring-card.md` (path via config helpers) INSTEAD of the
full profile + story bank.** The card is the distilled, always-needed tailoring context:
identity / locked fields, target roles, key numbers, the three skills lists (Never verbatim), and
a story-bank digest. It is your default context — do not open the full profile or story bank on a
routine run.

**Always also read the baseline resume** (`config.baseline_path()`) — it is the tailoring
substrate you edit in Step 5, and the card does not replace it.

**Open the full documents ONLY on one of these triggers** (and then read only what the trigger
needs — the full files win on any conflict with the card):
- **Card missing** → build it, then read the card: `.venv/bin/python
  skills/resume-writer/scripts/build_tailoring_card.py` (`--check` tests staleness).
- **Gardener card-staleness warning** (or `build_tailoring_card.py --check` reports changed
  sources) → rebuild the card, then use it.
- **The JD demands domains the card doesn't cover** → open the full profile
  (`config.profile_md_path()`) and read **only the relevant `interviews/behavioral-story-bank/`
  sections** for that domain. Supporting-library detail: [`reference.md`](reference.md) §
  "Supporting library (real detail sources)".

### Step 1: Create the Application Folder

Preflight must have passed (above). If job-search's `handoff.py` already scaffolded this folder
(`meta.yaml` + `source/JD-*.md` present), Step 1 is done — skip to Step 2 (if handoff reported
metadata gaps, run `status.py --enrich-metadata <folder>` first).

Otherwise generate a slug `<company>-<role>-<YYYYMMDD>` (lowercase, hyphens, no special chars),
confirm it is unused under every status folder, and create the folder + its `source/` subfolder.
Save the full JD text as `source/JD-<job title>.md` (one file per posting; never a bare `jd.md` —
`check.py` concatenates every `JD-*.md`), and write a schema-v5 `meta.yaml` with a uniform
`jobs:` list (one entry per posting), **every entry created with `status: "drafted"`**. Newly
generated applications always go under `applications/6_drafted/`, whose rollup for an all-drafted
app is `drafted`. `render.py` emits every output filename automatically from the configured stems —
never hand-name or hand-place files. **Trigger — hand-creating the folder (no `handoff.py` scaffold):
read ONLY [`reference.md`](reference.md) § "Application folder creation (Step 1 detail)" for the
`meta.yaml` skeleton + field rules and JD/output naming; if you hit a field the skeleton doesn't
cover, the application-tracker `SKILL.md` owns the full schema.**

### Step 2: Analyze the Job Description

Read the JD and identify:
1. **Required skills**: explicit "must have" or "required" items
2. **Preferred skills**: "nice to have", "bonus", "preferred" items
3. **Key responsibilities**: what the role does day-to-day
4. **Domain keywords**: specific technologies, methodologies, frameworks
5. **Seniority signals**: years of experience, leadership expectations
6. **Structured level facts**: stated/company job level, normalized seniority, required YOE
   min/max, and an approximate Google-equivalent float range. Prefer a matched, sourced
   company-cache mapping over generic title conversion; when the title is unlevelled, use explicit
   required YOE as the conservative fallback.
7. **Compensation facts**: posted base-salary/pay range and separately stated total
   compensation/OTE. Do not derive total compensation from assumed equity or bonus.
8. **Skill-list status**: compare each concrete skill/technology against the profile's
   Approved / Weak / Never lists (`Weak` is presented to users as **Weak or Selective**).
   Deduplicate close variants and preserve first-seen JD order for the batched
   uncategorized-skill queue in Step 7. Do not infer a category merely from how familiar or
   unusual a term sounds.

### Step 3: Gap Analysis

Compare JD requirements against the tailoring card (open the profile only on the triggers above)
and present this to the user before rewriting — a "Keyword Coverage Analysis" with four sections:
**Strong Matches** (skills/experience directly in both), **Can Reframe** (JD terms an existing
project maps to), **Gaps (be honest)** (what's missing or only adjacent), and **Recommended
Strategy** (which angle to lead with and which projects most directly match the JD).

### Step 4: Select Projects

The profile's projects are tagged `[draft]` or `[backup]`. Select the projects for this application:

For multi-employer baselines, keep employer order and project ownership; tailor direct role
bullets under the same honesty/length rules as project bullets. Rules below apply resume-wide.

- **Default**: Use **all** the `[draft]` projects (the full set — the profile is sized so they
  fill one page). Tailoring means small wording tweaks and rephrasing a project's bullets to fit
  the JD — **NOT** adding, inventing, or removing projects.
- **Never drop a project to tailor.** Keep the full project set. Remove a project ONLY as a last
  resort when the content genuinely will not fit on one page (see Step 6) — and when you must,
  drop the single least JD-relevant one, then shorten before removing more.
- **Never fabricate a project.** Only real profile projects (`[draft]` / `[backup]`) may appear;
  check.py fails on any title that isn't in the profile.
- **Swap rule**: Replace a `[draft]` project with a `[backup]` project ONLY if the backup is
  significantly better aligned with the JD (a 1-for-1 swap, not an addition/removal). Explain the
  swap to the user.
- **Ordering**: Lead with the profile's designated strongest/lead project (the profile marks
  which project should lead every resume); it leads regardless of role. Order the remaining
  projects by relevance to the JD. Candidate-specific ordering rules, if any, live in
  `references_private/`.

### Step 5: Tailor from the baseline (`tailored.yaml`)

**Always start from the baseline — never write from scratch.** It may use canonical
`employers:` or legacy `employer:` / `experience:`; do not convert formats merely to tailor.
The folder exists from Step 1; this only ensures `source/` exists:

```bash
mkdir -p applications/6_drafted/<slug>/source
# <baseline> = config.baseline_path() (resolve from config; real data under private/)
cp <baseline> applications/6_drafted/<slug>/source/tailored.yaml
```

`config.baseline_path()` is the exact transcription of the user's approved resume; tailoring means
**targeted edits** to that copy within the limits below. **The baseline you just copied IS the live
schema — read its fields directly; do not open reference.md for the schema on a routine run.**
(`**text**` = bold: the baseline already bolds key phrases; keep 1-3 JD-relevant bold phrases per
line.) Open [`reference.md`](reference.md) § "tailored.yaml schema" ONLY for a genuine edge case —
a legacy `employer:`/`experience:` layout, or a field the baseline doesn't show.

**Locked — never change (validated against `config.baseline_path()`):**
- Name, contact line, education line
- Every employer entry's company, job title, dates, and location (count/order included)
- Project titles — must exactly match a `[draft]` or `[backup]` project in the profile

**Fixed structure (validated by `skills/resume-writer/scripts/check.py`):**
- Summary count matches the baseline (the shipped/default profile has 3).
- Preserve all employers. Use 1-6 direct role bullets and 1-4 bullets per named project.
  Project-focused baselines may drop one project only for page fit (Step 6);
  hybrid/direct-bullet resumes are not forced into a five-project shape.
- Each bullet 45-215 characters (bold markers excluded); project titles ≤ 95.
- Rendered PDF must be exactly 1 page AND fill the page — no large blank band at the bottom.
  check.py fails a resume that ends too high (>1.5in of trailing whitespace). Fix a too-blank
  resume by lengthening bullets with real, traceable detail (target ~2 rendered lines each) —
  never by adding filler or dropping to fewer projects.
- **`**text**`** in any bullet or summary line renders as bold; keep 1-3 bold phrases per bullet,
  preferring the JD-relevant keywords.
- **One-page budget:** predict the page fit BEFORE rendering (Step 5.5) with `estimate_layout.py`,
  which prints the number. **Trigger — the estimate is ambiguous and you need the hand char-math:**
  read ONLY [`reference.md`](reference.md) § "One-page layout budget (char math)" (calibrated
  constants: LESSONS.md → "Pre-render layout budget", on a layout failure).

**Honesty (hard constraint — the three-list skill gate + no fabrication):**
- The profile's Skills section has three lists that gate every skill mention:
  - **Approved** — generally include in most resumes, if not all; still prioritize
    relevance and the one-page space limit.
  - **Weak** (user-facing: **Weak or Selective**) — include ONLY when the JD explicitly
    mentions the term (check.py verifies against every `source/JD-*.md`). This category does
    **not** necessarily mean low proficiency; it may instead mean the wording is unusual,
    awkward, overly specific, or otherwise undesirable on the regular resume.
  - **Never** — never include this skill in any resume, even when the JD mentions it
    (check.py scans skills lines, summaries, and bullets).
- A skill in none of the three lists fails validation — never add it silently; see Step 7
  (categorize new skills with the user).
- **Need the exact gate semantics or a threshold** (skill-list matching, cover-letter word
  counts, bullet/length limits)? Run `check.py --rules` (~1 KB) — never read the `check.py` source.
- Every bullet must map to real content the user actually did — reword, never invent. The source
  of truth is the profile (`config.profile_md_path()`) **plus** the supporting library
  (`interviews/behavioral-story-bank/`, answer bank, prior applications, notes). A detail is
  allowed on the resume if it is documented in one of these real sources.
- You MAY enrich a bullet with a concrete, real detail pulled from the story bank (a scale figure,
  a named artifact, a real tool) as long as it is traceable to that source and does not contradict
  the profile. Still forbidden: metrics, technologies, titles, or scope that do NOT appear in the
  profile or the library. If the story bank flags a number as an estimate/unverified, keep the
  profile's framing rather than inventing precision. Skills remain gated by the three lists.
- **Honest partial fit:** if there's a real gap, name it briefly and reframe as fast-ramping (one
  clause, not a paragraph); refuse to claim experience the user does not have. Never fabricate.

**Trigger — unsure how far you may rephrase or enrich a bullet:** read ONLY
[`reference.md`](reference.md) § "Rephrasing, detail enrichment & light-touch defaults".

### Step 5.5: Pre-render layout budget (one-shot the single page)

Rendering (DOCX → PDF) is slow, so predict the page fit from the YAML **before** rendering with
`estimate_layout.py` (it reconstructs the template geometry live from the reference DOCX and
prints an estimated height + verdict):

```bash
.venv/bin/python skills/resume-writer/scripts/estimate_layout.py applications/6_drafted/<slug>/
```

**Verdict protocol (calibrated bands against the ~734pt one-page budget).** A fit verdict you
give the user always has TWO parts: (1) the band verdict below, and (2) the statement that
**check.py's post-render page count is the authoritative gate — the estimate is only a
pre-check**. A verdict missing part (2) is incomplete.
- **OK** ~660–~715pt — 1 page with margin; proceed. **TIGHT** 715–734 — trim ~1 line.
  **OVERFLOW** > 734 — will be 2 pages; shorten the longest bullets/summary before rendering.
  **SPARSE** < ~660 — may trip check.py's "too blank"; lengthen bullets with real detail.
- Target **est ≤ ~715pt** (about one rendered line under the ~734pt budget) for a confident
  one-shot single page.
- **Simulate before you recommend:** apply a proposed trim to the YAML and re-run
  `estimate_layout.py` to confirm the fix lands under budget before rendering — don't guess.
- **Never drop a project** to hit the budget; shorten bullets first, and only as a last resort
  (when shortening isn't enough) drop the single least JD-relevant project. On SPARSE, lengthen
  with real, traceable detail — never filler or invented content.
- `render.py` runs this estimate itself and **aborts a clear overflow before any LibreOffice
  conversion** (est over budget by more than the ±1-line word-wrap noise); borderline/TIGHT
  still renders, and `--skip-estimate` bypasses the gate. Still simulate trims with
  `estimate_layout.py` here, and check.py's post-render page count stays the authoritative gate.
  See LESSONS.md → "Pre-render layout budget" for the calibrated constants and the font /
  margin / line-spacing levers.

### Step 6: Render + Validate

Ensure `meta.yaml` is schema v5 with complete structured metadata for every posting record before
rendering (`status.py --check-metadata`; fill gaps with `status.py --enrich-metadata <folder>`).
Then render — this first re-runs the one-page estimate as a pre-flight gate (aborting before any
conversion on a clear overflow; `--skip-estimate` bypasses), then writes the resume DOCX to
`source/`, the PDF to root, and (for each `meta.yaml` role whose bundle exists) the cover letter
DOCX/PDF, and runs check.py automatically:

```bash
.venv/bin/python skills/resume-writer/scripts/render.py applications/6_drafted/<slug>/
```

If check.py FAILs, fix `tailored.yaml` and re-render (re-run `estimate_layout.py` first to confirm
the fix lands under budget). Expect 1–2 cycles; **after 3, stop and report to the user**:
- **2 pages** → shorten the longest bullets first; drop the least JD-relevant project only as a
  last resort when shortening isn't enough (never drop a project just to tailor). Rare if you
  cleared Step 5.5.
- **too blank at the bottom** (`Resume looks too blank at the bottom`) → lengthen bullets with
  real, traceable detail (aim for ~2 rendered lines each) and keep all projects. Do NOT delete
  projects and do NOT pad with filler or invented content — pull genuine specifics from the
  profile / story bank.
- **bullet too long/short** → rewrite within 45-215 chars.
- **locked field / title / skill failures** → revert to the baseline value.

Checks can also be run standalone:
`.venv/bin/python skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/`.
**To learn exactly what check.py enforces (every gate + numeric threshold), run `check.py --rules`
(~1 KB) — never read the validator source.** Submit the resume DOCX from `source/` to portals (PDFs
are for humans). **Trigger — a render/layout failure the menu above doesn't resolve (LibreOffice /
DOCX internals, employer-header alignment, the schema-v5 `meta.yaml` gate, cover-letter render flags,
master-resume/log updates): read ONLY [`reference.md`](reference.md) § "Render & validate —
operational detail" and LESSONS.md → "Rendering / layout".**

### Cover letters & bundled application `.txt` (one per JD)

Write the bundle(s) before running `render.py` (it renders each role's cover letter from the
bundle and validates one per role). Research each JD's **product and that specific role** before
writing — **cap company/product research at 2 web fetches per letter unless the user asks for deep
research** — and keep every candidate claim traceable to the profile / library (no fabrication, no
generic flattery, no invented product claims). Each letter is individually researched and written
per posting; never reuse one across JDs. Skip cover letters only when the user explicitly asks.

**Bundled `.txt` structure (hard constraint):** one `<APPLICATION_STEM>_<job title>.txt` per
`meta.yaml` role, at the folder root, holding **three canonical copy-paste sections, each a title
line + `===` underline, in order — COVER LETTER, WHY THIS COMPANY & ROLE, PAST EXPERIENCE.** Plain
text only — **no Markdown, no `**bold**`, no bullet glyphs.** The **COVER LETTER** section starts
with **name + contact line, then the salutation** (`Dear <Company> Hiring Team,`) — **NO
company/role subject line**; its body is **at least two developed, full-sentence paragraphs** (not
telegraphic fragments) and ends `Sincerely,` + name. check.py enforces the numbers: each main
paragraph 60–180 words (≥2 such paragraphs) and total body 200–450 words — write to those bands up
front. **COVER LETTER body = two main paragraphs:** (1) interest + *researched* understanding of the
company/product and why this specific role (name the role; concrete product specifics, never generic
flattery); (2) your single most differentiating strength, proved with a real, quantified achievement
mapped to the JD's top requirements (tell the story behind a bullet — don't relist). An optional
25–45-word closing may follow.

The other two sections are plain prose, every claim traceable to the profile / library:
- **WHY THIS COMPANY & ROLE** — exactly two paragraphs, each a one-sentence summary then expand:
  (1) what the company builds + a specific researched reason you're interested; (2) your most
  relevant background mapped to the JD and why it's a strong mutual fit.
- **PAST EXPERIENCE** — lead with the current role + scope, then the most JD-relevant achievements
  across prior roles/projects in prose (a career narrative, not a company-by-company transcript).

**Trigger — the posting shows its own application/screening questions** (user pastes them, a
screenshot, or the JD lists them): append an extra **APPLICATION QUESTIONS** section after the three
canonical ones and read ONLY [`reference.md`](reference.md) § "APPLICATION QUESTIONS section" for its
mechanism. Full templates / word-count tables and the ATS guidelines also live in `reference.md` — a
routine letter needs none of it.

### Step 7: Categorize New JD Skills in One Batch (ALWAYS do this at the end)

After rendering, compute the uncategorized-skill queue with the script instead of diffing in
context — it reuses check.py's exact matching (aliases, nested `AWS (…)`, component-wise Weak), so
its queue matches the render gate:

```bash
.venv/bin/python skills/resume-writer/scripts/skills_diff.py applications/6_drafted/<slug>/
```

It prints the verbatim JD skill phrases in NONE of the profile's Approved / Weak / Never lists (one
per line), or `no uncategorized skills`. Present that queue as-is — no re-extraction. Still add a
skill you know the JD names but the script missed, or one the user raised directly.

For every JD skill in NONE of the lists, collect the complete queue and ask the user in one
batch at the end of the run to categorize each term by its concrete resume consequence:

- **Never** — never include this skill in any resume, even when a JD mentions it.
- **Weak or Selective** — include only when the JD specifically mentions it: limited
  familiarity, or wording too strange/awkward/specific for the regular resume.
- **Approved** — generally include in most resumes, if not all, subject to relevance and space.
- **Other** — needs clarification (phrase vs skill, normalization) before categorizing.

`Weak or Selective` is the user-facing label for the stored `### Weak` profile subsection —
record answers under `Weak`; never rename the subsection or the parser's category names.

The interaction protocol is strict:

1. **Gather the complete queue before asking.** Extract and deduplicate uncategorized skills
   across every JD; do not interrupt analysis with serial questions.
2. Ask all pending skills in **one batched interaction**. Each question must focus on
   exactly one skill and be single-select; use one question object per skill in the same
   form/tool call. Never combine several skills into one question or use a multi-select.
3. For every question, use this exact option order — three consequence-labeled choices,
   then Other:
   1. **Never — never include this skill in any resume**
   2. **Weak or Selective — include only when the JD specifically mentions it**
   3. **Approved — include in most resumes, if not all**
   4. **Other** (free text for clarification)
   With an interactive question tool whose built-in Other choice is automatic, provide only
   the three consequence-labeled choices in each question object; never show bare
   labels without consequences. Recommend a category in the prompt without reordering choices.
4. Wait for the complete response; the answers are permission to edit. If any are Other,
   clarify all unresolved terms in one follow-up batch (one question per skill) before editing.
   Once resolved, apply every answer in one profile edit and rebuild the tailoring card once.
5. In a background/non-interactive run, return the complete queue in one compact batch with
   one separated single-skill question per term; never spread it across later turns.

If newly Approved or Weak/Selective terms improve the resume, incorporate all relevant terms
in one edit, re-estimate layout, and render once. Weak/Selective remains JD-conditional even
when chosen for wording preference rather than proficiency.

Never silently add an uncategorized skill to the resume — check.py fails the render
if you try.

### Finish

Update the application log so job-search skips this draft next time (and records the company in
the search log): `.venv/bin/python skills/application-tracker/scripts/status.py --sync-log`.
When you reviewed a company's full board and decided **no suitable role** (no folder), record the
successful search instead: `status.py --log-search "<Company>" --outcome no_suitable`. Tell the
user which artifacts you produced and where (resume DOCX from `source/` to portals, PDFs for
humans; each JD's bundled `.txt` — cover letter + why-fit + past experience — is copy-paste ready),
then stop.

## Triggers → deeper reference (read ONLY the named § when the trigger fires — never the whole file)

- **Folder covers several roles at one company** → read ONLY [`reference.md`](reference.md) §
  "One resume, multiple roles (same company)" (Path A one-folder default; Path B splits +
  `target_position` only when the roles are too divergent for one honest resume).
- **Deep company + JD research (per JD)** → read ONLY [`reference.md`](reference.md) § "Deep company
  + JD research".
- **A `meta.yaml` field the Step-1 skeleton doesn't cover (later fields, enrichment)** → the
  `application-tracker` `SKILL.md` § "`meta.yaml` Schema" is the canonical owner.
- **Posting shows its own application/screening questions** → read ONLY [`reference.md`](reference.md)
  § "APPLICATION QUESTIONS section" (full cover templates / word-count tables / ATS guidelines live
  in the same file — only if a routine letter left you stuck).
- **A `tailored.yaml` edge case** (legacy `employer:`/`experience:`, hand char-math, how far to
  rephrase, supporting library) → read ONLY the matching [`reference.md`](reference.md) § ("tailored.yaml
  schema" / "One-page layout budget (char math)" / "Rephrasing…" / "Supporting library…").
- **A render / layout failure** (DOCX internals, calibrated constants, venv / LibreOffice) → read
  ONLY this skill's `LESSONS.md` § "Rendering / layout" or "Pre-render layout budget".
- **What check.py enforces** → run `check.py --rules` (never read the validator source).
- **Canonical application file tree** → `AGENTS.md` → "Application Folder Convention"; the `source/`
  + per-JD `.txt` layout summary is [`reference.md`](reference.md) § "Application folder layout".
