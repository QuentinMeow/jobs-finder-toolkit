# Design: Sharing & Maintaining Scripts Across Skills

> **Superseded (historical).** The toolkit shipped **Approach 2 — vendored self-contained skills** (see `AGENTS.md` → 'Sharing Code Across Skills'). This folder is kept as the design record; its 'current state' audit describes the pre-split tree and no longer matches the repo.

**Status:** superseded — Approach 2 adopted
**Scope:** how Python scripts should be organized, shared, and maintained as the
number of skills and scripts in this repo grows.
**Audience:** repo maintainer (human) deciding the architecture.

This folder holds one design doc per candidate approach plus this index. Read this
file first (problem + current state + comparison + recommendation), then the
per-approach docs:

| Doc | Approach | One-liner |
|-----|----------|-----------|
| [approach-1-shared-package.md](approach-1-shared-package.md) | Central importable package | One installable library; everything imports it (DRY-first) |
| [approach-2-vendored-self-contained.md](approach-2-vendored-self-contained.md) | Self-contained skills w/ vendored code | Each skill owns all its code; shared logic is copied in + drift-checked (portability-first) |
| [approach-3-cli-service-boundary.md](approach-3-cli-service-boundary.md) | CLI / service boundary | Nothing imports across boundaries; shared code is invoked as a CLI (decoupling-first) |
| [approach-4-hybrid-recommended.md](approach-4-hybrid-recommended.md) | **Hybrid (recommended)** | Tiny pure shared core + CLI contract + optional vendoring for exportable skills |

---

## 1. Problem statement

Scripts in this repo currently live in two different worlds:

1. **Repo-root toolkit scripts** under `scripts/`, bucketed by purpose:
   - `scripts/resume-render/` — `render.py`, `cover_letter.py`, `extract.py`, `pdf_convert.py`
   - `scripts/application-tracking/` — `status.py`, `migrate_layout.py`, `backfill_location.py`
   - `scripts/shared/` — `check.py`, `location.py`
2. **Skill-scoped scripts** under a skill folder, e.g.
   `.agents/skills/job-search/scripts/` — `search_jobs.py`, `sources.py`, `scoring.py`,
   `visa.py`, `registry.py`, `aggregators.py`, `common.py`, `company_roles.py`,
   `validate_companies.py`, `build_sponsor_index.py`.

Bundling scripts *inside* a skill is good and matches the Agent Skills standard
(see §3). The open question the maintainer asked:

> How should a skill share scripts with other skills and with the repo-root
> toolkit? What is the recommended approach as we add more skills and scripts?

Today there is **no defined answer**, and the ad-hoc answer that has grown in is
already breaking. Concrete symptoms (measured, not hypothetical — see §2).

## 2. Current-state audit (evidence)

### 2.1 Cross-boundary import via `sys.path` hacking — currently broken

`.agents/skills/job-search/scripts/company_roles.py` reaches into the repo-root
toolkit to reuse the location classifier:

```29:45:.agents/skills/job-search/scripts/company_roles.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SKILL_SCRIPTS.parents[3]
REPO_SCRIPTS = REPO_ROOT / "scripts"
for p in (str(SKILL_SCRIPTS), str(REPO_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from location import classify_location, is_match  # noqa: E402
from registry import load_registry  # noqa: E402
from sources import fetch_company  # noqa: E402
```

It adds `<repo>/scripts` to `sys.path` and does `from location import ...`, but
`location.py` was moved to `<repo>/scripts/shared/location.py`. Running it today:

```
$ .venv/bin/python .agents/skills/job-search/scripts/company_roles.py --name Anyscale
ModuleNotFoundError: No module named 'location'
```

A file move in one world silently broke a script in the other world. This is the
canonical failure mode of `sys.path` sharing.

### 2.2 The repo-root buckets also share via `sys.path` hacking

Every root script that needs a sibling bucket re-implements the same bootstrap:

```38:48:scripts/application-tracking/status.py
# Direct-execution support after the scripts/ split: put the sibling script
# buckets on sys.path so shared/ modules (check, location) import regardless of
# which bucket this script runs from.
for _bucket in ("shared", "resume-render", "application-tracking"):
    _bucket_dir = Path(__file__).resolve().parent.parent / _bucket
    if _bucket_dir.is_dir() and str(_bucket_dir) not in sys.path:
        sys.path.insert(0, str(_bucket_dir))

from check import (APPLICATION_STEM, RESUME_STEM, application_dir,
                   find_jd_files, source_dir, tailored_path)
from location import classify_locations, extract_jd_locations, is_match
```

The hardcoded bucket list `("shared", "resume-render", "application-tracking")` is
duplicated in `status.py`, `migrate_layout.py`, `backfill_location.py`, `check.py`,
`render.py`, and `cover_letter.py`. Add a bucket and you edit six files. There are
no `__init__.py` files anywhere — nothing is a real Python package.

### 2.3 `scripts/` is an overloaded, ambiguous name

In `SKILL.md` files, `scripts/foo.py` sometimes means the **repo-root** toolkit and
sometimes means the **skill's own** `scripts/` folder — with no way to tell which:

- `job-search/SKILL.md` says `scripts/registry.py` (skill-local) *and*
  `scripts/status.py` / `scripts/location.py` (repo-root) in the same document.

### 2.4 Documentation drift after the bucket reorg

The `scripts/` split into `resume-render/` / `application-tracking/` / `shared/`
was never propagated to the skill docs. These paths appear in `SKILL.md` files but
**no longer exist**:

```
MISSING (stale ref): scripts/status.py       (real: scripts/application-tracking/status.py)
MISSING (stale ref): scripts/check.py        (real: scripts/shared/check.py)
MISSING (stale ref): scripts/render.py       (real: scripts/resume-render/render.py)
MISSING (stale ref): scripts/cover_letter.py (real: scripts/resume-render/cover_letter.py)
MISSING (stale ref): scripts/location.py     (real: scripts/shared/location.py)
```

An agent that copy-pastes a command from `SKILL.md` runs a path that does not exist.

### 2.5 The location rule is already duplicated across the boundary

`scripts/shared/location.py` re-implements the "preferred metro OR US-remote" rule
that the job-search skill's `scripts/scoring.py` (`location_ok`) also encodes — its
own docstring calls this out:

```1:15:scripts/shared/location.py
"""Classify a posting location string against the job-search location rule.
...
that ``scripts/application-tracking/status.py --check-locations`` and
``scripts/shared/check.py`` can flag drafts that do not respect the location
criteria.

This mirrors the location logic in
``.agents/skills/job-search/scripts/scoring.py`` (``location_ok``) but works from
the raw location string alone (there is no separate ``remote`` field here).
```

So one business rule ("what counts as an acceptable location") lives in two files
in two worlds. When the rule changes, both must change in lockstep — with nothing
enforcing it.

### 2.6 What is actually shared (the real coupling surface is small)

Mapping who-uses-what:

| Module | Home | Consumers | Cross-cutting? |
|--------|------|-----------|----------------|
| `location.py` | `scripts/shared/` | application-tracking (`status`, `backfill_location`), **wants** job-search (`company_roles`), conceptually job-search (`scoring`) | **Yes** — pure logic, no deps |
| `check.py` stems/layout helpers (`RESUME_STEM`, `application_stem`, `application_roles`, `slugify_label`, `source_dir`) | `scripts/shared/` | resume-render (`render`, `cover_letter`), application-tracking (`status`, `migrate_layout`) | Yes — but only inside the "application" domain |
| `pdf_convert.py` | `scripts/resume-render/` | resume-render only (`render`, `cover_letter`) | No — intra-bucket |
| `registry.py` + `companies.yaml` | job-search skill | job-search only | No — skill-local |
| `common/sources/scoring/visa/aggregators` | job-search skill | job-search only | No — skill-local |

**Key insight:** the genuinely cross-cutting surface is tiny — essentially
`location.py` (pure, zero third-party deps) and a handful of naming/layout constants
in `check.py`. Everything else is single-owner. Any solution should optimize for
"keep the shared surface small and pure," not for sharing everything.

## 3. What the Agent Skills standard says (research)

Sources: Anthropic's [Agent Skills overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview),
[authoring best practices](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices),
the [open Agent Skills specification](https://agentskills.io/specification), and the
public [`anthropics/skills`](https://github.com/anthropics/skills) reference repo.

1. **A skill is a self-contained directory.** `SKILL.md` (required) + optional
   `scripts/`, `references/`, `assets/`. Scripts are *executed*, not read into
   context.
2. **Portability is a first-class goal.** "Skills use the same format everywhere.
   Build once, use across Claude apps, Claude Code, and API." Agent Skills are now
   published as an open cross-platform standard.
3. **File references must be relative to the skill root and shallow.** The spec:
   "use relative paths from the skill root … keep file references one level deep."
   Reaching *out* of the skill (`../../scripts/...`) is off-pattern.
4. **Scripts should "be self-contained or clearly document dependencies."** Deps are
   declared per skill — the reference repo ships per-skill
   `scripts/requirements.txt` (e.g. `mcp-builder`, `slack-gif-creator`) and uses the
   optional `compatibility` frontmatter field for system/runtime requirements.
5. **Anthropic's own answer to cross-skill sharing is to VENDOR (copy) code.** In
   `anthropics/skills`, the `docx`, `pptx`, and `xlsx` skills each carry their *own*
   full copy of the shared `office/` helper library — `base.py`, `docx.py`,
   `pptx.py`, `redlining.py`, the OOXML schemas, etc. appear **3 times**, once per
   skill. There is no central shared library imported across skills. Self-containment
   is chosen over DRY on purpose.
6. **Prefer scripts for deterministic work; make execution vs. read intent explicit;
   handle errors in the script ("solve, don't defer"); avoid magic constants.**

Takeaway: the standard pushes toward **self-contained skills with a stable,
documented invocation surface** and treats duplication as an acceptable cost of
portability. It says nothing endorsing a shared importable library *across* skills.

## 4. Design goals / evaluation criteria

Any approach is judged on:

- **G1 — No fragile imports.** A file move must not silently break a caller.
- **G2 — Single source of truth for shared logic** (or an enforced way to keep
  copies in sync). No silent divergence of the location rule, filename stems, etc.
- **G3 — Skill portability / self-containment.** How close is a skill to "copy the
  folder elsewhere and it works," per the open standard.
- **G4 — Clear ownership.** An unambiguous rule for "where does a new script go?"
- **G5 — Low ceremony.** Minimal boilerplate; adding a script/skill is cheap.
- **G6 — Discoverable & correct docs.** `SKILL.md` invocation paths stay accurate.
- **G7 — Scales.** Still sane at 15 skills / 60 scripts.

## 5. Comparison matrix

| Criterion | A: Shared package | B: Vendored self-contained | C: CLI boundary | D: Hybrid (rec.) |
|-----------|:---:|:---:|:---:|:---:|
| G1 no fragile imports | ✅ (real package) | ✅ (no cross imports) | ✅ (no imports) | ✅ |
| G2 single source of truth | ✅✅ | ⚠️ (copies + drift check) | ✅ | ✅ (core) / ⚠️ (vendored edges) |
| G3 skill portability | ❌ (repo-coupled) | ✅✅ | ⚠️ (needs the CLI present) | ✅ |
| G4 clear ownership | ✅ | ✅ | ✅ | ✅ |
| G5 low ceremony | ⚠️ (packaging/install) | ⚠️ (sync discipline) | ⚠️ (output contracts) | ⚠️ (two rules to learn) |
| G6 doc correctness | ✅ (stable import) | ✅ | ✅ (CLI names) | ✅ |
| G7 scales | ✅ | ⚠️ (copies multiply) | ✅ | ✅✅ |
| Effort to adopt | Medium | Low–Medium | Medium–High | Medium (phased) |
| Fit to Agent Skills std | ❌ off-pattern | ✅✅ canonical | ✅ ("execute the script") | ✅ |

## 6. Recommendation

**Adopt Approach 4 (Hybrid), rolled out in phases.** Rationale:

- This repo is a **single monorepo**, not a skill marketplace, and the compatibility
  symlinks (`.claude/skills`, `.cursor/skills`) already give cross-tool reuse *within
  the repo*. So the extreme portability of pure vendoring (Approach 2) is not needed
  today — but it is cheap to preserve as an option for the one or two skills that are
  genuinely reusable elsewhere (`job-search`).
- The real, measured pain is **fragile `sys.path` imports (§2.1, §2.2)**, **an
  overloaded `scripts/` name (§2.3)**, **doc drift (§2.4)**, and **a duplicated
  business rule (§2.5)** — all of which the Hybrid fixes directly.
- The genuinely shared surface is tiny and pure (§2.6), so a **small importable
  "core"** for repo-internal toolkit scripts (Approach 1, scoped down) removes the
  `sys.path` hacks with minimal packaging cost, while a **stable CLI contract**
  (Approach 3) is the *only* thing a skill is allowed to depend on across the
  boundary. Skills never import repo-root Python.

Concretely, the Hybrid says:

1. Turn `scripts/` into one installed, importable package (`jobsfinder`), killing all
   `sys.path` bootstraps and making the shared surface a normal `import`. One home for
   `location`, the `check` stems, and layout helpers.
2. A skill may **only** consume shared functionality through a **documented CLI**
   (e.g. `python -m jobsfinder.location --classify "..."`), never by importing repo
   Python. That keeps skills decoupled and their `SKILL.md` commands honest.
3. If a specific skill must be exportable/standalone (job-search), it **vendors** the
   one pure module it needs (`location.py`) into its own `scripts/_vendor/` with a
   `sync_vendored.py` + a drift-check test — exactly the `anthropics/skills` pattern,
   but for a single ~200-line pure file, not a whole library.
4. A short "where does a script go?" decision rule (in `AGENTS.md`) makes ownership
   unambiguous going forward.

See [approach-4-hybrid-recommended.md](approach-4-hybrid-recommended.md) for the full
design, directory layout, code sketches, and a phased migration plan. Phase 1
(package-ify `scripts/`, delete the `sys.path` hacks, fix the stale `SKILL.md` paths)
delivers most of the value on its own and is a safe, self-contained first step.

## 7. Cross-cutting fixes (do these regardless of approach)

These are pure wins independent of which architecture is chosen:

- **Fix the broken import in `company_roles.py`** (§2.1) — it is shipping broken.
- **Fix the stale `SKILL.md` command paths** (§2.4) — or (better) stop hand-writing
  paths that a reorg can break.
- **De-duplicate the location rule** (§2.5) — one implementation, one owner.
- **Add a `where-does-this-script-go` rule to `AGENTS.md`** (§ G4).
- **Keep `__pycache__` out of the tree** — it is gitignored but present in working
  copies; ensure it is never committed.
