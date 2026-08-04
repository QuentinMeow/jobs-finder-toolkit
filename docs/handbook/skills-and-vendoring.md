# Skills Layout & Sharing Code Across Skills

Expands `AGENTS.md` → "Sharing Code Across Skills".

## Skill directory layout

- `skills` is the canonical Agent Skills directory. Edit skill content there.
- `.agents/skills/<skill>`, `.claude/skills/<skill>`, and
  `.cursor/skills/<skill>` are symlinks for tool compatibility. Do not edit
  through duplicated copies.
- Keep each skill folder named the same as the `name` field in `SKILL.md`; use lowercase letters, numbers, and hyphens.

## Vendoring (how self-contained skills share code)

Skills are **self-contained** (Approach 2 of `docs/designs/skill-script-sharing/`).
A skill's `scripts/` may import its own sibling modules, but it **must never
import repo-root toolkit Python** and must never `sys.path`-inject a path
outside its own skill folder. When a skill needs a pure toolkit module, that
module is **vendored** (copied) into the skill:

- **One canonical source per shared module** lives in `automation/shared/`. Edit the
  logic there — never in a copy. **Whole package trees are vendored too**, not just
  single modules.
- **Byte-identical copies** are generated into each consuming skill's
  `scripts/_vendor/` (e.g. `skills/resume-writer/scripts/_vendor/config.py`,
  `skills/job-search/scripts/_vendor/location.py`,
  `skills/email-assistant/scripts/_vendor/mail/`).
  Everything in `_vendor/` except `__init__.py`/`README.md` is generated — do not edit.
- **The registry is the list.** `automation/vendoring/sync_vendored.py` holds
  `TARGETS` (`source module -> [copies]`) and `DIR_TARGETS`
  (`source package -> [copy dirs]`). Read those two dicts to learn what is vendored
  and which skills consume it; this page deliberately does not restate them, because a
  copied list here is a second source of truth that only the drift check can falsify —
  and it checks the copies, not the prose. After editing a canonical source, regenerate:
  `.venv/bin/python automation/vendoring/sync_vendored.py`.
- A drift check (`sync_vendored.py --check`) fails if any copy diverges from its
  source. It runs in the tracked `automation/hooks/pre-commit` hook (install once with
  `.venv/bin/python automation/bootstrap_overlay.py`), so copies can never
  silently drift.
- **It checks both directions.** As well as "does each declared copy still match its
  source", it audits every file under a `skills/*/scripts/_vendor/` root and fails on
  any that no `TARGETS`/`DIR_TARGETS` entry names — otherwise a module copied in and
  never declared is compared to nothing and rots while the gate stays green. Only
  `README.md` and `__init__.py`, directly in a `_vendor/` root, are exempt (see the
  previous bullet: they are the notice and the package marker, not generated code).
  So the fix for the failure is to declare the file or delete it — re-running the sync
  will not clear it.
- Skill scripts import the vendored module locally, e.g.
  `from _vendor.location import classify_location`.

**Testing the canonical module, not a copy.** `automation/shared/tests` is the
suite for `automation/shared/`, but `unittest` discovery imports every module in
that directory into one process, and some of them reach a skill's entry-point
script — which puts that skill's `_vendor/` on `sys.path`. A bare
`import job_metadata` then resolved to a COPY. Every `test_*.py` there now calls
`pin_shared_modules()` (from `automation/shared/tests/_canonical_imports.py`)
before its first repo-local import; it installs a `sys.meta_path` finder that
pins every vendored name to `automation/shared/`, so resolution no longer depends
on import order. Read that module's docstring before changing it — it lists what
the pin does **not** cover, chiefly that it is not a drift check and that the
`_vendor/` copies are exercised only by the per-skill suites under
`skills/*/scripts/tests`. `test_canonical_module_resolution.py` fails if a new
test module skips the call.

Where does a new shared module go? If **only one skill** needs it and it's
skill-specific, keep it in that skill's `scripts/`. If a skill needs a **pure toolkit
module**, add it to `automation/vendoring/sync_vendored.py`'s `TARGETS` (or `DIR_TARGETS`
for a package), run the sync, and import the `_vendor/` copy. Every skill that appears on
the right-hand side of those two dicts is a self-contained consumer and vendors what it
needs; the repo-root maintenance tooling (`automation/gardener/`, `automation/search-recall-audit/`,
`automation/company-levels/`, `automation/vendoring/`) may import
`automation/shared/` directly since it always runs inside this repo.
