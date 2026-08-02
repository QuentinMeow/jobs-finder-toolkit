# job-search's own docs still route the blacklist to the public registry

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: contradiction audit 2026-07-31, mechanical finding A1 — the remainder left
  unfixed by the four-site repair (branch `wip/13-blacklist-doc-routing`)
- **Claimed-by**: the doc edits landed in `8a1321a`; the record was corrected and
  re-verified on `wip/28-verification-regressions`, 2026-07-31

## Goal

Point the five remaining `skills/job-search/` doc sites at the merged registry, so the
job-search skill's own documentation stops instructing a reader to write a personal
blacklist row into the published `companies.yaml`.

## Context

The blacklist lives in the git-ignored overlay at `config.blacklist_path()`
(`private/market/blacklist.yaml`). `registry.load_registry()` merges it into
`skills/job-search/companies.yaml`'s entry list at load time
(`skills/job-search/scripts/registry.py`, `_overlay_blacklist_entries()`), and the two
sources share ONE entry schema — which is why a `blacklist:` row written into the public
file works, and why nothing downstream ever notices. The tracked registry carries zero
such rows (`grep -n '^\s*blacklist:' skills/job-search/companies.yaml` → no match).

The 2026-07-31 audit named four sites; they were fixed on `wip/13-blacklist-doc-routing`
(`docs/handbook/architecture.md`, `skills/application-tracker/LESSONS.md`,
`skills/resume-writer/reference.md`, `skills/job-search/companies.yaml`, plus the twin
sentence in `skills/job-search/scripts/registry.py`'s docstring). The canonical wording to
match is `skills/resume-writer/SKILL.md:89-92`.

**These five are FIXED — in `8a1321a`, the same commit that filed this task.** The task was
written while all three files were being edited concurrently by `wip/02-handoff-skiplog`,
`wip/04-job-search-scratch-paths` and `wip/07-company-roles-jd-digest`, so it was filed as
"not fixed"; once those branches landed, the same commit made the edits and the task text
was never updated to match. An independent verification of the stack caught the
contradiction (`8a1321a`'s own diff shows `SKILL.md` +3/-3 and `reference.md` +20/-9), and
corrected it here on 2026-07-31. **Nothing in the table below is still open** — it is kept
as the record of what was wrong and where:

| Site | What it says | Why it is wrong |
|---|---|---|
| `skills/job-search/reference.md:535-537` | *"**To blacklist a company** (never consider it), add a `blacklist: "<reason>"` key to its entry. If you don't poll it, add an identity-only row…"*, inside § Managing target companies, which is about `companies.yaml` | **The worst site in the whole finding** — it is not a description, it is a step-by-step instruction to write a personal skip rule into a published file. The audit missed it |
| `skills/job-search/reference.md:524` | *"`companies.yaml` … the single source of truth for company identity, ATS poll config, `tags`, and the blacklist"* | Same false claim as the four already fixed |
| `skills/job-search/reference.md:449-451` | *"**Blacklist (in `companies.yaml`)** — every posting from a registry entry carrying a `blacklist:` reason … is dropped"* | The behaviour is right; the parenthetical names the wrong file. Should read "in the MERGED registry" |
| `skills/job-search/SKILL.md:286` | *"`companies.yaml` \| Canonical company registry — identity, ATS poll config, tags …, blacklist"* | Same false claim |
| `skills/job-search/SKILL.md:274` | *"Managing `companies.yaml` (add a board token, validate, blacklist)"* | Routes the reader to the reference.md section above |

`skills/job-search/SKILL.md:296` (*"Registry loader + resolver (canonical name, blacklist,
poll targets…)"*) is CORRECT as written — the loader really does resolve the blacklist —
and needs no change.

A mechanical guard now backstops all five: the reconciler's `public-registry-blacklist`
check (`automation/reconcile/reconcile.py`) fails any commit that adds a `blacklist:` key
to the tracked registry, so a reader who follows `reference.md:535` today is stopped at
the pre-commit hook rather than at a human review. That is what makes this P1 rather than
P0 — the leak can no longer land, but the instruction is still wrong and still wastes the
reader's time.

Two adjacent list-completeness items are deliberately NOT in scope here; they belong to
the gate-list work on `wip/15-roadmap-and-gate-lists`:
- `AGENTS.md:230-233` names 4 of what are now 9 reconciler checks.
- `docs/handbook/repo-map.md:79` describes the reconciler's check surface.

## Definition of done

All met by `8a1321a`; re-verified 2026-07-31 on the stack tip — output in
`verification.md`.

- [x] All five sites above name the merged registry / `config.blacklist_path()`, matching
      `skills/resume-writer/SKILL.md:89-92`.
- [x] § Managing target companies tells the reader to add a blacklist row to the OVERLAY, and
      says the reconciler rejects one added to `companies.yaml`.
- [x] `grep -rn 'blacklist' skills/job-search/SKILL.md skills/job-search/reference.md` shows no
      remaining sentence that places blacklist rows in `companies.yaml`.
- [x] `.venv/bin/python automation/reconcile/reconcile.py --check` → OK.
- [x] `.venv/bin/python automation/gardener/verify_links.py` → OK.
- [x] `.venv/bin/python automation/metrics/instruction_budget.py --strict` → OK.
- [ ] Eval gate judged per `evals/README.md` for the `SKILL.md`/`reference.md` edits, with a
      recorded run or a one-line skip rationale. **Still open, and it is why this task is in
      review rather than done**: `8a1321a` recorded a skip rationale that understates its own
      diff (it claims 7 changed instruction lines across 2 files; `git show 8a1321a --numstat`
      gives 49 changed lines across 4 instruction files, 35 of them in `job-search` alone,
      over `evals/README.md`'s ~20-line MUST-run trigger). Either
      re-record the rationale against the real diff or run the `job-search` canaries.
