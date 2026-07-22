# Skills Layout & Sharing Code Across Skills

Expands `AGENTS.md` → "Sharing Code Across Skills".

## Skill directory layout

- `.agents/skills` is the canonical Agent Skills directory. Edit skill content there.
- `.claude/skills/<skill>` and `.cursor/skills/<skill>` are symlinks for tool compatibility. Do not edit through duplicated copies.
- Keep each skill folder named the same as the `name` field in `SKILL.md`; use lowercase letters, numbers, and hyphens.

## Vendoring (how self-contained skills share code)

Skills are **self-contained** (Approach 2 of `design/skill-script-sharing/`).
A skill's `scripts/` may import its own sibling modules, but it **must never
import repo-root toolkit Python** and must never `sys.path`-inject a path
outside its own skill folder. When a skill needs a pure toolkit module, that
module is **vendored** (copied) into the skill:

- **One canonical source per shared module** lives in `scripts/shared/` (today:
  `config.py`, `layout.py`, `location.py`, `job_metadata.py`, and
  `metadata_editor.py`). Edit the logic there — never in a copy.
- **Byte-identical copies** are generated into each consuming skill's
  `scripts/_vendor/` (e.g. `.agents/skills/resume-writer/scripts/_vendor/config.py`,
  `.agents/skills/job-search/scripts/_vendor/location.py`).
  Everything in `_vendor/` except `__init__.py`/`README.md` is generated — do not edit.
- The registry of `source -> [copies]` lives in `scripts/vendoring/sync_vendored.py`.
  After editing a canonical source, regenerate the copies:
  `.venv/bin/python scripts/vendoring/sync_vendored.py`.
- A drift check (`sync_vendored.py --check`) fails if any copy diverges from its
  source. It runs in the tracked `hooks/pre-commit` hook (install once with
  `python scripts/bootstrap_overlay.py`), so copies can never
  silently drift.
- Skill scripts import the vendored module locally, e.g.
  `from _vendor.location import classify_location`.

Where does a new shared module go? If **only one skill** needs it and it's
skill-specific, keep it in that skill's `scripts/`. If a skill needs a **pure toolkit
module**, add it to `scripts/vendoring/sync_vendored.py`'s `TARGETS`, run the sync, and
import the `_vendor/` copy. The self-contained skills (`resume-writer`,
`application-tracker`, `job-search`) vendor the shared modules they need; the repo-root
maintenance tooling (`scripts/maintenance/`, `scripts/vendoring/`) may import
`scripts/shared/` directly since it always runs inside this repo.
