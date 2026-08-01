# Verification — 2026-07-31-job-search-skill-writes-to-tmp-not-local

## Every `/tmp` scratch path in the job-search skill, before the change

```
$ grep -rn '/tmp' skills/job-search/
SKILL.md:123      --json-out /tmp/m.json
SKILL.md:128      open('/tmp/m.json')
SKILL.md:137      --json-out /tmp/matches.json
SKILL.md:201      --json /tmp/matches.json --select "rank 1"
SKILL.md:204      --json /tmp/matches.json --select "Acme Corp"
SKILL.md:207      --json /tmp/matches.json --all --report local/handoff-report.json
reference.md:423  --json-out /tmp/matches.json
scripts/tests/test_store_integration.py:194  Path("/tmp/real-config.yaml")
```

Six of the seven are instructions telling an agent where to write scratch, and
were changed. The seventh (`test_store_integration.py:194`) is a mocked config
path inside a unit test, not an instruction, and was deliberately left.

## The contradiction this task's fix exposed

`AGENTS.md:272` states scratch lives "ONLY under the top-level gitignored
`local/`". `docs/handbook/file-organization.md:69` granted the opposite
permission:

```
$ sed -n '69p' docs/handbook/file-organization.md      # before
  root. Machine scratch (`--json-out`) may target the OS `/tmp`, but keep anything worth revisiting
```

Corrected in the same change, so the rule reads the same in all three places.
`skills/resume-writer/LESSONS.md:42` carried the same violation and was fixed
with it.

## Link and budget gates

```
$ .venv/bin/python automation/gardener/verify_links.py
  references: 0 broken of 1696 verified · 28 advisory · 82 permitted
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync
  OK: 1696 references, the skill symlinks and the vendored copies verified.

$ .venv/bin/python automation/metrics/instruction_budget.py --strict
skills/job-search/SKILL.md       317 lines / 600  ok
skills/resume-writer/LESSONS.md  102 lines / 160  ok
OK: all instruction files within budget.
```

The verified-reference count moves 1697 → 1696 because the removed handbook
clause deleted one countable reference; no reference broke.

## Eval gate

Skipped, recorded in the PR body. `evals/README.md` lists "correcting paths,
flags, or labels to match code reality" as an explicit MAY-skip, and the edit is
under both MUST-run size thresholds on each affected skill: job-search is 2
instruction files / 7 changed lines, resume-writer is 1 file / 1 line. No gate,
protocol, or step semantics changed.

Noted disagreement: this task file asserted canaries must run, framing the edit
as behavioural because it changes where agents write. That conflicts with
`evals/README.md`'s stated criteria for an edit this size. The disagreement is
recorded rather than resolved silently.
