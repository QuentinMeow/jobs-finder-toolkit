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

## Before You Start

1. Read `AGENTS.md` for guardrails (no fabrication, consistency).
2. Read your candidate profile (`config.profile_md_path()`) — the comprehensive source of all experience, skills, and resume writing preferences.
3. Skim the supporting library for real, verifiable detail you can pull into bullets:
   - `interviews/behavioral-story-bank/` — deep, first-person write-ups of real projects
     (concrete scale, artifacts, and metrics). These are the richest source of legitimate
     detail beyond the profile.
   - `interviews/behavioral-answer-bank/`, prior tailorings in other
     `applications/<status>/<slug>/` folders, and `notes.md` files — additional real context.
   - Everything here describes work the user actually did; it is a valid source of truth
     alongside the profile. It is NOT license to invent — only to surface real detail.
4. Read `.agents/MEMORY.md` (if it exists) for cross-session learnings.
5. Read this skill's `LESSONS.md` for accumulated operational knowledge.
   - **Personalization / private overrides:** if this skill folder has a
     `references_private/` directory, read every file in it — those candidate-specific
     instructions, examples, and preferences OVERRIDE the generic examples in this
     SKILL.md. When it is absent (public / example mode), use the generic examples here
     as-is and take all candidate specifics from `config` and the profile
     (`config.profile_md_path()`).
6. **Pre-flight before any NEW application folder** (single posting, Path A, or Path B):
   - **Location gate** — confirm the posting satisfies the configured location policy
     (`config.location_policy()` — the allowed metros / US-remote / `us_only` rule) before
     drafting. A posting outside that policy (on-site/hybrid in a non-allowed metro with no
     remote option, or a role excluded by `us_only`) does NOT meet the search criteria; do
     not create the application (tell the user it was skipped for location). Record the real
     location in `meta.yaml`'s `location` field and verify with
     `.agents/skills/application-tracker/scripts/status.py --check-locations`.
   - `.agents/skills/job-search/companies.yaml` — if the company's registry entry has a
     `blacklist:` reason (match on name, aliases, or ATS token), do NOT create an
     application; tell the user it's blacklisted.
   - `<profile-dir>/applications-log.yaml` (`<profile-dir>` = `config.applications_root()/0_profile/`)
     — if this exact posting (same company + role, or same URL) is already logged, don't
     regenerate it. A *new* role at an already-applied company is fine to proceed with.
   - **Live folders (source of truth):** scan every
     `applications/{6_drafted,5_applied,4_in_progress,3_rejected,2_ignored}/<slug>/` (read each
     `meta.yaml` — company, `role` or `jobs:` entries, URLs). If the same posting
     already exists in any status folder, stop — point the user at that folder instead
     of creating a duplicate. If the log might be stale, run
     `.venv/bin/python .agents/skills/application-tracker/scripts/status.py --sync-log` first, then re-read the log; still
     cross-check folders before creating a new slug.
7. **Scratch stays in `tmp/`** (research probes, scraped HTML/JSON) — never the repo root, an
   application folder, or `scripts/`; application deliverables are not scratch. See `AGENTS.md`
   → "Scratch & Temporary Files".
8. **Subagent cap:** for multi-application work, at most **8 subagents total** per request —
   see `AGENTS.md` → "Subagent Budget".

## Application Folder Layout (source/ + per-JD bundled .txt)

**AGENTS.md → "Application Folder Convention" holds the canonical file tree** — read it. In
short: each folder keeps a clean **root** (the final PDFs, the bundled
`..._Application_<job title>.txt` file(s), `meta.yaml`, optional `notes.md`) and a **`source/`**
subfolder (JD files, `tailored.yaml`, all DOCX). **One resume covers the folder, but cover
letters are one-to-one with JDs** — one `..._Cover_Letter_<job title>.pdf` + one bundled
`..._Application_<job title>.txt` per `meta.yaml` role (single-role folder = one of each). The
`<job title>` suffix is the role's slug (via `layout.slugify_label`, e.g.
`Senior_Platform_Engineer`); `render.py` / `cover_letter.py` derive the role list from
`meta.yaml` and emit + place every file automatically — never hand-name or hand-place them.

## Workflow: Tailor Resume for a Job

**Pre-flight (required — do this before Step 1, Path A, or Path B):** complete
"Before You Start" item 6 (blacklist + applications log + existing status folders).
Do not `mkdir` or write JD/meta files until the company is allowed and this posting
(or slug) is not already covered. If the user only wants to refresh an existing draft,
edit that folder — do not create a second one.

**Default deliverables — generate all of these unless the user opts out.** Every tailoring
run produces, in `applications/6_drafted/<slug>/`:
1. **Resume** — DOCX (in `source/`) + PDF (at root). ONE resume covers the whole folder (Steps 1–6).
2. **One bundled application `.txt` per JD** (at root), `..._Application_<job title>.txt`, each
   with all three written sections (cover letter, why this company/role, past experience),
   one-to-one with each `meta.yaml` role / `source/JD-<job title>.md`. When you can see the
   posting's actual application questions, also answer them in the same bundle.
3. **One cover letter PDF per JD** (at root), `..._Cover_Letter_<job title>.pdf`, rendered from
   that role's bundle's COVER LETTER section.

**Cover letters are one-to-one with JDs** — a multi-role folder gets a distinct, individually
researched letter per posting, never one shared letter. Skip cover letters only when the user
explicitly asks ("resume only"). Tell the user which artifacts you produced and where. See the
"Bundled Application .txt" section below and [`reference.md`](reference.md) for the templates.

### Step 1: Create the Application Folder

**Pre-flight again:** confirm blacklist + log + no matching folder under any
`applications/<status>/` (see "Before You Start" item 6). Abort if duplicate or
blacklisted.

Generate a slug: `<company>-<role>-<YYYYMMDD>` (lowercase, hyphens, no special characters).
Confirm the slug path does not already exist under any status folder.

Newly generated applications always go under **`applications/6_drafted/`** — this is the
user's review queue. (The user later moves the folder into `applied/`, `in_progress/`,
`rejected/`, or `ignored/` themselves; the folder is the source of truth for status, so
do not add a `status` field to `meta.yaml`.)

Create the folder and its `source/` subfolder. Put the files listed below in place:

**Job description file(s)** — Save the full JD text in `source/`; postings get taken down.
**Always name JD files `JD-<job title>.md`** — for a single posting or multiple. The
`<job title>` is the posting's title, lowercased with hyphens (e.g.
`JD-senior-software-engineer-infrastructure.md`). One file per posting; never a bare
`jd.md`. `.agents/skills/resume-writer/scripts/check.py` reads and concatenates every `JD-*.md` in `source/`, so
Weak-skill validation honors a term mentioned in any of the JDs.

**Multiple jobs at one company — one resume by default, split only when the roles are very
different** (different companies always get their own folder). See "One Resume, Multiple Roles
(same company)" below for the full decision.

**`meta.yaml`** — Application metadata (no `status` field — the folder is the status).
Always a **uniform `jobs:` list** — one entry per posting, even a single role (a
one-element list). Structured facts (`workplace`, `sponsorship`, `job_level`,
`required_yoe`, `salary_range`) live inside each `jobs:` entry; company-scope fields stay
at the top. Note the company-scope `channel` (how you found the lead) is named apart from
each fact's `source` (provenance) so they never collide.

Minimal creation-time skeleton (single posting — a one-element `jobs:` list; a multi-role
folder is the same list with one entry per posting):
```yaml
job_metadata_schema_version: 3
company: "Company Name"
research_date: "YYYY-MM-DD"   # search date: when you generated this draft
channel: ""                   # how you found it (linkedin | referral | recruiter | cold)
referrer: ""
next_action: ""
notes: ""
jobs:
  - role: "Role Title"
    jd_file: "JD-role-title.md"
    location: "City, ST"      # the posting's location, exactly as listed (city/hybrid/remote)
    workplace: ""             # enriched below: onsite | hybrid | remote | unknown
    url: ""
    posted_date: ""           # when the JD was posted (from the posting site), if available
    sponsorship: ""           # enriched below: likely | unlikely | unknown (always confirm)
    fit: "strong"             # optional: your read on match strength (strong/good/partial)
    job_level: {}             # enriched below: normalized + Google-equivalent range + confidence + source
    required_yoe: {}          # enriched below: {min, max, confidence, source}
    salary_range: null        # enriched below: {min, max, confidence, source}, USD/year, or null
```

Write only this creation-time set: `location` verbatim per `jobs:` entry (must satisfy the
location policy — see "Location gate"), and every `jobs:` entry's exact `jd_file` (never
associate JDs by index or sorted filename). **The `application-tracker` skill
(`.agents/skills/application-tracker/SKILL.md`, "`meta.yaml` Schema") is the single canonical
owner of the full field list, rules, and later fields (`recruiter_email`, `comp_notes`,
`stage`)** — don't restate the schema here. After the full JD is saved, fill the empty
placeholders by handing off to its enrichment (never add a `status` field — status is the
folder). Here `applications/` stands for `config.applications_root()` — with the example
config, `examples/applications/`:

```bash
.venv/bin/python .agents/skills/application-tracker/scripts/status.py \
  --enrich-metadata applications/6_drafted/<slug>/
```

**Location gate (hard requirement — respect the search criteria).** Only draft an
application whose posting location satisfies the configured location policy
(`config.location_policy()` — the allowed metros, US-remote, and `us_only` rule). A role
that is on-site or hybrid in a non-allowed metro with no allowed-metro office and no
US-remote option, or a role excluded by `us_only`, does NOT meet the criteria — do not
create the application (tell the user it was skipped for location). Record the real
posting location in `location` and verify the whole drafted folder with
`.venv/bin/python .agents/skills/application-tracker/scripts/status.py --check-locations`; every drafted app must
report `match`. For a multi-role company, keep only the postings that match the policy.

**Output file names (fixed convention — recruiter-friendly, NOT `resume.pdf`).** `render.py`
emits all filenames automatically from the configured stems — never hand-name or hand-place
them (layout in "Application Folder Layout" above): ONE resume `<RESUME_STEM>.{docx,pdf}`, and
**one per `meta.yaml` role** a bundled `<APPLICATION_STEM>_<job title>.txt` (author this — the
source of truth for that JD's cover letter + copy-paste answers) plus a rendered
`..._Cover_Letter_<job title>.{docx,pdf}`. The `<job title>` suffix is the role slug via
`layout.slugify_label`. The separate `target_position` mechanism labels only the RESUME for the
divergent multi-role split (Path B) — see [`reference.md`](reference.md); leave it unset
otherwise.

### Step 2: Analyze the Job Description

Read the JD and identify:
1. **Required skills**: explicit "must have" or "required" items
2. **Preferred skills**: "nice to have", "bonus", "preferred" items
3. **Key responsibilities**: what the role does day-to-day
4. **Domain keywords**: specific technologies, methodologies, frameworks
5. **Seniority signals**: years of experience, leadership expectations
6. **Structured level facts**: stated/company job level, normalized seniority, required
   YOE min/max, and an approximate Google-equivalent float range. Prefer a matched,
   sourced company-cache mapping over generic title conversion; when the title is
   unlevelled, use explicit required YOE as the conservative fallback.
7. **Compensation facts**: posted base-salary/pay range and separately stated total
   compensation/OTE. Do not derive total compensation from assumed equity or bonus.
8. **Skill-list status**: compare each concrete skill/technology against the profile's
   Approved / Weak / Never lists. Deduplicate close variants and preserve first-seen JD
   order for the one-at-a-time uncategorized-skill queue in Step 7. Do not infer a category
   merely from how familiar or unusual a term sounds.

### Step 3: Gap Analysis

Compare JD requirements against your candidate profile (`config.profile_md_path()`) and present
this to the user before rewriting — a "Keyword Coverage Analysis" with four sections: **Strong
Matches** (skills/experience directly in both), **Can Reframe** (JD terms an existing project
maps to), **Gaps (be honest)** (what's missing or only adjacent), and **Recommended Strategy**
(which angle to lead with and which projects most directly match the JD).

### Step 4: Select Projects

The profile's projects are tagged `[draft]` or `[backup]`. Select the projects for this application:

- **Default**: Use **all** the `[draft]` projects (the full set — the profile is sized so
  they fill one page). Tailoring means small wording tweaks and rephrasing a project's
  bullets to fit the JD — **NOT** adding, inventing, or removing projects.
- **Never drop a project to tailor.** Keep the full project set. Remove a project ONLY as a
  last resort when the content genuinely will not fit on one page (see Step 6) — and when
  you must, drop the single least JD-relevant one, then shorten before removing more.
- **Never fabricate a project.** Only real profile projects (`[draft]` / `[backup]`) may
  appear; check.py fails on any title that isn't in the profile.
- **Swap rule**: Replace a `[draft]` project with a `[backup]` project ONLY if the backup is significantly better aligned with the JD (a 1-for-1 swap, not an addition/removal). Explain the swap to the user.
- **Ordering**: Lead with the profile's designated strongest/lead project (the profile marks which project should lead every resume); it leads regardless of role. Order the remaining projects by relevance to the JD (keep the most JD-relevant projects near the top). Candidate-specific ordering rules, if any, live in this skill's `references_private/`.

### Step 5: Generate `tailored.yaml`

**Folder must already exist from Step 1** (with Step 1 pre-flight completed — do not pick a
new slug or `mkdir` a second application folder here). The command below only ensures
`source/` exists inside that folder.

**Always start from the baseline — never write from scratch:**

```bash
mkdir -p applications/6_drafted/<slug>/source
# <baseline> = config.baseline_path() (resolve it from config; real data under private/)
cp <baseline> applications/6_drafted/<slug>/source/tailored.yaml
```

`config.baseline_path()` is the exact transcription of the user's approved resume.
Tailoring means making **targeted edits** to that copy, within the Tailoring Limits
below. The schema:

```yaml
name: "Jordan Rivers"
contact_line: "City, ST • jordan.rivers@example.com • linkedin.com/in/jordanrivers"

summary_bullets:
  - "First bullet — lead with most relevant framing for this role"
  - "Second bullet — highlight differentiating experience"
  - "Third bullet — breadth of platform/collaboration skills"

education_line: "B.S. in Computer Science, Lakemont University, 2015"

skills:
  - label: "Programming Languages"
    items: "Python, Java, Go, JavaScript, TypeScript, SQL, Bash, HTML, CSS"
  - label: "Skills"
    items: "AWS, Docker, Kubernetes, Terraform, PostgreSQL, Redis, gRPC, REST APIs, microservices, distributed systems, event-driven architecture, CI/CD, observability"

employer:
  company: "Northwind Systems"
  role: "Senior Software Engineer"
  dates: "2018 – Present"
  location: "City, ST"
  projects:
    - title: "Project Title"
      bullets:
        - "Action verb + what you did + impact/scale"
        - "Another bullet"
        - "Optional third bullet"
```

**Bold markers**: `**text**` in any bullet or summary line renders as bold. The baseline
already bolds key phrases; when rewording a bullet, keep 1-3 bold phrases and prefer
bolding the JD-relevant keywords.

### Tailoring Limits (user's personalized rules — hard constraints)

The user wants targeted per-JD tailoring: keep the resume anchored to the baseline, but
rephrasing experience bullets and adding real detail from the library is encouraged where it
improves JD fit (see "Rephrasing & detail enrichment" below). It is still not a from-scratch
rewrite, and the hard constraints below always hold. `.agents/skills/resume-writer/scripts/check.py` enforces most of them
automatically; violating them fails the render.

**Locked — never change (validated against `config.baseline_path()`):**
- Name, contact line, education line
- Employer, job title, dates, location
- Project titles — must exactly match a `[draft]` or `[backup]` project in the profile

**Fixed structure (validated):**
- Exactly 3 summary bullets
- 4-6 projects (default = the full `[draft]` set, normally 5), 2-3 bullets each (default 3).
  Keep every project; projects are not dropped to tailor — remove one only when the content
  cannot fit on one page (Step 6).
- Each bullet 45-215 characters (bold markers excluded); project titles ≤ 95
- Rendered PDF must be exactly 1 page AND fill the page — no large blank band at the bottom.
  check.py fails a resume that ends too high (>1.5in of trailing whitespace); target bullets
  that run ~2 rendered lines so the page fills. Fix a too-blank resume by lengthening bullets
  with real, traceable detail — never by adding filler or dropping to fewer projects.
- **One-page budget (predict BEFORE rendering — see "Pre-render layout budget" below).**
  On the shipped Arial-10 template the page holds ~734pt of content. A full body line
  wraps at **~110 chars** (bulleted) / **~115 chars** (skills/education); each wrapped
  body line costs ~11.5pt, a skills/education line ~13.2pt. As a fast mental check, the
  default full-project resume (3 summary bullets + 2 skills lines + 5 projects × 3 bullets)
  fits when nearly every bullet stays ≤ 2 rendered lines: keeping most bullets in the
  **~150-175 char** range lands the whole resume near the budget. Run `estimate_layout.py`
  (below) to get the exact number instead of guessing.

**Honesty (validated where possible):**
- The profile's Skills section has three lists that gate every skill mention:
  - **Approved** — safe to include in any resume
  - **Weak** — JD-conditional: include ONLY when the JD explicitly mentions the term
    (check.py verifies against every `source/JD-*.md`). "Weak" does **not** necessarily
    mean low proficiency; it may instead mean the wording is unusual, awkward, overly
    specific, or otherwise undesirable on the regular resume unless that exact term
    appears in the JD.
  - **Never** — skills the user doesn't know; must not appear anywhere on the resume
    (skills line, summary, or bullets — check.py scans all text)
- A skill in none of the three lists fails validation — never add it silently; see
  Step 7 (categorize new skills with the user)
- Every bullet must map to real content the user actually did — reword, never invent.
  The source of truth is your candidate profile (`config.profile_md_path()`) **plus** the supporting library
  (`interviews/behavioral-story-bank/`, answer bank, prior applications, notes). A detail
  is allowed on the resume if it is documented in one of these real sources.
- You MAY enrich a bullet with a concrete, real detail pulled from the story bank (e.g.,
  a scale figure like "~N services across M regions", a named artifact, or a real
  tool) as long as it is traceable to that source and does not contradict the profile.
- Still forbidden: metrics, technologies, titles, or scope that do NOT appear in the profile
  or the library. If the story bank flags a number as an estimate/unverified, keep the
  profile's framing rather than inventing precision. Skills remain gated by the three lists.

**Rephrasing & detail enrichment in Experience (allowed — user-approved):**
- You may **lightly rephrase experience bullets** to mirror JD terminology and sharpen
  impact, beyond just swapping single terms. Keep the same underlying fact; change the
  wording. Preserve the strong-action-verb + impact shape and 1-3 bold phrases per bullet.
- You may **add real detail from the supporting library** (see "Before You Start") to make
  a bullet more concrete and JD-relevant — e.g., pull specific scale, a named artifact, or a
  real tool from `interviews/behavioral-story-bank/` when it strengthens the match. The
  detail must be traceable to a real source and must fit the 45-215 char limit.
- This is still not a rewrite: change wording and add real specifics, but do not invent
  facts, and do not turn every bullet over. The check.py 60%-reworded warning is now a soft
  signal, not a target — rephrase where it genuinely improves JD fit, leave the rest.

**Light-touch defaults (your judgment):**
- Reorder projects so the most relevant come first (the profile's designated lead project
  always leads — see Step 4), and adjust which bold phrases carry emphasis.
- Swap in at most ONE `[backup]` project, and only when it is clearly a better fit;
  explain the swap to the user
- Skills lines: reorder so JD-relevant items come first; merge in JD-conditional Weak-list
  terms only when the JD explicitly mentions them, regardless of why the user classified
  the term as Weak

### Step 5.5: Pre-render layout budget (one-shot the single page)

Rendering (DOCX → PDF) is slow, so predict the page fit from the YAML **before** rendering with
`estimate_layout.py` (it reconstructs the template geometry live from the reference DOCX and
prints an estimated height + verdict):

```bash
.venv/bin/python .agents/skills/resume-writer/scripts/estimate_layout.py applications/6_drafted/<slug>/
```

- **OK** — 1 page with margin; proceed. **TIGHT** — trim ~1 line. **OVERFLOW** — will be 2
  pages; shorten the longest bullets/summary before rendering. **SPARSE** — may trip check.py's
  "too blank"; lengthen bullets with real detail.

Target **est ≤ ~715pt** (about one rendered line under the ~734pt budget) for a confident
one-shot single page. `render.py` prints this estimate up front too; check.py's post-render page
count stays the authoritative gate. See LESSONS.md → "Pre-render layout budget" for the
calibrated constants and the font / margin / line-spacing levers.

### Step 6: Render + Validate

Before rendering, validate that every posting record has complete structured metadata:

```bash
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --check-metadata
```

`check.py` strictly enforces schema version 3: `meta.yaml` must be `job_metadata_schema_version: 3`
with a `jobs:` list, and each entry must carry a valid `workplace` and `sponsorship` word
plus complete `job_level`, `required_yoe`, and `salary_range` structures. `salary_range`
may be `null` when no pay range is posted; the `job_level` and `required_yoe` structures
must still exist with their bounds (unstated bounds are `null`).

```bash
# Renders resume DOCX (source/) + PDF (root) + cover letter, then runs check.py.
# Accepts the app folder or the source/tailored.yaml path.
.venv/bin/python .agents/skills/resume-writer/scripts/render.py applications/6_drafted/<slug>/
```

Rendering copies `config.reference_docx_path()` (the user's formatted resume) and replaces
content while preserving all fonts, spacing, margins, and bullet styles.

**Layout requirement — employer header alignment**: `render.py` right-aligns `dates | location`
with a computed tab stop (never space padding); don't reintroduce manual spaces in the
reference DOCX employer line. See LESSONS.md → "Rendering / layout" for the DOCX internals.

If validation FAILs, fix `tailored.yaml` and re-render until it passes (and re-run
`estimate_layout.py` after editing to confirm the fix lands under budget before rendering again):
- **2 pages** → shorten the longest bullets first; only drop the least JD-relevant project as
  a last resort when shortening isn't enough (never drop a project just to tailor). This
  should be rare if you cleared `estimate_layout.py` (Step 5.5) before rendering.
- **too blank at the bottom** (`Resume looks too blank at the bottom`) → the page is
  under-filled. **Lengthen bullets with real, traceable detail** (aim for ~2 rendered lines
  each) and keep all projects. Do NOT delete projects, and do NOT pad with filler or invented
  content — pull genuine specifics (scale, named artifacts, real tools) from the profile / story bank
- **bullet too long/short** → rewrite within 45-215 chars
- **locked field / title / skill failures** → revert to the baseline value

Checks can also be run standalone: `.venv/bin/python .agents/skills/resume-writer/scripts/check.py applications/6_drafted/<slug>/`

The render writes the resume DOCX to `source/` and the PDF to the folder root. For **each
role in `meta.yaml`**, if a bundled `..._Application_<job title>.txt` exists, `render.py`
also renders its COVER LETTER section to `source/..._Cover_Letter_<job title>.docx` +
`..._Cover_Letter_<job title>.pdf` (at root) in the same run (skip with `--no-cover-letter`;
render just one with `cover_letter.py --label "<Role>"`). `render.py`/`check.py` validate a
cover letter for every role, so make sure every JD has its own bundle before rendering. Tell
the user where these files are (submit the resume DOCX from `source/` to portals, PDFs for
humans) and that each JD's bundled `.txt` (cover letter + why-fit + past experience) is ready
to copy-paste into that posting's portal.

**Update the application log** after creating a new draft so job-search skips it next time
(and records the company in the search log):

```bash
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --sync-log
```

When you reviewed a company's full board and decided **no suitable role** (no folder),
record the successful search:

```bash
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --log-search "<Company>" --outcome no_suitable
```

For the **divergent multi-role split** (Path B), set `target_position` in each
`tailored.yaml` and render the folders separately — see [`reference.md`](reference.md) →
"Path B". Remind them to review before submitting.

**When the user updates their master resume**: copy the new DOCX to `config.reference_docx_path()`
AND update `config.baseline_path()` to match its content exactly (this is the one-time
"rewrite" step; everything after is automatic).

### Step 7: Categorize New JD Skills One at a Time (ALWAYS do this at the end)

After rendering, extract every concrete skill/technology the JD mentions (languages,
frameworks, tools, platforms, methodologies — not soft skills) and compare against the
profile's three lists (Approved / Weak / Never, matching case-insensitively and counting
close variants like "Go"/"Golang" or "K8s"/"Kubernetes" as the same skill). Use the
deduplicated, first-seen order recorded in Step 2.

For any JD skill in NONE of the lists, ask the user at the end of the run to categorize
it with these meanings:

- **Never** — user doesn't know it; never include
- **Weak** — JD-conditional; include only when a JD explicitly mentions it. This may
  represent limited familiarity, but it may instead reflect strange, awkward, overly
  specific, or undesirable wording that should not appear on the regular resume.
- **Approved** — user knows it well and is comfortable including it in any resume
- **Other** — the user needs clarification, wants to distinguish a phrase from a skill,
  or wants to discuss how it should be normalized before categorizing it

The interaction protocol is strict:

1. Ask about **exactly one skill at a time**, regardless of how many are pending. Never
   put multiple skill questions in one tool call, form, message, batch, or multi-select;
   never offer an "apply my whole split" shortcut.
2. Always display choices in this exact order to reduce mis-clicks:
   1. **Never**
   2. **Weak**
   3. **Approved**
   4. **Other** (free text for clarification)
   With an interactive question tool whose built-in Other choice is automatic, provide
   only Never, Weak, and Approved in that order so the tool appends Other last. Use one
   question object per call. If recommending a category, state the recommendation in the
   prompt without changing the choice order.
3. Wait for the user's answer before asking about the next skill. After a Never / Weak /
   Approved answer, update the corresponding list in the candidate profile
   (`config.profile_md_path()`); that answer is the required permission for this profile
   edit. Then ask the next queued skill, if any.
4. If the user selects Other, clarify that same skill and then ask it again with the same
   fixed choice order. Do not update the profile or advance the queue until it is
   categorized.
5. In a background or otherwise non-interactive run, do not dump all pending skills as
   simultaneous choices. Return only the first pending skill question, then continue one
   skill per user response in later turns.

After the queue is complete, if a newly Approved or Weak term would improve the
just-rendered resume, offer to re-tailor with it. A newly Weak term remains JD-conditional
even when the reason is wording preference rather than proficiency.

Never silently add an uncategorized skill to the resume — check.py fails the render
if you try.

## One Resume, Multiple Roles (same company)

When a candidate wants several openings at the **same company**, decide up front whether
one resume can serve them all. **Default to one resume**; split only when the roles are
truly divergent.

**Decision rule.** Do the postings share a coherent theme — overlapping requirements, the
same job family, a common honest angle you can lead with?
- **Yes (default) → ONE resume covering the whole set** (path A below). Most same-company
  clusters land here, e.g. three adjacent platform/infra roles applied to in one pass.
- **No — the roles are fundamentally different**, so no single honest resume serves both
  (e.g. a backend/platform role vs. a frontend web role with little overlap) → **split
  into a separate application folder per role** (path B below) and
  label each resume with its target position.

### Path A — one resume, one folder (default)

Handle the whole set as a **single application folder** — not one folder per role:

0. **Pre-flight (required before any folder or JD files):** run "Before You Start" item 6
   (blacklist + applications log + existing status folders). Do not `mkdir` until checks pass;
   a combined folder must not duplicate an existing same-company multi-role app unless you are
   intentionally extending it (default: stop and use the existing folder).

1. **JD files** — save one `source/JD-<job title>.md` per posting (full JD text + URL).
   `.agents/skills/resume-writer/scripts/check.py` reads and concatenates every `source/JD-*.md`, so a Weak skill
   mentioned in *any* of the JDs validates.
2. **`meta.yaml`** — use the `jobs:` list form (see Step 1). One entry per posting with
   `role`, `jd_file` (the `JD-<job title>.md` name), `url`, `posted_date`, the four
   structured job metadata fields, and an optional `fit` note. Keep company-wide fields
   (`company`, `research_date`, `source`, `notes`) at the top level. Run
   `status.py --enrich-metadata <folder>` after every JD is saved.
3. **Analyze + gap-analyze every JD** (Steps 2-3), then tailor the **one resume** to the
   **shared, honest theme** across all of them. Order projects and skills by what the roles
   have in common; call out in `tailored.yaml`'s header comment which role each choice serves
   and what is deliberately NOT claimed for the weaker-fit roles.
4. **Categorize new skills (Step 7) across the union of all JDs.** Deduplicate close
   variants, then follow Step 7's strict one-question-at-a-time protocol and fixed
   Never → Weak → Approved → Other choice order; a larger multi-role union is never a
   reason to batch questions.
5. **Write one bundled `..._Application_<job title>.txt` per JD** — cover letters are
   one-to-one with postings. Research each JD individually and write a distinct, tailored
   COVER LETTER + WHY + PAST EXPERIENCE for it; do NOT reuse one letter across the set. The
   `<job title>` suffix matches each `meta.yaml` role slug.
6. **Render + validate** — there is one `tailored.yaml` / one rendered resume for the folder,
   but `render.py` produces one cover letter per JD (one per `meta.yaml` role) and validates
   each. Confirm every role has its own bundle before rendering.

### Path B — two resumes, split folders (very different roles)

Only when a same-company cluster is too divergent to tailor honestly with one resume: split
into a separate single-posting application folder per role and set `target_position` in each
`tailored.yaml` so the RESUME filename carries a distinguishing suffix (e.g.
`..._Resume_Backend_Engineer.pdf`). Cover letters and bundled `.txt` files stay per-JD labeled
from `meta.yaml` either way. **See [`reference.md`](reference.md) → "Path B" for the full
per-folder procedure (pre-flight, `target_position`, independent render/validate).**

## Deep Company + JD Research (do this before writing any prose, once PER JD)

Before writing each JD's cover letter, why-fit, or past-experience sections, research the
company's **product** and that **specific JD**. The written content must demonstrate that
the candidate understands what the company builds and how *that* role fits — not generic
enthusiasm. Draw on the JD text itself and honest company research (product, mission,
customers, recent launches, the team's problem space). Reference concrete, real specifics;
never invent product claims or flatter vaguely. Every claim about the candidate stays
traceable to the profile or supporting library (no fabrication). **When a folder covers
several JDs, do this research per posting and write a distinct letter for each — the whole
point of the one-to-one mapping is that each letter speaks to its own role and team.**

## Bundled Application .txt + cover letters (one per JD)

Generate **one bundled plain-text file per JD** on every tailoring run unless the user opts
out — one per `meta.yaml` role, at the folder root, named `<APPLICATION_STEM>_<job title>.txt`
(the `<job title>` suffix is the role slug via `layout.slugify_label`). Each bundle holds three
canonical copy-paste sections, each introduced by a title line + `===` underline (COVER LETTER,
WHY THIS COMPANY & ROLE, PAST EXPERIENCE), and is the source of truth for that JD's cover
letter: `render.py` / `cover_letter.py` render its COVER LETTER section into
`..._Cover_Letter_<job title>.{docx,pdf}`. Each letter is individually researched and written
per posting — never reuse one across JDs. Skip cover letters only when the user explicitly asks.

**When you can see the posting's actual application/screening questions** (the user pastes them,
shares a portal screenshot, or the JD lists them), also answer those exact questions in the same
bundle — an extra APPLICATION QUESTIONS section appended after the three canonical ones.

**See [`reference.md`](reference.md) for the full templates and hard rules:** the bundled-`.txt`
template with per-paragraph word counts, the cover-letter mandatory structure / enforced length
/ technique (`check_cover_letter`), the WHY and PAST EXPERIENCE section shapes, the APPLICATION
QUESTIONS mechanism, and the ATS optimization guidelines.
