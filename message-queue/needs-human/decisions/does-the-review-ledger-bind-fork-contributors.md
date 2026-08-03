# Does a fork PR owe review-ledger rows, or does the gate need a contributor exemption?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [CONTRIBUTING.md — the section that binds outside contributors](../../../CONTRIBUTING.md)
- **Blocks**: nothing today, because no fork PR has hit it. It becomes blocking for
  one outside contributor the moment the first one does, and they will have no
  instruction to follow.
- **Default path**: if a fork PR arrives before this is decided, the maintainer appends
  the ledger row at merge and tells the contributor to ignore the red gate. Nothing in
  the repository says so, which is the point of this item.
- **Cost if wrong**: one-time
- **Safe to merge because**: no fork PR has hit this yet; the first one is handled by a maintainer
  appending the row inside that PR, which is reviewable and revertible before it merges.

## Background

`CONTRIBUTING.md:88-92` is unambiguous about who it binds:

> **Who this section binds.** It is written for **outside contributors** working
> from a fork. … Where the two disagree, the audience decides: fork → this file,
> maintainer branch → the skill.

It then tells them (`:107-109`):

> 5. **CI must be green.** Fork PRs run the leak guard tokenless (structural + path
>    checks) — a clean tree passes; if the guard fires on your PR, it found
>    something that looks personal and it must come out, not be excepted.

That paragraph enumerates what a fork PR runs and names one gate. It omits the one a fork
PR cannot satisfy.

**Measurement corrected 2026-08-02, and the question is unchanged.** Two figures cited here
have moved: `grep -ic "review_ledger\|review gate\|review_gate" CONTRIBUTING.md` now returns
**3**, not 0 (`:26`, `:83`, `:87`, added in `cb631f7`), and `:33-35` no longer calls its check
list *"the canonical one"* — it now says the contributor list is *"a **subset**, not a mirror"*
and that `.github/workflows/ci.yml` is *"the authoritative gate list"*. The paragraph quoted
above has also moved to `:120-122`. What none of that changes: those three mentions say the
review gate **runs**, never what a fork contributor **owes** it. The `## Commits & pull
requests` section that binds forks (rules 1-6) still says nothing about the ledger, so a fork
PR still goes red at `ci.yml` with no instruction anywhere telling the contributor what to do.

**What actually happens to a fork PR** — worth stating precisely, because the mechanism is
not the one it looks like from a distance:

1. A fork clone has this repository's full history, so `automation/publish/review_ledger.yaml`
   resolves normally. The "no resolvable row" tolerance at `review_gate.py:833-843` — which
   exempts a tree shipping none of `tasks/`, `memory/`, `message-queue/`, `history/`,
   `docs/roadmap/` — is **not** the branch a fork reaches. A fork has all five.
2. The gate finds the last ledger row that is an ancestor of the PR head, diffs from there,
   sees the contributor's own commits touching published files, and returns
   `EXIT_REVIEW_REQUIRED` (`review_gate.py:861-869`). CI goes red at `ci.yml:154-163`.
3. The contributor reads `review_required_message` (`review_gate.py:566-600`), which tells
   them:

   > These files ship to a public repository. Read the diff and confirm none of it
   > contains a real name, employer, school, date, salary, or anything about the
   > owner's actual job hunt.

   and then to append a row to `automation/publish/review_ledger.yaml` with
   `reviewed_by: agent   # or: human`.

**Two things are wrong with asking an outside contributor to do that.** The first is that
the certification is not one they can make: "anything about the owner's actual job hunt"
is a judgement that requires knowing the owner's job hunt, which is precisely what the
public tree withholds. A contributor can only ever rubber-stamp it. The second is
mechanical — the ledger is append-only, so any two concurrent fork PRs both add a row at
the same tail and conflict with each other by construction.

**And the review is not lost by exempting them.** The gate is one-behind by design: it
reads the ledger from the working tree against HEAD. A fork PR merged without a row leaves
the merge commit unacknowledged, and the *maintainer's very next commit* fails the gate
with exactly that diff to review. So an exemption defers the review to the person who can
perform it; it does not skip it.

The sibling question — whether `AGENTS.md` should name this gate at all — is filed as
`message-queue/needs-human/decisions/should-the-contract-documents-name-the-review-gate.md`.
That one is about agents in this repository; this one is about humans in a fork. Either
may be answered alone.

## Options

### Option A — CONTRIBUTING teaches contributors to add their own rows

A short section under "Commits & pull requests": the gate exists, here is what it wants,
append the row it prints.

*Pros:* no code change; the rule is finally written down somewhere. *Cons:* it asks an
outsider to certify the absence of your personal data from a diff, which they cannot
assess; it guarantees a merge conflict between any two concurrent fork PRs; and it puts a
maintainer-owned audit file into the edit surface of every drive-by contributor.

### Option B — exempt fork PRs in CI; the maintainer records the review at merge

One conditional in `.github/workflows/ci.yml:154-163` keyed on
`github.event.pull_request.head.repo.fork`, plus two sentences in `CONTRIBUTING.md` saying
the maintainer records the public review and the contributor owes nothing.

*Pros:* the certification stays with the only person who can make it; no ledger edits from
forks, so no conflicts; and the deferred review is picked up automatically by the
maintainer's next commit, as above. *Cons:* the gate is now conditional on a CI expression,
which is a shape you have deliberately avoided elsewhere — `EXPORT_ABSENT_ROOTS` exists
specifically so the export is detected *on its own shape* rather than by a flag the
workflow passes (`review_gate.py:117-129`). This exemption cannot be derived from tree
shape, because a fork clone is shape-identical to the maintainer's.

### Option C — a first-class `--contributor` mode on the gate

Same effect as B, but the gate owns the decision instead of the workflow, and prints why
it stood down.

*Pros:* keeps the logic and its explanation in the gate, matching how the export case is
handled. *Cons:* strictly more code than B for the same behaviour, and the flag still has
to be passed by the workflow — so it does not actually recover the "detected on its own
shape" property that makes the export case clean. `--allow-not-applicable` already exists
but must not be reused here: its help text pins it to *"a tree you know is a mirror"*
(`review_gate.py:898-903`), and a fork is not one.

### Option D — leave it; the first fork PR discovers it

*Pros:* nothing to build for a case that has not occurred. *Cons:* the way it gets
discovered is an outside contributor's first PR going red on a gate no document mentions,
with a message asking them to vouch for your privacy. That is the single worst first
impression this repository can make, and it is currently the default.

## Recommendation

**Option B.** What the ledger records is "did anything about the owner's real job hunt
ship" — a question with exactly one qualified answerer, so `reviewed_by` should never name
a contributor. Exempting fork PRs in CI puts the certification back with you and loses
nothing, because the one-behind design means your next commit surfaces the unreviewed
merge anyway.

The honest cost of B is the one named in its Cons: it is the first place the gate's arming
depends on something other than the tree in front of it. If that bothers you more than it
bothers me, Option C moves the same conditional inside the gate where it can explain
itself, at the price of more code for identical behaviour.

Whichever you choose, `CONTRIBUTING.md` gains a sentence — even Option D is only tolerable
if the file says out loud that a fork PR will go red here and that the maintainer handles
it.

**Your answer:** ______
