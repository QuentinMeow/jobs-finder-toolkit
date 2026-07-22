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

**Each `jobs:` entry carries its own `status`; the status folder an application lives in is the
DERIVED overall status** — a rollup of the per-job statuses (see "Overall status" below). Each
application is a folder `<company>-<role>-<YYYYMMDD>/` that sits inside one status folder:

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
| root | `meta.yaml` | Application metadata this skill manages (per-job `status`; the folder is the derived rollup) |
| root | `<RESUME_STEM>.pdf` | Final resume PDF (committed) |
| root | `<COVER_STEM>_<job title>.pdf` | Final cover letter PDF (committed), one per JD |
| root | `<APPLICATION_STEM>_<job title>.txt` | Bundled copy-paste answers (COVER LETTER + WHY THIS COMPANY & ROLE + PAST EXPERIENCE), one per JD |
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

**Per-job `status` is the fine-grained source of truth; the status folder is the DERIVED overall
status.** Each `jobs:` entry carries a required `status`
(`drafted|applied|in_progress|rejected|ignored` — the same labels as the folders), a required
structured **`progress`** summary (see "Per-job progress" below — schema v5 replaced the retired
free-text `stage` with it), and an optional `status_date` (`YYYY-MM-DD`, stamped by tooling on
each transition). The parent folder is the overall status rolled up from those per-job values
(see "Overall status" below); the validator errors when the folder and the rollup disagree, and
the scripts keep them in sync — a manual folder move must be re-synced via `status.py --update`.
There is **no** top-level `status` or `stage` field, and a per-job `stage` key is rejected.
This skill is the canonical owner of the metadata schema. Resume-writer creates the
initial file; job-search supplies posting facts; application-tracker validates and
enriches them.

`meta.yaml` is a file a **human** skims to decide "what is this and should I apply?", so it
is deliberately flat and small. Company-scope fields sit at the top; everything that varies
per posting lives in a **uniform `jobs:` list — one entry per posting, always a list even
for a single role.** Every structured fact is `{min, max, confidence, source}` (job_level
also carries a plain-English `normalized` word); `workplace` and `sponsorship` are single-word
reads. There is no per-field provenance, no per-field dates, and no per-field links: the dates
are the top-level `research_date` (search date), each posting's `posted_date`, and each posting's
tooling-stamped `status_date`. The
company-scope `channel` (how you found the lead) is named apart from the per-fact `source`
(provenance) on purpose, so the two never collide.

```yaml
job_metadata_schema_version: 5
company: "Google"
research_date: "2026-04-16"  # search date: when the draft was generated
channel: "linkedin"          # how you found it (free text; e.g. linkedin | referral | recruiter | cold)
referrer: "John Doe"         # who referred you (if applicable)
recruiter_email: ""          # recruiter contact
comp_notes: ""               # compensation expectations / negotiation notes
next_action: "Follow up with John on 04/23"
notes: ""                    # short inline notes (string or list of strings)
jobs:
  - role: "ML Infrastructure Engineer"
    jd_file: "JD-ml-infrastructure-engineer.md"  # unique JD-<title>.md in source/
    status: "applied"        # REQUIRED: drafted | applied | in_progress | rejected | ignored
    status_date: "2026-04-20" # optional: date of this job's last status change (tooling-stamped)
    progress:                # REQUIRED structured summary (replaces the retired free-text stage)
      phase: application_review        # which hiring step (see "Per-job progress")
      state: waiting_employer          # what is happening now / who acts next
      # label: "Virtual technical screen"       # optional employer wording (required for phase: other)
      # calendar_item: "cal-google-ml-infrastructure-engineer-01"  # links the calendar.md entry
      # updated_at: "2026-04-20T17:03:00Z"      # tool-stamped; agents never invent timestamps
      # source: {kind: manual, ref: ""}         # manual | email (email requires the stored message key)
    location: "Remote (US)"
    workplace: "remote"      # onsite | hybrid | remote | unknown (arrangement, not the city)
    url: "https://..."
    store_key: ""            # optional: raw-data-layer store entity key (e.g. gh-1234567), copied by handoff.py from the search JSON — the durable link to the posting's biography; never hand-edited
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
- Metadata uses the integer top-level `job_metadata_schema_version: 5`. There is **no
  backward compatibility**: validators only accept version 5, and `status.py --check-metadata`
  validates **every** status folder by default (`--statuses <labels>` narrows to a subset).
  Migrate a v4 file with the preview-first `migrate_to_v5.py` (dry-run fleet diff; `--write`
  applies checksum-guarded atomic edits).
- Each `jobs:` entry carries a required `status` (`drafted|applied|in_progress|rejected|ignored`),
  a required `progress` mapping (see "Per-job progress"), and an optional `status_date`
  (`YYYY-MM-DD`, written by `status.py` transitions — never fabricate it; absent is valid). The
  status folder must equal the rollup of the per-job statuses (see "Overall status"); the
  validator errors on a mismatch, on any top-level `status`/`stage` key, and on the retired
  per-job `stage` key.
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

### Per-job progress (phase + state + calendar link)

`jobs[].progress` is the normalized "where is this role, and who acts next?" summary
(design: `design/application-progress-calendar/README.md`). `label` preserves employer-specific
wording so the enums never grow per company. Fields: required `phase` + `state`; optional
`label`, `calendar_item` (the linked `calendar.md` entry id), tool-stamped `updated_at`,
and `source` (`{kind: manual|email, ref}` — an email source requires the neutral stored
message key, never a subject/sender/body).

- **Phases** (which hiring step): `application_prep`, `application_review`, `recruiter_screen`,
  `assessment`, `hiring_manager`, `technical_interview`, `interview_loop`, `team_match`,
  `offer`, `background_check`, `onboarding`, `other` (a real employer-specific phase that
  does not fit yet — `label` is then REQUIRED).
- **States** (what is happening now): `unknown` (never guess), `action_required`,
  `booking_required` (owner must pick a slot / send availability), `awaiting_schedule`
  (availability sent, no confirmed time yet), `scheduled` (a specific future time AND
  timezone are confirmed — they live on the calendar entry), `reschedule_required`,
  `reschedule_pending`, `waiting_employer`, `awaiting_result`, `closed`.
- **Coupling**: rejected/ignored jobs have state exactly `closed` (their last phase is kept
  for funnel analysis); an active job is never `closed`. Changing only phase/state NEVER
  moves an application between status folders.

### The calendar file (`config.calendar_path()`)

One private `calendar.md` (default `<applications_root>/0_profile/calendar.md`) holds every
scheduling todo, confirmed interview time, follow-up date, and append-only reschedule history.
Sections project entry state: **Action needed** (`action_required|booking_required|
reschedule_required`), **Waiting for confirmation** (`awaiting_schedule|reschedule_pending`),
**Scheduled** (confirmed times, chronological), and **My notes and personal todos** (owner-only).
Tools own ONLY the `<!-- jobhunt-calendar ... -->` marked entries; unmarked lines are preserved
byte-for-byte. A confirmed reschedule marks the old occurrence `superseded` and appends the
replacement — old times are never overwritten; a time merely passing never completes an
interview. **This tracker is the only writer, and it updates `meta.yaml` + `calendar.md`
together, transactionally — both commit or neither.** Malformed markers, duplicate ids, a
scheduled entry without exact time + timezone, and checksum races all fail closed.

### Overall status (folder = derived rollup)

The status folder is the per-job statuses rolled up by precedence — any job at a higher tier
sets the folder:

```
in_progress > applied > drafted > rejected > ignored
```

So one role rejected + one in interview rolls up to `in_progress`; all roles rejected rolls up to
`rejected`; all ignored to `ignored`. `status.py --update` / `--update-job` recompute this and move
the folder to match, so the folder and the per-job statuses never disagree. A hand-moved folder
that no longer matches its rollup fails `status.py --check-metadata` until you re-sync it with
`status.py --update`.

### One resume, multiple roles (same company)

The `jobs:` list is uniform, so a multi-role application is just a `jobs:` list with more
than one entry. When a company posts several jobs, the default is **one resume covering them
all** in a single folder; the resume-writer only splits into separate applications when the
roles are too different for one honest resume (those carry a `target_position` and
position-labeled filenames). The folder holds one `source/JD-<job title>.md` per posting,
each mapped one-to-one to a `jobs:` entry:

```yaml
job_metadata_schema_version: 5
company: "Cohere"
research_date: "2026-07-15"
channel: "cold"
next_action: ""
notes: ""
jobs:
  - role: "Senior Software Engineer, Agent Infrastructure"
    jd_file: "JD-senior-software-engineer-agent-infrastructure.md"
    status: "in_progress"    # this role reached an interview...
    status_date: "2026-07-19"
    progress:
      phase: interview_loop
      state: awaiting_schedule
      label: "Virtual onsite"
      calendar_item: "cal-cohere-senior-software-engineer-01"
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
    status: "rejected"       # ...while this one was closed
    status_date: "2026-07-18"
    progress:
      phase: recruiter_screen   # last known phase is kept for funnel analysis
      state: closed
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

The two per-job statuses above roll up to `in_progress`, so this folder lives in
`applications/4_in_progress/`. `status.py` renders such an application as its first role plus
`"(+N more)"`, tagging `[mixed]` when the postings' statuses differ.

### Status Values (folder labels, and the per-job `status` values)

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
.venv/bin/python skills/application-tracker/scripts/status.py
```

Prints a table of all applications with company, role, date, status, source, and files. Shows funnel summary if multiple statuses exist.

### Filter Postings

`status.py` reports one row per application; to slice **one row per `jobs:` posting** across every
status folder, use the posting-granularity filter:

```bash
# Applied/in-progress postings that are remote and a strong fit
.venv/bin/python skills/application-tracker/scripts/filter_jobs.py \
  --status applied,in_progress --workplace remote --fit strong
# Backend roles you qualify for (<=6 YOE), most-senior first
.venv/bin/python skills/application-tracker/scripts/filter_jobs.py \
  --role backend --max-yoe 6 --sort level
# In-progress postings currently in an interview loop, as JSON
.venv/bin/python skills/application-tracker/scripts/filter_jobs.py \
  --status in_progress --phase interview_loop --json
# Everything where the owner owes a scheduling action
.venv/bin/python skills/application-tracker/scripts/filter_jobs.py \
  --progress-state action_required,booking_required,reschedule_required
```

Filters AND across flags and OR within a comma list: `--status` · `--phase` /
`--progress-state` (progress enums) · substring `--company` / `--role` / `--location` /
`--slug` / `--channel` · `--workplace` · `--sponsorship` · `--fit` · `--min-level` /
`--max-level` · `--min-salary` · `--max-yoe` · `--posted-after` · `--since`. Output is an
aligned table (or `--json` / `--count`), with `--sort company|date|level|salary|fit|status`
and `--limit N`.

### Enrich / Validate Job Metadata

After the resume-writer saves `meta.yaml` and the full JD, populate any missing
level/experience/compensation facts:

```bash
# Single application: safe, insert-only, checksum-guarded write.
.venv/bin/python skills/application-tracker/scripts/status.py \
  --enrich-metadata applications/6_drafted/<slug>/

# Fleet preview: dry-run by default, covers ALL status folders. Review before adding --write.
.venv/bin/python skills/application-tracker/scripts/backfill_job_metadata.py

.venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
```

The editor preserves comments, quotes, blank lines, newline style, and unrelated fields.
Unknown or unstated facts remain `null`/`not_stated`—never fabricate them. Validation is
strict: only schema version 5 is accepted, and `--check-metadata` validates **every** status
folder by default (`--statuses <labels>` narrows the scope).

### Update Status

Two commands write the per-job `status` fields and keep the folder in sync. **Only run them when
the user asks** — they manage their own pipeline moves.

**Whole-application transition** — sets **every** posting's `status` to the target and stamps
today's `status_date`, then moves the folder:

```bash
.venv/bin/python skills/application-tracker/scripts/status.py --update <slug> <status>
```

`<status>` is one of `drafted | applied | in_progress | rejected | ignored`. Example:
`... --update google-ml-engineer-20260416 in_progress` stamps every job and moves
`applications/5_applied/google-ml-engineer-20260416/` to `applications/4_in_progress/`.

**Per-posting transition** — change one role in a multi-posting app; the tool recomputes the
rollup and moves the folder only if the overall status changed:

```
status.py --update-job <slug> <role-match> <status>
  <role-match>: case-insensitive substring of jobs[].role, OR a 1-based index;
                must match exactly one posting (else lists candidates, exits non-zero).
  <status>:     drafted | applied | in_progress | rejected | ignored
Examples:
  status.py --update-job acme-multi-20260720 "Backend Engineer" in_progress
  status.py --update-job acme-multi-20260720 2 rejected
```

Every status transition also stamps that posting's deterministic `progress` summary
(drafted -> `application_prep`/`action_required`; applied -> `application_review`/
`waiting_employer`; rejected/ignored -> keep phase, state `closed`; in_progress -> keep phase,
keep a deliberately-set scheduling state, else `unknown` — never guessed) and updates any
linked calendar entry in the same transaction.

If the user moves a folder **by hand**, it can drift from the rollup — re-sync it by running
`status.py --update <slug> <status>` for the folder's new status.

### Update Progress (phase/state — never moves folders)

```
status.py --update-progress <slug> <role-match> --phase <phase> --state <state> [--label TEXT]
```

Sets one posting's structured progress (with a tool-stamped `updated_at` and
`source: {kind: manual}`), writing `meta.yaml` and `calendar.md` together — both or neither.
Entering a scheduling state (`booking_required|awaiting_schedule|scheduled|reschedule_required|
reschedule_pending`) creates the calendar entry when the job has none and records its stable id
as `progress.calendar_item`. `--state scheduled` requires the entry to already carry the
confirmed exact time + timezone (record them on the entry in `calendar.md`, then run
`--sync-calendar --write`). Close a role via `--update-job ... rejected|ignored`, never via
`--state closed`.

### Calendar check & sync (human edits are proposals, preview-first)

```
status.py --check-calendar            # read-only: markers, duplicate ids, meta<->calendar drift
status.py --sync-calendar             # preview how owner edits map back to progress
status.py --sync-calendar --write     # apply the previewed proposals transactionally
```

Owner-edit surfaces the sync understands: a **checked box** (booking done -> `awaiting_schedule`;
reschedule request sent -> `reschedule_pending`; interview happened -> `awaiting_result`; owed
action done -> `waiting_employer`), a filled **`reschedule_to` + `reschedule_timezone`**
(confirmed replacement — the old occurrence is kept as `superseded`), and **`cancel: true`**
(occurrence recorded `cancelled`; the role is never auto-rejected). Anything malformed fails
closed with a report instead of a partial write.

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
1. Run `.venv/bin/python skills/application-tracker/scripts/status.py`
2. Highlight any applications needing action — the table's **Action needed** block
   (progress states `action_required|booking_required|reschedule_required`) plus
   `next_action` fields
3. Surface the **Overdue waiting** block (bookings past their calendar `follow_up_at`
   with no confirmation) — "active with no action" is not the same as "active and
   stuck scheduling"
4. Note stale applications (applied > 2 weeks ago with no status change)
5. Show conversion rates if enough data exists

## Job Discovery

Job discovery lives in the **`job-search`** skill (`skills/job-search/SKILL.md`).
It searches public ATS boards with profile-based criteria (role, keywords, location,
recency, and visa sponsorship), ranks matches, and writes them to `config.discoveries_dir()`.

Typical flow: `job-search` (find a posting) → `resume-writer` (create
`applications/6_drafted/<slug>/` and tailor) → the user reviews and, once applied, moves the
folder to `applications/5_applied/` → this skill (record metadata / pipeline notes).
