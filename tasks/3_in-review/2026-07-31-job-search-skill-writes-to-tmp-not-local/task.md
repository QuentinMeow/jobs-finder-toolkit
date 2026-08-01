# `skills/job-search/SKILL.md` tells agents to write scratch to `/tmp`, against the repo's own rule

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: backlog triage, 2026-07-31 — found while re-measuring phase 8's per-skill path counts; **not** phase-8 work
- **Claimed-by**: agent session 2026-07-31 (PR fix/01-scratch-rule-consistency)

## Goal

Bring the job-search skill's scratch paths in line with `AGENTS.md`'s scratch rule, which the same
file already follows in one place and violates in six.

## Context

`AGENTS.md` → "Scratch & Temporary Files": throwaway work *"lives ONLY under the top-level
gitignored `local/` in purpose-named subfolders … never the repo root or a tracked/product
folder"*. `skills/job-search/SKILL.md` names `/tmp/*.json` in **six** command examples — the
search snapshot, the handoff input, and the select/report flows — while the last of those six
already writes its *report* half to `local/` on the same line. So the file contradicts itself and
the contract. (Corrected 2026-07-31: this paragraph and the closing line of the next section
originally said "five". `git show f307a40^:skills/job-search/SKILL.md | grep -n '/tmp'` returns
six lines — 123, 128, 137, 201, 204, 207.)

Why it is not merely cosmetic: `/tmp` is the OS temp directory. It is outside the repo, so nothing
in this repo's hygiene tooling can see what accumulates there, the gardener cannot expire it, and a
snapshot an agent tells the user about may be gone after a reboot — while `local/` is gitignored,
purpose-named, inspectable and swept.

**Verify-with**:

```bash
grep -n '/tmp/' skills/job-search/SKILL.md
grep -n 'local/' skills/job-search/SKILL.md
```

## The reason this is its own task and not a one-line fix in passing

Editing a `SKILL.md`'s command examples changes where agents actually write, so it is a
**behavioural** edit under the risk-based eval gate in [`evals/README.md`](../../../evals/README.md)
— `job-search` canaries must run and be recorded, not skipped with a rationale. That is the whole
cost of this task; the edit itself is eight paths (6 in `SKILL.md`, 1 in `reference.md`, 1 in
`skills/resume-writer/LESSONS.md`) plus one handbook sentence.

The shipping agent disagreed and skipped the gate, with the rationale recorded in
`verification.md` § Eval gate. The disagreement is unresolved: this box stays unticked.

Check the snapshot-path examples against `skills/job-search/reference.md` and the scripts'
argparse defaults in the same pass, so the skill and its reference do not end up disagreeing.

## Definition of done

Boxes 1 and 2 were re-checked on the stack tip `40871e6`, 2026-07-31, and ticked then — they
were met by `f307a40` and had simply never been marked.

- [x] No `/tmp/` path remains in `skills/job-search/SKILL.md`; each is a purpose-named subfolder
      under `local/` — `grep -rn '/tmp' skills/job-search/` returns one line,
      `scripts/tests/test_store_integration.py:194`, a mocked config path in a unit test
- [x] The skill and `reference.md` agree about where a snapshot lives — both name
      `local/matches.json` (`SKILL.md:137,140,207,210,213`, `reference.md:451`)
- [ ] `job-search` canaries run and are recorded per `evals/README.md` — **still open.** The
      shipping commit skipped the gate on a size rationale; this task filed the edit as
      behavioural. Nothing has run.
