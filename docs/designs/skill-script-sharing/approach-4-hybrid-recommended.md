# Approach 4 — Hybrid (not adopted)

**Strategy:** Use the right tool for each layer instead of forcing one model
everywhere. Combine a small importable **core** for repo-internal toolkit code
(Approach 1, scoped tiny), a stable **CLI contract** as the only cross-boundary
dependency (Approach 3), and **selective vendoring** for the one or two skills that
must be exportable (Approach 2). This matches how this repo actually is — a private
monorepo whose skills are shared *within* the repo via symlinks, with latent (not
urgent) external-portability needs.

## Why hybrid, for this repo specifically

- The **cross-cutting shared surface is tiny and pure** (README §2.6): essentially
  `location.py` (no third-party deps) plus a few naming/layout constants. There is no
  large shared library to agonize over — so a lightweight core is cheap.
- The **measured pain** (README §2.1–§2.5) is fragile `sys.path` imports, an
  overloaded `scripts/` name, doc drift, and one duplicated rule. All four are fixed
  by "make the shared surface a real import within the repo, and forbid skills from
  importing repo code — they use the CLI instead."
- **Portability matters for `job-search`** (most likely to be reused elsewhere) but
  not for the resume/tracking toolkit (repo-only by nature). So apply the expensive
  self-containment treatment *only where it pays off*.

## The three layers

### Layer 1 — Repo-internal core (importable, Approach 1, scoped tiny)

Turn `scripts/` into one installable package `jobsfinder` with a small `core`
subpackage as the single home for cross-cutting logic. Delete every `sys.path`
bootstrap. This layer is for **toolkit scripts that only ever run in this repo**
(resume-render, application-tracking).

```
jobsfinder/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── location.py          # THE location rule — single source of truth
│   └── naming.py            # RESUME_STEM, slugify_label, source_dir, application_roles
├── resume_render/           # render.py, cover_letter.py, pdf_convert.py, extract.py
├── application_tracking/    # status.py, migrate_layout.py, backfill_location.py
└── check.py
pyproject.toml               # editable-installed into .venv; declares deps + `jf` CLI
```

```python
# any toolkit script, no path hacks:
from jobsfinder.core.location import classify_locations, is_match
from jobsfinder.core.naming import RESUME_STEM, application_roles
```

### Layer 2 — CLI contract (Approach 3) is the ONLY cross-boundary dependency

Skills **never** `import jobsfinder`. The single hard rule:

> A skill may depend on the repo toolkit **only** through a documented `jf` CLI
> command. It may never import repo-root Python, and it may never `sys.path`-inject a
> path outside its own skill folder.

Expose the small shared surface skills actually need as `jf` subcommands with JSON
output (and a batch mode for hot loops):

```bash
jf location classify "Remote - US"          # {"category":"us_remote","match":true}
jf location classify-batch < postings.jsonl # one JSON verdict per line (hot loops)
```

This keeps skills decoupled and their `SKILL.md` commands stable and correct.

### Layer 3 — Selective vendoring (Approach 2) for exportable skills only

For a skill that must run **standalone** (outside this repo, or in a no-network API
sandbox) — realistically just `job-search` — vendor the single pure module it needs
into the skill, with a drift check. Do **not** vendor into repo-only toolkit areas.

```
skills/job-search/scripts/
├── search_jobs.py
├── scoring.py               # uses _vendor.location (kills the duplicated rule)
├── company_roles.py         # uses _vendor.location (fixes today's broken import)
└── _vendor/
    ├── README.md            # "generated from jobsfinder/core/location.py; do not edit"
    └── location.py
```

`jobsfinder/core/location.py` is the source; `sync_vendored.py` copies it into the
skill's `_vendor/`; a CI drift test fails if they diverge. One pure ~200-line file,
one target — cheap, and it makes `job-search` genuinely portable.

## The decision rule (add to AGENTS.md)

> **Where does a new script go?**
> 1. Used by **exactly one skill**, and specific to it? → that skill's `scripts/`.
> 2. Used by **repo-only toolkit** areas (resume-render / application-tracking)? →
>    `jobsfinder/<domain>/`; if cross-cutting & pure → `jobsfinder/core/`.
> 3. Needed by a skill **and** the toolkit? → put the logic in `jobsfinder/core/`,
>    expose it as a `jf` subcommand, and have the skill call the CLI. If that skill
>    must run standalone, additionally **vendor** the pure module into its `_vendor/`.
> 4. Throwaway probe/experiment? → `tmp/<purpose>/` (never committed).
>
> **Skills never import repo-root Python.** Cross-boundary = CLI or vendored copy.

This makes ownership unambiguous (G4) and stops the `scripts/` ambiguity (README §2.3)
from recurring.

## How it scores against the goals

- **G1 no fragile imports ✅** — real package within the repo; no cross-boundary
  `sys.path`; skills use CLI/vendor.
- **G2 single source of truth ✅** — `core.location` is canonical; the job-search copy
  is a drift-checked generated artifact, not an independent fork.
- **G3 portability ✅** — toolkit stays repo-coupled (correctly), `job-search` is
  self-contained via `_vendor/`.
- **G4 ownership ✅** — the decision rule above.
- **G5 ceremony ⚠️** — two mechanisms to learn (import vs CLI/vendor), but each is
  simple and applied in an obvious context.
- **G6 docs ✅** — stable `jf ...` commands + `python -m jobsfinder...`; no bucket
  paths to drift; fixes README §2.4.
- **G7 scales ✅✅** — new repo-only code = a normal import; new skill code = stays in
  the skill; only genuinely shared+exportable logic pays the vendoring tax, and that
  set stays small by design.

## Trade-offs / honest downsides

- Two sharing mechanisms coexist (import within repo, CLI/vendor across the boundary).
  That is more to explain than a single dogma — mitigated by the one-paragraph
  decision rule.
- The `jf` CLI is a contract you must keep stable; changing its JSON output is a
  breaking change (same caveat as Approach 3, but the surface is intentionally tiny).
- Vendoring adds a generated `_vendor/` copy + a drift test for `job-search` (same
  caveat as Approach 2, but scoped to one file).

## Phased migration plan

**Phase 0 — cross-cutting fixes (do now, independent of everything):**
- Fix the broken import in `company_roles.py` (README §2.1).
- Fix the stale `SKILL.md` command paths (README §2.4).
- Add `__pycache__` hygiene check (never commit).

**Phase 1 — package-ify the toolkit (delivers most of the value; safe, self-contained):**
- Add `pyproject.toml` + `jobsfinder/` package; `git mv` the `scripts/` buckets into
  `jobsfinder/{core,resume_render,application_tracking}` + `check.py`.
- Extract naming/layout constants from `check.py` into `jobsfinder/core/naming.py`;
  move `location.py` into `jobsfinder/core/`.
- Delete all six `sys.path` bootstraps; replace with `from jobsfinder...` imports.
- `.venv/bin/pip install -e .`; update README/AGENTS setup + all toolkit command docs
  to `python -m jobsfinder...` (or console scripts).

**Phase 2 — CLI contract:**
- Add a `jf` umbrella CLI (`jf location classify[/-batch]`, wrap existing `status` /
  `render` as `jf status` / `jf render`), JSON output + documented schema + contract
  tests.
- Point all `SKILL.md`/`AGENTS.md` commands at `jf ...`.

**Phase 3 — de-duplicate + vendor the exportable skill:**
- Collapse `scoring.location_ok` onto `core.location` (via CLI batch call or vendored
  copy).
- Add `sync_vendored.py` + drift test; generate `job-search/scripts/_vendor/location.py`;
  switch `company_roles.py` / `scoring.py` to the vendored copy.
- Wire the drift check + `ruff`/import check into pre-commit and/or CI.

Each phase is independently shippable and reversible. Phase 0 + Phase 1 alone
eliminate every *broken* thing in the current-state audit; Phases 2–3 harden the model
for growth.

## Rejected alternatives (why not the pure forms)

- **Pure Approach 1** — best DRY, but makes *all* skills repo-coupled and unable to
  run in a clean/no-network sandbox; contradicts the Agent Skills portability model.
- **Pure Approach 2** — most portable, but forces every repo-only toolkit script to
  pay the vendoring/sync tax for zero portability benefit; copies multiply at scale.
- **Pure Approach 3** — cleanest seams, but subprocess overhead and a
  contract-versioning burden are overkill for hot-loop pure functions and for logic
  that never crosses a boundary.

The Hybrid takes the best of each and confines each one's cost to where it earns its
keep.
