# A company's first search must find every open role, and the docs must say so

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: owner decision 2026-08-02, recorded as `memory/decisions/first-search-finds-every-open-role.md` (folded from the queue item first-search-recency-window, deleted in the folding commit — git history is the archive)
- **Claimed-by**:

## Goal

`search_jobs.py` finds every open role on a company's first-ever search — no recency gate, older
roles matched by default — and narrows to the profile's `max_age_days` on every later run, with
the widened window printed in the run header. The job-search skill's own documents state that
rule, so no agent has to rediscover it.

## Context

The decision and the owner's reasoning are in `memory/decisions/first-search-finds-every-open-role.md`;
read it first. The short version: for a company nobody has searched yet the whole board is new
information, so the age gate drops still-open roles for no reason. Two such postings were
confirmed lost, with no filtered row and no count.

What is already done, and what is not:

- **Done** — `docs/handbook/repo-map.md` now states the rule on the
  `config.company_search_log_path()` row: no row for a company means it has never been searched,
  and that run finds every open role.
- **Not done, and the reason** — nothing under `skills/job-search/` was touched. The folding
  session held only the process tree (`message-queue/`, `memory/`, `docs/handbook/`,
  `tasks/0_backlog/`) while other agents held the skill. So both the code change and the skill's
  own documents are still on the old behaviour.

Files that carry the old contract and need to agree with the decision:

- `skills/job-search/scripts/search_jobs.py` — the date gate that drops anything older than
  `max_age_days`.
- `skills/job-search/scripts/company_roles.py` — the `--match-only` path, which already applies no
  recency filter; after this change the two scripts stop disagreeing on a first search and keep
  disagreeing (correctly) afterwards.
- `skills/job-search/SKILL.md` and `skills/job-search/reference.md` — the posting-age sections.
- `skills/job-search/profiles/README.md` — the `max_age_days` description.

One trap worth naming: `tasks/0_backlog/2026-08-01-job-search-docs-route-the-location-policy-to-the-wrong-file`
records that `SKILL.md` and the shipped profile template already disagree about whether posting
age filtering is on by default. Fix that disagreement in the same pass or this rule lands on top
of a contradiction.

## Definition of done

- [ ] A search against a company with no row in `config.company_search_log_path()` applies no
      posting-age gate, and a search against a company that has a row applies the profile's
      `max_age_days` — covered by a test that exercises both directions.
- [ ] The run header names the widened window on a first search, so the output explains why it
      differs from a repeat run.
- [ ] `skills/job-search/SKILL.md`, `reference.md` and `profiles/README.md` state the first-search
      rule and no longer imply the profile's window applies to every run.
- [ ] `.venv/bin/python automation/reconcile/reconcile.py --check` and the job-search test suite
      both exit 0.
