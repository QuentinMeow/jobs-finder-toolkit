---
name: ask-me-anything
visibility: public
description: Orientation guide for the whole job-hunting toolkit — the five-step workflow (set up profile/filters → search jobs → generate applications → review & track → interview prep), the repo structure, and which skill + dependencies each step needs. Use when the user is new or asks "how does this work", "how do I use this", "where do I start", "what do I do next", "what do I need installed", or about the overall process, folder structure, or how the skills fit together.
---

# Ask Me Anything — Job-Hunting Toolkit Guide

This skill is the **orientation and how-to guide** for the whole toolkit. Use it to answer
"how does this repo work?" and to walk a user through their job hunt step by step with the
AI agent. It does **not** do the work itself — it explains the process and hands off to the
specialized skill for each step.

## When to Use

Read and follow this skill when the user:
- Is new to the repo and asks how it works / where to start / what to do next.
- Asks for the overall workflow, the folder structure, or how the skills fit together.
- Asks what they need installed or configured to run a given step.
- Wants a plain-English tour before diving into search, tailoring, or prep.

For the *actual* work, hand off to the specialized skill (each is a separate `SKILL.md`):
`job-search`, `resume-writer`, `application-tracker`, `company-research`,
`behavioral-interview-prep`. This skill just routes the user to the right one at the right
time and explains the dependencies.

## The Big Picture

The toolkit turns one **candidate profile** into tailored, ATS-optimized applications and
tracks them through a pipeline. Content (your experience, in markdown/YAML) and formatting
(a reference DOCX template) are kept separate, so the AI edits *content* and a script renders
*format*. The five steps:

```
0. Setup ......... install deps + config.yaml + profile/baseline/reference DOCX   (one time)
1. Profile & filters   define WHO you are and WHAT you want          → job-search profile
2. Search .............. find matching, fresh, sponsorship-aware roles → job-search skill
3. Generate ............ tailor a resume + cover letters per posting   → resume-writer skill
4. Review & track ...... you decide apply/ignore, then move the folder → application-tracker
5. Interview prep ...... company research + behavioral (+ coding) prep → company-research /
                                                                          behavioral-interview-prep
```

**Per-job status, folder = overall status.** Every application is a folder
`applications/<company>-<role>-<date>/` inside a numbered status folder. Each posting in its
`meta.yaml` `jobs:` list carries its own `status`; the folder is the derived overall status
(new drafts land in `6_drafted/`, then `5_applied/`, `4_in_progress/`, `3_rejected/`, or
`2_ignored/` as things progress). Transitions happen only when *you* ask — via
`status.py --update` / `--update-job`. See `application-tracker` for details.

## Prerequisites (install once)

These are the global dependencies. Per-step extras are listed under each step.

| What | Why | Install |
|------|-----|---------|
| Python 3.11+ in a repo venv | Runs every toolkit script | `python3 -m venv .venv` (Python 3.11+; or `uv venv --seed`), then always call `.venv/bin/python` |
| Python packages | YAML + DOCX + PDF parsing | `.venv/bin/pip install -r requirements.txt` (pyyaml, python-docx, pypdf) |
| LibreOffice **or** Word+docx2pdf | DOCX → PDF for resumes/cover letters (Step 3) | `brew install --cask libreoffice` (recommended), or `pip install docx2pdf` if you have Word |
| Any AI coding agent | Reads `AGENTS.md` + `skills/` and drives the workflow | Open the repo in the agent (Claude Code, Cursor, Codex, …); skills auto-route |

Optional but recommended: install the git hooks so vendored script copies can't
drift — run `python automation/bootstrap_overlay.py` (installs both tracked hooks).

Always invoke scripts with the repo venv (`.venv/bin/python ...`); the system Python is
often too old. On macOS the renderer looks for LibreOffice at `~/Applications/LibreOffice.app`
then `/Applications/LibreOffice.app`.

## Step 0 — Configuration (do this first)

Everything candidate-specific comes from a git-ignored **`config.yaml`** — never hardcoded.
Copy the tracked placeholder and edit it:

```bash
cp config.example.yaml config.yaml
```

`config.yaml` declares your identity (`candidate.name`, `contact_line`, `name_slug`,
`title_slug`), the **paths** to your source-of-truth files, the default job-search profile,
and your **location policy** (preferred metros + US-remote + `us_only`). Paths resolve
relative to the config file's directory. The four files the paths point at:

| Path key | What it is | How to create it |
|----------|-----------|------------------|
| `paths.profile_md` | Your complete professional profile (markdown): all experience, projects tagged `[draft]`/`[backup]`, and your Approved/Weak/Never **skill lists**. The source of truth. | Start from `examples/profile/profile.example.md`; replace with your real content. |
| `paths.baseline_yaml` | Exact YAML transcription of your **approved** resume — the anchor every tailored resume starts from. | Copy `examples/profile/baseline.example.yaml`; or extract from a DOCX with `resume-writer/scripts/extract.py`. |
| `paths.reference_docx` | Your formatted resume DOCX — the render *template* (fonts/margins/styles preserved). | Copy `examples/templates/reference.example.docx`; replace with your own formatted resume. |
| `paths.company_levels_yaml` | Optional reusable level/YOE/comp reference cache. | Optional; `examples/profile/company-levels.example.yaml` shows the shape. |

If you don't set `config.yaml`, the toolkit falls back to `config.example.yaml` (the fake
"Jordan Rivers" candidate) so every script still runs out of the box for a demo.

**Keep real data private.** Real profile/baseline/reference DOCX and all applications +
interviews are personal products. Point `config.yaml`'s paths at the git-ignored **`private/`**
overlay (its own git repo). See `AGENTS.md` → "Public vs Private"
and `handbook/private-overlay.md` for the two-repo model. Never commit real identity to the public
repo — `config.yaml` itself is git-ignored.

## Step 1 — Profile & Filters (who you are, what you want)

Your *identity/experience* lives in the profile (Step 0). Your *search criteria* live in a
**job-search profile**: `skills/job-search/profiles/<label>.yaml`, selected by
`config.job_search.default_profile`. It encodes target roles/titles, keywords, seniority
band, location + radius, visa policy, recency, and AI-native-company preference.

Tell the agent something like:
> "Set up my job-search filters: senior backend/platform roles, my metro area + US-remote,
> needs H-1B transfer sponsorship, AI-infra companies preferred."

The agent edits/copies a profile YAML (starting from `profiles/_TEMPLATE.yaml` or
`profiles/example.yaml`) — criteria live in the profile, never baked into scripts.

**Dependencies:** just `config.yaml` + a profile YAML (pyyaml). No network yet.

## Step 2 — Search for Matching Jobs (`job-search` skill)

Ask the agent:
> "Find jobs matching my profile" / "What backend roles were posted in the last week that
> sponsor H-1B?" / "Search AI-infra companies in my metro area."

The `job-search` skill fetches live postings from 100+ company ATS boards + keyless
aggregators + JobSpy (Indeed/Google), filters by title/location/visa, scores and ranks
them, skips blacklisted / already-considered / recently-searched employers, and writes a
ranked shortlist to your discoveries dir (`config.discoveries_dir()`,
`applications/1_discoveries/` by default). It only ever surfaces real postings with a source URL.

**Dependencies:**
- Network access (public read APIs; no keys needed for the default "Stage 1" run).
- `python-jobspy` for the Indeed/Google scraper (in the venv already; `pip install python-jobspy` if missing).
- Optional **Stage 2** (`--stage 2`): LinkedIn/Glassdoor + keyed aggregators — set
  `RAPIDAPI_KEY` (JSearch) and/or `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` env vars. Missing keys are skipped quietly.
- Optional visa boost: `openpyxl` + DOL disclosure XLSX for `build_sponsor_index.py`.

Read `skills/job-search/SKILL.md` for the full flag set and the two-stage model.

## Step 3 — Generate an Application (`resume-writer` skill)

Pick a posting from the shortlist and tell the agent:
> "Tailor my resume for this job: <paste JD or URL>" (or "for posting #3 from the search").

The `resume-writer` skill creates `applications/6_drafted/<slug>/` (here `applications/` means
`config.applications_root()` — with the shipped example config, `examples/applications/`),
saves the JD(s) under `source/JD-<title>.md`, writes `meta.yaml`, tailors `source/tailored.yaml`
**starting from
your baseline** (targeted edits only — no fabrication, skills gated by your Approved/Weak/Never
lists), then renders and validates:
- `<RESUME_STEM>.pdf` (root, for humans) + `.docx` (in `source/`, for ATS portals) — one resume.
- **One cover letter per posting** `..._Cover_Letter_<title>.pdf`, each individually researched.
- **One bundled `..._Application_<title>.txt` per posting** with copy-paste COVER LETTER /
  WHY THIS COMPANY & ROLE / PAST EXPERIENCE sections (plus the portal's actual questions when visible).

Validation (`check.py`) is automatic and mandatory: locked identity fields, real project
titles, bullet lengths, one full page, and a proper cover letter. A failed render is fixed,
never shipped. Say "resume only" to skip cover letters.

**Dependencies:** LibreOffice (or Word + docx2pdf) for PDF; python-docx; your
`reference_docx` + `baseline_yaml`. Network only for the per-JD company research.

Read `skills/resume-writer/SKILL.md` for the tailoring rules and layout budget.

## Step 4 — Review, Decide, and Track (`application-tracker` skill)

This step is **yours**. Open the drafted folder and review the `meta.yaml`, the resume PDF,
and each bundled `.txt`. Then:
- **Apply:** submit the DOCX to the ATS portal, paste the `.txt` answers, then move the
  folder to `applications/5_applied/` (by hand, or ask the agent:
  `status.py --update <slug> applied`).
- **Ignore:** move it to `applications/2_ignored/` so it's not reconsidered.

Check pipeline health any time:
```bash
.venv/bin/python skills/application-tracker/scripts/status.py
```
The `application-tracker` skill also enriches/validates `meta.yaml` job metadata (level,
YOE, salary, sponsorship), records interview notes in `notes.md`, and keeps the search
skip-logs in sync (`status.py --sync-log`). **The agent never changes application status
unless you ask** — per-job statuses and the matching folder move are your decision, made
through `status.py --update` / `--update-job`.

**Dependencies:** pyyaml only (no network, no LibreOffice).

Read `skills/application-tracker/SKILL.md` for the `meta.yaml` schema and commands.

## Step 5 — Interview Prep (when a role moves forward)

Once you hear back (folder in `4_in_progress/`), prep with two skills:
- **`company-research`** — deep, interview-ready research: product, the hard technical
  challenges and why they're hard, competitive moat/defensibility/growth (evidence-based,
  5-Whys), AI strategy, culture, the role deep-dive, plus offer-decision facts (comp/WLB/
  visa) and a **question bank**. Saved under `interviews/company-specific/<company>/company-info/`.
  > "Research <company> for my upcoming interview and build a question bank."
- **`behavioral-interview-prep`** — project-based STAR story bank and reusable answers under
  `interviews/behavioral-story-bank/` and `interviews/behavioral-answer-bank/`.
  > "Build behavioral stories from my profile and map them to Amazon LPs."

(Real interview products mount under the private overlay — `private/interviews/...`.)

(Coding-interview prep is a separate **private** skill that ships only with the private
overlay, so it isn't part of the public toolkit.)

**Dependencies:** network access for live company research (`curl`/web fetch); the
application's `meta.yaml` + JD + your profile for grounding. No LibreOffice.

## Repo Structure at a Glance

```
config.yaml (git-ignored) / config.example.yaml   # identity, paths, filters (Step 0)
requirements.txt                                   # Python deps
examples/                                          # fake "Jordan Rivers" profile + a worked drafted app
private/                                            # your overlay (own git repo, git-ignored) — real data mounts here:
  applications/    # your pipeline (config.applications_root(): 0_profile 1_discoveries 2_ignored…6_drafted)
  interviews/      # story banks + per-company research
  templates/reference.docx    # your render template (config.reference_docx_path())
skills/<skill>/                             # the skills (SKILL.md + self-contained scripts/)
automation/shared|vendoring|maintenance|publish/       # shared helpers, vendoring, exporter/leak-guard
AGENTS.md                                           # the full agent contract (deep reference)
README.md                                           # human quickstart
```

For the authoritative details, the agent should read **`AGENTS.md`** (repo contract) and the
specific `SKILL.md` for the step at hand — this guide is the map, those are the manuals.

## Public vs Private (why some things aren't here)

The toolkit ships as a **public** repo (timeless tooling + the fake example candidate) with an
optional **private overlay** (your real identity, applications, interviews, and the private
`coding-interview` skill) — its own git repo mounted at a git-ignored `private/` path. If you
cloned the public repo, everything in Steps 0–5 works with the example config immediately; drop
in your own `config.yaml` + private files to make it yours. For the authoritative model see
**`AGENTS.md`** → "Public vs Private", the README's "Public + private (two-repo) setup", and
`handbook/private-overlay.md`.

## Answering "Ask Me Anything" Questions

When the user asks a how-to question, answer from this map, then point them at the exact skill
and command. Keep answers concrete: name the step, the skill, the command, and the dependency.
Common ones:

- **"Where do I start?"** → Step 0 (install deps + `cp config.example.yaml config.yaml`), then Step 1.
- **"How do I find jobs?"** → Step 2, `job-search` skill; needs network + `python-jobspy`.
- **"How do I make a resume for this posting?"** → Step 3, `resume-writer`; needs LibreOffice.
- **"How do I mark something as applied?"** → Step 4; move the folder or `status.py --update <slug> applied`.
- **"How do I prep for the interview?"** → Step 5, `company-research` + `behavioral-interview-prep`.
- **"Do I need API keys?"** → No for the default search; only for Stage-2 aggregators.
- **"Where does my private data go?"** → the overlay / git-ignored paths; see `handbook/private-overlay.md`.

If a request is ambiguous (which role, which profile, apply vs ignore), ask before acting —
never fabricate experience, and never move an application folder without the user's say-so.
