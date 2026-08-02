# Verification — 2026-07-31-answer-bank-renders-company-answers-into-the-question-bank

Retro-closure, 2026-08-02. The code half shipped in `ac34371` ("Route a
company-prefixed answer to the company folder", PR #161) and is an ancestor of
`f360aec`. The one bullet that is NOT discharged is split out and named below —
this closure does not claim it.

```
$ git merge-base --is-ancestor ac34371 HEAD; echo $?
0
```

## DoD 1 — `output_targets_for` routes a company-prefixed slug to `companies_root()/<key>/derived/`

`skills/behavioral-interview-prep/scripts/answer_bank.py`, `_target_for`:

```
    company_dir = _company_dir(root, key)
    if company_dir is None:
        raise UnroutableOutput(...)
    return company_dir / COMPANY_DERIVED_DIRNAME / f"{slug}.md"
```

`_general_*` slugs keep the question-bank target; an unknown key is refused
rather than invented (no folder is ever created).

## DoD 2/3 — duplicate-owner check on the same targets; suite green

```
$ git show --stat ac34371 -- skills/behavioral-interview-prep/scripts/tests/test_answer_bank.py
 .../scripts/tests/test_answer_bank.py | 136 ++++++++++++++++++--

$ .venv/bin/python automation/gates/run_gates.py
  PASS   tests-behavioral-prep  exit 0     4.4s
```

## DoD 4 — the "Known gap" paragraph and the `§ File Location` caveat are deleted

`ac34371`'s `SKILL.md` diff removes both:

```
-**Known gap, do not paper over it:** `answer_bank.py --render` still writes every output beside
-its source's parent, i.e. back into `question-bank/<slug>.md`. ...
-  (`--render` still emits into the question bank — move the file; see § File Location)
```

Re-grepped at HEAD — no "Known gap" about render targets survives:

```
$ grep -n -i "known gap\|move the file" skills/behavioral-interview-prep/SKILL.md
(no match)
```

## DoD 5 — canaries: NOT discharged here; split out as its own task

`evals/results/` holds exactly one `behavioral-interview-prep` record,
`behavioral-interview-prep-70d79c6e812e-2026-07-23.md`, which predates `ac34371`
and does not cover it. That debt is filed and scoped as
`2026-08-01-discharge-161-canary-debt`, whose own Context states: *"Every other
bullet in that task's Definition of done already appears implemented in PR
#161's diff ... Only the canary-run bullet is unchecked and unrecorded."*

This task is closed on that split (`tasks/README.md`: a task too big to plan is
split, child tasks link the parent). The canary obligation is live and tracked;
it is not being waved through.
