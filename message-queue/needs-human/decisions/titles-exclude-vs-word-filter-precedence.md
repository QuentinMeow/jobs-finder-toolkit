# When you write the same word in `titles.exclude` and `word_filter`, which one of your own lists wins?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-09
- **Source**: [issue triage index, 2026-08-03 batch](../../../tasks/0_backlog/2026-08-09-issue-triage-2026-08-03-batch/task.md) · GitHub issue #256 · structured debate between two advocates, both measured against an 11,783-posting corpus
- **Blocks**: nothing. The reorder half of this area (#232) shipped separately and independently;
  it was measured at zero row changes.
- **Default path**: **change nothing.** `word_filter` continues to rescue a `titles.exclude`
  drop into review, exactly as today. What DID ship alongside this: a load-time warning naming
  any word that appears in both lists and which one currently wins, and per-term counters for
  title-gate drops that were previously uncounted. Those make the collision visible without
  deciding it.
- **Cost if wrong**: recurring-loss
- **Safe to merge because**: no filtering rule changed and no default value moved. The two
  things that did ship — a warning and a counter — only add output; reverting either is a
  single-commit revert that changes no verdict.

## Background

Your search profile has two places that can name a job title, and both are yours:

- `titles.exclude` — the older, two-class list. `profiles/README.md:37-38` documents it
  absolutely: *"A posting is a candidate if its title contains at least one `include` term and
  none of the `exclude` terms."*
- `titles.word_filter` — the newer three-class block (`hard_exclude` / `soft_exclude` /
  `include`) introduced by your own decision
  `memory/decisions/search-filter-vocabulary-is-profile-owned.md` (2026-08-02).

When the same word appears in both, the second one silently wins: `search_jobs.py:839-848`
runs after the title gate and reverses its hard `no_match` into a review row. Nothing warns
you, and no artifact records that your exclude was overridden.

**This is live in the shipped public example.** `skills/job-search/profiles/example.yaml`
lists `manager`, `data scientist` and `research scientist` in `titles.exclude` (~:33-46) AND
in `word_filter.soft_exclude` (~:86-89). So the shipped example contradicts itself three
times.

**Measured on 11,783 real postings with that shipped example profile:**

```
today                      shortlist=786   review=1613   rescued=2130
if titles.exclude wins     shortlist=786   review= 458   rescued=   5

rows that stop reaching review: 1155
   title.excluded.manager             1077
   title.excluded.data scientist        42
   title.excluded.research scientist    35
```

The shortlist does not move at all. The entire effect is on the review queue.

**Two facts that cut in opposite directions, both verified:**

- The rescue lane is mostly junk: only **22%** of its 2,130 rows carry an engineering role
  noun, and its top-of-file reads `Cost Accounting Manager`, `International Tax Manager`,
  `Country Manager, Italy`. Its genuine "a product is literally named Manager" saves number
  about **3** titles.
- But `skills/search-recall-audit/LESSONS.md:52-63` records that in a real recall audit,
  **2 of 12** hard-`manager`-dropped titles were genuine IC false negatives. Applied naively
  to 1,077 manager rows that is a large number of real roles going invisible every run.

## Options

The axis: whether your older, more specific statement or your newer, deliberately-authored one
speaks for your current intent — and whether a wrongly-excluded role should be recoverable.

### Option A — change nothing; keep the rescue *(recommended)*
`word_filter` continues to override `titles.exclude` into review. The new warning tells you
when it is happening and to which words.

***Example consequence:*** You run a search and the summary says `manager: 1077 postings your
exclude list named were rescued into review by word_filter`. Your shortlist is unchanged. If
that is not what you wanted, you delete `manager` from `soft_exclude` and it stops — but until
you do, you keep skimming a review file that is three-quarters titles you already rejected.

### Option B — `titles.exclude` becomes terminal, with a receipt
Nothing rescues an explicit exclude. Excluded rows are written to a capped
`excluded-by-your-profile.md` sidecar naming the title, company, URL and the exact term that
dropped it, so nothing vanishes.

***Example consequence:*** Your review queue drops from 1,613 rows to 458 and becomes worth
opening. Two or three times a month, a genuine engineering role whose title happened to
contain "manager" is not in it — it is in a sidecar file you have to remember to open.

### Option C — fix only the shipped example, decide nothing
Remove the three colliding words from `example.yaml`'s `soft_exclude` and leave the precedence
rule alone. 1,154 of the 1,155 rows resolve without any rule change.

***Example consequence:*** The shipped example stops contradicting itself and its review queue
shrinks by 71%. Your own private profile is untouched and behaves exactly as before, so if you
have the same collision there, you get the warning and fix it yourself in one line.

## Recommendation

**Option A now, and Option C as soon as you tell me which way to fix the example.** The
collision is a configuration bug, not a precedence bug — and the cleanest primitive for a
configuration bug is a loud warning plus a corrected example, which is what shipped. Option B
removes 1,155 rows per run from the surface you actually work from, and the repo's own recall
audit says roughly one in six of the manager drops is a real role; that is a trade only you
should make, and it should not run in `main` unanswered for weeks.

I deliberately did not pick a direction for Option C, because which of your two lists is
"really" your intent is the same question as this decision.

**Strongest case against this:** you wrote `manager` in `titles.exclude` and the public README
tells you that means the posting is not a candidate. Option A keeps a state where the
documentation is simply false, and 1,077 rows per run prove it. There is a fair reading in
which the honest fix is Option B and the "recall insurance" defence is really a defence of a
lane that is 78% non-engineering and that nobody opens — in which case A is preserving a
comforting fiction and calling it safety.

**Confidence:** medium-high on the numbers — the 786/1613/458/1155 figures come from running
the real `filter_score_rank` on a real corpus, and both advocates reproduced the collision in
the shipped example independently. Lower on the recall estimate: the "2 of 12" false-negative
rate comes from one small audit, and I did **not** re-measure it on this corpus. If that rate
is really 1-in-6, Option B is worse than it looks; if it was an unlucky sample, Option B is
better. That measurement is the one thing that would settle this.

**Your answer:** ______
