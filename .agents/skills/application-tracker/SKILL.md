---
name: application-tracker
visibility: public
description: Track job applications, manage statuses, review pipeline health, and record interview, company, recruiter, compensation, or next-action notes. Use when the user asks about application status, pipeline health, or updating applications/<status>/<slug>/meta.yaml or notes.md.
---

# Application Tracker Skill

## When to Use

Use this skill when the user asks to:
- Check application status or pipeline
- Update an application's status
- Record interview notes, contacts, or compensation info
- Review pipeline health or conversion rates
- Find which resume was used for a specific application

## Before You Start

1. Read `AGENTS.md` for the application folder convention.
2. Read this skill's `LESSONS.md` for operational knowledge.
   - **Personalization / private overrides:** if this skill folder has a
     `references_private/` directory, read every file in it — those candidate-specific
     notes and examples OVERRIDE the generic examples in this SKILL.md. When it is
     absent (public / example mode), use the generic examples here and take all
     candidate specifics from `config` and the profile.
3. **Scratch stays in `tmp/`** (never the repo root or an application folder) — see `AGENTS.md`
   → "Scratch & Temporary Files".

## Application Folder Convention

**Status is the folder an application lives in** — not a field. Each application is a
folder `<company>-<role>-<YYYYMMDD>/` that sits inside one status folder:

```
applications/6_drafted/<slug>/      # tailored, awaiting the user's review/decision
applications/5_applied/<slug>/      # submitted
applications/4_in_progress/<slug>/  # heard back / interviews scheduled
applications/3_rejected/<slug>/     # rejected at any stage
applications/2_ignored/<slug>/      # decided not to submit; don't reconsider
```

(The profile dir `<applications_root>/0_profile/` and `config.discoveries_dir()` are support
folders, not applications — skip them.)

Each application folder keeps a clean **root** (finished deliverables + tracking) and a
**`source/`** subfolder (generation inputs/intermediates):

| Location | File | Purpose |
|----------|------|---------|
| root | `meta.yaml` | Application metadata this skill manages (status is the folder, not a field) |
| root | `<RESUME_STEM>.pdf` | Final resume PDF (committed) |
| root | `<COVER_STEM>_<job title>.pdf` | Final cover letter PDF (committed), one per JD |
| root | `<APPLICATION_STEM>.txt` | Bundled copy-paste answers: COVER LETTER + WHY THIS COMPANY & ROLE + PAST EXPERIENCE sections |
| root | `notes.md` | Optional: interview notes, company research, prep notes |
| `source/` | `JD-<job title>.md` | Full job-description text, one file per posting, always `JD-`-prefixed |
| `source/` | `tailored.yaml` | Tailored resume content (created by resume-writer) |
| `source/` | `<RESUME_STEM>.docx` | Editable resume DOCX (submit this to ATS portals) |
| `source/` | `<COVER_STEM>_<job title>.docx` | Editable cover letter DOCX, one per JD |

Filenames may carry a target-position suffix (e.g. `..._Resume_Frontend_Engineer.pdf`)
when one company's roles were split into two divergent resumes. `status.py` detects the
resume (`docx`/`pdf`), cover letter (`cl`), and bundled application (`txt`) artifacts by
glob, so labeled names count.

## `meta.yaml` Schema

Do **not** store the top-level status in `meta.yaml` — the status folder is the source of
truth. `meta.yaml` holds the rest of the metadata, plus an optional free-form `stage` note
for finer tracking while in `in_progress/` (e.g. "screen", "onsite", "offer").
This skill is the canonical owner of the metadata schema. Resume-writer creates the
initial file; job-search supplies posting facts; application-tracker validates and
enriches them.

`meta.yaml` is a file a **human** skims to decide "what is this and should I apply?", so it
is deliberately flat and small. Company-scope fields sit at the top; everything that varies
per posting lives in a **uniform `jobs:` list — one entry per posting, always a list even
for a single role.** Every structured fact is `{min, max, confidence, source}` (job_level
also carries a plain-English `normalized` word); `workplace` and `sponsorship` are single-word
reads. There is no per-field provenance, no per-field dates, and no per-field links: the only
dates are the top-level `research_date` (search date) and each posting's `posted_date`. The
company-scope `channel` (how you found the lead) is named apart from the per-fact `source`
(provenance) on purpose, so the two never collide.

```yaml
job_metadata_schema_version: 3
company: "Google"
research_date: "2026-04-16"  # search date: when the draft was generated
channel: "linkedin"          # how you found it (free text; e.g. linkedin | referral | recruiter | cold)
referrer: "John Doe"         # who referred you (if applicable)
recruiter_email: ""          # recruiter contact
comp_notes: ""               # compensation expectations / negotiation notes
next_action: "Follow up with John on 04/23"
stage: ""                    # optional finer stage within in_progress (screen/onsite/offer)
notes: ""                    # short inline notes (string or list of strings)
jobs:
  - role: "ML Infrastructure Engineer"
    jd_file: "JD-ml-infrastructure-engineer.md"  # unique JD-<title>.md in source/
    location: "Remote (US)"
    workplace: "remote"      # onsite | hybrid | remote | unknown (arrangement, not the city)
    url: "https://..."
    posted_date: ""          # when the JD was posted (from the posting site), if known
    sponsorship: "unknown"   # likely | unlikely | unknown (heuristic; always confirm)
    fit: "strong"            # optional quick read: strong | good | partial
    job_level:
      normalized: "senior"   # intern|entry|mid|senior|staff|senior_staff|principal|distinguished|unknown
      min: 4.8               # approx Google-equivalent ladder level (float); null if unknown
      max: 5.4
      confidence: "medium"   # high | medium | low | unknown
      source: "company_reference"  # company_reference | title | required_yoe | generic
    required_yoe:
      min: 5                 # null when the JD states no bound
      max: 8
      confidence: "high"
      source: "job_description"    # job_description | company_reference | not_stated
    salary_range:            # null when no pay range is posted (assumed USD/year)
      min: 185000
      max: 240000
      confidence: "high"
      source: "job_description"    # job_description | company_reference
```

`research_date` is the canonical search date; `status.py` falls back to the slug date when
rendering the pipeline table.

Metadata rules:
- Metadata uses the integer top-level `job_metadata_schema_version: 3`. There is **no
  backward compatibility**: validators only accept version 3, and by default only validate
  applications in the `drafted` folder (`status.py --check-metadata`); other status folders
  are ignored unless explicitly targeted.
- **Always a `jobs:` list** — one entry per posting, even a single-role application (a
  one-element list). `job_level`, `required_yoe`, and `salary_range` live inside each
  `jobs:` entry, never at company scope. `total_compensation_range` is not part of the
  schema.
- Every structured field is exactly `{min, max, confidence, source}`; `job_level` adds
  `normalized`. `confidence` is one of `high|medium|low|unknown`.
- Each `jobs:` entry also carries two single-word reads: `workplace`
  (`onsite|hybrid|remote|unknown` — the arrangement, distinct from the `location` city) and
  `sponsorship` (`likely|unlikely|unknown` — a heuristic JD scan; always confirm with the
  employer). Both are required and enrichment fills them.
- The company-scope `channel` field (how the lead was found, e.g. `linkedin|referral|recruiter|cold`)
  is named separately from the per-fact `source` (provenance) so the two never collide.
- Use numbers, not strings such as `"$185k"`, for bounds. A missing bound is `null`. A
  posting with no pay range has `salary_range: null` (not a min/max of null).
- `job_level.min/max` are the approximate **Google-equivalent ladder level** as floats
  (e.g. `4.8`–`5.4`), even when integral (`5.0`), because the cross-company conversion is
  approximate. `normalized` is the human-readable seniority word.
- `salary_range` is assumed **USD per year**; it drops currency/period/geography (US-focused
  postings). If a posting is genuinely hourly or non-USD, note it in `comp_notes`.
- JD facts win. Use the reusable company cache at `config.company_levels_path()`
  (default: `company-levels.yaml` beside the configured profile) only when the posting omits
  a level/YOE; salary comes from the posting itself.
- Run `status.py --enrich-metadata <slug-or-path>` after saving the JD. It uses a
  checksum-guarded, atomic, formatting-preserving editor and inserts only missing facts.
  Empty placeholders (`{}`, `""`, or `null` when a generated fact exists) count as missing;
  populated or manually edited facts are preserved.
  Bulk backfill is dry-run by default:
  `backfill_job_metadata.py --statuses drafted,applied,in_progress,rejected,ignored`.
  Review the preview before adding `--write`.
- Every `jobs:` entry must have a unique, existing, basename-only `jd_file`, and every
  `JD-*.md` in the folder must be associated with one role. There is no positional or
  sorted-filename fallback.

### One resume, multiple roles (same company)

The `jobs:` list is uniform, so a multi-role application is just a `jobs:` list with more
than one entry. When a company posts several jobs, the default is **one resume covering them
all** in a single folder; the resume-writer only splits into separate applications when the
roles are too different for one honest resume (those carry a `target_position` and
position-labeled filenames). The folder holds one `source/JD-<job title>.md` per posting,
each mapped one-to-one to a `jobs:` entry:

```yaml
job_metadata_schema_version: 3
company: "Cohere"
research_date: "2026-07-15"
channel: "cold"
next_action: ""
notes: ""
jobs:
  - role: "Senior Software Engineer, Agent Infrastructure"
    jd_file: "JD-senior-software-engineer-agent-infrastructure.md"
    location: "Remote (US)"
    workplace: "remote"
    url: "https://..."
    posted_date: ""
    sponsorship: "unknown"
    fit: "strong"            # optional read on match strength
    job_level: {normalized: senior, min: 5.0, max: 5.7, confidence: low, source: title}
    required_yoe: {min: 5, max: null, confidence: high, source: job_description}
    salary_range: null
  - role: "Site Reliability Engineer, Inference Infrastructure"
    jd_file: "JD-site-reliability-engineer-inference-infrastructure.md"
    location: "Remote (US)"
    workplace: "remote"
    url: "https://..."
    posted_date: ""
    sponsorship: "unknown"
    fit: "good"
    job_level: {normalized: unknown, min: null, max: null, confidence: low, source: title}
    required_yoe: {min: null, max: null, confidence: unknown, source: not_stated}
    salary_range: null
```

`status.py` renders such an application as its first role plus `"(+N more)"`.

### Status Values (each is a folder under `applications/`)

| Status folder | Meaning |
|---------------|---------|
| `drafted` | Resume tailored but not yet submitted (the user's review queue) |
| `applied` | Application submitted |
| `in_progress` | Heard back — recruiter screen, technical/onsite interviews, or offer stage |
| `rejected` | Rejected at any stage |
| `ignored` | Decided not to submit; don't reconsider this posting |

## Workflows

### Check Pipeline Status

```bash
.venv/bin/python .agents/skills/application-tracker/scripts/status.py
```

Prints a table of all applications with company, role, date, status, source, and files. Shows funnel summary if multiple statuses exist.

### Enrich / Validate Job Metadata

After the resume-writer saves `meta.yaml` and the full JD, populate any missing
level/experience/compensation facts:

```bash
# Single application: safe, insert-only, checksum-guarded write.
.venv/bin/python .agents/skills/application-tracker/scripts/status.py \
  --enrich-metadata applications/6_drafted/<slug>/

# Fleet preview: dry-run by default. Review before adding --write.
.venv/bin/python .agents/skills/application-tracker/scripts/backfill_job_metadata.py \
  --statuses drafted,applied,in_progress,rejected,ignored

.venv/bin/python .agents/skills/application-tracker/scripts/status.py --check-metadata
```

The editor preserves comments, quotes, blank lines, newline style, and unrelated fields.
Unknown or unstated facts remain `null`/`not_stated`—never fabricate them. Validation is
strict: only schema version 3 is accepted, and `--check-metadata` validates the `drafted`
folder by default.

### Update Status

Status changes by **moving the application folder** into the target status folder. The
user usually does this by hand; you can also do it with:

```bash
.venv/bin/python .agents/skills/application-tracker/scripts/status.py --update <slug> <status>
```

where `<status>` is one of `drafted | applied | in_progress | rejected | ignored`.
Example: `.venv/bin/python .agents/skills/application-tracker/scripts/status.py --update google-ml-engineer-20260416 in_progress`
moves `applications/5_applied/google-ml-engineer-20260416/` to `applications/4_in_progress/`.

Only move a folder when the user asks — they manage their own pipeline moves.

### Record Interview Notes

Create or update `applications/<status>/<slug>/notes.md` (in whichever status folder the
application currently lives) with structured notes:

```markdown
# Google ML Infrastructure Engineer — Notes

## Company Research
- Team: ML Platform, under Cloud org
- Product: Vertex AI infrastructure layer

## Screen (2026-04-20)
- Recruiter: Jane Smith (jane@example.com)
- Topics: system design focus, K8s experience
- Outcome: Moving to onsite

## Onsite (2026-04-28)
- Round 1 (System Design): ...
- Round 2 (Coding): ...
- Round 3 (Behavioral): ...
```

### Find Which Resume Was Used

The `source/tailored.yaml` in each application folder IS the resume content used. To compare:
- Read `applications/<status>/<slug>/source/tailored.yaml` for the tailored version
- Read your candidate profile (`config.profile_md_path()`) for the base content
- Diff to see what was changed for that application

### Pipeline Health Review

When the user asks "how's my pipeline?" or "what's my status?":
1. Run `.venv/bin/python .agents/skills/application-tracker/scripts/status.py`
2. Highlight any applications needing action (check `next_action` fields)
3. Note stale applications (applied > 2 weeks ago with no status change)
4. Show conversion rates if enough data exists

## Job Discovery

Job discovery lives in the **`job-search`** skill (`.agents/skills/job-search/SKILL.md`).
It searches public ATS boards with profile-based criteria (role, keywords, location,
recency, and visa sponsorship), ranks matches, and writes them to `config.discoveries_dir()`.

Typical flow: `job-search` (find a posting) → `resume-writer` (create
`applications/6_drafted/<slug>/` and tailor) → the user reviews and, once applied, moves the
folder to `applications/5_applied/` → this skill (record metadata / pipeline notes).
