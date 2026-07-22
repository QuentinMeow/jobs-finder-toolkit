# Approach 1 — Central importable package ("toolkit as a library")

**Strategy:** DRY-first. Make the repo's Python one real, installable package with a
single, canonical home for every shared module. Everything — root toolkit scripts and
skill scripts alike — imports from it with normal `import` statements. Delete all
`sys.path` bootstraps.

## How it works

1. Convert `scripts/` into an installable package, e.g. `jobsfinder`, with a
   `pyproject.toml` and `__init__.py` files.
2. Install it editable into the repo venv once: `.venv/bin/pip install -e .`. After
   that, `import jobsfinder.location` works from any CWD, any script, no path hacks.
3. Shared logic gets one home (`jobsfinder/core/`). Domain code gets subpackages.
4. Skill scripts `import jobsfinder...` the same way root scripts do.

### Proposed layout

```
jobsfinder/                         # installed package (was scripts/)
├── __init__.py
├── core/                           # cross-cutting, dependency-light
│   ├── __init__.py
│   ├── location.py                 # single home for the location rule
│   └── naming.py                   # RESUME_STEM, slugify_label, source_dir, ...
├── resume_render/
│   ├── __init__.py
│   ├── render.py                   # was scripts/resume-render/render.py
│   ├── cover_letter.py
│   ├── pdf_convert.py
│   └── extract.py
├── application_tracking/
│   ├── __init__.py
│   ├── status.py
│   ├── migrate_layout.py
│   └── backfill_location.py
├── check.py                        # validation (was scripts/shared/check.py)
└── job_search/                     # skill implementation moved into the package
    ├── __init__.py
    ├── search_jobs.py
    ├── sources.py
    ├── scoring.py                  # location_ok now calls core.location — no dup
    ├── registry.py
    └── ...
pyproject.toml                      # declares the package + deps + console scripts
```

`.agents/skills/job-search/scripts/` becomes a **thin shim** that just calls the
package, e.g. `search_jobs.py` → `from jobsfinder.job_search.search_jobs import main; main()`.

### Code sketch

Before (today, in six files):

```python
for _bucket in ("shared", "resume-render", "application-tracking"):
    _bucket_dir = Path(__file__).resolve().parent.parent / _bucket
    if _bucket_dir.is_dir() and str(_bucket_dir) not in sys.path:
        sys.path.insert(0, str(_bucket_dir))
from check import RESUME_STEM, application_dir
from location import classify_locations, is_match
```

After:

```python
from jobsfinder.check import RESUME_STEM, application_dir
from jobsfinder.core.location import classify_locations, is_match
```

`pyproject.toml` (sketch):

```toml
[project]
name = "jobsfinder"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pyyaml>=6,<7", "python-docx>=0.8,<2", "pypdf>=4,<7"]

[project.optional-dependencies]
jobsearch = ["openpyxl", "python-jobspy"]   # heavy/optional, only for job-search

[project.scripts]
jf-status = "jobsfinder.application_tracking.status:main"
jf-render = "jobsfinder.resume_render.render:main"
jf-jobsearch = "jobsfinder.job_search.search_jobs:main"

[tool.setuptools.packages.find]
include = ["jobsfinder*"]
```

Console scripts also give stable command names (`jf-status`) that never break on a
file move — a fix for the stale-path problem (README §2.4).

## Pros

- **G1 ✅✅ No fragile imports.** Real package resolution; moving a file changes one
  import line, caught immediately by `ruff`/`pyflakes`/import errors at load.
- **G2 ✅✅ True single source of truth.** `core.location` is *the* location rule; the
  job-search `location_ok` duplication (README §2.5) collapses into one function.
- **G4 ✅ Clear ownership.** "Shared = `jobsfinder/core`; domain = its subpackage;
  skill-specific = its subpackage." Import path tells you the owner.
- **G6 ✅ Docs stay correct.** Console-script names / `python -m jobsfinder.x` are
  stable; no bucket paths to drift.
- **G7 ✅ Scales cleanly.** Standard Python packaging is proven at far larger sizes;
  optional-dependency groups keep heavy deps (jobspy, openpyxl) out of the base.
- Enables real unit tests (`import jobsfinder...` in a `tests/` dir) and type
  checking across the whole toolkit.

## Cons

- **G3 ❌ Kills skill portability.** A skill whose `scripts/` do
  `import jobsfinder...` is **not** self-contained — it only runs inside this repo
  with the package installed. This directly contradicts the Agent Skills standard
  ("relative paths from the skill root," "build once, use everywhere") and the
  `anthropics/skills` vendoring pattern. You could never lift `job-search` out to
  another machine/marketplace without shipping the whole package.
- **Install step becomes mandatory.** `pip install -e .` must run before anything
  works; a fresh clone or a sandbox without install is broken. Agent runners that
  execute a skill in a clean environment (the API code-execution sandbox has *no*
  network and no install step) cannot use it.
- **G5 ⚠️ Packaging ceremony.** `pyproject.toml`, `__init__.py`, editable install,
  and moving skill code into the package is a non-trivial one-time refactor and a
  conceptual shift ("skills call into a central lib").
- Blurs the skill boundary: the job-search *implementation* now lives in the package,
  and the skill folder is a shim — some maintainers dislike that indirection.

## When to choose this

Choose Approach 1 if you are certain these skills will **only ever** run inside this
one repo/venv (no external export, no API-sandbox execution), and you value maximum
DRY and testability over portability. It is the best pure-engineering answer for a
closed monorepo and the worst fit for the "skills are portable artifacts" model.

## Migration steps

1. Add `pyproject.toml` + `jobsfinder/__init__.py`; `git mv scripts/* jobsfinder/`
   into the subpackage layout above; add `__init__.py` to each subpackage.
2. Replace every `sys.path` bootstrap with real `from jobsfinder... import ...`.
3. Move `job_search` scripts into `jobsfinder/job_search/`; reduce the skill's
   `scripts/*.py` to thin `main()` shims (or `python -m` docs).
4. Collapse `scoring.location_ok` to call `jobsfinder.core.location`.
5. `.venv/bin/pip install -e .`; add it to the README/AGENTS setup steps.
6. Update all `SKILL.md` / `AGENTS.md` commands to `python -m jobsfinder...` or the
   console-script names.
7. Add `tests/` and a `ruff`/import check in a pre-commit or CI step.

**Effort:** Medium (packaging + moving skill code + doc sweep). Reversible.
