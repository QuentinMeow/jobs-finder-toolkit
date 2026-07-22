# File & Folder Organization

Expands `AGENTS.md` → "File & Folder Organization" and "Scratch & Temporary
Files".

**Group files by purpose in a meaningful subfolder — never dump files into a broad,
generically named directory.** A bare `scripts/` (or `utils/`, `lib/`, `inputs/`,
`docs/`, `data/`, `misc/`) is too vague on its own: the folder name must announce what
its contents are *for*. Prefer a purpose-scoped subfolder such as
`automation/shared/`, `automation/vendoring/`, or `skills/<skill>/scripts/` over a
flat `scripts/`.

**Before creating ANY new file, reason about the whole folder tree** and place the file
where its purpose is obvious:

- **Think tree-first.** Ask "what is this file for, and which purpose-named folder
  already expresses that?" Put it there. If no such folder exists and the file belongs to
  a group, create the purpose-named subfolder first, then add the file.
- **Purpose over mechanism.** Name folders after the job they do (`shared`,
  `vendoring`, `company-info`, `oa-references`), not after a file type or a
  generic bucket (`scripts`, `docs`, `files`, `data`).
- **Generic top-level folders must fan out into purpose subfolders.** `scripts/` splits
  into `shared/`, `vendoring/`, and `maintenance/`; each skill keeps its code under
  `skills/<skill>/scripts/`. The former generic `docs/` was dissolved into
  `handbook/` (reference) + `design/` (design programs) for exactly this reason. Follow
  the same pattern for anything new that would otherwise land in a generic root.
- **Don't orphan single files at a generic root.** A lone reference PDF, asset, image, or
  note belongs in a named subfolder (e.g. an OA reference PDF goes in
  `.../coding/oa-references/`), not loose beside unrelated files.
- **Match the existing convention.** Folder names are lowercase with hyphens; reuse an
  established purpose folder instead of inventing a near-duplicate.
- **Surface conflicts, don't silently break the pattern.** If a file genuinely fits no
  existing purpose folder, propose the new subfolder name; if existing layout conflicts
  with this rule, flag it and propose a refactor rather than adding to the mess.

Skill-scoped code is an accepted exception: a skill may keep its implementation in its own
`skills/<skill>/scripts/` because the parent skill folder already names the purpose.

**Coding-interview files** (`interviews/company-specific/<company>/coding/`): a single-file
solution stays flat as `<problem>.py`; give a problem its **own** subfolder
`coding/<problem>/<problem>.py` only when it carries extra assets (question screenshots,
PDFs, input files). Do not hard-wrap code lines in these files — keep each line on one line
unless it exceeds 150 characters (see the `coding-interview` skill).

## Scratch & temporary files

Ad-hoc, throwaway work — one-off API/ATS probes, scraper snippets, fetched raw HTML/JSON,
sanity-check scripts, any disposable intermediate — MUST live under the single top-level
**`tmp/`** folder in **purpose-named subfolders**, never in the repo root or a tracked/product
folder (`applications/`, `scripts/`, `templates/`, `skills/`, `interviews/`). A hard rule
for every agent and skill; the old flat `tmp_*.py`-in-root habit is retired.

- **Location & lifecycle:** everything disposable lives under `tmp/<purpose>/`. The whole `tmp/`
  tree is gitignored — nothing in it is committed, and nothing in
  the committed toolkit may import from or depend on `tmp/`. Temp files are disposable: delete them
  once done; if a probe proves worth keeping, promote it into the proper skill's `scripts/`.
- **Purpose-named buckets** (the name must announce the contents' job): `tmp/ats_scripts/` (job-board/
  ATS API probes), `tmp/web_artifacts/` (fetched raw HTML/JSON/career-page snapshots), `tmp/scratch/`
  (quick sanity checks). Descriptive lowercase file names inside each; never a bare `tmp_*.py` in the
  root. Machine scratch (`--json-out`) may target the OS `/tmp`, but keep anything worth revisiting
  in a named `tmp/` bucket.
