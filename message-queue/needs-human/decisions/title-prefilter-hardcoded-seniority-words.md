# Should the big-tech title prefilter keep its hardcoded seniority skip list, or delegate to the profile's `titles.exclude`?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [`_BIGTECH_TITLE_SKIP` / `_title_prefilter` in `sources.py`](../../../skills/job-search/scripts/sources.py) vs [`assess_title` in `scoring.py`](../../../skills/job-search/scripts/scoring.py), which disagree about who owns seniority. The fork was found while fixing the prefilter's unanchored-substring defect; the substring half is fixed, this half is not.
- **Blocking**: nothing. Search runs unchanged.
- **Default path**: **keep the hardcoded list.** The five words stay in `_BIGTECH_TITLE_SKIP`, boundary-matched like every other entry, and the deliberate exception is written into the code comment and pinned by `test_hardcoded_seniority_words_are_still_skipped_pending_the_decision` so it cannot drift silently while this is open.

## Background

Before a Workday / Amazon / Apple / Meta board posting can be scored, it has to
survive a coarse **title prefilter** in `sources.py`. The prefilter runs on the
title alone, before the per-posting detail fetch, so a title it drops is never
fetched at all.

```python
_BIGTECH_TITLE_SKIP = (
    "intern", "internship", "co-op", "new grad", "graduate program", "apprentice",
    "manager", "director", "principal", "distinguished", "fellow",
    "vice president", "vp", "sales", "marketing", "recruit", "designer",
    "data scientist", "research scientist", "account executive", "customer success",
)
```

`skills/job-search/scripts/sources.py`, called at the four big-tech fetchers.
The comment above it claims: *"This never drops a title the pipeline's title gate
would keep."*

That claim is false for five of those entries. `scoring.assess_title`
(`skills/job-search/scripts/scoring.py`) decides titles against the **profile's**
`titles.include` / `titles.exclude` lists, and it happily matches
`Principal Infrastructure Engineer` when the profile includes
`infrastructure engineer`. The prefilter drops it first. So a profile that
deliberately targets Principal-and-above or applied-scientist roles receives
**zero of them from those four employers**, no matter what its own include list
says — silently, with no filtered row and no count.

The five entries at issue are exactly: `principal`, `distinguished`, `fellow`,
`data scientist`, `research scientist`. Every other entry is an occupation the
title gate would reject anyway (recruiting, sales, design, management,
early-career), so those are not in question.

**Why this is the owner's call and not an agent's.** The right answer depends on
a file the agent cannot read: your real search profile lives in the private
overlay, and this session was blocked from opening it. Two very different
outcomes follow from what is in it:

- If your profile's `titles.exclude` **already** lists those terms, removing them
  from the fetcher changes nothing you would notice — the profile catches them one
  gate later, and the fetcher stops duplicating a rule the profile owns.
- If it **does not**, removing them widens the fetch, and that widening is not
  free. `fetch_workday` is capped at `max_candidates=60`; `fetch_amazon`,
  `fetch_apple` and `fetch_meta` at `80`. The cap is applied to the candidate list
  in the order the search pages returned it, so newly-admitted Principal /
  scientist titles **consume budget that wanted roles used to get**. The failure
  is displacement, not noise: a role pushed past the cap is never fetched, so it
  produces no filtered row, leaves no trace in the snapshot, and nothing reports
  that it existed. That is the same silent-loss shape as the sponsorship and
  location defects this round of work is fixing.

**What to check before answering.** Open your real search profile — the one a
bare `--profile <label>` resolves to, which `search_jobs.profile_search_dirs()`
looks up in `config.search_profiles_dir()` (the overlay) before the tracked
`skills/job-search/profiles/` fallback — and read its `titles.exclude` list
(the key `scoring.assess_title` reads at `scoring.py:168`). Two questions:

1. Does `titles.exclude` already contain `principal`, `distinguished`, `fellow`,
   `data scientist` and `research scientist`?
2. Do you *want* Principal-and-above or applied-scientist roles from Workday /
   Amazon / Apple / Meta at all?

If the answer to 2 is yes, the current code cannot give them to you, whatever your
include list says.

## Options

### Option A — keep the hardcoded list (the default path)
Zero change; the fetch stays as cheap and as narrowly targeted as it is today, and
the per-board budgets keep going to the titles they go to now. **Cost:** the
fetcher keeps a seniority policy that the profile is supposed to own, so the two
disagree and the fetcher wins. If you ever add Principal or scientist roles to
your profile's include list, they will not arrive from these four employers and
nothing will tell you why. The code comment now says this out loud, which converts
an invisible bug into a documented limitation — but it is still a limitation.

### Option B — remove the five words; let `titles.exclude` decide
One owner of the rule. The prefilter keeps only occupations the title gate could
never keep, and seniority/discipline is entirely the profile's business — which is
where every other title decision already lives. **Cost:** the candidate budgets
fill with more rows, so a search over those four boards is slower and, if your
profile does not exclude these terms, wanted roles can be displaced out of the
fetch entirely and invisibly. If you choose this, the safe order is to add the
terms to your overlay profile's `titles.exclude` **first**, in a separate commit,
and only then remove them from the fetcher.

### Option C — remove the five words *and* raise the candidate budgets
Removes the displacement risk that makes B costly, by giving the wider candidate
set more room (say 60 → 100 Workday, 80 → 120 the others). **Cost:** more detail
fetches per board on every run — slower searches and more request volume against
four third-party APIs, paid on every run, to fix a problem that only exists if
your profile does not already exclude these terms. Worth considering only if the
answer to B's precondition is "no, my profile does not exclude them, and yes, I do
want those roles".

### Option D — pass the profile's exclude list into `fetch_company`
The structurally correct version of B: the prefilter is built from
`profile["titles"]["exclude"]` at call time via `common.term_matches`, so there is
one list and it is yours. **Cost:** a signature change through `fetch_company` and
`search_jobs.py`, and it inherits B's displacement risk exactly. This is a real
piece of work, not a one-line edit; it is also the option that makes the other
three stop mattering.

## Recommendation

**Option A for now — which is why it is the default path — and Option D as the
task to schedule if you want this properly resolved.** I originally removed the
five words as part of fixing the prefilter's substring defect, on the reasoning
that one owner of a rule beats two. That reasoning still holds and I would still
argue for D on design grounds. What changed is that I could not verify the
precondition: with your profile unreadable in this session, removing them is a
guess whose downside is a silent, unreportable loss of wanted roles, which is
precisely the failure class the surrounding work exists to remove. Trading a
*documented* limitation for an *invisible* one is a bad trade even when the
documented one is uglier.

If you answer B or D, say so and I will also add the terms to the overlay
profile's `titles.exclude` in the same change, so the widening is fenced by the
gate that should have owned it all along.

**Your answer:** ______
