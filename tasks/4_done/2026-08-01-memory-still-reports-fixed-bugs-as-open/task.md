# `memory/` reports four fixed things as open, and one ADR points handovers off the tracked tree

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**: agent, session 2026-08-02 (branch `docs/26-contract-and-record-corrections`)

## Goal

Nothing an agent reaches through `memory/index.md` describes present-tense breakage the code has
already fixed, or sends a write to a directory the repo does not use.

## Context

`AGENTS.md:113-114` puts `memory/index.md` in the boot sequence, and `memory/README.md:3` says
everything outside `decisions/` states *current* truth. Six entries do not.

1. **`memory/known-issues/location-title-only-foreign-leak.md:3` — `Status: open`.** Its body
   (`:12-14`) says a posting whose foreign city appears only in the title survives location
   filtering. The search now passes the title into the classifier:
   `skills/job-search/scripts/scoring.py:319` — `title=posting.title,` — read in the rejecting
   direction at `automation/shared/location.py:759-763`. Re-running the entry's own reproduction
   returns `foreign`/`no_match`. `docs/roadmap/desired-state.md:68-69` still lists it among the
   defects with "the shortest path to a wrong artifact reaching the user", so the roadmap points
   work at it too.

2. **`memory/known-issues/rw-tailor-single-posting-canary-fixture-conflict.md:3` — `Status: open`,**
   and `:44-46` prescribes a "manual, undocumented workaround" for every gate run. Its Suggested fix
   is already implemented: `evals/canaries/resume-writer.yaml:19-37` stages an ISOLATED fresh-tailoring
   scaffold seeded with only `meta.yaml` + `source/JD-*.md`, citing the same issue by number.

3. **`memory/known-issues/render-py-pdf-skipped-libreoffice-flake.md:43-45` — "No structural fix has
   landed".** `skills/resume-writer/LESSONS.md:99-103` says the opposite ("is now handled inside
   `pdf_convert.py`"), and `skills/resume-writer/scripts/pdf_convert.py:8-12` verifies a >1 KB PDF
   landed, clears lock state, retries once and raises instead of returning `None`. Its `Source:`
   line also no longer points at the text it quotes.

4. **`memory/known-issues/skills-diff-provenance-noise.md:38-40`** proposes dropping degree-pattern
   candidates; `skills/resume-writer/scripts/skills_diff.py:106-109` already ships `_DEGREE_CHAIN_RE`.
   `Status: open` is still correct for the provenance-header half — only the Suggested fix needs the
   done half struck, or an agent re-implements it.

5. **`memory/decisions/workspace-layout-public-root-plus-review-gate.md:80-81`** states under
   *Consequences*, as accomplished fact: "Session handovers move to `private/local/history/` (never
   committed), so the reconciler's `handover-present` check becomes local-only and vacuous in CI."
   Nothing of the sort happened: `AGENTS.md:157-158` writes handovers to
   `history/conversations/<YYYY-MM-DD>-<slug>/`, `automation/reconcile/reconcile.py:587` checks
   `history/conversations`, and 33 handovers are tracked — the newest three days *after* the ADR.
   `message-queue/needs-human/decisions/history-untracked-in-phase-5.md` is open on exactly this,
   with the default path "`history/` does **not** move", but the ADR carries no pointer to it, so an
   agent reading the ADR writes its handover somewhere that never reaches a remote.
   ADRs are immutable (`AGENTS.md:95`), so the fix is a forward-link in the header, the convention
   `memory/decisions/process-folders-layout.md:4` already uses — not an edit to the Consequences text.

6. **`memory/decisions/sponsorship-offer-versus-denial.md:32-34`** still lists bare `all` as a
   scope-limit cue; `automation/shared/job_metadata.py:1525` dropped it (it is now an *ambiguous*
   cue at `:1567`). Two later ADRs reversed this one and each amended its own header, but this file
   — the one whose rule produced `likely`/`match` on a written refusal — has no `Superseded-by`
   line, and all three sit adjacent in `memory/index.md:21-23` with no ordering signal.

Filed rather than fixed in place because flipping a `known-issues` status is a claim about the code
that the next reader will trust, and each one wants its fixing commit named (the zone's own
retention rule) — plus item 5 amends an immutable record and item 1 also touches
`docs/roadmap/desired-state.md`.

## Definition of done

- [ ] Entries 1-3 carry `Status: fixed` with the fixing commit, or are pruned per
      `memory/known-issues/README.md`'s retention rule; entry 4's Suggested fix names only the
      outstanding half.
- [ ] `docs/roadmap/desired-state.md` no longer lists a fixed defect as live.
- [ ] The workspace-layout ADR links `history-untracked-in-phase-5.md` in its header; the first
      sponsorship ADR links its two successors.
- [ ] `.venv/bin/python automation/reconcile/reconcile.py --check --fix-index` leaves
      `memory/index.md` unchanged, and the full pre-commit chain is green.
