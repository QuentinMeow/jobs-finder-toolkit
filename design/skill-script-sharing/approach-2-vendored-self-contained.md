# Approach 2 — Self-contained skills with vendored shared code

**Strategy:** Portability-first. Every skill owns *all* the code it runs, under its
own `scripts/`. When two skills (or a skill and the root toolkit) need the same
logic, that logic has ONE canonical source and is **copied ("vendored")** into each
consumer. A sync script + a drift-check test keep the copies identical. No code is
ever imported across a skill boundary.

This is exactly what Anthropic does in the public `anthropics/skills` repo: the
`docx`, `pptx`, and `xlsx` skills each carry a full copy of the shared `office/`
helper library (`base.py`, `docx.py`, `redlining.py`, OOXML schemas, …) — the same
files appear three times, once per skill. Self-containment is chosen over DRY.

## How it works

1. Pick a **canonical home** for each shared module. Natural choice: the "most
   owning" skill, or a top-level `shared-lib/` that is a *source*, not an import
   target. For this repo: `location.py` and the naming/layout helpers are the shared
   items.
2. Each skill/toolkit area that needs a shared module gets a **copy** under its own
   `scripts/_vendor/` (clearly marked "generated — do not edit").
3. A `sync_vendored.py` script copies canonical → all vendor targets. A
   `test_vendored_in_sync.py` (run in CI / pre-commit) fails if any copy has drifted
   from its source, so the copies can never silently diverge.
4. Skill scripts import their *local* vendored copy: `from _vendor.location import
   classify_location`. No `sys.path` reaching outside the skill.

### Proposed layout

```
shared-lib/                              # canonical SOURCES (not imported directly)
├── location.py
├── naming.py
└── sync_vendored.py                     # copies sources into every registered target
                                         # + registry of {source -> [targets]}

.agents/skills/job-search/scripts/
├── search_jobs.py
├── scoring.py                           # imports _vendor.location (no dup rule)
├── company_roles.py                     # imports _vendor.location  (fixes the bug)
└── _vendor/                             # GENERATED — do not edit
    ├── README.md                        # "run shared-lib/sync_vendored.py to update"
    └── location.py                      # byte-identical copy of shared-lib/location.py

scripts/resume-render/
├── render.py
├── _vendor/
│   └── naming.py
scripts/application-tracking/
├── status.py
└── _vendor/
    ├── location.py
    └── naming.py
```

### Drift check (the linchpin)

```python
# test_vendored_in_sync.py — run in pre-commit/CI
import hashlib, sys
from pathlib import Path
from sync_vendored import TARGETS   # {source_path: [vendor_paths]}

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

drift = [(src, dst) for src, dsts in TARGETS.items()
         for dst in dsts if digest(src) != digest(dst)]
if drift:
    for src, dst in drift:
        print(f"OUT OF SYNC: {dst} != {src}")
    print("Run: python shared-lib/sync_vendored.py")
    sys.exit(1)
```

## Pros

- **G3 ✅✅ Maximum portability / self-containment.** Any skill folder can be lifted
  out and run elsewhere (another repo, the Claude API code-execution sandbox with no
  network, a marketplace) with zero external dependencies. This is *the* canonical
  Agent Skills pattern and what the standard optimizes for.
- **G1 ✅ No fragile cross-boundary imports.** Nothing reaches outside its own folder;
  a file move in one world cannot break another. Fixes README §2.1 by construction.
- **G4 ✅ Clear ownership.** "Canonical source in `shared-lib/`; everything else is a
  generated copy; edit the source, never the copy."
- **Runs in any environment**, including sandboxes with no install step and no
  network — a strict superset of where Approach 1 works.
- Matches the reference implementation maintainers already look to.

## Cons

- **G2 ⚠️ DRY only by enforcement, not by construction.** The same file physically
  exists N times. Without the drift check running reliably, copies diverge — the
  exact problem in README §2.5 (location rule in two places), just formalized. The
  guarantee is only as good as the pre-commit/CI hook.
- **G5 ⚠️ Sync discipline.** Editing shared logic is a two-step ritual: edit the
  source, then run `sync_vendored.py`, then commit the regenerated copies. Easy to
  forget; noisy diffs (one logical change touches N copies).
- **G7 ⚠️ Copies multiply with scale.** At 15 skills each vendoring 3 modules, a
  one-line fix to a shared module produces a 15-file diff. Reviewable but heavy.
- Vendored copies inflate the repo and can confuse search/grep ("why are there five
  `location.py`?").
- Overkill for logic that only ever runs in this repo — you pay the portability tax
  even for skills you will never export.

## When to choose this

Choose Approach 2 if **portability is a real requirement** — you plan to publish
skills to a marketplace, run them in the Claude API sandbox, or share individual
skill folders across repos/machines. It is the "correct by the standard" answer and
the right default for a skills *library* meant for distribution. For a private,
single-repo toolkit it is heavier than necessary — which is why the recommendation
(Approach 4) applies vendoring *selectively*, only to skills that must be exportable.

## Migration steps

1. Create `shared-lib/` with the canonical `location.py` + `naming.py` (extract the
   stems/layout helpers out of `check.py`).
2. Write `sync_vendored.py` with a `TARGETS` registry mapping each source to its
   vendor destinations; write `test_vendored_in_sync.py`.
3. Run the sync to generate every `_vendor/` copy; switch each script to import its
   local `_vendor` copy (this also **fixes** `company_roles.py`, README §2.1).
4. Delete the `sys.path` bootstraps and the duplicated `scoring.location_ok` rule
   (import the vendored `location` instead).
5. Wire the drift check into pre-commit + CI so copies can never diverge unnoticed.
6. Update `SKILL.md`/`AGENTS.md`: document that `_vendor/` is generated and how to
   regenerate.

**Effort:** Low–Medium (mostly mechanical + one sync script + one test). Reversible.
