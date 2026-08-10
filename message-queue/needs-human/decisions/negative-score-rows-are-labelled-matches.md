# Should a posting the scorer penalised into negative territory still be called a match?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-09
- **Source**: [issue triage index, 2026-08-03 batch](../../../tasks/0_backlog/2026-08-09-issue-triage-2026-08-03-batch/task.md) · GitHub issue #269
- **Blocks**: nothing. Every affected row is visible in the shortlist today; the question is
  what to call it.
- **Default path**: **add no threshold.** Gates decide membership, score decides order — that
  is the current contract and it stays until this is answered. Do not add a score floor, a
  "low confidence" section, or a review demotion on a hunch.
- **Cost if wrong**: recurring-loss
- **Safe to merge because**: nothing was written and no filtering changed. The one shipped
  change nearby (#286, which routes over-cap rows to review) is a *gate* fix with its own
  evidence, not a score threshold, and reverts independently.

## Background

There is **no score threshold anywhere** in the search pipeline — a repo-wide search for
`min_score`, `score_floor` and `score_threshold` returns nothing. `filter_score_rank` appends
a row to `kept` on the sole condition that `review_reasons` is empty
(`search_jobs.py:887-890`), and `select_diverse` only orders and caps.

Negative scores are reachable by design: an over-levelled title penalty
(`scoring.py:562-567`), a YOE over-reach penalty (`:644-646`), and a flat `-4`
(`:594`). So the scorer can actively penalise a posting and the report will still present it
under a heading that says these are matches. One audit run observed 14 of 21 main-list rows
carrying negative scores.

Two facts make this less alarming than it first reads, and they matter for the decision:

- **The reasons explaining the penalty are exactly what the report used to cut off.** The
  rationale column was sliced at 100 characters with no ellipsis, and the mismatch warnings
  (`over-leveled (-N)`, `visa: …`) are appended last. That truncation was fixed on
  2026-08-09, so a penalised row now *shows why* it was penalised. Some of this issue's
  sting may already be gone.
- **A threshold is a recall gate wearing a ranking costume.** `AGENTS.md` says content gates
  are never changed on a hunch, and `search-recall-audit` exists precisely to measure this
  class of change.

## Options

The axis: how much the toolkit should protect the user's attention, against how much it is
willing to hide a job it cannot confidently judge.

### Option A — document the contract, change no behaviour *(recommended)*
Say plainly in the report and the skill that gates decide membership and score only ranks, so
a low or negative score means "ranked last", not "rejected". Nearly free.

***Example consequence:*** Your shortlist still ends with three roles that are probably too
senior for you, but each now carries `over-leveled (-6)` in its rationale, and you skim past
them in two seconds instead of wondering why they are there.

### Option B — route `score <= 0` to the review lane
A real threshold. The main list becomes rows the scorer did not penalise.

***Example consequence:*** Your shortlist gets noticeably shorter and cleaner — and a role you
would have taken drops out of it, into a review file of several hundred rows that you do not
open, because a title token the scorer disliked outweighed everything else.

### Option C — keep every row, add a `Low confidence` section below the shortlist
No row leaves the report; the presentation separates confident from penalised.

***Example consequence:*** Nothing is ever hidden, and the report grows a second table you
have to read. On a thin search day, the confident section is empty and the whole shortlist
sits under a heading that says the tool is unsure.

## Recommendation

**Option A now, and only consider B after a measured `search-recall-audit` run.** The
observed harm — "the tool says match and clearly means it less" — is a *labelling* failure,
and the truncation fix has already restored the evidence that makes a penalised row legible.
Option B trades an attention cost for a recall cost, and this repo's whole guardrail posture
says that trade must be measured before it is made, not guessed. Option C is defensible but
adds a permanent second table to solve a problem that one sentence of documentation and an
already-shipped rendering fix largely address.

**Strongest case against this:** a shortlist is a *recommendation*, and a recommendation that
includes items the recommender scored below zero is not merely mislabelled, it is wrong.
Users do not read contracts; they read the heading. If two-thirds of the main list is
negative-scored — as one audit measured — then Option A is a decision to keep shipping a
list that is mostly noise and to blame the reader for not knowing the convention. Under that
reading, Option C is the honest minimum and A is a rationalisation of the status quo.

**Confidence:** medium — I verified that no threshold exists anywhere and confirmed the three
penalty sites. I did **not** re-measure the negative-score ratio after the 2026-08-09
rendering and gate fixes landed, and that ratio is the number this decision should turn on.

**Your answer:** ______
