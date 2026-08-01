# May a mailbox review move your applications on its own, or must every status change be asked for?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-01
- **Source**: [email-assistant's Pipeline Status Reconciliation section](../../../skills/email-assistant/SKILL.md) · [application-tracker's Update Status section](../../../skills/application-tracker/SKILL.md) · [`AGENTS.md`](../../../AGENTS.md) "Application Folder Convention"
- **Blocking**: nothing. Both readings are live today; which one you get depends on which skill the agent happened to read first.
- **Default path**: **ask first.** Until you answer, an agent doing a mailbox review reports the transitions the evidence supports and runs no `status.py --update`/`--update-job` unless the request named status work ("reconcile my pipeline", "update my applications from email"). This is the conservative side: it never moves a folder you did not ask to have moved, and the only cost is one extra confirmation.

## Background

Three instruction surfaces disagree about whether reading your mail may change your pipeline.

**email-assistant says yes, automatically.** `skills/email-assistant/SKILL.md:128-129`:

> During a requested job-related mailbox review, automatically reconcile clear application outcomes
> with the repository.

Its step 5 (`:154-164`) then makes the transition through the tracker commands, and step 6 runs
`status.py --sync-log`.

**application-tracker says no, not unless asked.** `skills/application-tracker/SKILL.md:404-405`:

> Two commands write the per-job `status` fields and keep the folder in sync. **Only run them when
> the user asks** — they manage their own pipeline moves.

**The contract sides with the tracker.** `AGENTS.md:310-313`: "the **user** moves folders, or use
`status.py --update`/`--update-job` — agents never move them unless asked". The orientation skill
agrees (`skills/ask-me-anything/SKILL.md:181`: "The agent never changes application status").

This is not a wording nicety. `status.py:1272` is a real `shutil.move(str(src), str(dest))`: the
email path physically relocates the folder between the numbered status directories. So "summarise
my recruiter mail this morning" either leaves your tree untouched or silently rewrites five
`meta.yaml` files and moves four folders, depending on which document the agent read first.

The honest case for each side: automatic reconciliation is the whole point of connecting the
mailbox — a rejection email you have already read should not need a second instruction to land — and
the email skill gates it hard already (explicit hiring signals only, one unambiguous
`match-application` result, per-role vs whole-application scope, and a full report of every change).
Against it: a status change is the one thing in this repo you have consistently reserved for
yourself, an ambiguous match moves the wrong folder, and the undo is manual.

## Options

### Option A — Ask first (the default path above)

A mailbox review reports proposed transitions with their evidence; it writes nothing to `meta.yaml`
and moves nothing until you say so. Cost: one confirmation per review, and a stale pipeline if you
skip the confirmation. Fix: delete the "automatically" clause from `email-assistant/SKILL.md:128`
and make step 5 conditional on an explicit ask.

### Option B — Automatic, but only on an explicit reconciliation request

Keep the automation, and scope its trigger: a plain "read/summarise my mail" reports only; "reconcile
my pipeline" / "update my applications from email" transitions. Cost: the two request shapes must be
distinguishable in practice, and they sometimes are not. Fix: `email-assistant/SKILL.md:128` names
the triggering request shapes; `application-tracker/SKILL.md:404` gains "or when an
evidence-backed reconciliation was requested"; `AGENTS.md:313` gains the same carve-out.

### Option C — Automatic on any job-related mailbox review (today's email-assistant text)

The mailbox is the source of truth and the repo follows it. Cost: the tracker and the contract must
both be amended to permit it, and you lose the guarantee that no agent moves a folder you did not
name. Recommended only if you want the pipeline to be maintenance-free.

## Recommendation

**Option B.** It keeps the value that made you connect the mailbox — you should not have to re-tell
an agent about a rejection you both just read — while restoring the invariant the contract and two
other skills state: a status write happens because you asked for one, not as a side effect of
reading. It is also the smallest edit that leaves exactly one rule in the tree, and it degrades
safely: if the trigger is ambiguous, the agent falls back to reporting, which is Option A.

**Your answer:** ______
