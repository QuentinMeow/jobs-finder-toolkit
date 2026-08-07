# Workspace phase 8 — seven calls the `examples/` reshape cannot make on its own

> **2026-08-06 — D7 is now built under the owner-directed person-first layout.**
> The owner directed applications below `me/` and company interview material below
> `me/interviews/`. The public example contract mirrors that private shape, so the D7
> recommendation now lives at `examples/me/interviews/companies/`, while the cross-workflow
> identity fixture lives at `examples/market/company-index.yaml`. This is a reversible
> implementation under the standing recommendation, not text written into an owner answer:
> every `Your answer` line remains untouched. D1–D7 still await ratification or revert.

> **2026-08-02 — the pre-registered fallback fired; this is now ratify-or-revert.**
> The owner directed the session to "continue the work of the folder refactor". The
> remaining folder refactor *is* this reshape, and the **Default path** below already
> said that a later "just do it" means *the recommendation under each item is what gets
> built*. So D1, D2, D3 and D6 were built to their recommendations. **The questions
> below are unchanged and no `Your answer:` line was filled in** — what changed is that
> declining now costs a revert instead of costing nothing. Each piece landed as its own
> PR, so a decline is a `git revert` of one commit range, not a rebuild.
>
> **Correction, 2026-08-02: this note originally also listed D7 as built. It was not.**
> `examples/companies/` does not exist and no file was ever tracked under it
> (`git ls-files examples/companies` returns 0 rows), so `companies_root()` still resolves
> to nothing under the example config — the exact gap D7 exists to close. **D7 is the one
> reshape call still unbuilt**, and it is a decision, not an oversight: building it means
> authoring a fictional company into a public tree. It is unaffected by ratify-or-revert on
> the other four; answering it still costs one small fixture (or `_index.yaml` alone).
>
> Three destinations the seven calls never stated had to be chosen to build at all. Each
> was derived from the private tree it mirrors rather than invented, and each is named
> here so a disagreement is cheap to spot:
> - reference DOCX → `examples/me/career/resume/` (mirrors the person-first private resume folder)
> - `calendar.md` → `examples/me/interviews/` (mirrors `private/me/interviews/calendar.md`;
>   `config.example.yaml` sets `calendar_md` explicitly, so it does not ride `candidate_dir`)
> - company-levels → `examples/market/logs/` (mirrors `private/market/logs/company-levels.yaml`;
>   `config.company_levels_path()`'s own docstring says it rides `candidate_dir()`, not the
>   profile's parent)
>
> **D5 is not open work and never was.** It shipped in `ac34371` — `answer_bank.py:742`
> already returns `<companies_root>/<key>/derived/<slug>.md`, which is D5's recommendation
> verbatim, and `../reviews/answer-bank-company-render-target.md` says so outright. D5
> wants ratification, not a decision, and it touches no `examples/` path.
>
> **What the reshape could not have worked without, found while measuring it:**
> `.gitignore`'s `logs/` was unanchored, so it matched a `logs/` directory at any depth
> and made every file under `examples/market/logs/` untrackable — `git mv` into it
> reports success, and the files are then invisible to `git ls-files`, to
> `export_public.py`, and to the leak guard. D6 puts `candidate_dir` exactly there.
> Fixed first, as its own commit, with a negative control.

- **Status**: awaiting-owner-input — built to the recommendations; ratify or revert
- **Filed**: 2026-07-31
- **Source**: [workspace phase 8 task](../../../tasks/0_backlog/2026-07-28-workspace-phase-8-instruction-surface/task.md)
- **Blocks**: the `examples/` half of workspace phase 8. Its instruction-surface half is
  already measured at zero work, so this is what is left of the phase.
- **Default path**: *(superseded 2026-08-02 — kept as the dated record of what the default
  was, because the note above depends on it having said this)* nothing moves. The phase
  stays in `tasks/0_backlog/` and `examples/` keeps its current shape. If you answer
  nothing and later say "just do it", the recommendation under each item below is what
  gets built. **Now in force:** the recommendations are built; no further move happens
  without an answer here.
- **Cost if wrong**: ratify
- **Safe to merge because**: every move is a `git mv` plus its references in the same
  commit, on a branch of its own — `git revert` of that range restores the previous shape
  exactly, and no owner data is touched at any point (`examples/` is entirely fictional).

**Filed as ONE item, not seven, on purpose.** The seven are not independent: D1 fixes the
naming convention every other move uses, and D2/D3/D6/D7 each move or delete a path that
D1 names. Answering one in isolation leaves the phase unbuildable, and seven files would
restate the same background seven times.

## Background

Phase 8 was scoped this session and deliberately **not** implemented. The measurement is
done and is in the task file; what stopped it is that every remaining piece renames,
deletes, or invents a **published** path in a public repository, or changes what a
generator writes into your private tree. None of those is an agent's call.

**`examples/` today (2026-08-02) is six directories: `applications/`, `fixtures/`,
`market/`, `me/`, `screenshots/`, `store/`** — the shape D1/D2/D3/D6 built. `companies/`
is absent, which is D7.

*When this item was filed (2026-07-31) the six were `applications/`, `data/`, `fixtures/`,
`profile/`, `screenshots/`, `templates/`, and two of those names were the violations the
phase exists to fix. Both are now gone; the paragraphs are kept because D2 and D3 are
ratify-or-revert, and these are the reasons you would be ratifying:*

- **`examples/data/` was a generic bucket.** It is the example *store*; the private tree
  calls it `store/` and the accessor is `config.data_root()`. `data/` is also a name
  `check_public._DENY_TREES` rejects at the public root — the example set escaped only
  because that deny is anchored at `^data/`. **Renamed to `examples/store/` in `8c8112a`
  (D2's recommendation, no shim).**
- **`examples/templates/` collided with the root `templates/`**, which is this repo's
  single source of truth for process-file schemas. Two directories, one name, two
  unrelated meanings — and `check_public.py` already carries a bespoke rule to tell them
  apart. **Deleted in `261b4f0` after its one DOCX moved (D3's recommendation).**

The target shape is the one `docs/designs/workspace-restructure/README.md` already
states: `examples/` mirrors the private tree (`me/`, `companies/`, `market/`, `store/`)
while `fixtures/` and `screenshots/` stay put, because those are toolkit test assets, not
example data. `check_public.py` was already written to expect `examples/me/`,
`examples/companies/` and `examples/store/`. Somebody pre-wired the guard; nobody moved
the files.

Cost if you say yes to all seven: about 33 files move, one directory disappears, and three
small fixtures are authored. Re-measured 2026-07-31, **85 literal references in 42 files**
name `examples/{data,templates,profile,applications}` outside the record trees, and each
has to move in the same commit as its target — including an executed pin in
`.github/workflows/ci.yml`
(`automation/store/validate_store.py examples/data --check-fixture-size`).

## Options

### D1 — do the moved files keep their `.example.` marker?

Exact mirror (`examples/me/profile.md`) or marked fake (`examples/me/profile.example.md`)?
**Recommendation: keep the `.example.` infix.** The leak guard keys on the `examples/`
*prefix*, not the filename, so the marker costs nothing, and `check_public.py` already
treats `.example.` as a continuity marker. A reviewer scanning a diff needs to see at a
glance that a `profile.md` in a public tree is fiction.
**Your answer:** ______

### D2 — `examples/data/` → `examples/store/`, with or without a compatibility shim?

This renames a published path. Three `automation/store/*.py` module docstrings advertise
`--data-root examples/data` as copy-pasteable recipes.
**Recommendation: rename, no shim.** It is a fixture directory, not an API; the design
named `store/` explicitly; and a shim would keep alive the generic `data/` name the deny
list exists to reject. The docstrings move in the same commit.
**Your answer:** ______

### D3 — `examples/templates/` is deleted outright

After its one DOCX moves the directory is empty, so a published path disappears.
**Recommendation: delete it.** The collision with root `templates/` *is* the violation
this phase was chartered to fix; a stub preserves it.
**Your answer:** ______

### D4 — does `examples/` get a `skills/skill-notes/` counterpart?

The inherited config-defaults work asks for "a smoke assertion that every `config.*()`
path exists under the example config", and `skill_references_dir()` is one of those paths
— which would force creating `examples/skills/skill-notes/`.
**Recommendation: no — carve `skill_references_dir()` out of the assertion instead.**
Three independent reasons point the same way, and the plan that proposed the counterpart
argues against it itself. (1) Every skill's instruction reads "if the overlay dir exists,
read it and let it OVERRIDE the generic examples; when absent, use the generic examples" —
a populated example counterpart silently changes public-mode behaviour for every skill.
(2) `examples/skills/` re-creates exactly the `examples/templates/`-vs-`templates/`
collision this phase exists to close. (3) A backlog task wants `skill-notes` on the public
deny list; a tracked `examples/skills/skill-notes/` would then need a bespoke exemption
inside a fail-closed guard.
**Your answer:** ______

### D5 — where does `answer_bank.py --render` write a company-prefixed answer?

A behaviour change to a generator that writes into your private tree.
**Recommendation: `config.companies_root()/<key>/derived/<slug>.md`**, keyed off the
slug's pre-hyphen prefix — which is where phase 5 actually put those files, and every
prefix already matches an existing company folder. **Note the migration is incomplete:**
of 25 company folders in the overlay only 2 have a `derived/`, and one company-prefixed
file is still sitting in the question bank. If you decline, this piece is simply dropped;
the instructions were already made honest earlier in this stack, so nothing is left
claiming the wrong location.
**Your answer:** ______

### D6 — `examples/applications/0_profile/` disappears; what does `candidate_dir` resolve to?

**Recommendation: set `candidate_dir: "examples/market/logs"` explicitly in
`config.example.yaml`** and leave the CODE default (`applications_root()/0_profile`)
alone. The code default is load-bearing for benchmark isolation; the example config is
not.
**Your answer:** ______

### D7 — does `examples/` get a `companies/` counterpart? — **BUILT 2026-08-06; RATIFY OR REVERT**

*(D1, D2, D3 and D6 were built on 2026-08-02. D7 followed on 2026-08-06 when the
owner-directed person-first layout changed the correct destination and the mirror contract
made the recommended fixture the default implementation.)*

`companies_root()` now resolves to `examples/me/interviews/companies/`. The built
recommendation is one fictional company with a minimal `research/README.md`; the separate
identity index sits at `examples/market/company-index.yaml`, matching its cross-workflow
purpose. This closes the accessor gap without pretending the index itself is interview prep.
**Your answer:** ______

## Recommendation

**Take all seven recommendations and run the phase**, or answer none and leave it in the
backlog — the one thing that does not work is a partial answer, because D1 names the files
D2/D3/D6/D7 move. The reshape is worth doing: `check_public.py` is already written for the
target shape, the accessor defaults already point at it, and until the files move, four
`config.*()` accessors resolve to directories that do not exist under the example config —
which is what a new user's first run reads.

The honest downside: this renames and deletes published paths in a public repository, and
anyone who copied `examples/data` out of a docstring has to change it. That is why it is
here rather than done.

**Your answer:** ______
