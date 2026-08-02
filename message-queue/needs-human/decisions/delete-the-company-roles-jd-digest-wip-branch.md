# Should the `70a620f` archive ref be deleted?

> **2026-08-02 — the ref changed shape, the question did not.** The owner asked for a
> repository with one long-lived branch. `wip/07-company-roles-jd-digest` was not work in
> progress; it was an archive keeping `70a620f` reachable. It is now the annotated tag
> **`archive/jd-digest-70a620f`** (local and on `origin`), and the branch is deleted.
> Nothing was lost — `git show 70a620f32968` still resolves, and `git tag --contains` names
> the tag. **The question below is unchanged**: whether to drop the ref *at all* is still
> the owner's, and the default is still to keep it. Read "branch" below as "ref".

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-01
- **Source**: [the ref's only commit, `70a620f` "Give the ATS-API JD path a digest mode"](../../../skills/job-search/scripts/fetch_jd.py)
- **Blocks**: nothing. The ref is not in any stack and nothing builds on it.
- **Default path**: **keep it.** No agent deletes the ref, locally or on the remote.
- **Cost if wrong**: ratify
- **Safe to merge because**: keeping a branch writes nothing and costs one ref; the
  decision that is expensive is the *other* one, and it stays available.

## Background

`wip/07-company-roles-jd-digest` holds one commit on top of `main` (`70a620f`), pushed
one day ago as PR #182. It is 890 insertions across six files — a digest mode for the
ATS-API JD path in `company_roles.py` / `fetch_jd.py`, plus 513 lines of new tests.

Two things make this an owner call rather than routine branch hygiene.

**Two designs disagree about whether the work should exist.** The digest-mode approach
and the durable/disposable direction in the workspace-restructure family point at
different shapes for the same JD-fetch path. Neither has been retired, so "is this branch
obsolete?" currently has two defensible answers depending on which design you read first.

**It is the only copy of tested bytes, and it is owner data.** PR #182 was pushed
specifically to preserve it. The 513 test lines were written against a real ATS response
shape; nothing else in the tree records that shape. `AGENTS.md` is unambiguous that agents
never delete owner data, and a branch holding the sole copy of work the owner deliberately
preserved is squarely that.

## Options

### Option A — keep it (the default path)

The branch stays until you say otherwise.

- Costs one ref and zero maintenance. It is not in a stack, so it never needs rebasing and
  cannot go stale in a way that breaks anything.
- The tested bytes stay recoverable whichever design wins.
- Cost: a `wip/` branch that a future reader may mistake for live work. Mitigated by this
  item existing.

### Option B — delete it

Treat the design disagreement as settled against the digest approach and drop the branch.

- One fewer ambiguous ref.
- Cost: irreversible in practice. Once both local and remote refs are gone the commit is
  unreachable and will eventually be garbage-collected. The test file is the real loss —
  it encodes an ATS response shape that would have to be re-derived from a live API.

### Option C — keep it, and record which design supersedes it

Keep the ref and add one line to the relevant design saying the digest approach is (or is
not) superseded, so the ambiguity does not survive.

- Removes the reason this question exists.
- Cost: requires deciding the design question first, which is the harder half.

## Recommendation

**Option A**, and Option C when you next touch that design family. Deleting is the one
irreversible move available here, the branch costs essentially nothing to keep, and the
thing it holds is a test fixture derived from a live external API — the most expensive
category of thing to re-create. If the digest approach is genuinely dead, deleting the
branch is still not urgent; recording *why* it is dead is the part that has value.

**Your answer:** ______
