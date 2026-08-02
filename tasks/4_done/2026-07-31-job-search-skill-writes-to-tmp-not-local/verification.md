# Verification — 2026-07-31-job-search-skill-writes-to-tmp-not-local

**Corrected 2026-07-31 on the stack tip `40871e6`.** As first written this file carried
three false figures — an undercount of its own edits, a `verify_links` count that was
never produced by any tree, and a stated direction of travel that was backwards. Each is
corrected in place below with the command that produced the replacement. The original
numbers were measured on the isolated `main`-based worktree the change was authored in
and never re-run after the branch was stacked.

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

That grep prints **eight** lines, not seven. **Seven** of the eight are instructions
telling an agent where to write scratch, and were changed. The **eighth**
(`test_store_integration.py:194`) is a mocked config path inside a unit test, not an
instruction, and was deliberately left.

Tree-wide the change makes **eight** path substitutions plus one prose sentence — the
grep above only sees `skills/job-search/`, so it misses the resume-writer line:

```
$ git show f307a40 --numstat --format=''
2	2	docs/handbook/file-organization.md        # the sentence, not a path
6	6	skills/job-search/SKILL.md
1	1	skills/job-search/reference.md
1	1	skills/resume-writer/LESSONS.md
```

6 + 1 + 1 = 8 paths. "Six of the seven" undercounted both halves.

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

At this change's own commit `f307a40`, and at its parent `47a15d4` (`main`):

```
$ git checkout f307a40^ && .venv/bin/python automation/gardener/verify_links.py
  references: 0 broken of 1697 verified · 28 advisory · 82 permitted · 1115 refs NOT verified in this tree (classes above)
  OK: 1697 references, the skill symlinks and the vendored copies verified.

$ git checkout f307a40 && .venv/bin/python automation/gardener/verify_links.py
  references: 0 broken of 1698 verified · 28 advisory · 82 permitted · 1115 refs NOT verified in this tree (classes above)
  OK: 1698 references, the skill symlinks and the vendored copies verified.
```

**The count moves 1697 → 1698 — UP one, not down.** The `verification.md` this change
adds names more paths than the removed handbook clause did, so the tree gains a
countable reference. The figure `1696` is reproducible only by deleting this file, and
no run ever printed it. Both the number and the direction were wrong.

Re-run on the stack tip `40871e6`, where this change is merged:

```
$ .venv/bin/python automation/gardener/verify_links.py
  references: 0 broken of 2552 verified · 42 advisory · 107 permitted · 1201 refs NOT verified in this tree (classes above)
  OK: 2552 references, the skill symlinks and the vendored copies verified.     exit 0

$ .venv/bin/python automation/metrics/instruction_budget.py --strict
skills/job-search/SKILL.md                       351  27395   6848    600    ok
skills/resume-writer/LESSONS.md                  106   8314   2078    160    ok
OK: all instruction files within budget.                                        exit 0
```

(The budget block as first written quoted 317 and 102 lines — correct at `f307a40`,
stale at the tip, and abridged to two of the report's six columns.)

## Eval gate

Skipped, recorded in the PR body. `evals/README.md` lists "correcting paths,
flags, or labels to match code reality" as an explicit MAY-skip, and the edit is
under both MUST-run size thresholds on each affected skill. The real diff sizes,
counted the way `evals/README.md` counts them (added + deleted lines):

```
$ git show f307a40 --numstat --format='' | grep -E 'skills/[a-z-]+/(SKILL|LESSONS|reference)\.md'
6	6	skills/job-search/SKILL.md
1	1	skills/job-search/reference.md
1	1	skills/resume-writer/LESSONS.md
```

job-search is **2 instruction files / 14 changed lines**; resume-writer is 1 file / 2
lines. The original text said "7 changed lines" for job-search, which counts edited
locations rather than changed lines and understates it by half. The conclusion is
unaffected — 14 is still well under the ~20-line MUST-run trigger, and 2 files is under
the 3-file trigger — but the rationale now rests on the number the rule actually uses.
No gate, protocol, or step semantics changed.

Noted disagreement: this task file asserted canaries must run, framing the edit
as behavioural because it changes where agents write. That conflicts with
`evals/README.md`'s stated criteria for an edit this size. The disagreement is
recorded rather than resolved silently.
