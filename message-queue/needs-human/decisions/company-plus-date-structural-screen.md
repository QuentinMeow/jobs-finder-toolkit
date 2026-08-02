# Should the leak guard screen for a real company name next to a date, and if so, how hard?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [queue hygiene tooling task, gap A](../../../tasks/0_backlog/2026-07-21-todo-queue-hygiene-tooling/task.md)
- **Blocks**: nothing. The gardener half of that task (`queue-hygiene`) shipped without this.
- **Default path**: no company-plus-date screen is added. `check_public.py` keeps screening
  exactly the four shapes it screens today, and the human review gate stays the only thing that
  catches a company name next to a date.
- **Cost if wrong**: ratify
- **Safe to merge because**: no screen is added, so nothing is written or blocked; adding it later
  is a pure addition to `check_public.py`.

## Background

`automation/publish/check_public.py` derives personal tokens from the config and overlay, and adds
four **structural** screens in `_structural_hits`: email address, phone number, home path and
LinkedIn URL. It runs over `message-queue/` with no exclusion — the tree is deliberately in scope —
so a queue item is scanned on every commit.

The one shape it structurally cannot see is **a real company name next to a date**, because
company names are not identity tokens: nothing derives them, so nothing matches them. That gap is
already documented, and it is why the human review gate exists — three of the review ledger's most
valuable catches independently say the same sentence, and its company detector caught a real leak
in phase 7. So this is not a theoretical hole. It is a known hole with a human standing in it.

The reason it has not been closed mechanically: **this repo's public tree names companies and
dates constantly and legitimately.** `skills/job-search/companies.yaml` is a tracked registry of
company identities. Every ADR carries a date. Design docs name ATS vendors (Greenhouse, Lever,
Ashby) in the same paragraph as a dated decision. A naive "capitalised word near a `20\d\d`"
regex fires on a large fraction of the tracked corpus on day one, and a gate that fires on
hundreds of legitimate lines is a gate people learn to bypass.

**This overlaps `process-weight-what-to-cut.md` D6, which is also unanswered.** D6 splits a
different pair of proposals along exactly this line — the correctness half stays in a blocking
gate, the judgement half moves somewhere advisory — and D6b explicitly names the review gate's
company detector as the precedent for "prints hints and never fails the gate by itself". If you
answer D6 with a general preference for that split, this question is largely answered too;
option B below is what that preference produces here.

## Options

### Option A — do nothing

The review gate already covers this shape, with a human reading the diff. Cost: zero. Risk: it is
a human, in a repo where every other invariant is mechanical, and the ledger itself records that
the compulsion to read the diff is what produced the catches — not a checklist item.

### Option B — an advisory hint, never a blocker *(recommended)*

`check_public.py` grows a `hints:` section, printed but excluded from the exit code, listing lines
where a **known company name** (drawn from `skills/job-search/companies.yaml` — the registry
already exists, so no new list is invented) appears within N lines of a `YYYY-MM-DD` or a
`20\d\d`. The reviewer sees a short list next to the diff they are already reading; nothing is
blocked; a false positive costs one glance.

This mirrors the review gate's company detector, which is the only precedent in this repo for a
detector that names companies. It also means the registry, not a hand-maintained allowlist, is the
source of truth for "what is a company name" — one list to keep current instead of two.

### Option C — a blocking regex with a vendor allowlist

The same detection, wired into the exit code, with an allowlist of ATS vendors and any company the
public tree legitimately names. Strongest guarantee. Two costs, both real: the allowlist is a new
tracked file that must be maintained forever and grows on every false positive, and the first run
over the existing tree will have to be triaged before it can be turned on at all (unmeasured, but
the registry has enough rows and the docs enough dates that this is not a five-minute job).

### Option D — narrow the scope instead of the rule

Apply a blocking company-plus-date screen to `message-queue/` and `tasks/` **only** — the trees
where a real posting or recruiter thread would plausibly be pasted — and leave `docs/`, `skills/`
and `memory/` alone, where the legitimate company-and-date prose lives. Much lower false-positive
surface than C. Weaker: a leak in a design doc or an ADR walks through, and those trees have had
leaks before.

## Recommendation

**Option B.** The measured evidence in this repo is that the catches come from a human reading the
diff, and that the mechanical detectors were silent for all three of the most valuable ones. An
advisory hint strengthens exactly that reader without creating a gate that fires on the repo's own
legitimate content, and it costs no new tracked list. If it proves noisy the hint is deleted with
no migration; if it proves accurate, promoting it to Option C later is a one-line change to where
its findings are counted — which is the correct order to attempt it in.

Whichever way this goes, the DoD line it belongs to should be settled with it: the task's planted
`message-queue/needs-human/reviews/` defect is only "caught" under C and D. Under B it is
*surfaced*, and the check is that the hint appears — not that the commit fails.

**Your answer:** ______
