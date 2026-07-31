# The instruction surface says what the code does

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: doc-vs-code contradiction audit, 2026-07-30 (findings 6, 7, 8, 15, 18) + the
  re-measured phase-8 plan's "correct the instructions that are factually wrong" section
- **Claimed-by**: agent (2026-07-31)

## Goal

Every document in this repo that describes the code describes what the code actually does:
the gate table lists every gate with its real flags and its real location, the gardener skill
documents all eight routines, the public-skill count is right, each PR-workflow rule names its
audience, and the four instructions that pointed at a location holding nothing point at the
real one.

## Context

Six items, each re-verified against the code on this branch before being changed — several
findings in the source audit predate PRs 01-07 of this stack, which already moved `ci.yml`,
the pre-commit surface, `instruction_budget.py`, `verify_links.py`, `check_public.py`,
`config.py`, `review_gate.py` and `reconcile.py`.

1. **Gate table.** `skills/github-workflow/SKILL.md` §3 listed nine gates and omitted the tenth
   the hook runs (`automation/gardener/verify_links.py`), and printed `--require-roots`
   unconditionally where both hook branches key on `[ -d private ]`. Earlier PRs in this stack
   also added four of these gates to CI, so the "Where" column now names hook vs CI vs both.
2. **Gardener routines.** `gardener.py`'s `ROUTINES` dispatches eight; the skill documented six.
   `skill-drift` and `store-report` appeared in no skill doc, no handbook page and no
   `AGENTS.md`, so `--all` (whose `ALL_ORDER` runs all eight) emitted output the skill could
   not explain.
3. **Skill count.** `docs/handbook/architecture.md` said "the eight public skills"; there are
   eleven, per `sync_skill_manifests.public_skills()` and every other surface.
4. **Stacked PRs.** `CONTRIBUTING.md` forbade what `skills/github-workflow/SKILL.md` teaches.
   Neither said which audience it binds — though CONTRIBUTING's own step 1 already carved the
   maintainer out, and the skill already noted the rule was contributor-facing.
5. **`.cursor/skills/github-manager/`** — an untracked, contentless leftover of the
   `github-manager` -> `github-workflow` rename.
6. **Four wrong instructions** — the search-profile location (ask-me-anything, job-search),
   the company behavioural-answer location (behavioral-interview-prep), and the status-folder
   range (`AGENTS.md`).

Out of scope by instruction: `examples/` (a later, larger reshape), and any behaviour change to
`answer_bank.py` (filed as its own backlog task).

## Definition of done

- [x] The gate table lists all ten gates, with the two conditional `--require-roots` branches
      and the hook/CI split stated; verified against `automation/hooks/pre-commit` and
      `.github/workflows/ci.yml` as they stand on this branch.
- [x] `skills/gardener/SKILL.md` documents all eight routines and `--all`'s fixed order.
- [x] `architecture.md` says eleven; no other doc carries a stale count
      (`grep -rn 'eight public'` over `docs/ README.md AGENTS.md CONTRIBUTING.md skills/ evals/`).
- [x] `CONTRIBUTING.md` states its audience and rule 6 says it does not bind the maintainer.
- [x] The orphan directory is gone; the manifest-sync fixture no longer uses its name.
- [x] Each of the four instructions names the location the code and the tree actually use.
- [x] `instruction_budget.py --strict`, `reconcile.py --check --require-roots`,
      `check_public.py` and `verify_links.py --require-roots --no-overlay` all clean;
      full gate ALL GREEN after the closing ledger commit (`verification.md`).
