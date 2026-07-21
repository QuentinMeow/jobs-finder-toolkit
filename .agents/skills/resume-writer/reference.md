# Resume Writer — Reference (bundled .txt templates, application questions, Path B, ATS)

Detailed reference for the `resume-writer` skill — the on-demand detail behind the SKILL.md
Quickstart. SKILL.md points here for: application folder creation + layout, the `tailored.yaml`
schema, rephrasing / light-touch tailoring defaults, the one-page layout char-math, render
operational detail, the supporting library, deep company + JD research, one-resume-multiple-roles
(Path A / Path B), the bundled-`.txt` templates + word counts, the cover-letter structure/length
rules, the APPLICATION QUESTIONS mechanism, and the ATS optimization guidelines. Read the relevant
section when its trigger fires. Everything candidate-specific still comes from `config` + the
profile (`config.profile_md_path()`); `<profile-dir>` = `config.applications_root()/0_profile/` —
the skip-log + tailoring-card directory (the profile file itself may live elsewhere).

## Application folder layout (source/ + per-JD bundled .txt)

**AGENTS.md → "Application Folder Convention" holds the canonical file tree** — read it. In
short: each folder keeps a clean **root** (the final PDFs, the bundled
`..._Application_<job title>.txt` file(s), `meta.yaml`, optional `notes.md`) and a **`source/`**
subfolder (JD files, `tailored.yaml`, all DOCX). **One resume covers the folder, but cover
letters are one-to-one with JDs** — one `..._Cover_Letter_<job title>.pdf` + one bundled
`..._Application_<job title>.txt` per `meta.yaml` role (single-role folder = one of each). The
`<job title>` suffix is the role's slug (via `layout.slugify_label`, e.g.
`Senior_Platform_Engineer`); `render.py` / `cover_letter.py` derive the role list from
`meta.yaml` and emit + place every file automatically — never hand-name or hand-place them.

## Application folder creation (Step 1 detail)

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
Weak-or-Selective validation honors a term mentioned in any of the JDs.

**Multiple jobs at one company — one resume by default, split only when the roles are very
different** (different companies always get their own folder). See "One resume, multiple roles
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
them (layout in "Application folder layout" above): ONE resume `<RESUME_STEM>.{docx,pdf}`, and
**one per `meta.yaml` role** a bundled `<APPLICATION_STEM>_<job title>.txt` (author this — the
source of truth for that JD's cover letter + copy-paste answers) plus a rendered
`..._Cover_Letter_<job title>.{docx,pdf}`. The `<job title>` suffix is the role slug via
`layout.slugify_label`. The separate `target_position` mechanism labels only the RESUME for the
divergent multi-role split (Path B) — see "Path B" below; leave it unset otherwise.

## Supporting library (real detail sources)

Beyond the tailoring card / profile, skim the supporting library for real, verifiable detail you
can pull into bullets (open only on the SKILL.md trigger "the JD demands domains the card doesn't
cover", and read only the relevant sections):
- `interviews/behavioral-story-bank/` — deep, first-person write-ups of real projects
  (concrete scale, artifacts, and metrics). These are the richest source of legitimate
  detail beyond the profile.
- `interviews/behavioral-answer-bank/`, prior tailorings in other
  `applications/<status>/<slug>/` folders, and `notes.md` files — additional real context.
- Everything here describes work the user actually did; it is a valid source of truth
  alongside the profile. It is NOT license to invent — only to surface real detail.

## tailored.yaml schema

`config.baseline_path()` is the exact transcription of the user's approved resume. Tailoring means
making **targeted edits** to that copy, within the Tailoring Limits in SKILL.md Step 5. The schema:

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

employers:
  - company: "Northwind Systems"
    role: "Senior Software Engineer"
    dates: "2018 – Present"
    location: "City, ST"
    bullets: ["Action verb + what you did + impact/scale"]  # optional
    projects:  # optional named project blocks
      - title: "Project Title"
        bullets: ["Action verb + what you did + impact/scale", "Another bullet"]
```

`employers:` supports direct `bullets:`, named `projects:`, or both. Legacy `employer:` and
`experience:` remain accepted, but never together; every employer needs content and is locked.
**Bold markers**: `**text**` in any bullet or summary line renders as bold. The baseline
already bolds key phrases; when rewording a bullet, keep 1-3 bold phrases and prefer
bolding the JD-relevant keywords.

## Rephrasing, detail enrichment & light-touch defaults

The user wants targeted per-JD tailoring: keep the resume anchored to the baseline, but
rephrasing experience bullets and adding real detail from the library is encouraged where it
improves JD fit (see "Rephrasing & detail enrichment" below). It is still not a from-scratch
rewrite, and the SKILL.md Step 5 hard constraints always hold. `.agents/skills/resume-writer/scripts/check.py` enforces most of them
automatically; violating them fails the render.

**Rephrasing & detail enrichment in Experience (allowed — user-approved):**
- You may **lightly rephrase experience bullets** to mirror JD terminology and sharpen
  impact, beyond just swapping single terms. Keep the same underlying fact; change the
  wording. Preserve the strong-action-verb + impact shape and 1-3 bold phrases per bullet.
- You may **add real detail from the supporting library** (see "Supporting library (real detail
  sources)" above) to make
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
- Skills lines: reorder so JD-relevant items come first; merge in terms categorized as
  Weak or Selective only when the JD explicitly mentions them, regardless of why the user
  chose that category

## One-page layout budget (char math)

Predict the page fit BEFORE rendering (SKILL.md Step 5.5). On the shipped Arial-10 template the
page holds ~734pt of content. A full body line
wraps at **~110 chars** (bulleted) / **~115 chars** (skills/education); each wrapped
body line costs ~11.5pt, a skills/education line ~13.2pt. As a fast mental check, the
default full-project resume (3 summary bullets + 2 skills lines + 5 projects × 3 bullets)
fits when nearly every bullet stays ≤ 2 rendered lines: keeping most bullets in the
**~150-175 char** range lands the whole resume near the budget. Run `estimate_layout.py`
(SKILL.md Step 5.5) to get the exact number instead of guessing. Each additional employer
adds approximately 16pt; direct and project bullets consume the same body-line budget.
Calibrated constants and the font / margin / line-spacing levers: LESSONS.md →
"Pre-render layout budget".

## Render & validate — operational detail

`check.py` strictly enforces schema version 3: `meta.yaml` must be `job_metadata_schema_version: 3`
with a `jobs:` list, and each entry must carry a valid `workplace` and `sponsorship` word
plus complete `job_level`, `required_yoe`, and `salary_range` structures. `salary_range`
may be `null` when no pay range is posted; the `job_level` and `required_yoe` structures
must still exist with their bounds (unstated bounds are `null`).

Rendering copies `config.reference_docx_path()` (the user's formatted resume) and replaces
content while preserving all fonts, spacing, margins, and bullet styles.

**Layout requirement — employer header alignment**: `render.py` right-aligns `dates | location`
with a computed tab stop (never space padding); don't reintroduce manual spaces in the
reference DOCX employer line. See LESSONS.md → "Rendering / layout" for the DOCX internals.

The render writes the resume DOCX to `source/` and the PDF to the folder root. For **each
role in `meta.yaml`**, if a bundled `..._Application_<job title>.txt` exists, `render.py`
also renders its COVER LETTER section to `source/..._Cover_Letter_<job title>.docx` +
`..._Cover_Letter_<job title>.pdf` (at root) in the same run (skip with `--no-cover-letter`;
render just one with `cover_letter.py --label "<Role>"`). `render.py`/`check.py` validate a
cover letter for every role, so make sure every JD has its own bundle before rendering. Tell
the user where these files are (submit the resume DOCX from `source/` to portals, PDFs for
humans) and that each JD's bundled `.txt` (cover letter + why-fit + past experience) is ready
to copy-paste into that posting's portal.

**When the user updates their master resume**: copy the new DOCX to `config.reference_docx_path()`
AND update `config.baseline_path()` to match its content exactly (this is the one-time
"rewrite" step; everything after is automatic).

## Deep company + JD research (do this before writing any prose, once PER JD)

Before writing each JD's cover letter, why-fit, or past-experience sections, research the
company's **product** and that **specific JD**. The written content must demonstrate that
the candidate understands what the company builds and how *that* role fits — not generic
enthusiasm. Draw on the JD text itself and honest company research (product, mission,
customers, recent launches, the team's problem space). Reference concrete, real specifics;
never invent product claims or flatter vaguely. Every claim about the candidate stays
traceable to the profile or supporting library (no fabrication). **When a folder covers
several JDs, do this research per posting and write a distinct letter for each — the whole
point of the one-to-one mapping is that each letter speaks to its own role and team.** Keep
this to ~2 web fetches per letter unless the user asks for deep research.

## Bundled Application .txt (generated by default — one per JD)

Generate **one bundled plain-text file per JD** on every tailoring run unless the user opts
out — one per `meta.yaml` role, named
`<applications_root>/6_drafted/<slug>/<APPLICATION_STEM>_<job title>.txt`
(the `<job title>` suffix is the role slug via `layout.slugify_label`). Each file holds three
**canonical** copy-paste sections, each introduced by a title line + `===` underline (this
exact structure is what `cover_letter.py` parses) — plus, when you can see the posting's
actual application questions, an optional **APPLICATION QUESTIONS** section appended after
them (see "APPLICATION QUESTIONS section" below):

```
COVER LETTER
============

Jordan Rivers
City, ST • jordan.rivers@example.com • linkedin.com/in/jordanrivers

Dear <Company> Hiring Team,

<MAIN PARAGRAPH 1 — Interest + company/product understanding (70-140 words):
one full-sentence paragraph that names the specific role, shows genuine,
researched understanding of what the company builds and why it matters, and
connects that to why you want to contribute. Concrete product specifics,
never generic flattery.>

<MAIN PARAGRAPH 2 — Unique personal strength (80-150 words): one full-sentence
paragraph proving your single most differentiating strength for THIS role,
with a real, quantified achievement from the profile/story bank mapped to the
JD's top requirements. Tell the story behind a resume bullet; don't relist.>

<OPTIONAL closing (25-45 words): brief call to action + thanks.>

Sincerely,
Jordan Rivers


WHY THIS COMPANY & ROLE
=======================

<plain-text answer>


PAST EXPERIENCE
===============

<plain-text answer>
```

Rules for the file:
- Plain English throughout — no Markdown, no `**bold**`, no bullet glyphs. It must paste
  cleanly into portal text boxes.
- Keep the three canonical section titles + `===` underlines exactly as shown so the
  renderer can find the COVER LETTER section. You MAY append extra sections (e.g.
  APPLICATION QUESTIONS) AFTER these three — the parser only reads the COVER LETTER section
  and ignores the rest, so extra sections never break rendering. Never put a `===`/`---`
  rule directly under a question line, or it will be misparsed as a section header.
- **Name it `..._Application_<job title>.txt`, one per `meta.yaml` role** (the `<job title>`
  suffix is the role slug via `layout.slugify_label`, matching `..._Cover_Letter_<job title>`).
  This holds for both single-role and multi-role folders. `render.py`/`cover_letter.py` look
  up the exact labeled file per role — a labeled lookup never falls back to another role's
  bundle, so each role's file must exist and be named correctly.

### COVER LETTER section (renders to the per-JD cover-letter DOCX + PDF)

For each role, `render.py` / `.agents/skills/resume-writer/scripts/cover_letter.py` render this section into
`source/..._Cover_Letter_<job title>.docx` + `..._Cover_Letter_<job title>.pdf` (at root).
Render all of a folder's cover letters with
`.venv/bin/python .agents/skills/resume-writer/scripts/cover_letter.py <applications_root>/6_drafted/<slug>/`, or just one role's
with `.venv/bin/python .agents/skills/resume-writer/scripts/cover_letter.py <applications_root>/6_drafted/<slug>/ --label "<Role>"`.
Each JD's letter must be individually researched and written — no shared/boilerplate letter.

Write it so it parses cleanly:
- Line 1 = name; line 2 = the contact line (must contain `•` or the email). **Do NOT add a
  company/role subject line** — the rendered letter starts with the name + contact, then
  goes straight to the salutation.
- One blank line, then the salutation (`Dear <Company> Hiring Team,` — or a named person if
  the JD/company page names one; never "To Whom It May Concern").
- Body: **one paragraph per line** (do NOT hard-wrap a paragraph across lines), blank line
  between paragraphs. End with `Sincerely,` then the name.

**Mandatory structure (enforced by `.agents/skills/resume-writer/scripts/check.py`, `check_cover_letter`). This is not
optional — a telegraphic or too-short letter FAILS the render and must be rewritten:**

The body has **at least two developed main paragraphs**, written as professional,
full-sentence prose (NEVER telegraphic keyword fragments, sentence stubs, or
comma-spliced clause lists):

1. **Main paragraph 1 — Interest + company/product understanding (70-140 words).**
   Name the specific role, demonstrate genuine, *researched* understanding of what the
   company actually builds (product, customers, mission, a concrete recent detail) and why
   it matters, and connect that to why you are drawn to this role. Specific and
   substantive — never generic flattery or invented product claims.
2. **Main paragraph 2 — Unique personal strength (80-150 words).**
   Prove your single most differentiating strength for THIS role with a real,
   quantified achievement from the profile / story bank, mapped to the JD's top
   requirements. Tell the story behind a resume bullet rather than relisting bullets.

An **optional** brief closing paragraph (25-45 words) may follow with a call to action and
a thank-you. The salutation and one-line closings do NOT count toward the two main
paragraphs.

**Enforced length (hard limits — `check_cover_letter`):**
- Each of the two main paragraphs: within **60-180 words** (write to the paragraph targets above).
- **At least two** paragraphs must land in that 60-180-word band.
- Whole letter body: **200-450 words** total (target ~250-400; one page, never more).
- No placeholder text (`to be written`, `TODO`, unfilled `<...>`), or the check fails.

**Technique (research-backed — HBR, The Muse, Harvard Career Services, Novoresume, Zety,
2024-2026):**
- **Full sentences, active voice, strong verbs.** Recruiters read this after the resume; it
  must read like a person wrote it, not a keyword dump. This is the #1 quality bar.
- **Complement, don't repeat** the resume — tell the story behind a bullet, don't relist it.
- Mirror the JD's top / most-repeated requirements and prove each with a real, quantified
  example. Focus on what you bring to them.
- **Honesty**: if there's a real gap, name it briefly and reframe as fast-ramping — one clause,
  not a paragraph; never fabricate.
- **Keep logistics OUT of the persuasive body.** Do NOT put visa/H-1B sponsorship, relocation,
  or availability lines inside the main paragraphs — they read as unprofessional there and the
  check warns on them. If sponsorship must be stated, use the dedicated portal field, not the
  letter body.
- Never "To Whom It May Concern"; never "My name is… I have X years…" boilerplate openings.

### WHY THIS COMPANY & ROLE section

Answers **why this company, why this job, why the candidate is a strong fit** — a quick
reference to paste into portal "why do you want to work here?" boxes. Short and precise, not
an essay. **Exactly two paragraphs**, each opening with a one-sentence summary then expanding:

1. **Company + interest (summary → why).** One-line summary of what the company builds and
   why it's compelling, then a specific, researched detail about the product / mission /
   vision and genuine interest. Specific, not flattery.
2. **Background + fit (summary → why).** One-line summary of the candidate's most relevant
   background, then concrete real experience mapped to the JD's top requirements — why it's a
   strong fit for both the company (what he brings) and the candidate (why it fits his path).

### PAST EXPERIENCE section

A plain-English answer for portal "describe your relevant experience / tell us about your
background" boxes. Lead with the current role and scope, then summarize the most
JD-relevant achievements across prior roles and named projects in prose. A multi-employer
resume is still a career narrative, not a company-by-company transcript: include older work
only when it strengthens this JD's fit, while keeping employer/project ownership accurate.
Draw only on real content from the profile / `tailored.yaml` / supporting library; mirror
the JD's terminology where honest. Keep it tight (a lead paragraph plus a few short
experience/project paragraphs).

### APPLICATION QUESTIONS section (answer the portal's actual questions when you can see them)

The three sections above are the defaults you always write. **In addition, whenever you can
see the posting's actual application/screening questions** — the user pastes them, shares a
screenshot of the portal, or the JD/portal itself lists them — answer those specific
questions directly in the same bundle so they are saved and copy-paste ready. This applies
to the substantive prompts that need a crafted, tailored answer — the "why this role / why
this company / describe your relevant experience"-style free-text questions, plus any
role-specific prompt (e.g. "How do you manage thousands of hosts?", "What about this role
aligns with what you're looking for next?"). It does NOT apply to generic identity or
logistics fields that need no crafting (name, address, work authorization) — though a short,
direct answer to a yes/no, location, or compensation field the user asked about is fine.

Append these as a single extra section AFTER the three canonical ones, titled after the
company so it's obvious which posting they belong to:

```
<COMPANY> APPLICATION QUESTIONS
===============================

Q: <the exact question text from the portal>

<plain-text answer, tailored to the exact wording of the question>


Q: <next question>

<answer>
```

Rules:
- **Answer the exact question asked, in its own wording** — do not just paste the generic
  WHY / PAST EXPERIENCE text. When a portal question maps to one of the three canonical
  sections, adapt that content to the specific phrasing and length the question implies;
  when it's role-specific, write a fresh, tailored answer. Reuse the real detail already in
  the bundle/resume, but re-shape it to the question.
- Prefix each question with `Q: ` and put the answer on the following line(s). Only the top
  section title gets the `===` underline — **never** put a line of only `=` or `-` under a
  question, or the bundle parser will treat that question as a new section header.
- Plain English, copy-paste ready; every claim stays traceable to the profile / library
  (no fabrication), exactly like the rest of the bundle.
- One APPLICATION QUESTIONS section per bundle (per JD); each role's own
  `..._Application_<job title>.txt` carries the questions for its own posting.

## One resume, multiple roles (same company)

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

0. **Pre-flight (required before any folder or JD files):** run the SKILL.md Quickstart →
   Preflight (blacklist + applications log + existing status folders). Do not `mkdir` until checks pass;
   a combined folder must not duplicate an existing same-company multi-role app unless you are
   intentionally extending it (default: stop and use the existing folder).

1. **JD files** — save one `source/JD-<job title>.md` per posting (full JD text + URL).
   `.agents/skills/resume-writer/scripts/check.py` reads and concatenates every
   `source/JD-*.md`, so a Weak/Selective skill mentioned in *any* of the JDs validates.
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
   variants, gather the complete queue, then follow Step 7's batched one-question-per-skill
   protocol and fixed, consequence-labeled Never → Weak or Selective → Approved → Other
   choice order.
5. **Write one bundled `..._Application_<job title>.txt` per JD** — cover letters are
   one-to-one with postings. Research each JD individually and write a distinct, tailored
   COVER LETTER + WHY + PAST EXPERIENCE for it; do NOT reuse one letter across the set. The
   `<job title>` suffix matches each `meta.yaml` role slug.
6. **Render + validate** — there is one `tailored.yaml` / one rendered resume for the folder,
   but `render.py` produces one cover letter per JD (one per `meta.yaml` role) and validates
   each. Confirm every role has its own bundle before rendering.

## Path B — two resumes, split folders (very different roles)

Use this only when a same-company cluster is too divergent to tailor honestly with one resume
(see "One resume, multiple roles (same company)" above). Different companies always get their own folder.

0. **Pre-flight (required before any folders):** complete the SKILL.md Quickstart → Preflight for
   **each** planned role — the `blacklist:` field in `.agents/skills/job-search/companies.yaml`,
   `<profile-dir>/applications-log.yaml` (run `--sync-log` if stale), and live
   status folders via `meta.yaml` (same role or URL). Do not `mkdir` until checks pass.
   Each planned slug must be unused under all status folders.
1. **One application folder per role** (or per coherent group), each a normal
   single-posting application: `<company>-<roleA>-<date>/` and `<company>-<roleB>-<date>/`,
   each with its own `source/JD-<job title>.md`, `meta.yaml` (single-element `jobs:` list),
   `source/tailored.yaml`, and the full default deliverables (resume + a per-JD cover letter +
   bundled `..._Application_<job title>.txt`).
2. **Set `target_position` in each `tailored.yaml`** to the role name, so the rendered RESUME
   filename carries a distinguishing suffix (e.g. `..._Resume_Backend_Engineer.pdf` vs.
   `..._Resume_Frontend_Engineer.pdf`). The cover letter and bundled `.txt` are already
   job-title-labeled per JD from `meta.yaml` (each folder has one role → one cover letter).
3. **Tailor, render, and validate each folder independently.** Explain to the user why you
   split (which requirements are irreconcilable in one honest resume). Render each folder
   separately:

```bash
.venv/bin/python .agents/skills/resume-writer/scripts/render.py <applications_root>/6_drafted/<company>-<roleA>-<date>/
.venv/bin/python .agents/skills/resume-writer/scripts/render.py <applications_root>/6_drafted/<company>-<roleB>-<date>/
```

## ATS Optimization Guidelines

Modern ATS platforms (Workday, Greenhouse, iCIMS) do **contextual/semantic matching and
skills-graph scoring**, not just literal keyword lookup. So the goal is honest,
well-placed keyword coverage — not density. Score benchmarks vary, but a resume that
carries every *required* skill from the posting, parses cleanly, and puts its top
keywords in high-weight locations is the target.

### Keyword placement (highest-leverage — ATS weights *where* a keyword appears)
- The **summary is read first and carries the highest per-word weight** — put the role's
  top 3-5 keywords there, honestly framed.
- Keywords in a **properly labeled Skills section outrank the same words buried in a
  bullet** — surface JD-critical skills there (Approved list, or user-facing
  Weak/Selective + explicit JD mention).
- The **first bullet under each project** is weighted more than later bullets — lead with
  the most JD-relevant bullet per project (reorder within the 2-3 without rewriting).
- Any term appearing **2+ times in the JD is almost certainly weighted** — make sure the
  resume covers each of those at least once.

### Content (your job as the rewriter)
- Mirror the JD's exact terminology ("machine learning" not just "ML"; "React.js" not "React")
- Include both full terms and acronyms: "Continuous Integration/Continuous Deployment (CI/CD)"
- Lead bullets with strong action verbs: Built, Designed, Led, Implemented, Optimized
- Quantify: scale, %, $, time saved, team size
- Build a target keyword set of ~10-25 items you *genuinely* have; prioritize the top
  5-10 that repeat in the JD or are central to the role
- Avoid keyword stuffing — 1-2 natural mentions per keyword. Under semantic-matching ATS,
  stuffing is actively penalized, not just ineffective

### Format / parse safety (mostly handled by the template — verify, don't defeat)
- **Submit the .docx** to ATS portals — it parses more reliably than PDF across systems.
  The PDF is for human review / email. (render.py produces both.)
- Single-column, standard section headers ("Summary", "Education & Skills", "Experience"),
  no tables / text boxes / images-of-text / multi-column — the reference template enforces this
- Standard bullet glyphs only (•, -) — no checkmarks, arrows, or custom symbols
- Standard fonts, 10-12pt (template-controlled)

### Common Mistakes to Avoid
- Don't change job titles (that's fabrication)
- Don't add technologies the user hasn't used
- Don't inflate metrics (interviews will expose this)
- Don't use creative section headers ("Where I've Worked" instead of "Experience")
- Don't omit dates (ATS flags this)
- Don't claim "hands-on ML model development" when the experience is infrastructure-side
