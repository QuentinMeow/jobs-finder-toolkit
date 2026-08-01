# Verification — 2026-07-31-job-search-docs-still-route-the-blacklist-to-the-public-registry

Measured 2026-07-31 on `wip/28-verification-regressions` (branched from the stack tip
`941f75f`), not on the branch that made the edits. The work itself landed in `8a1321a`;
this file exists because the task shipped asserting the opposite and nobody re-ran the
checks after the fixing commit.

## The five sites now route to the overlay

```
$ grep -n 'blacklist' skills/job-search/SKILL.md skills/job-search/reference.md
skills/job-search/reference.md:477:- **Blacklist (in the MERGED registry)** — every entry carrying a `blacklist:` reason
skills/job-search/reference.md:479:  Always applied. The rows live in the git-ignored overlay at `config.blacklist_path()`
skills/job-search/reference.md:480:  (`private/market/blacklist.yaml`), which `registry.load_registry()` merges with
skills/job-search/reference.md:569:**To blacklist a company** (never consider it), add the row to the git-ignored overlay at
skills/job-search/reference.md:570:`config.blacklist_path()` (`private/market/blacklist.yaml`) — **never to `companies.yaml`,
skills/job-search/reference.md:571:which is published.** A blacklist row is a personal skip rule naming a real employer;
skills/job-search/reference.md:577:without `ats`. A `blacklist:` key committed to `companies.yaml` now fails the reconciler
skills/job-search/reference.md:578:(`public-registry-blacklist`) in pre-commit and CI.
skills/job-search/SKILL.md:308:| Managing `companies.yaml` (add a board token, validate) and where blacklist rows go | `reference.md` § Managing target companies |
skills/job-search/SKILL.md:320:| `companies.yaml` | Canonical company registry — identity, ATS poll config, tags (incl. the `ai-lab`/`ai-infra`/`ai-native` family). Blacklist rows live in the overlay at `config.blacklist_path()`, never here |
```

Whole lines are dropped from the middle of that output, never edited: the run also prints
`reference.md:375,453,466,473,500,503` and `SKILL.md:44,91,93,305,330`, which describe the
skip logic and the loader rather than where a row is written. No remaining sentence in
either file places a blacklist row in `companies.yaml`.

## The commit that did it

```
$ git show 8a1321a --numstat --format= | grep -E "job-search/(SKILL|reference)"
3	3	skills/job-search/SKILL.md
20	9	skills/job-search/reference.md
```

## Gates

Re-run 2026-07-31 on the stack tip `40871e6`. The reference total was 2537 when this file
was first written on `wip/28-verification-regressions`; that branch has since moved, so
the figure is refreshed rather than left to rot.

```
$ .venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (9 checks clean)                                            exit 0

$ .venv/bin/python automation/gardener/verify_links.py     # last line of the report
  OK: 2552 references, the skill symlinks and the vendored copies verified.  exit 0

$ .venv/bin/python automation/metrics/instruction_budget.py --strict
OK: all instruction files within budget.                                   exit 0
```

## What is NOT verified

The eval-gate line of the definition of done. `8a1321a` recorded a skip rationale stating
"7 changed instruction lines across 2 files"; the real diff is larger:

```
$ git show 8a1321a --numstat --format= | grep -E 'skills/[a-z-]+/(SKILL|LESSONS|reference)\.md'
7	3	skills/application-tracker/LESSONS.md
3	3	skills/job-search/SKILL.md
20	9	skills/job-search/reference.md
3	1	skills/resume-writer/reference.md
$ …| awk '{a+=$1; d+=$2} END {print a+d}'
49
```

49 changed instruction lines across 4 files, 35 of them in `job-search`, against
`evals/README.md`'s ~20-line MUST-run trigger — and the `reference.md` change rewrites a
procedure, which is a trigger on its own. No canary run has been recorded. That box stays
unticked, and is what the reviewer of this task decides.
