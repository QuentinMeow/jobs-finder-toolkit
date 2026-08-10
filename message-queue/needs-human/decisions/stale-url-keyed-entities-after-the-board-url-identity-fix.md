# Should the store's now-orphaned `url-` entities be removed, and by whom?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-09
- **Source**: [posting identity fix](../../../skills/job-search/scripts/posting_identity.py)
- **Blocks**: nothing. The fix works, and the store heals its *content* on the next
  ordinary build without this being answered.
- **Default path**: agents leave every existing store entity exactly where it is.
  No agent deletes a store entity under any condition (`AGENTS.md` guardrail).
- **Cost if wrong**: one-time
- **Safe to merge because**: nothing has been deleted. The change only stops NEW
  observations from keying on a board URL; every byte already in `derived/` and
  `index/` is untouched, and reverting the commit restores the old keying for
  future builds too.

## Background

A source that returns its bare listing URL for every row — RemoteOK can return
`https://remoteok.com/remote-jobs/` instead of a per-job permalink — used to give
every one of those unrelated jobs the SAME entity key, because the key was a hash
of the URL. One key means one entity, so the store folded unrelated postings
together: one job's title shipped attached to another job's description, and the
absorbed posting vanished with no record that it had ever been seen.

Measured on a throwaway store with two fictional postings sharing one board URL:
the old code produced **one** entity for **two** jobs. The second company and its
role were absent from `derived/` and from the index entirely.

The fix stops a board URL from being treated as identity; such rows fall through
to the existing weak content key, which keeps different jobs apart.

**What happens to a store that was already built.** Editing `posting_identity.py`
changes the module hash that the fold cache fingerprints, so the very next
ORDINARY build (no `--rebuild` flag) does a full re-fold from raw and re-keys
those rows automatically. Verified end to end:

```
store: full fold this run (fold cache stale (fingerprint changed))
build_postings: mode=incremental, fold=full, pending=0, entities=3, ...
```

Both real postings came back as separate entities. **But the old fused `url-…`
entity is still there** — a third entity for two real jobs. It is carried forward
by the index floor, which exists precisely so an entity never silently disappears.
`--rebuild` keeps it too (also verified). So the store self-heals its content and
accumulates one stale entity per previously-fused board URL.

How many exist in your real store is not something this agent can see (the private
overlay is not mounted here). To count them:

```
.venv/bin/python automation/store/store_show.py   # or grep derived/ for url- keys
```

A stale one is recognizable as a `url-` entity whose `source_ids` all carry the
same generic board URL, sitting beside newer `ck-` entities for the same jobs.

## Options

The axis is tidiness against irreversibility — a smaller, truer store against
keeping a record nothing can regenerate if the judgement was wrong.

### Option A — Leave them (the default path)

They stay as historical records of what was actually observed. The store carries a
few extra rows; queries over `postings` see one stale entity per previously-fused
board URL, each with a real title and company that did once appear in a fetch.

***Example consequence:*** a search of your store for "Staff Data Scientist" turns
up two hits that are really one job — the current `ck-` entity and its retired
`url-` twin — and you have to notice the duplicate yourself.

### Option B — You delete them, once, by hand

After a build, you remove the identified `url-` entity directories yourself and
re-run the build. The store then holds exactly one entity per real posting.

***Example consequence:*** the duplicate disappears and the store reads cleanly —
but if one of those `url-` entities was the only surviving record of a posting
whose raw blob has since been pruned by retention, that posting is gone for good,
because a rebuild reconstructs entities from raw and there is no raw left.

## Recommendation

**Option A — leave them.** They are cheap (a handful of rows), they are honest
records of a real observation, and the risk in Option B is asymmetric: retention
prunes raw blobs over time, so a `url-` entity can outlive the raw that would
recreate it. Nothing about the corruption is ongoing — the fix stops new
fusions, and the affected postings have already been recovered as their own
entities. If the duplicates become annoying, deleting them later costs the same
as deleting them now.

**Strongest case against this:** a store that permanently contains entities the
builder can no longer produce from raw is a store whose invariant "derived is
regenerable from raw" is quietly false, and every future reader of the code has to
learn that exception. Deleting them now, while you can still tell exactly which
ones they are, keeps that invariant true — and the window for identifying them
cleanly closes as more builds accumulate.

**Confidence:** medium — I verified the re-keying, the automatic full re-fold, and
that both `--rebuild` and the ordinary path keep the stale entity, all on
throwaway stores with fictional data. I did NOT inspect the real store (no overlay
mounted), so I do not know how many entities this affects there, or whether any of
them is referenced by an application `store_key` or an annotation. An annotation
pointing at a deleted entity hard-fails the next build with an orphan error, which
is loud but would need fixing before any build could succeed.

**Your answer:** ______
