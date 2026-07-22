# Application Folder Convention (full)

The canonical file tree is in `AGENTS.md` → "Application Folder Convention". The full status
model, per-file descriptions, `meta.yaml` fields, and the divergent-role split follow.

Each application is a folder named `<company>-<role>-<YYYYMMDD>/`. **Each `jobs:` entry carries a
per-job `status`; the parent status folder is the derived overall status (rollup) and the two must
agree.** Applications are always created under
`applications/6_drafted/<company>-<role>-<YYYYMMDD>/`. The status folders and what they mean:

| Folder | Status | Who moves it |
|--------|--------|--------------|
| `applications/6_drafted/` | tailored, awaiting the user's review/decision | created here by the resume-writer skill |
| `applications/5_applied/` | submitted | the **user** moves the folder here manually |
| `applications/4_in_progress/` | heard back / interviews scheduled | the **user** moves the folder here manually |
| `applications/3_rejected/` | rejected at any stage | the **user** moves the folder here manually |
| `applications/2_ignored/` | decided not to submit; don't reconsider | the **user** moves the folder here manually |

**Numeric-prefix convention.** Every folder under `applications/` carries a `0_`–`6_`
prefix (`0_profile`, `1_discoveries`, `2_ignored`, `3_rejected`, `4_in_progress`,
`5_applied`, `6_drafted`) so a plain directory listing sorts into pipeline order. The
prefix is part of the on-disk folder name only — the CLI status **labels** stay
unprefixed (`drafted`, `applied`, `in_progress`, `rejected`, `ignored`): the summary table
and `status.py --update <slug> <status>` still take the bare label, and `status.py` maps
each label to its numbered folder (`applied` → `applications/5_applied`, etc.). Do not
rename these folders back to unprefixed names.

Agents should create applications under `applications/6_drafted/` and never move them
between status folders unless the user explicitly asks (they manage moves manually, or
via `.agents/skills/application-tracker/scripts/status.py --update <slug> <status>`).

Each application folder splits into a small set of **root** files (the finished
deliverables you submit / paste, plus tracking metadata) and a **`source/`**
subfolder (everything used to generate them):

One resume covers the whole folder, but **cover letters are one-to-one with JDs** — one
`<COVER_STEM>_<job title>.pdf` + one bundled `<APPLICATION_STEM>_<job title>.txt` per
`meta.yaml` role. A single-role folder has exactly one of each (still job-title-labeled); a
multi-role folder (a `jobs:` list) has one per posting. The stems below come from
`config.resume_stem()` / `config.cover_stem()` / `config.application_stem()` — with the
example config the resume stem is `Jordan_Rivers_Software_Engineer_Resume`:

```
applications/6_drafted/<slug>/                     # e.g. a 2-role folder
├── meta.yaml                                    # tracking metadata (per-job status; folder = derived rollup)
├── <RESUME_STEM>.pdf                            # ONE final resume (for humans/email)
├── <COVER_STEM>_<Role_A>.pdf                    # one cover letter per JD
├── <COVER_STEM>_<Role_B>.pdf
├── <APPLICATION_STEM>_<Role_A>.txt              # one bundled packet per JD
├── <APPLICATION_STEM>_<Role_B>.txt
├── notes.md                                     # optional interview/company notes
└── source/
    ├── JD-<job title A>.md                       # one per posting, ALWAYS JD-prefixed
    ├── JD-<job title B>.md
    ├── tailored.yaml                             # AI-tailored resume content (one resume)
    ├── <RESUME_STEM>.docx                        # submit this DOCX to ATS portals
    ├── <COVER_STEM>_<Role_A>.docx
    └── <COVER_STEM>_<Role_B>.docx
```

The `<Role>` suffix is the role's slug (underscores, via `layout.slugify_label`, e.g.
`Senior_Platform_Engineer`), derived one-to-one from each `meta.yaml` role. `render.py` /
`cover_letter.py` emit these names automatically — never hand-name or hand-place them.

Root files:
- `meta.yaml` — human-readable tracking metadata. Top-level `job_metadata_schema_version: 4`
 plus company-scope fields and a uniform **`jobs:` list — one entry per posting, always a list
 even for a single role** (each entry carries `role`, its exact `jd_file`, a required per-job
 `status` (optional `stage`/`status_date`), `location`, `workplace`, `sponsorship`, and the flat
 `job_level`/`required_yoe`/`salary_range` facts; no `total_compensation_range`). **The
 `application-tracker` skill (`.agents/skills/application-tracker/SKILL.md`,
 "`meta.yaml` Schema") is the single canonical owner of the full schema and rules** — read it
 before writing or validating a `meta.yaml`; don't restate the field list elsewhere. Run
 `status.py --enrich-metadata <folder>` after saving the JD. The per-job `status` fields are the
 fine-grained truth and the folder is their derived rollup, and the role list is the canonical set
 of cover letters. Only create an application
 whose `location` matches the configured location policy (`config.location_policy()` — the
 candidate's preferred metros plus US-remote / `us_only` rule) — verify with
 `.agents/skills/application-tracker/scripts/status.py --check-locations`; a role that is
 on-site/hybrid outside the allowed metros or non-US must not be drafted.
- `..._Resume.pdf` — the single final resume PDF (generated, committed)
- `..._Cover_Letter_<job title>.pdf` — one final cover-letter PDF per JD (generated, committed)
- `..._Application_<job title>.txt` — one plain-text packet per JD, each bundling three
  copy-paste sections introduced by a title + `===` underline: **COVER LETTER**, **WHY THIS
  COMPANY & ROLE**, and **PAST EXPERIENCE**. Plain English, no Markdown/bold — paste straight
  into that posting's portal boxes. Each `.txt` is the source of truth for its cover letter:
  `render.py` renders `..._Cover_Letter_<job title>.pdf` from its COVER LETTER section (name +
  contact, then the salutation — no job-title/subject line). Every letter is researched and
  tailored to its own JD — never reuse one letter across postings.
- `notes.md` — optional interview notes and company research

`source/` files (generation inputs/intermediates):
- `JD-<job title>.md` — full job-description text, one file per posting, **always**
  `JD-`-prefixed and slug-named after the job title (single or multiple postings).
  `check.py` reads and concatenates every `JD-*.md` in `source/` (via `layout.find_jd_files`).
- `tailored.yaml` — AI-tailored content matching the render schema (one resume per folder);
  may set an optional top-level `target_position` to add a role suffix to the RESUME
  filename (divergent-split only)
- `..._Resume.docx` — the editable resume DOCX (submit this to ATS portals)
- `..._Cover_Letter_<job title>.docx` — one editable cover-letter DOCX per JD

When one company's roles are too different for a single honest resume, they are split into
separate application folders and each `tailored.yaml` sets `target_position`, so the RESUME
filename carries a role suffix (e.g. `..._Resume_Frontend_Engineer.pdf`); the cover letter
and bundled `.txt` are always job-title-labeled per JD regardless of the split.

Slug format: lowercase, hyphens, no special characters. Example: `google-ml-engineer-20260416`.
