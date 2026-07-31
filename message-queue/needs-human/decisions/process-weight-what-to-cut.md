# Has the process machinery outgrown the work it tracks — and which parts do we cut?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [the ADR's own revisit trigger](../../../memory/decisions/workspace-layout-public-root-plus-review-gate.md) — *"Revisit if the review-gate row rate proves unworkable in practice"* — plus [the review ledger](../../../automation/publish/review_ledger.yaml), which is the artifact that rate produced
- **Blocking**: nothing. Seven sub-decisions, each with its own default path. Answer them independently; they are not a package.
- **Default path**: **status quo on every rule.** Nothing is deleted, no gate is weakened or disarmed, and no new gate is added while this is open. The two exceptions need no permission because an existing decision already covers them: D1's batching (already permitted by `docs/designs/workspace-restructure/review-gate.md`) and D4's "fix it in the PR" preference (already the observed best practice).

## Background

A backlog triage concluded that this repo's process machinery has outgrown the work it tracks, and
proposed six cuts. A second pass re-measured every figure. **Read the two paragraphs below before
anything else — they are what changed the conclusion.**

**The headline statistic is a review-ledger statistic in disguise.** "41 of the last 100 commits
are pure bookkeeping" is confirmed (measured 43 of 80 non-merge commits) — but **32 of those 43
touch the review ledger and nothing else.** Tasks, memory and the message queue together account
for 3. And the "last 100 commits" window spans **two days** — exactly the two days in which the
review gate was being bedded in. Over the seven days before it, pure-process commits ran at 21 of
100. So this is one rule's cost, two days old, not a chronic condition.

**The cut line is not "process vs work". It is who reads the artifact.** Machinery that produces
something a *human* must answer is used and demonstrably effective: the decisions queue (9 items,
one of which measurably overruled an agent default), ADRs (cited from design files, task files and
commit messages), and the review ledger — which caught a leak in an **already-merged PR** that had
passed the leak guard and every other check, plus three real code defects and a near-miss that
would have written an application slug into a tracked public file. Machinery that produces
something for a *future agent* to read has essentially no evidence of ever being read: 29
handovers with **zero cross-session citations**, `message-queue/needs-agent/` with **zero items
ever in 346 commits**, `memory/lessons/` empty, `memory/facts/` at one entry.

### What was re-verified for this filing, on 2026-07-31

| Claim | Verdict |
|---|---|
| Review ledger has never used the schema's `finding: none` shorthand | **Holds.** 74 rows now, zero of them `none` — every clean row is a written paragraph |
| 29 session handovers vs 106 merges | **Holds exactly.** A handover per PR would produce ~3.6x *more* files, not fewer |
| `needs-agent/requests/` and `needs-agent/retries/` have never received an item | **Holds.** Zero additions to either, ever |
| `tasks/2_blocked/` has never held a task | **Holds.** The only path ever to exist under it is `.gitkeep` |
| `memory/lessons/` empty, `memory/facts/` has one entry | **Holds** |
| 7 open `memory/known-issues/`, 2 resolved-but-still-indexed | **Was true; the second half is now fixed.** The two resolved entries were deleted and the index regenerated in the same PR that filed this. 7 remain open, 4 of them product defects with no task |
| ~30% of task files carry a false load-bearing claim | **Holds, and the two worst are now fixed.** The inverted phase-7b premise and phase-8's dead 595-line blocker were both corrected in the PR that filed this |
| `check_roadmap_fresh` never reads the date, so it "has never caught anything and structurally cannot" | **STALE — this was fixed on the same PR stack.** The check now parses `Last-updated` and compares it to today. Any argument in D6 resting on "the reconciler's checks cannot fire" must be re-read with that in mind |

**The strongest single number, which the triage did not cite:** across all 346 commits, the four
process trees (`tasks/`, `memory/`, `history/`, `message-queue/`) are touched 126 times against
**50 for `skills/`** — the toolkit that actually does the job hunt. The review ledger alone, at 61
commits, exceeds `skills/`.

## Options

There is no single choice here. Each sub-decision below carries its own options, recommendation
and default path, and each has its own **Your answer** line. In summary:

| # | Question | Recommendation |
|---|---|---|
| D1 | Review-ledger row per PR instead of per commit? | **Batch within a branch, keep the scope, add a size cap** |
| D2 | Handover per PR instead of per session? | **Neither — execute the ADR you already decided: untrack `history/`** |
| D3 | Cap the backlog at 10 items? | **No. Attack staleness, not count** |
| D4 | Stop auto-filing review findings as tasks? | **Replace the default with a four-way routing rule** |
| D5 | Delete `tasks/2_blocked/`? | **Not worth a change of its own; fold it into something else or drop it** |
| D6 | Two new reconciler checks? | **One of them, reshaped. The other belongs in the gardener** |
| D7 | Three zones with no evidence of use, one with no drain | **Keep two, time-box two, give `known-issues/` a drain** |

---

## D1 — Review-ledger row per PR instead of per commit?

**What it costs.** 74 rows. Two-thirds of them cost a **dedicated commit**, even though the gate's
own design doc prescribes staging the row alongside the next change. **No row has ever used the
`finding: none` shorthand** — every clean row is a written paragraph, which is where much of the
per-row cost lives.

**What it has bought.** The single highest-yield rule in the repo. Three of its most valuable
catches — a leak in an already-merged PR, two further application-history sites, and a
`--file-retries` leak vector — were **invisible to both mechanical detectors**. All three rows
independently state the same reason: *company names are not identity tokens*, so the leak guard
cannot see them. They were caught because an agent was compelled to read the diff.

### Option A — status quo (row per commit range)
Finest attribution, tightest reading unit. Costs ~2 rows and ~1.3 dedicated commits per PR.

### Option B — one row per PR over `base..tip`, with a size cap *(recommended)*
Written at the branch tip before push. **Split into a second row whenever the range exceeds ~40
watched files or the PR carries more than one logical change.** Plus two changes that cost
nothing: enforce the already-documented ride-along so a mid-branch row is never committed alone,
and permit a one-sentence clean finding.

Measured saving: ~30 fewer rows and ~10 fewer dedicated commits over the observed window — a
25–33% cut to ledger overhead, **not** the 32%-of-all-commits the framing implies.

**What breaks, and who pays.** Attribution coarsens from a commit range to a branch, which weakens
exactly the gate's accountability story ("a row that says `none` on a diff that later turns out to
leak is evidence about the reviewer"). **A future you, reconstructing when a leak entered, pays.**
And one row over a 100-file diff is where rubber-stamping starts — the design doc already rejected
per-file attestation on that reasoning, and per-PR moves in the same direction. The 40-file cap is
what keeps this from being the mistake the design already foresaw.

### Option C — narrow the watched set to the exporter allowlist
Rejected on evidence. That allowlist excludes `memory/`, `tasks/`, `message-queue/` and
`history/` — and **the merged-PR leak, the two application-history sites and the `--file-retries`
near-miss all landed in that excluded set.**

**Default path while unanswered:** keep per-commit rows, but start batching within a branch
immediately (already permitted) and stop committing rows alone mid-branch.

**Your answer:** ______

---

## D2 — Handover per PR instead of per session?

**The proposal is inverted as stated.** 29 sessions vs 106 merges: a handover per PR produces
~3.6x *more* handovers, not fewer.

**And the decision is already made, by you.**
`memory/decisions/workspace-layout-public-root-plus-review-gate.md` (decided 2026-07-28, by owner):
*"Session handovers move to `private/local/history/` (never committed), so the reconciler's
`handover-present` check becomes local-only and vacuous in CI."* **It has not been executed** — 29
handovers are still tracked.

### Option A — handover per PR
Rejected: 3.6x more artifacts, and it contradicts a decided ADR.

### Option B — execute the existing ADR: untrack `history/` *(recommended)*
Removes 11 pure-write commits, every handover-triggered ledger row, and one class of review-gate
exposure (handovers are prose about real work written into the public tree; one ledger finding is
a handover under-reporting its own filed defects).

**What is lost, and who pays.** A handover is currently the only tracked record of **what was
deliberately not done, and why** — "drift I did *not* sweep", "the overlay PR must merge with or
before #115", "eight broken anchors in a file I declined to touch". Git records what was done;
nothing else records a conscious omission. Untracked, a **different machine or a fresh clone**
cannot see that residue. Given zero cross-session citations in 29 handovers, the population that
pays is currently empty — but it is you, on a new laptop, if it ever isn't.

### Option C — keep tracking, shrink the handover to its residue
Change `templates/handover.md` so a handover records only what is not recoverable elsewhere.
Cheaper per file, keeps the tracked record, but does not remove the pure-write commits.

**Recommendation: B, with C's template shrink applied first**, so the local-only handovers that
remain are the useful 20%. `AGENTS.md` already assumes this end state: *"the handover may be
local-only and a later session must be able to continue from tracked files alone."*

**Default path while unanswered:** keep writing per-session handovers to `history/` exactly as
now. Do **not** switch to per-PR under any reading.

**Your answer:** ______

---

## D3 — Cap the backlog at 10 items, demoting the rest to one-line rows?

**The measured problem is not count — it is decay.** 26 items is not intrinsically too many. What
makes them expensive is that the repo moved 346 commits in 12 days, so a task's Context section
describes a tree that no longer exists. Of five tasks re-verified claim by claim, **2 carried a
materially false central claim and 5 carried at least one stale coordinate.** The failure mode is
precise: **the prose claims survived; the coordinates did not.** Nothing in the task format
obliges a filer to record the command that would re-establish the claim, so the only way to tell a
live task from a dead one is to redo the investigation.

A hard cap of 10 attacks the symptom, is arbitrary, and creates a **new recurring ritual** —
deciding weekly which items to demote, i.e. more process. It would also have demoted nothing about
the item that was simply *finished*.

### Option A — hard cap at 10; the rest become one-line rows
Forces prioritisation, but 10 has no evidence behind it and the demotion decision becomes a chore.

### Option B — demote by age and staleness, with a soft target *(recommended)*
An item is demoted to a one-line row in a single `tasks/0_backlog/icebox.md` when **either** it is
more than **21 days** old **or** its central claim has not been re-verified since filing. The row
carries id, one sentence, and the commit sha at which the claim was last known true. Demotion
happens in one batched sweep, never per item. ~10 live items is a *signal to sweep*, not a gate.
Two additions: every task carries a `Verify-with:` command (see D4), and a sweep starts by running
each task's own definition-of-done command — the cheapest possible pruning pass, and nobody runs it.

Worth fixing while in the format: 5 of 26 items record a dependency and **none uses a structured
field**; two are written *inside the `Priority:` line*, where no reader or tool looks. Adding a
`Depends-on` key is smaller than either cap and fixes a real invisibility.

Design detail: the icebox must be **one file**, not folders — `check_task_structure()` requires
`Priority`/`Area`/`Source` in every `tasks/*/<id>/task.md`, so a flat markdown file is what stops
the reconciler firing on the very cleanup meant to reduce noise.

**What breaks, and who pays.** A one-line row loses the Context section, so whoever revives the
item re-derives it. Against that: a stale Context costs the same re-derivation *plus* the risk of
acting on a false premise.

### Option C — do nothing
Defensible if you intend to read the backlog. Zero of the 26 came from you.

**Default path while unanswered:** file no new backlog items that D4's rule would reject; leave
the existing items in place; delete nothing.

**Your answer:** ______

---

## D4 — Stop auto-filing adversarial-review findings as task folders?

**Judge this on what actually happened.** The highest-value adversarial findings in this repo's
history were **never filed as tasks** — they were fixed inline in the same commit and recorded in
the ledger row: three real code defects in one commit (an empty covered-set on every run since the
file was written, a crash on an undefined name, a `--forget-log` silently revertible by the next
`--sync-log`), and a leak vector designed out in the same commit that introduced it.

The findings that *became* task folders are the residue — the ones nobody could act on
immediately. So the answer is not "stop filing". It is that **the task folder is the wrong default
container**, and the default should be "fix it here".

### Option A — status quo (file every finding as a task)
Produced the measured backlog: restructure phases 5–7 filed exactly 10 of 26 items, in a list that
is 19/26 harness work and that nobody outside the agent loop reads.

### Option B — a four-way routing rule with a per-review cap *(recommended)*

Applied in order; first match wins.

1. **Can I fix it inside the PR under review without changing that PR's stated goal?** → **Fix it
   now.** Name it in the PR body and in the ledger row's `finding:`.
2. **Is it a defect in tracked code, config or instructions I cannot fix here — because it needs a
   decision I may not make, or more than one commit?** → **File one task. Cap: at most one task
   per review.** More than one task-worthy finding is evidence the PR is not done.
3. **Is it a real defect nobody should fix now (upstream, environmental, low severity, known
   flake)?** → **`memory/known-issues/`**, with a mandatory `Review-by:` date.
4. **Otherwise → nowhere.** If it concerns the PR, say it in the PR body. Otherwise drop it.
   *"This could be nicer"* is not a finding.

**Plus the part that attacks the false-claim rate at its source:** a task filed under (2) carries
a **`Verify-with:` line — the exact command whose output made the claim true** — and states its
claim in terms that command can re-check. **No line numbers.** Three of five re-verified tasks
cited line references that had moved by 11 to 283 lines while the prose stayed correct. Coordinates
rot; `grep -n 'def check'` does not.

**What breaks, and who pays.** Rule (1) puts unrelated fixes into a PR, which makes the diff harder
to review and muddies `git bisect` — **the reviewer pays**, which is why (1) is gated on "without
changing the PR's stated goal". Rule (3) routes more into `memory/known-issues/`, a zone with
**no drain** (D7) — adopting (3) without D7 makes a measured problem worse.

### Option C — ban task-filing from reviews entirely
Cleanest and wrong: findings that genuinely need a decision would be lost, and this repo's history
shows those exist.

**Default path while unanswered:** apply rules (1) and (4) now — they need no permission, and (1)
is already the observed best practice. Continue filing under (2) but with the re-verification
command recorded, and hold to one task per review.

**Your answer:** ______

---

## D5 — Delete `tasks/2_blocked/`?

**Never used**: the only path ever to exist under it is `.gitkeep`. Two things that were not
weighed:

**It is empty because the contract tells agents not to block.** `AGENTS.md` sets mode `async` —
*"decide everything reversible … stop only on `Blocking: yes`."* An empty `2_blocked/` is that
design working, not machinery rotting.

**But blocked tasks do exist — they are parked somewhere unreadable.** Five backlog items record a
dependency in free prose, two of them *inside the `Priority:` line*. None is in `2_blocked/`. The
folder is unused not because blocking never happens but because there is no `Depends-on` field to
make it legible. **Fix the field (D3) and the folder question answers itself.**

**Executing this cut costs more than it saves**: a doc edit, a code edit, plausibly a test, a
ledger row and a PR — to remove one table row and one tuple entry. A standalone PR to delete an
empty directory is itself an instance of the problem this document is about.

- **Option A — delete it now, as its own change.** Net negative.
- **Option B — keep it, and fold the removal into the next change that already touches
  `tasks/README.md` or `STATUS_DIRS`** *(recommended)*. Costs nothing either way.
- **Option C — keep it permanently**, as the parking spot the `Blocking: yes` path requires.

**Default path while unanswered:** leave it. Do not open a PR for it.

**Your answer:** ______

---

## D6 — Add two reconciler checks: unticked definition-of-done, and a stale-item age flag?

**Split them.** The reconciler is a **blocking** gate — pre-commit and CI, exit 1 on any finding.
A hygiene finding added to it blocks **every unrelated commit in the repo** until someone grooms a
backlog. That is the wrong tool for "this item is old". The repo already draws this line
elsewhere: the review gate's company detector *prints hints and never fails the gate by itself*.
`reconcile.py` has no advisory tier.

### D6a — the definition-of-done check: **keep it, reshaped**

An unticked box in `3_in-review` is a **correctness** claim, not a judgement call: the task file
says the work is not done and the folder says it is. Two measured facts it must survive:

1. **Four in-review tasks fail it today** — one with 10 of 10 boxes unticked. Landing the check
   alone turns pre-commit red for every unrelated commit until those four are groomed. (This PR
   groomed the *record* by writing down what each is missing, but did not tick anything.)
2. **Half the in-review tasks have no checkboxes at all.** `templates/task/task.md` says
   "Definition of done: `<Checkable bullet(s)>`" — it does not mandate checkbox syntax. As
   proposed, the check is evaded by not using checkboxes, which is already the majority style.

Shape: extend the existing `check_task_structure()` rather than adding a ninth check — it already
walks `tasks/<status>/<id>/` with the right `is_dir()` guard, and `CHECK_ROOTS["task-structure"]`
already exists so `--require-roots` needs no change. Inside the existing
`3_in-review`/`4_done` branch, after the `verification.md` finding: require a checkbox-shaped
Definition of done, then report any `- [ ]` count. **Three things must land in the same commit**,
per the module's own rule that a format change edits `templates/` and the matching check together:
the template edit mandating checkbox syntax, the grooming of the currently-failing tasks, and a
test — otherwise this joins the checks with no dedicated test and no evidence of ever firing.

### D6b — the age flag: **move it to the gardener, not the reconciler**

"This item is 40 days old" is a prompt for judgement, not a violated invariant. Blocking a commit
on it punishes whoever commits next for a backlog nobody groomed.

Shape: a dry-run routine registered in `gardener.py`'s `ROUTINES`, reading the folder *names* under
`tasks/0_backlog/` and `tasks/3_in-review/` (the id already encodes the filed date, pinned by
`TASK_ID_RE`, so no git call is needed and it stays correct after an export). One line per item
past threshold, **exit 0 always**. It fills a real hole: the gardener's 8 routines touch
discoveries, logs, lessons, the tailoring card, skill drift, the store, links and metrics — and
**none touches `tasks/` or `memory/known-issues/`**.

If you would rather keep the age flag in the reconciler, the honest way is an `ADVISORY` set
mirroring the existing `PRIVATE_CHECKS` pattern, printed under a `hints:` heading and excluded
from the exit code — about 15 lines. Do not add a non-blocking concern to a blocking tool without
that tier.

**Default path while unanswered:** neither is added. No check is weakened or removed meanwhile.

**Your answer:** ______

---

## D7 — Three zones with no evidence of use, and one with no drain

Not in the original six, but the measurement turned these up and they are cheaper wins than
anything above.

**(a) The `needs-agent/` half of the message queue has never been used.** Zero items ever, in 346
commits — and `file_retries()` carries 13 tests for a path that has never run on a real finding.
`requests/` is your inbound drop box; its emptiness is the root cause of "zero tasks filed by the
owner". Either it is the wrong channel for you, or nobody told you it exists.

**(b) `memory/lessons/` is empty and `memory/facts/` has one entry**, twelve days after both were
created. The gardener has a `lessons-report` routine reporting on an empty zone.

**(c) `memory/known-issues/` has no drain.** Seven open entries, one referenced by any task, eight
of nine bulk-seeded on a single day. Two resolved-but-still-indexed entries were deleted in the PR
that filed this — one of them 49 merges past its own *"delete after one PR cycle"* instruction —
but nothing prevents the next two. **D4 rule (3) routes more findings here, so adopting D4 without
a drain makes this worse.**

- **Option A — leave all three.** They cost little in isolation; the harm is credibility.
  Instructions that describe unused machinery train agents to treat the contract as aspirational.
- **Option B *(recommended)*** —
  - **`needs-agent/retries/`**: keep. It is the reconciler's only escape valve from "a finding
    blocks every commit", and D6 makes that valve matter more.
  - **`needs-agent/requests/`**: keep, and **tell me in one line how you would prefer to hand
    agents work** — chat, a doc's `## Human questions` section, or this queue. If it is not this
    queue, delete the folder and remove it from the boot ritual, because a boot step that scans an
    always-empty folder is a per-session tax on every session forever.
  - **`memory/lessons/` and `memory/facts/`**: give them 30 more days. If still empty, delete both
    zones and the `lessons-report` routine.
  - **`memory/known-issues/`**: add a `Review-by:` key to `templates/memory/known-issue.md`,
    extend the `memory-schema` check to require it (that check has no evidence of ever firing —
    this would give it a job), and add a known-issue age reporter to D6b's routine.

**Default path while unanswered:** nothing is deleted. The zones stay.

**Your answer:** ______

---

## Recommendation

Take **D7(c) and D4 together first** — they are the cheapest and they depend on each other. Then
**D1's batching**, which is the only one with a measured cost worth the change and whose governing
ADR names this exact revisit trigger. **D2 is not a new decision**, it is one you already made and
that has not been executed. **D3's count cap and D5's deletion are the two proposals to decline**:
the cap aims at the wrong variable (staleness, not count) and would have demoted nothing about the
item that was already finished, and deleting an empty directory costs more process than it saves.

One thing the triage got right and understated: **the machinery that writes for a future agent has
no evidence of ever being read; the machinery that writes for a human is used and effective.**
That is the cut line, and it is sharper than "process has outgrown the work".

**Your answer:** ______
