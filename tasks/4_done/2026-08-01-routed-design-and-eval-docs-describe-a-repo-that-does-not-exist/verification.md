# Verification — 2026-08-01-routed-design-and-eval-docs-describe-a-repo-that-does-not-exist

## Item 1 — the "not implemented" design is implemented, and there are eleven skills

```
$ grep -n 'runs in pre-commit\|review_gate.py --staged' automation/hooks/pre-commit
106:"$PY" automation/publish/review_gate.py --staged

$ ls -d skills/*/ | wc -l
      11
$ ls skills
application-tracker  ask-me-anything  behavioral-interview-prep  company-research
email-assistant  gardener  github-workflow  interview-calendar  job-search
resume-writer  search-recall-audit
```

`github-workflow/` is the skill the "10 public skills" tree omitted. The execution plan
(`execution-plan.md`) already said "phases 0-6 are merged into `main`", and
`docs/roadmap/current-state.md` says "**Phase 7 is done**".

## Item 2 — the validator task exists in no status directory

```
$ find tasks -maxdepth 2 -name '*tree-instructions*'
(no output)
```

`docs/roadmap/desired-state.md` says "**The tree-instructions validator is dropped**". The one
re-filed item is real and closed:

```
$ ls -d tasks/4_done/2026-07-31-leak-guard-silently-skips-an-unreadable-file
tasks/4_done/2026-07-31-leak-guard-silently-skips-an-unreadable-file
```

## Item 3 — "no ancestor row" is not one outcome

From `automation/publish/review_gate.py`'s `main()` and its EXIT CODES docstring, the
branches when `chain.last_ancestor()` is `None`:

- `is_shallow(repo)` → `GateError(_shallow_message())` → exit 2
- `not chain.any_resolved()` and `allow_not_applicable` → `NotApplicable` → **exit 0**
- `not chain.any_resolved()` and `is_published_export(repo)` → `NotApplicable` → **exit 0**
- `not chain.any_resolved()` otherwise → `GateError(_no_resolvable_row_message(...))` → exit 2
  ("the ledger describes a history this checkout does not have")
- some rows resolved → `GateError(_stale_ack_message(...))` → exit 2 ("the ledger is out of
  sync with this branch" — the one the spec named)

plus, earlier: not a git repo, or `HEAD` unresolvable → `NotApplicable` → exit 0. The two
exit-0 paths are `except NotApplicable: … return EXIT_OK`. `is_published_export` is
`not any((repo / root).is_dir() for root in EXPORT_ABSENT_ROOTS)` — i.e. the shape of the
checkout decides.

The flags CI actually uses:

```
$ grep -n 'review_gate.py --verify-all' .github/workflows/ci.yml
200:            python automation/publish/review_gate.py --verify-all --head "$PR_HEAD"
202:            python automation/publish/review_gate.py --verify-all
```

## Item 4 — no transcript miner exists

```
$ grep -rn 'transcript miner\|transcript_miner' --include='*.py' automation/
(no output)

$ grep -n '_summarize_transcript' automation/metrics/hook_collect.py
112:def _summarize_transcript(path_str) -> dict:
212:    row.update(_summarize_transcript(payload.get("transcript_path")))
```

`hook_collect.py`'s docstring describes its Stop mode as producing
`{<token sums>, wall_clock_s, tool_calls, transcript_lines}` — none of "failure count by
tool", "retry classification", or "tokens burned in failed+meaningless-retry turns". Outcome
chosen: strike the requirement, which the task lists as legitimate.

## Item 5 — the collector is opt-in and unwired here

```
$ sed -n '4,8p' automation/metrics/hook_collect.py
Reads a hook JSON payload from stdin and appends ONE JSON line to
``logs/metrics.jsonl``. Metrics are OPT-IN: wire these hooks (SessionStart,
PostToolUse, Stop) from your local ``.claude/settings.local.json`` (see
``docs/handbook/metrics.md`` for the metric set and rationale); they are intentionally
NOT tracked so contributors never run them by default.

$ ls -a .claude
.  ..  skills
$ ls logs
ls: logs: No such file or directory
```

So `report.py --by-sha` prints nothing in a fresh checkout — which several existing records
already say in prose (`evals/results/company-research-…-correctness.md`,
`…job-search-70a620f32968-…`, `…resume-writer-25f465e2e9ad-…`).

## Item 6 — two artifact paths, and a `protocol.md` that does not exist

```
$ grep -rn 'evals/artifacts\|evals/runs/artifacts' evals/
evals/protocols/stage-benchmarks.md:69:  `private/evals/runs/artifacts/<row-id>/` for pairwise quality comparison.
evals/results/TEMPLATE.md:113:**Artifacts:** stage output for A and B saved under `private/evals/artifacts/<row-id>/` …

$ find . -name 'protocol.md' -not -path './private/*'
(no output)
```

(Line numbers pre-edit.) `docs/designs/workspace-restructure/README.md:181` fixes the overlay
layout as `evals/{canaries,fixtures,runs}/`, so the protocol's path is the correct one and the
template — the file an agent copies — was writing outside the sanctioned tree. `protocol.md`
replaced with `docs/designs/token-usage-modes/benchmark-scenario.md`, which exists.

## Item 7 — the size table, re-measured

```
$ wc -c AGENTS.md docs/handbook/README.md skills/job-search/SKILL.md \
        skills/job-search/reference.md skills/job-search/LESSONS.md \
        skills/resume-writer/SKILL.md skills/resume-writer/reference.md \
        skills/resume-writer/LESSONS.md skills/resume-writer/scripts/check.py \
        skills/application-tracker/SKILL.md
   27496 AGENTS.md
    2077 docs/handbook/README.md
   28907 skills/job-search/SKILL.md
   46656 skills/job-search/reference.md
   12204 skills/job-search/LESSONS.md
   32317 skills/resume-writer/SKILL.md
   34942 skills/resume-writer/reference.md
    8314 skills/resume-writer/LESSONS.md
   46754 skills/resume-writer/scripts/check.py
   30851 skills/application-tracker/SKILL.md
```

Measured at `e91f6cb` (this branch's base) on 2026-08-02. **All ten public rows differ from
the table's claim** — the table said 14,282 / 37,645 / 18,689 / 25,219 / 6,921 / 26,950 /
34,539 / 6,937 / 36,824 / 19,724 respectively. The worst is `docs/handbook/README.md`:
37,645 claimed against 2,077 actual, an 18.1x overstatement, in the row that a boot-tax
lever would lean on hardest. Note this differs from the task's own figures (it recorded
`AGENTS.md` at 26,850 and job-search `SKILL.md` at 27,395) because the tree moved again
between filing and this session — which is the reason the table now carries a commit rather
than the word "Live".

The five remaining rows (tailoring card, baseline, profile, story bank, one JD) are overlay
artifacts and cannot be measured from the public tree; they are split into their own table
and labelled as the last recorded 2026-07-20 measurement.

## Gate required by the Definition of done

```
$ .venv/bin/python automation/gardener/verify_links.py --require-roots --no-overlay   # EXIT=0
  references: 0 broken of 2989 verified · 38 advisory · 125 permitted · 1323 refs NOT verified in this tree
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync
  OK: 2989 references, the skill symlinks and the vendored copies verified.
```
